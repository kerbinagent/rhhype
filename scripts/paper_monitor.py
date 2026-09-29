#!/usr/bin/env python3
"""Streaming, bounded, fee-aware multi-venue paper trading monitor (no orders)."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
import copy
from dataclasses import asdict
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import resource
from pathlib import Path
import signal
import sys
import time

import aiohttp
import monitor as legacy
from paper_engine import EngineConfig, PaperEngine, key
from paper_funding import FundingService
from paper_store import PaperStore
from paper_streams import StreamManager
from paper_refresh import run_hl_refresh
import paper_ui

ROOT=Path(__file__).resolve().parents[1]
LOG=logging.getLogger('paper_monitor')


def resident_memory_mb():
    try:
        return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/(1024*1024)
    except (OSError,ValueError,IndexError):return None


async def checkpoint_to_store(engine,store,state,trades,signals,evidence):
    """Failed persistence keeps its records queued with the matching ledger."""
    work=asyncio.create_task(asyncio.to_thread(store.checkpoint,state,trades=trades,signals=signals,evidence=evidence))
    try:
        try:await asyncio.shield(work)
        except asyncio.CancelledError:
            await work
            raise
    except Exception:
        engine.transitions=trades+engine.transitions
        engine.signals=signals+engine.signals
        engine.evidence=evidence+engine.evidence
        raise


class BookRing:
    """Sampling and explicit memory budget independent of message frequency."""
    def __init__(self,max_bytes=16*1024*1024,seconds=30,sample_interval=.5):
        self.max_bytes=max_bytes;self.seconds=seconds;self.sample_interval=sample_interval
        self.rows=deque();self.used=0;self.last={}

    def add(self,b):
        k=f"{b['venue']}:{b['market']}";now=b['received']
        if now-self.last.get(k,0)<self.sample_interval:return
        self.last[k]=now
        # Conservative Python object allowance for tuple + two floats + containers.
        cost=1024+160*(len(b.get('bids',[]))+len(b.get('asks',[])))
        if cost<=self.max_bytes:
            self.rows.append((now,k,cost,b));self.used+=cost
        while self.rows and (self.used>self.max_bytes or now-self.rows[0][0]>self.seconds):
            self.used-=self.rows.popleft()[2]
        if len(self.last)>4096:
            self.last={k:t for k,t in self.last.items() if now-t<self.seconds}

    def around(self,keys,limit=4):
        found=[b for _,k,_,b in self.rows if k in keys]
        return found[-limit:]


def position_funding_segments(p,now=None):
    """Partial closes hold their own quantities through their own settlement times."""
    legs=[]
    for leg in p['legs']:
        if leg['entry_time'] is None:continue
        for fill in leg['exit_fills']:
            legs.append({'venue':leg['venue'],'market':leg['market'],'side':leg['side'],
                         'quantity':fill['quantity'],'entry_time':leg['entry_time'],'exit_time':fill['timestamp']})
        if now is not None and leg['remaining']>0:
            legs.append({'venue':leg['venue'],'market':leg['market'],'side':leg['side'],
                         'quantity':leg['remaining'],'entry_time':leg['entry_time'],'exit_time':now})
    return {'legs':legs}


def all_markets(engine):
    markets={key(m):m for pair in engine.pairs.values() for m in (pair['hl'],pair['other'])}
    for position in engine.positions.values():
        for leg in position['legs']:
            markets.setdefault(leg['key'],leg|{'asset':position['asset']})
            if leg.get('remaining',0)>0:
                markets[leg['key']]=markets[leg['key']]|{'risk_priority':True}
    return list(markets.values())


async def run(args,store,config):
    stop=asyncio.Event();wake=asyncio.Event();stream_changed=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    saved=store.load_state() or {}
    engine=PaperEngine([],config,state=saved.get('engine'))
    if args.shadow_strategies:engine.enable_shadows()
    ring=BookRing(args.book_memory_mb*1024*1024,args.book_window_seconds)
    feeds={};discovery_stats=Counter();runtime={'status':'starting','last_metadata':0.0,'last_checkpoint':0.0,
        'funding_errors':{},'last_snapshot':None,'loop_lag_ms':0.0,'last_pair_plan':[]}
    stream_signature=None
    lag_samples=deque(maxlen=1200)
    rate_sample=(time.monotonic(),0)
    usage=resource.getrusage(resource.RUSAGE_SELF)
    cpu_sample=(time.monotonic(),usage.ru_utime+usage.ru_stime)
    timeout=aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout,connector=aiohttp.TCPConnector(limit=64),
                                     headers={'User-Agent':'rhhype-paper-monitor/4.0'}) as session:
        funding=FundingService(session,max_cache_events=2048,reference_tolerance_seconds=10)
        if saved.get('funding'):funding.load_state(saved['funding'])
        client=legacy.Client(session,args,discovery_stats)

        def on_book(book):
            engine.receive(book);ring.add(book);wake.set()

        def on_status(venue,payload):
            nonlocal stream_signature
            references=payload.get('references',[])
            for r in references:
                try:
                    value=r.get('oracle_price',r.get('reference_price'))
                    if value is not None:
                        funding.observe_reference(r.get('venue',venue),r['market'],r['timestamp'],value,r.get('reference_kind'))
                except (KeyError,TypeError,ValueError):engine.stats['invalid_reference_events']+=1
            normal={k:v for k,v in payload.items() if k!='references'}
            if normal:feeds.setdefault(venue,{}).update(normal)

        async def discovery():
            while True:
                try:
                    pairs,failed=await legacy.discover(client,args)
                    if args.max_pairs:pairs=pairs[:args.max_pairs]
                    # Discovery Standard fees are a baseline; portfolios reprice Lighter independently.
                    for p in pairs:
                        for m in (p['hl'],p['other']):
                            if m['venue'] in ('lighter','rh_lighter'):
                                m['published_fee_floor_bps']=m['fee_bps']
                    engine.update_pairs(pairs)
                    runtime.update(last_metadata=time.time(),status='running' if pairs else 'no_matching_markets',
                                   failed_venues=failed,last_pair_plan=pairs)
                    legacy.atomic_json(args.out/'markets.json',{'updated_at':time.time(),'pairs':pairs,'failed_venues':failed})
                    stream_changed.set();wake.set()
                    LOG.info('Discovery %d pairs, %d assets; unavailable=%s',len(pairs),len({p['asset'] for p in pairs}),failed)
                    delay=30 if failed or not pairs else args.refresh_seconds
                except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,KeyError,TypeError) as e:
                    LOG.warning('Discovery retry: %s',e);engine.stats['discovery_errors']+=1;delay=15
                await asyncio.sleep(delay)

        async def streams():
            nonlocal stream_signature
            manager_task=None;manager_stop=None
            try:
                while True:
                    markets=all_markets(engine)
                    signature=tuple(sorted(key(m) for m in markets))
                    if signature!=stream_signature or (manager_task and manager_task.done()):
                        if manager_task:
                            manager_stop.set()
                            manager_task.cancel()
                            result=await asyncio.gather(manager_task,return_exceptions=True)
                            if result and isinstance(result[0],Exception):LOG.warning('Stream manager ended: %s',result[0])
                        stream_signature=signature
                        if markets:
                            manager_stop=asyncio.Event()
                            manager=StreamManager(session,markets,on_book,on_status,max_levels=100,
                                                  prefer_bbo=args.hl_bbo)
                            manager_task=asyncio.create_task(manager.run(manager_stop))
                    stream_changed.clear()
                    try:await asyncio.wait_for(stream_changed.wait(),timeout=5)
                    except asyncio.TimeoutError:pass
            finally:
                if manager_task:
                    manager_stop.set();manager_task.cancel();await asyncio.gather(manager_task,return_exceptions=True)

        async def poll():
            # Explicit alternative, bounded by legacy per-host gates. A short
            # interval does NOT bypass public REST quotas; streaming is default.
            generation=0
            async def worker(m):
                try:
                    b=await client.book(m)
                    on_book({'venue':m['venue'],'market':m['market'],'bids':b['levels'][0],
                             'asks':b['levels'][1],'received':b['received'],'engine_time':b['engine_time'],
                             'valid':True,'generation':generation,'sequence':b['received']})
                    feeds.setdefault(m['venue'],{}).update(connected=True,transport='poll')
                except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,RuntimeError,KeyError) as e:
                    on_book({'venue':m['venue'],'market':m['market'],'received':time.time(),'valid':False,
                             'bids':[],'asks':[],'generation':generation,'reason':str(e)[:120]})
            while True:
                start=time.monotonic();markets=all_markets(engine)
                sem=asyncio.Semaphore(12)
                async def job(m):
                    async with sem:await worker(m)
                await asyncio.gather(*(job(m) for m in markets))
                await asyncio.sleep(max(.05,args.poll_interval-(time.monotonic()-start)))

        async def engine_loop():
            while not stop.is_set():
                engine.tick(time.time())
                wake.clear()
                try:await asyncio.wait_for(wake.wait(),timeout=.05)
                except asyncio.TimeoutError:pass

        async def heartbeat():
            while not stop.is_set():
                expected=time.monotonic()+.05
                await asyncio.sleep(.05)
                lag=max(0,(time.monotonic()-expected)*1000)
                runtime['loop_lag_ms']=lag;lag_samples.append(lag)
                runtime['max_loop_lag_ms']=max(runtime.get('max_loop_lag_ms',0),lag)

        async def funding_loop():
            checked={}
            while True:
                now=time.time()
                # Flat positions release capital only after settled funding is
                # known. Service those first; open marks need one update per
                # crossed UTC boundary, with retries only while incomplete.
                positions=sorted(engine.positions.values(),key=lambda p:p['status']!='AWAITING_FUNDING')
                for p in positions:
                    was_closed=p['status']=='AWAITING_FUNDING'
                    if not any(l['quantity']>0 for l in p['legs']):continue
                    now=time.time()
                    if now-checked.get(p['id'],0)<10:continue
                    if not was_closed:
                        boundary=int(now//3600)*3600
                        crossed=any(l['entry_time'] is not None and l['entry_time']<boundary for l in p['legs'])
                        previous=p.get('open_funding',{})
                        if not crossed or (previous.get('complete') and previous.get('covered_until',0)>=boundary):continue
                    checked[p['id']]=now
                    if p.get('funding_history_truncated'):
                        result={'complete':False,'cashflow_usd':None,'estimated':False,'events':[],
                                'missing':['partial exit history exceeded bounded detail; funding incomplete']}
                    else:
                        query=position_funding_segments(copy.deepcopy(p),None if was_closed else now)
                        result=await funding.cashflows(query)
                    current=engine.positions.get(p['id'])
                    if current:
                        if was_closed and current['status']=='AWAITING_FUNDING':
                            engine.settle_funding(p['id'],result,time.time())
                        elif current['status']!='AWAITING_FUNDING':
                            current['open_funding']=result|{'covered_until':now}
                checked={k:v for k,v in checked.items() if k in engine.positions}
                await asyncio.sleep(1)

        async def references_loop():
            while True:
                # Streams continuously provide references. Batch fallback only
                # near boundaries, plus startup for Aster's funding schedule.
                now=time.time();offset=now%3600
                if offset<15 or offset>3585 or not runtime.get('reference_bootstrap'):
                    result=await funding.sample_references(all_markets(engine))
                    runtime['funding_errors']=result['errors']
                    if all_markets(engine):runtime['reference_bootstrap']=True
                await asyncio.sleep(10)

        checkpoint_lock=asyncio.Lock()
        async def checkpoint(status=None):
            nonlocal rate_sample,cpu_sample
            async with checkpoint_lock:
                now=time.time();trades,signals,evidence,finished=engine.drain()
                for p in finished:
                    evidence.append((p['id']+':closed',{'trade':p,'nearby_books':ring.around({leg['key'] for leg in p['legs']})},'closed_trade',now))
                state={'engine':copy.deepcopy(engine.export_state()),'funding':funding.dump_state(),'saved_at':now,
                       'runtime_model':4}
                # Slow serialization/SQLite work stays out of the feed event loop.
                await checkpoint_to_store(engine,store,state,trades,signals,evidence)
                metrics=await asyncio.to_thread(store.snapshot,now)
                mono=time.monotonic();book_rate=(engine.stats['book_events']-rate_sample[1])/max(.001,mono-rate_sample[0])
                rate_sample=(mono,engine.stats['book_events'])
                ordered_lag=sorted(lag_samples)
                usage=resource.getrusage(resource.RUSAGE_SELF);cpu_now=usage.ru_utime+usage.ru_stime
                cpu_percent=100*max(0,cpu_now-cpu_sample[1])/max(.001,mono-cpu_sample[0])
                cpu_sample=(mono,cpu_now)
                lag_p95=ordered_lag[int(.95*(len(ordered_lag)-1))] if ordered_lag else 0
                snap=engine.snapshot(time.time())|{'updated_at':time.time(),'status':status or runtime['status'],
                    'pair_count':len(engine.pairs),'feeds':copy.deepcopy(feeds),'transport':args.transport,
                    'hl_quote_mode':'bbo_plus_depth' if args.hl_bbo else 'depth',
                    'hl_targeted_refresh':args.hl_refresh,
                    'storage':{**metrics['storage_stats'],'retained':metrics['retained'],'evidence_bytes':metrics['evidence_bytes'],
                               'book_ring_bytes':ring.used,'book_ring_max_bytes':ring.max_bytes},
                    'loop_lag_ms':runtime['loop_lag_ms'],'max_loop_lag_ms':runtime.get('max_loop_lag_ms',0),
                    'loop_lag_p95_ms':lag_p95,'cpu_percent_one_core':cpu_percent,
                    'performance_status':'busy' if cpu_percent>=85 or lag_p95>=50 else 'ok',
                    'book_events_per_second':book_rate,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                    'resident_memory_mb':resident_memory_mb(),
                    'funding_errors':runtime['funding_errors'],
                    'cost_assumptions':asdict(config),'metadata_age_seconds':time.time()-runtime['last_metadata'] if runtime['last_metadata'] else None}
                # Persisted best peaks survive restart even if absent from current universe.
                snap['top_signals']=metrics['top_signals']
                await asyncio.to_thread(legacy.atomic_json,args.out/'paper_snapshot.json',snap)
                runtime['last_snapshot']=snap;runtime['last_checkpoint']=now

        async def reports():
            while True:
                if runtime['last_metadata'] and time.time()-runtime['last_metadata']>args.max_metadata_age:
                    runtime['status']='paused_stale_metadata'
                await checkpoint()
                LOG.info('pairs=%d books=%d positions=%d completed=%d lag=%.1fms',len(engine.pairs),engine.stats['book_events'],len(engine.positions),
                         sum(x['closed_trades']+x['estimated_trades'] for x in engine.ledgers.values()),runtime['loop_lag_ms'])
                await asyncio.sleep(args.report_seconds)

        async def tui():
            while True:
                paper_ui.draw(runtime['last_snapshot']);await asyncio.sleep(.5)

        tasks=[asyncio.create_task(discovery()),asyncio.create_task(streams() if args.transport=='stream' else poll()),
               asyncio.create_task(engine_loop()),asyncio.create_task(heartbeat()),asyncio.create_task(funding_loop()),asyncio.create_task(references_loop()),
               asyncio.create_task(reports())]
        if args.transport=='stream' and args.hl_refresh:tasks.append(asyncio.create_task(run_hl_refresh(engine,client,on_book,stop)))
        if args.tui:tasks.append(asyncio.create_task(tui()))
        stopper=asyncio.create_task(stop.wait());timer=asyncio.create_task(asyncio.sleep(args.duration)) if args.duration else None
        reason='stopped'
        try:
            await asyncio.wait(tasks+[stopper]+([timer] if timer else []),return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task.done():task.result()
        except BaseException:
            reason='failed';raise
        finally:
            stop.set()
            # Keep a short timer scheduled while thread-backed checkpoints
            # finish. A completed to_thread callback can otherwise be left
            # pending in the selector during idle shutdown on Python 3.13.
            async def shutdown_pulse():
                while True:await asyncio.sleep(.05)
            pulse=asyncio.create_task(shutdown_pulse())
            for task in tasks+[stopper]+([timer] if timer else []):task.cancel()
            try:
                await asyncio.gather(*tasks,stopper,*([timer] if timer else []),return_exceptions=True)
                engine.censor_all(reason,time.time())
                await checkpoint(reason)
                # Close the executor while the pulse is active. asyncio.run
                # will see it already shut down when it closes the loop.
                await loop.shutdown_default_executor()
                LOG.info('Stopped with durable open positions; restart resumes exits, not synthetic fills')
            finally:
                pulse.cancel();await asyncio.gather(pulse,return_exceptions=True)


def arguments(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'data/paper-monitor')
    p.add_argument('--watch',action='store_true')
    p.add_argument('--shadow-strategies',action='store_true',help='Add five independent Standard-fee strategy experiments; saved experiments resume automatically')
    p.add_argument('--tui',action=argparse.BooleanOptionalAction,default=sys.stdout.isatty())
    p.add_argument('--transport',choices=['stream','poll'],default='stream')
    p.add_argument('--hl-bbo',action='store_true',help='Subscribe to faster HL best quotes; top-only books must cover executable size')
    p.add_argument('--hl-refresh',action=argparse.BooleanOptionalAction,default=True,
                   help='Use targeted HL REST books; disable for an isolated public-stream experiment')
    p.add_argument('--venues',nargs='+',choices=list(legacy.BASE),default=list(legacy.BASE))
    p.add_argument('--assets',nargs='+')
    p.add_argument('--max-pairs',type=int,default=0,help='0 = all matched pairs')
    p.add_argument('--min-volume',type=float,default=1000000)
    p.add_argument('--notional',type=float,default=1000)
    p.add_argument('--capital',type=float,default=20000,help='Prefunded cash per independent fee scenario')
    p.add_argument('--margin-fraction',type=float,default=1,help='Paper initial margin fraction; default fully collateralized')
    p.add_argument('--max-positions',type=int,default=10)
    p.add_argument('--max-matched-notional',type=float,default=10000)
    p.add_argument('--holding-seconds',type=float,default=10,help='Request exit after this many seconds from matched entry fills')
    p.add_argument('--take-profit-usd',type=float,default=.10,help='Request exit when estimated net liquidation P&L reaches this amount')
    p.add_argument('--no-take-profit',dest='take_profit_usd',action='store_const',const=None,help='Only timed exits, for fixed-hold benchmark runs')
    p.add_argument('--network-delay-ms',type=float,default=100)
    p.add_argument('--entry-slippage-bps',type=float,default=10)
    p.add_argument('--fill-timeout-seconds',type=float,default=3)
    p.add_argument('--extra-cost-bps',type=float,default=5)
    p.add_argument('--capital-rate',type=float,default=.05)
    p.add_argument('--max-age',type=float,default=2)
    p.add_argument('--max-skew',type=float,default=1)
    p.add_argument('--max-divergence-bps',type=float,default=500)
    p.add_argument('--signal-interval',type=float,default=.1)
    p.add_argument('--poll-interval',type=float,default=1)
    p.add_argument('--refresh-seconds',type=float,default=3600)
    p.add_argument('--max-metadata-age',type=float,default=7200)
    p.add_argument('--report-seconds',type=float,default=2)
    p.add_argument('--duration',type=float,default=0)
    p.add_argument('--hl-fee-bps',type=float,default=4.5)
    p.add_argument('--aster-fee-bps',type=float,default=4)
    p.add_argument('--aster-rwa-fee-bps',type=float,default=1.25)
    p.add_argument('--aster-group-b-fee-bps',type=float,default=10)
    p.add_argument('--max-db-mb',type=int,default=128)
    p.add_argument('--max-events',type=int,default=20000)
    p.add_argument('--max-trades',type=int,default=5000)
    p.add_argument('--window-hours',type=float,default=24)
    p.add_argument('--evidence-mb',type=int,default=16)
    p.add_argument('--book-memory-mb',type=int,default=16)
    p.add_argument('--book-window-seconds',type=float,default=30)
    p.add_argument('--verbose',action='store_true')
    args=p.parse_args(argv)
    for k,v in vars(args).items():
        if isinstance(v,(float,int)) and not isinstance(v,bool) and (not math.isfinite(v) or v<0):p.error(f'{k} must be finite and nonnegative')
    for name in ('capital','notional','max_positions','max_matched_notional','holding_seconds','fill_timeout_seconds','max_age','max_skew','signal_interval',
                 'refresh_seconds','report_seconds','max_db_mb','max_events','max_trades','window_hours','evidence_mb','book_memory_mb','book_window_seconds'):
        if getattr(args,name)<=0:p.error(f'{name} must be positive')
    if not 0<args.margin_fraction<=1:p.error('margin-fraction must be in (0,1]')
    if args.max_metadata_age<=args.refresh_seconds:p.error('max-metadata-age must exceed refresh-seconds')
    if args.signal_interval<.02:p.error('signal-interval must be at least .02s')
    if args.report_seconds<.5:p.error('report-seconds must be at least .5s')
    if args.tui and not sys.stdout.isatty():p.error('--tui requires a terminal')
    args.venues=sorted(set(args.venues));args.assets=sorted(set(args.assets)) if args.assets else None
    args.lighter_tier='standard'
    return args


def config_from(args):
    return EngineConfig(notional=args.notional,capital_usd=args.capital,margin_fraction=args.margin_fraction,
        max_positions=args.max_positions,max_matched_notional=args.max_matched_notional,holding_seconds=args.holding_seconds,take_profit_usd=args.take_profit_usd,
        network_delay_ms=args.network_delay_ms,entry_slippage_bps=args.entry_slippage_bps,fill_timeout_seconds=args.fill_timeout_seconds,
        extra_cost_bps=args.extra_cost_bps,capital_rate=args.capital_rate,max_book_age=args.max_age,max_skew=args.max_skew,
        max_divergence_bps=args.max_divergence_bps,signal_interval=args.signal_interval,metadata_max_age=args.max_metadata_age)


def main(argv=None):
    args=arguments(argv)
    if args.watch:
        paper_ui.watch(args.out/'paper_snapshot.json');return
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'paper.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another paper monitor owns this output directory')
        lock.seek(0);lock.truncate();lock.write(str(os.getpid())+'\n');lock.flush()
        handler=RotatingFileHandler(args.out/'paper.log',maxBytes=2000000,backupCount=3)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        LOG.addHandler(handler);LOG.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        if sys.stderr.isatty() and not args.tui:LOG.addHandler(logging.StreamHandler())
        config=config_from(args)
        engine_settings=asdict(config)
        if config.take_profit_usd is None:engine_settings.pop('take_profit_usd')
        settings={'model':4,'engine':engine_settings,'venues':args.venues,'assets':args.assets,'min_volume':args.min_volume,'max_pairs':args.max_pairs,
                  'hl_fee_bps':args.hl_fee_bps,'aster_fee_bps':args.aster_fee_bps,'aster_rwa_fee_bps':args.aster_rwa_fee_bps,'aster_group_b_fee_bps':args.aster_group_b_fee_bps}
        store=PaperStore(args.out/'paper.sqlite3',settings,max_db_mb=args.max_db_mb,max_events=args.max_events,
                         max_trades=args.max_trades,window_seconds=args.window_hours*3600,evidence_max_bytes=args.evidence_mb*1024*1024)
        legacy.atomic_json(args.out/'paper_config.json',settings|{'storage':{'max_db_mb':args.max_db_mb,'evidence_mb':args.evidence_mb,
            'max_events':args.max_events,'max_trades':args.max_trades,'window_hours':args.window_hours,'book_memory_mb':args.book_memory_mb}})
        try:
            if args.tui:
                with paper_ui.terminal():asyncio.run(run(args,store,config))
            else:asyncio.run(run(args,store,config))
        except Exception:
            LOG.exception('Paper monitor failed; previous checkpoint retained');raise
        finally:store.close()


if __name__=='__main__':main()
