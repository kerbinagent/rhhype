#!/usr/bin/env python3
"""Bounded WebSocket-only paired paper trial; never submits exchange orders."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from dataclasses import asdict
import copy
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import time

import aiohttp

from horizon_observer import load_plan, atomic_json
from paper_contingent import PairedTrial, trial_config
from paper_engine import EngineConfig, key, scenario_fee
from paper_store import PaperStore
from paper_streams import StreamManager


ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger('contingent_observer')
ASSETS = ('GRAM','GRASS','NEAR','SNDK','SOXL','SPCX','VVV','XPL',
          'BTC','ETH','NVDA','XAG')
MAX_PAIRS = 24


class CheckpointCommitUncertain(RuntimeError):
    """Stop writes when the previous transaction's commit cannot be proven."""


def select_pairs(plan, *, max_pairs=MAX_PAIRS, min_volume=1_000_000):
    if not isinstance(max_pairs,int) or not 1 <= max_pairs <= MAX_PAIRS:
        raise ValueError('max_pairs must be 1–24')
    if not math.isfinite(min_volume) or min_volume < 0:
        raise ValueError('invalid min_volume')
    selected = []
    for asset in ASSETS:
        for venue in ('lighter','rh_lighter'):
            matches = [p for p in plan if p.get('asset') == asset and
                       p.get('hl',{}).get('venue') == 'hyperliquid' and
                       p.get('other',{}).get('venue') == venue and
                       min(float(p['hl'].get('volume',0)),
                           float(p['other'].get('volume',0))) >= min_volume]
            if matches:
                selected.append(max(matches,key=lambda p: min(
                    float(p['hl']['volume']),float(p['other']['volume']))))
            if len(selected) >= max_pairs:
                break
        if len(selected) >= max_pairs:
            break
    for pair in selected:
        for market in (pair['hl'],pair['other']):
            for field in ('fee_bps','published_fee_floor_bps'):
                if field in market:
                    raw=float(market[field])
                    if not math.isfinite(raw) or raw<0:
                        raise ValueError('invalid frozen Standard fee metadata')
            fee = scenario_fee(market,'convergence')
            if not math.isfinite(fee) or fee < 0:
                raise ValueError('invalid frozen Standard fee metadata')
    return selected


def args_from(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markets',type=Path,required=True,
                        help='Existing paper monitor markets.json; read only')
    parser.add_argument('--out',type=Path,default=ROOT/'data/contingent-research')
    parser.add_argument('--duration',type=float,default=1200)
    parser.add_argument('--report-seconds',type=float,default=5)
    parser.add_argument('--max-pairs',type=int,default=24)
    parser.add_argument('--min-volume',type=float,default=1_000_000)
    parser.add_argument('--max-metadata-age-hours',type=float,default=2)
    parser.add_argument('--dry-run',action='store_true')
    args = parser.parse_args(argv)
    values=(args.duration,args.report_seconds,args.min_volume,args.max_metadata_age_hours)
    if (not all(math.isfinite(x) for x in values) or not 0 < args.duration <= 2400 or
            args.report_seconds <= 0 or args.min_volume < 0 or
            args.max_metadata_age_hours <= 0 or not 1 <= args.max_pairs <= MAX_PAIRS):
        parser.error('invalid finite trial bounds')
    if (args.out.resolve() == args.markets.parent.resolve() or
            args.markets.parent.resolve() in args.out.resolve().parents):
        parser.error('output must be separate from source monitor directory')
    return args


def settle_no_boundary(engine, now):
    """Exact zero only where no filled leg crossed an hourly funding instant."""
    count=0
    for position in list(engine.positions.values()):
        if position['status'] != 'AWAITING_FUNDING':
            continue
        filled=[leg for leg in position['legs'] if leg.get('entry_time') is not None]
        if not filled or any(leg.get('exit_time') is None or
                             int(leg['entry_time']//3600) != int(leg['exit_time']//3600)
                             for leg in filled):
            continue
        engine.settle_funding(position['id'],
            {'complete':True,'cashflow_usd':0.0,'estimated':False,
             'events':[],'missing':[],'method':'no UTC-hour boundary crossed'},now)
        count += 1
    return count


def checkpoint(store, trial, status, feeds, started, *, final=False,
               checkpoint_lag=None, runtime=None):
    began=time.monotonic()
    now=time.time()
    batches=[engine.drain() for engine in (trial.control,trial.treatment)]
    prior=copy.deepcopy((trial.control.cohorts,trial.control.cohort_rows,
                         trial.control.cohort_counts,trial.control.cohort_sums))
    trial.ingest_terminal_transitions(batches)
    state=copy.deepcopy({'version':1,'saved_at':now,'checkpoint_id':f'{now:.9f}',
           'started_at':started,'study_status':status,'trial':trial.export_state(),
           'funding_method':'exact zero only without UTC-hour boundary; crossed unresolved'})
    trades=[trade for transitions,_,_,_ in batches for trade in transitions]
    signals=[signal for _,signals,_,_ in batches for signal in signals]
    evidence=[item for _,_,items,_ in batches for item in items]
    evidence += list(trial.control.evidence)
    trial.control.evidence=[]
    try:
        store.checkpoint(state,trades,signals,evidence)
    except Exception as exc:
        # PaperStore can report a post-COMMIT maintenance error. If the exact
        # state is durable, do not requeue its trades or double-count cohorts.
        try:
            persisted=store.load_state()
        except Exception as probe_error:
            raise CheckpointCommitUncertain('cannot determine checkpoint commit') from probe_error
        if persisted and persisted.get('checkpoint_id')==state['checkpoint_id']:
            raise CheckpointCommitUncertain('checkpoint committed but maintenance failed') from exc
        (trial.control.cohorts,trial.control.cohort_rows,
         trial.control.cohort_counts,trial.control.cohort_sums)=prior
        for engine,(transitions,items,proof,finished) in zip(
                (trial.control,trial.treatment),batches):
            engine.transitions=transitions+engine.transitions
            engine.signals=items+engine.signals
            engine.evidence=proof+engine.evidence
            engine.finished=finished+engine.finished
        raise
    snap=trial.snapshot(now)
    snap.update({'status':status,'started_at':started,'updated_at':now,
                 'duration_seconds':now-started,
                 'feeds':copy.deepcopy(feeds),'transport':'public_websocket_only',
                 'runtime':dict(runtime or {}),
                 'hl_quote_mode':'newest_BBO_or_L2; no depth splice',
                 'trial_rest_book_requests':0,
                 'funding_method':'exact zero only without UTC-hour boundary; crossed unresolved',
                 'storage':store.snapshot(now)['storage_stats'],
                 'last_completed_checkpoint_pause_ms':checkpoint_lag[-1] if checkpoint_lag else None,
                 'prior_checkpoint_pause_max_ms':max(checkpoint_lag) if checkpoint_lag else None,
                 'prior_checkpoint_pause_p95_ms':sorted(checkpoint_lag)[max(0,math.ceil(.95*len(checkpoint_lag))-1)] if checkpoint_lag else None,
                 'final':final})
    path=store.path.parent/'contingent_snapshot.json'
    atomic_json(path,copy.deepcopy(snap))
    elapsed_ms=(time.monotonic()-began)*1000
    if checkpoint_lag is not None:
        checkpoint_lag.append(elapsed_ms)
    if elapsed_ms>50:
        LOG.warning('Checkpoint paused shared WebSocket processing for %.1f ms',elapsed_ms)


async def run(args, pairs, metadata_age):
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for signum in (signal.SIGINT,signal.SIGTERM):
        loop.add_signal_handler(signum,stop.set)
    config=trial_config(EngineConfig())
    config.metadata_max_age=args.max_metadata_age_hours*3600
    frozen_pair_economics=[{'asset':p['asset'],'metadata_timestamp':p['metadata_timestamp'],
        'markets':[{name:m.get(name) for name in ('venue','market','fee_bps',
            'published_fee_floor_bps','step','min_qty','max_qty','min_notional')}
            for m in (p['hl'],p['other'])]} for p in pairs]
    store=PaperStore(args.out/'contingent.sqlite',
                     {'trial_version':1,'config':asdict(config),
                      'transport':'websocket_only','assets':ASSETS,
                      'max_pairs':args.max_pairs,'min_volume':args.min_volume,
                      'frozen_pair_economics':frozen_pair_economics},
                     max_db_mb=128,max_events=5000,max_trades=5000,
                     window_seconds=86400,max_evidence_rows=2000)
    saved=store.load_state()
    trial=PairedTrial(pairs,config,
        control_state=saved.get('trial',{}).get('control') if saved else None,
        treatment_state=saved.get('trial',{}).get('treatment') if saved else None,
        now=time.time())
    started=saved.get('started_at',time.time()) if saved else time.time()
    if saved and saved.get('study_status') in ('stopped','duration_elapsed'):
        store.close()
        raise RuntimeError('Stopped study output cannot be resumed; use a new directory')
    feeds={};stats=Counter();status='running'
    checkpoint_lag=deque(maxlen=120)
    loop_lag=deque(maxlen=1200)
    closing=False
    markets=list({key(m):m for p in pairs for m in (p['hl'],p['other'])}.values())
    atomic_json(args.out/'plan.json',{
        'version':1,'created_at':started,'source_markets':str(args.markets.resolve()),
        'metadata_age_seconds':metadata_age,'pairs':pairs,'config':asdict(config),
        'transport':'public_websocket_only','trial_rest_book_requests':0,
        'selection_assets':ASSETS,'study_duration_seconds':args.duration,
        'production_comparison_limit':'trial lacks targeted HL REST books'})

    def on_book(book):
        if closing:return
        stats['book_events']+=1
        trial.receive(book)

    def on_status(venue,payload):
        if closing:return
        state={k:v for k,v in payload.items() if k!='references'}
        if state:feeds.setdefault(venue,{}).update(state)

    async def ticker():
        while not stop.is_set():
            now=time.time()
            trial.tick(now)
            stats['funding_zero_settled']+=settle_no_boundary(trial.control,now)
            stats['funding_zero_settled']+=settle_no_boundary(trial.treatment,now)
            expected=time.monotonic()+.05
            await asyncio.sleep(.05)
            lag=max(0,(time.monotonic()-expected)*1000)
            loop_lag.append(lag)
            stats['loop_lag_max_ms']=max(stats['loop_lag_max_ms'],lag)

    async def reporter():
        while not stop.is_set():
            runtime=dict(stats)
            runtime['loop_lag_p95_ms']=sorted(loop_lag)[max(0,math.ceil(.95*len(loop_lag))-1)] if loop_lag else 0.0
            checkpoint(store,trial,status,feeds,started,checkpoint_lag=checkpoint_lag,
                       runtime=runtime)
            try:await asyncio.wait_for(stop.wait(),timeout=args.report_seconds)
            except asyncio.TimeoutError:pass

    tasks=[]
    skip_final_checkpoint=False
    try:
        async with aiohttp.ClientSession(headers={'User-Agent':'rhhype-contingent-research/1.0'}) as session:
            manager=StreamManager(session,markets,on_book,on_status,max_levels=100,prefer_bbo=True)
            tasks=[asyncio.create_task(manager.run(stop)),
                   asyncio.create_task(ticker()),asyncio.create_task(reporter())]
            timer=asyncio.create_task(asyncio.sleep(args.duration))
            stopper=asyncio.create_task(stop.wait())
            done,_=await asyncio.wait([*tasks,timer,stopper],return_when=asyncio.FIRST_COMPLETED)
            if timer in done:status='duration_elapsed'
            elif stopper in done:status='stopped'
            for task in tasks:
                if task in done:
                    task.result()
                    raise RuntimeError('trial worker stopped unexpectedly')
            closing=True
            stop.set()
            for task in [*tasks,timer,stopper]:task.cancel()
            await asyncio.gather(*tasks,timer,stopper,return_exceptions=True)
    except BaseException as exc:
        status='failed'
        skip_final_checkpoint=isinstance(exc,CheckpointCommitUncertain)
        closing=True
        stop.set()
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        raise
    finally:
        # Open exposure remains in the checkpoint; never synthesize an exit.
        closing=True
        try:
            if not skip_final_checkpoint:
                runtime=dict(stats)
                runtime['loop_lag_p95_ms']=sorted(loop_lag)[max(0,math.ceil(.95*len(loop_lag))-1)] if loop_lag else 0.0
                checkpoint(store,trial,status,feeds,started,final=True,
                           checkpoint_lag=checkpoint_lag,runtime=runtime)
        finally:
            store.close()


def main(argv=None):
    args=args_from(argv)
    plan,age=load_plan(args.markets,args.max_metadata_age_hours)
    pairs=select_pairs(plan,max_pairs=args.max_pairs,min_volume=args.min_volume)
    if not pairs:raise SystemExit('No eligible preselected HL/Core/RH pairs')
    if args.dry_run:
        print(json.dumps({'assets':ASSETS,'pairs':[{'asset':p['asset'],
            'hl':key(p['hl']),'other':key(p['other'])} for p in pairs],
            'metadata_age_seconds':age,'rest_book_requests':0},indent=2))
        return
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'contingent.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another trial owns this output directory')
        lock.seek(0);lock.truncate();lock.write(str(os.getpid())+'\n');lock.flush()
        handler=RotatingFileHandler(args.out/'contingent.log',maxBytes=2*1024*1024,backupCount=2)
        logging.basicConfig(level=logging.INFO,handlers=[handler],
                            format='%(asctime)s %(levelname)s %(message)s')
        asyncio.run(run(args,pairs,age))


if __name__=='__main__':
    main()
