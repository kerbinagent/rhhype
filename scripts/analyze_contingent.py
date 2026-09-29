"""Stopped-only, read-only accounting of the HL-first paper trial.

The retained SQLite rows are an inspection window.  Lifetime totals come
from the checkpoint ledgers; missing cohort or trade rows are reported as
coverage gaps, never assigned a zero outcome.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

MAX_DB_BYTES = 256 * 1024 * 1024
MAX_ROWS = 20_000
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_RAW_BYTES = 64 * 1024 * 1024
FINAL_STATUSES = {'CLOSED', 'CLOSED_ESTIMATED', 'ABORTED'}
KNOWN_ZERO = {'abstained', 'study_cap', 'aborted'}


def _number(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} is missing or invalid') from exc
    if not math.isfinite(result):
        raise ValueError(f'{label} is not finite')
    return result


def exposure(position, original_quantity, freeze_at):
    """Integrate unmatched filled quantity; batch equal-time changes first.

    A still-open position has only an observed-to-freeze lower-bound interval.
    Truncated or inconsistent exit histories make the timing unavailable.
    """
    q0 = _number(original_quantity, 'original quantity')
    if q0 <= 0:
        raise ValueError('original quantity must be positive')
    if position.get('funding_history_truncated'):
        return {'coverage': 'censored_exit_history', 'equivalent_seconds': None,
                'wall_seconds': None, 'peak_fraction': None}
    events = defaultdict(lambda: [0.0, 0.0])
    entry = [0.0, 0.0]
    for leg in position.get('legs', []):
        side = leg.get('side')
        if side not in ('long', 'short'):
            raise ValueError('trade must have a long and short leg')
        ix = 0 if side == 'long' else 1
        quantity = _number(leg.get('quantity', 0), 'leg quantity')
        if quantity < -1e-8:
            raise ValueError('negative entry quantity')
        if quantity > 0:
            timestamp = _number(leg.get('entry_time'), 'entry time')
            events[timestamp][ix] += quantity
            entry[ix] += quantity
        fills = leg.get('exit_fills', [])
        if quantity > 0 and not fills and _number(leg.get('remaining', quantity), 'remaining') < quantity - 1e-8:
            return {'coverage': 'missing_exit_history', 'equivalent_seconds': None,
                    'wall_seconds': None, 'peak_fraction': None}
        for fill in fills:
            amount = _number(fill.get('quantity'), 'exit quantity')
            if amount <= 0:
                raise ValueError('nonpositive exit quantity')
            events[_number(fill.get('timestamp'), 'exit time')][ix] -= amount
    if len(position.get('legs', [])) != 2 or {x.get('side') for x in position['legs']} != {'long','short'}:
        raise ValueError('trade must have exactly one long and one short leg')
    if not events:
        if position.get('status') in FINAL_STATUSES:
            return {'coverage':'complete','equivalent_seconds':0.0,'wall_seconds':0.0,
                    'peak_fraction':0.0,'entry_phase_equivalent_seconds':0.0,
                    'exit_phase_equivalent_seconds':0.0}
        return {'coverage':'observed_to_freeze','equivalent_seconds':None,
                'wall_seconds':None,'peak_fraction':None,
                'observed_to_freeze_equivalent_seconds':0.0,
                'observed_to_freeze_wall_seconds':0.0}
    boundary = position.get('opened_at')
    boundary = _number(boundary, 'opened_at') if boundary is not None else None
    balances = [0.0, 0.0]
    prior = None
    equivalent = wall = peak = entry_seconds = exit_seconds = 0.0

    def interval(start, end):
        nonlocal equivalent, wall, peak, entry_seconds, exit_seconds
        if end < start - 1e-8:
            raise ValueError('nonmonotonic exposure interval')
        seconds = max(0.0, end-start)
        fraction = abs(balances[0]-balances[1])/q0
        equivalent += fraction*seconds
        if fraction > 1e-9:
            wall += seconds
        peak = max(peak, fraction)
        if boundary is None:
            entry_seconds += fraction*seconds
        else:
            entry_seconds += fraction*max(0.0, min(end, boundary)-start)
            exit_seconds += fraction*max(0.0, end-max(start, boundary))

    for timestamp in sorted(events):
        if prior is not None:
            interval(prior, timestamp)
        for ix in (0,1):
            balances[ix] += events[timestamp][ix]
            if balances[ix] < -1e-7 or balances[ix] > entry[ix]+1e-7:
                raise ValueError('exit history creates negative or excess inventory')
            if abs(balances[ix]) < 1e-7:
                balances[ix] = 0.0
        prior = timestamp
    complete = position.get('status') in FINAL_STATUSES or (
        position.get('status') == 'AWAITING_FUNDING' and all(
            _number(leg.get('remaining',0), 'remaining') <= 1e-8 for leg in position['legs']))
    if complete and any(abs(x) > 1e-7 for x in balances):
        return {'coverage': 'missing_exit_history', 'equivalent_seconds': None,
                'wall_seconds': None, 'peak_fraction': None}
    if not complete:
        frozen = _number(freeze_at, 'freeze time')
        if frozen < prior - 1e-8:
            raise ValueError('freeze precedes retained fill')
        interval(prior, frozen)
    if not complete:
        return {'coverage':'observed_to_freeze','equivalent_seconds':None,
                'wall_seconds':None,'peak_fraction':None,
                'observed_to_freeze_equivalent_seconds':equivalent,
                'observed_to_freeze_wall_seconds':wall,
                'observed_to_freeze_peak_fraction':peak}
    return {'coverage':'complete','equivalent_seconds':equivalent,'wall_seconds':wall,
            'peak_fraction':peak,'entry_phase_equivalent_seconds':entry_seconds,
            'exit_phase_equivalent_seconds':exit_seconds}


def _trade_outcome(position, original_quantity, freeze_at):
    status = position['status']
    if status == 'ABORTED':
        if any(_number(leg.get('quantity',0), 'aborted quantity') > 1e-8
               for leg in position.get('legs',[])):
            raise ValueError(f'aborted position has a fill: {position["id"]}')
        net = 0.0
        label = 'aborted'
    elif status in ('CLOSED', 'CLOSED_ESTIMATED'):
        net = _number(position.get('net_pnl_usd'), 'closed net')
        label = 'closed' if status == 'CLOSED' else 'estimated'
    elif status == 'AWAITING_FUNDING':
        net = None
        label = 'funding_unresolved'
    else:
        net = None
        label = 'open_exposure'
    timing = exposure(position, original_quantity, freeze_at)
    if net is not None and status != 'ABORTED':
        leg_fees=sum(_number(leg.get('fees_usd',0), 'leg fees') for leg in position.get('legs',[]))
        if abs(leg_fees-_number(position.get('fees_usd'), 'position fees'))>1e-6:
            raise ValueError(f'leg fees do not reconcile for {position["id"]}')
        for leg in position.get('legs',[]):
            entry_fee=_number(leg.get('entry_fee',0), 'entry fee')
            exit_fee=_number(leg.get('exit_fee',0), 'exit fee')
            if abs(_number(leg.get('fees_usd',0), 'leg fees')-entry_fee-exit_fee)>1e-6:
                raise ValueError(f'entry/exit fees do not reconcile for {position["id"]}')
            exit_fill_fees=sum(_number(fill.get('fee',0), 'exit fill fee')
                              for fill in leg.get('exit_fills',[]))
            if not position.get('funding_history_truncated') and abs(exit_fee-exit_fill_fees)>1e-6:
                raise ValueError(f'exit fill fees do not reconcile for {position["id"]}')
        components = (position.get('price_pnl'), position.get('fees_usd'),
                      position.get('other_costs_usd'), position.get('capital_costs_usd'),
                      position.get('funding_usd'))
        if any(x is None for x in components):
            raise ValueError(f'closed trade lacks cost components: {position["id"]}')
        price, fees, reserve, capital, funding = (
            _number(value,label) for value,label in zip(components,
                ('price pnl','position fees','reserve','capital cost','funding')))
        if abs(net-(price-fees-reserve-capital+funding)) > 1e-6:
            raise ValueError(f'component P&L does not reconcile for {position["id"]}')
    legs=position.get('legs',[])
    matched=(len(legs)==2 and all(leg.get('entry_result')=='filled' for leg in legs)
             and abs(_number(legs[0].get('quantity',0),'first filled quantity')-
                     _number(legs[1].get('quantity',0),'second filled quantity'))<1e-9)
    if status=='ABORTED':
        trade_class='zero_abort'
    elif matched:
        trade_class='both_filled'
    elif status=='ENTRY_PENDING':
        trade_class='entry_pending'
    elif position.get('exit_reason')=='entry_failure' or any(
            leg.get('entry_result') is not None for leg in legs):
        trade_class='entry_failed'
    else:
        trade_class='other_open'
    return {'status': label, 'net_usd': net, 'timing': timing,
            'matched_entry': matched, 'trade_class':trade_class,
            'fees_usd': _number(position.get('fees_usd',0) or 0,'position fees'),
            'reserve_usd': _number(position.get('other_costs_usd',0) or 0,'reserve'),
            'capital_usd': _number(position.get('capital_costs_usd',0) or 0,'capital cost'),
            'funding_usd': (_number(position['funding_usd'],'funding')
                            if position.get('funding_usd') is not None else None),
            'price_pnl_usd': _number(position.get('price_pnl',0) or 0,'price pnl')}


def analyze(state, cohorts, trades, *, input_hash=None):
    if state.get('study_status') not in ('stopped','duration_elapsed'):
        raise ValueError('contingent trial must have a durable stopped checkpoint')
    trial = state['trial']
    control_state, treatment_state = trial['control'], trial['treatment']
    selected = int(control_state['cohort_counts'].get('selected',0))
    frozen = _number(state.get('saved_at'), 'saved_at')
    summary = {'version':1, 'study_status':state['study_status'],
               'saved_at':frozen, 'checkpoint_id':state.get('checkpoint_id'),
               'input_sha256':input_hash,
               'source_config_hash':state.get('_source_config_hash'),
               'selection':{'selected':selected,'mapped':len(cohorts),
                            'mapping_complete':len(cohorts)==selected,
                            'missing_cohort_rows':max(0,selected-len(cohorts)),
                            'durable_cohort_counts':control_state['cohort_counts'],
                            'durable_finalized_sums':control_state.get('cohort_sums',{})},
               'policies':{}, 'pairs':{}, 'coverage':{}, 'limitations':[
                   'Public-book paper fills are not exchange fills.',
                   'The candidate selector is control-driven and routes share market events.',
                   'Policy ledgers are independent counterfactual portfolios; do not add their P&L.',
                   'A zero-fill abort or abstention is zero trading cash, not a profitable execution.']}
    positions = {}
    for name, engine in (('control',control_state),('treatment',treatment_state)):
        policy = 'simultaneous' if name == 'control' else 'hl_first'
        ledger = engine['ledgers']['convergence']
        positions.update(engine.get('positions',{}))
        summary['policies'][name] = {'trial_policy':policy,
            'ledger':{k:ledger.get(k) for k in ('entry_attempts','aborted_trades',
                'closed_trades','estimated_trades','closed_pnl_exact','closed_pnl_estimated',
                'fees_usd','other_costs_usd','capital_costs_usd','funding_usd')},
            'cohort_outcomes':{}, 'trade_class_outcomes':{},
            'mapped_flat_trade_components':{},
            'timing':{}, 'latency_seconds':{}}
    by_policy = {'control': Counter(), 'treatment':Counter()}
    timing_sum = {'control':Counter(), 'treatment':Counter()}
    timing_counts = {'control':Counter(), 'treatment':Counter()}
    class_counts = {'control':Counter(), 'treatment':Counter()}
    class_net = {'control':Counter(), 'treatment':Counter()}
    latencies = {'control':defaultdict(list), 'treatment':defaultdict(list)}
    pair_counts = Counter()
    missing_trade_ids=[]
    mapped_ids=set()
    for cohort_id,row in sorted(cohorts.items(), key=lambda x:(x[1].get('selected_at',0),x[0])):
        q0=_number(row.get('original_quantity'), 'cohort original quantity')
        t0=_number(row.get('selected_at'), 'candidate time')
        outcomes={}
        for name in ('control','treatment'):
            ident=row.get(name+'_position_id')
            if ident is None:
                stored=row.get(name+'_result') or {}
                status=stored.get('status')
                if status not in ('abstained','study_cap'):
                    status='missing_admission'
                outcome={'status':status,'net_usd':0.0 if status in KNOWN_ZERO else None,
                         'matched_entry':False,'timing':None,
                         'trade_class':status if status in ('abstained','study_cap') else 'missing'}
            else:
                mapped_ids.add(ident)
                position=positions.get(ident) or trades.get(ident)
                if position is None:
                    missing_trade_ids.append(ident)
                    outcome={'status':'missing_trade','net_usd':None,
                             'matched_entry':False,'timing':None,'trade_class':'missing'}
                else:
                    expected='simultaneous' if name=='control' else 'hl_first'
                    if position.get('trial_policy')!=expected or position.get('cohort_id')!=cohort_id:
                        raise ValueError(f'cohort/trade identity mismatch: {ident}')
                    signal=position.get('signal') or {}
                    if 'quantity' in signal and abs(_number(signal['quantity'],'signal quantity')-q0)>1e-8:
                        raise ValueError(f'cohort/trade quantity mismatch: {ident}')
                    if signal.get('route') is not None and row.get('route') is not None and signal['route']!=row['route']:
                        raise ValueError(f'cohort/trade route mismatch: {ident}')
                    outcome=_trade_outcome(position,q0,frozen)
                    stored=row.get(name+'_result') or {}
                    if stored.get('exposure_metric_status')=='complete' and outcome['timing']['coverage']=='complete':
                        if (abs(_number(stored.get('unmatched_equivalent_seconds'),'stored equivalent seconds')-
                                outcome['timing']['equivalent_seconds'])>1e-6 or
                                abs(_number(stored.get('one_leg_clock_seconds'),'stored wall seconds')-
                                outcome['timing']['wall_seconds'])>1e-6):
                            raise ValueError(f'cohort/trade exposure mismatch: {ident}')
                    if position['status'] in ('AWAITING_FUNDING','CLOSED','CLOSED_ESTIMATED'):
                        by_policy[name]['flat_rows']+=1
                        for field in ('fees_usd','reserve_usd','capital_usd','price_pnl_usd'):
                            by_policy[name][field]+=outcome[field]
                        if outcome['funding_usd'] is not None:
                            by_policy[name]['funding_usd']+=float(outcome['funding_usd'])
                    timing=outcome['timing']
                    timing_counts[name][timing['coverage']]+=1
                    if timing['coverage']=='complete':
                        for field in ('equivalent_seconds','wall_seconds',
                                      'entry_phase_equivalent_seconds','exit_phase_equivalent_seconds'):
                            timing_sum[name][field]+=timing[field]
                    elif timing['coverage']=='observed_to_freeze':
                        timing_sum[name]['observed_to_freeze_equivalent_seconds']+=(
                            timing['observed_to_freeze_equivalent_seconds'])
                        timing_sum[name]['observed_to_freeze_wall_seconds']+=(
                            timing['observed_to_freeze_wall_seconds'])
                    for leg in position.get('legs',[]):
                        if leg.get('entry_time') is None:
                            continue
                        venue='hl' if leg.get('venue')=='hyperliquid' else 'peer'
                        candidate_latency=leg['entry_time']-t0
                        if candidate_latency < -1e-6:
                            raise ValueError(f'fill predates candidate: {ident}')
                        latencies[name][f'candidate_to_{venue}_fill'].append(candidate_latency)
                        if name=='treatment' and venue=='peer':
                            sent=(position.get('contingent') or {}).get('peer_sent_at')
                            if sent is not None:
                                peer_latency=leg['entry_time']-sent
                                if peer_latency < -1e-6:
                                    raise ValueError(f'peer fill predates send: {ident}')
                                latencies[name]['peer_send_to_peer_fill'].append(peer_latency)
            outcomes[name]=outcome
            summary['policies'][name]['cohort_outcomes'][outcome['status']]=(
                summary['policies'][name]['cohort_outcomes'].get(outcome['status'],0)+1)
            class_key=f"{outcome['trade_class']}:{outcome['status']}"
            class_counts[name][class_key]+=1
            if outcome['net_usd'] is not None:
                class_net[name][class_key]+=_number(outcome['net_usd'],'cohort net')
        a,b=outcomes['control'],outcomes['treatment']
        if a['net_usd'] is not None and b['net_usd'] is not None and a['status']!='estimated' and b['status']!='estimated':
            pair_counts['both_exact_known']+=1
            pair_counts['treatment_minus_control_usd']+=b['net_usd']-a['net_usd']
            if a['matched_entry'] and b['matched_entry'] and a['status']=='closed' and b['status']=='closed':
                pair_counts['both_filled_exact']+=1
                pair_counts['both_filled_treatment_minus_control_usd']+=b['net_usd']-a['net_usd']
        if (a['matched_entry'] and a['status']=='closed' and not b['matched_entry']
                and b['status'] in KNOWN_ZERO | {'closed','estimated'}):
            pair_counts['foregone_control_matches']+=1
            pair_counts['foregone_control_match_net_usd']+=a['net_usd']
            if a['net_usd']>0:pair_counts['foregone_control_wins']+=1
        if a['status'] in ('missing_trade','open_exposure','funding_unresolved') or b['status'] in ('missing_trade','open_exposure','funding_unresolved'):
            pair_counts['not_both_resolved']+=1
        elif a['status']=='estimated' or b['status']=='estimated':
            pair_counts['estimated_pair_excluded_from_exact']+=1
    for name in ('control','treatment'):
        policy=summary['policies'][name]
        policy['mapped_flat_trade_components']=dict(by_policy[name])
        policy['trade_class_outcomes']={key:{'count':count,
            'known_net_usd':class_net[name][key] if key in class_net[name] else None}
            for key,count in sorted(class_counts[name].items())}
        policy['timing']={'complete_positions':timing_counts[name]['complete'],
                          'observed_to_freeze_positions':timing_counts[name]['observed_to_freeze'],
                          'censored_exit_history':timing_counts[name]['censored_exit_history']+
                              timing_counts[name]['missing_exit_history'],
                          'equivalent_seconds':(timing_sum[name]['equivalent_seconds']
                                                if timing_counts[name]['complete'] else None),
                          'wall_seconds':(timing_sum[name]['wall_seconds']
                                          if timing_counts[name]['complete'] else None),
                          'entry_phase_equivalent_seconds':(
                              timing_sum[name]['entry_phase_equivalent_seconds']
                              if timing_counts[name]['complete'] else None),
                          'exit_phase_equivalent_seconds':(
                              timing_sum[name]['exit_phase_equivalent_seconds']
                              if timing_counts[name]['complete'] else None),
                          'observed_to_freeze_equivalent_seconds':(
                              timing_sum[name]['observed_to_freeze_equivalent_seconds']
                              if timing_counts[name]['observed_to_freeze'] else None),
                          'observed_to_freeze_wall_seconds':(
                              timing_sum[name]['observed_to_freeze_wall_seconds']
                              if timing_counts[name]['observed_to_freeze'] else None)}
        policy['latency_seconds']={k:{'count':len(v),'mean':sum(v)/len(v),
                'median':sorted(v)[len(v)//2],
                'p90':sorted(v)[min(len(v)-1, math.ceil(.9*len(v))-1)]}
                for k,v in latencies[name].items() if v}
        ledger=policy['ledger']
        terminal_rows=[trade for trade in trades.values() if trade.get('trial_policy')==policy['trial_policy']
                       and trade.get('status') in FINAL_STATUSES]
        actual_terminal=len(terminal_rows)
        expected_terminal=sum(int(ledger.get(k,0) or 0) for k in ('closed_trades','estimated_trades','aborted_trades'))
        policy['terminal_trade_coverage']={'expected_from_ledger':expected_terminal,
            'retained_terminal_rows':actual_terminal,'complete':actual_terminal==expected_terminal}
        if actual_terminal==expected_terminal:
            exact_sum=sum(_number(t.get('net_pnl_usd'), 'closed net') for t in terminal_rows
                          if t['status']=='CLOSED')
            estimated_sum=sum(_number(t.get('net_pnl_usd'), 'estimated net') for t in terminal_rows
                              if t['status']=='CLOSED_ESTIMATED')
            if (abs(exact_sum-_number(ledger['closed_pnl_exact'], 'ledger exact pnl'))>1e-6 or
                    abs(estimated_sum-_number(ledger['closed_pnl_estimated'], 'ledger estimated pnl'))>1e-6):
                raise ValueError(f'{name} retained trades do not reconcile to durable ledger')
    summary['pairs']={**dict(pair_counts),
        'treatment_minus_control_usd':(
            pair_counts['treatment_minus_control_usd'] if pair_counts['both_exact_known'] else None),
        'both_filled_treatment_minus_control_usd':(
            pair_counts['both_filled_treatment_minus_control_usd']
            if pair_counts['both_filled_exact'] else None),
        'foregone_control_match_net_usd':(
            pair_counts['foregone_control_match_net_usd']
            if pair_counts['foregone_control_matches'] else None)}
    summary['coverage']={'missing_trade_ids':missing_trade_ids[:100],
        'missing_trade_count':len(missing_trade_ids),
        'unmapped_retained_trade_count':sum(1 for ident in trades if ident not in mapped_ids),
        'all_original_candidates_mapped':len(cohorts)==selected,
        'all_terminal_trades_retained':all(p['terminal_trade_coverage']['complete']
                                         for p in summary['policies'].values()),
        'paired_measures_complete':len(cohorts)==selected and not missing_trade_ids}
    return summary


def load_database(path):
    path=Path(path).resolve()
    if not path.is_file() or path.stat().st_size>MAX_DB_BYTES:
        raise ValueError('missing or oversized contingent SQLite database')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        record=connection.execute('SELECT payload FROM engine_state WHERE id=1').fetchone()
        if not record:raise ValueError('missing durable contingent checkpoint')
        if len(record[0].encode())>MAX_EVIDENCE_BYTES:
            raise ValueError('checkpoint payload exceeds analyzer bound')
        state=json.loads(record[0])
        if state.get('study_status') not in ('stopped','duration_elapsed'):
            raise ValueError('contingent trial must be stopped before analysis')
        trade_count=connection.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
        evidence_count=connection.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
        if trade_count>MAX_ROWS or evidence_count>MAX_ROWS:
            raise ValueError('retained row count exceeds analyzer bound')
        digest=hashlib.sha256(record[0].encode())
        try:
            config_record=connection.execute(
                "SELECT value FROM meta WHERE key='config_hash'").fetchone()
        except sqlite3.OperationalError:
            config_record=None
        if config_record:
            state['_source_config_hash']=config_record[0]
            digest.update(b'config_hash\0'+config_record[0].encode()+b'\0')
        trades={}
        for ident,payload in connection.execute('SELECT id,payload FROM trades ORDER BY id'):
            if len(payload.encode())>64*1024:
                raise ValueError(f'trade payload exceeds analyzer bound: {ident}')
            digest.update(ident.encode()+b'\0'+payload.encode()+b'\0')
            trades[ident]=json.loads(payload)
        cohorts={r['cohort_id']:r for r in state['trial']['control'].get('cohort_rows',[])}
        cohorts.update(state['trial']['control'].get('cohorts',{}))
        for ident,kind,payload in connection.execute(
                "SELECT key,kind,payload FROM evidence WHERE kind IN ('candidate_cohort','cohort_outcome') ORDER BY key"):
            if len(payload)>256*1024:
                raise ValueError(f'evidence payload exceeds analyzer bound: {ident}')
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                raw=compressed.read(MAX_EVIDENCE_BYTES+1)
            if len(raw)>MAX_EVIDENCE_BYTES:
                raise ValueError(f'inflated evidence exceeds analyzer bound: {ident}')
            digest.update(ident.encode()+b'\0'+raw+b'\0')
            row=json.loads(raw)
            previous=cohorts.get(row['cohort_id'])
            if previous is not None and any(previous.get(field)!=row.get(field) for field in
                ('selected_at','original_quantity','control_position_id','treatment_position_id')):
                raise ValueError(f'conflicting durable cohort identity: {row["cohort_id"]}')
            if previous is None or (row.get('finalized') and not previous.get('finalized')):
                cohorts[row['cohort_id']]=row
        connection.execute('COMMIT')
        return state,cohorts,trades,digest.hexdigest()
    finally:
        connection.close()


def _write_atomic_bytes(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.contingent-',delete=False) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path=Path(temporary.name)
    try:
        os.replace(temporary_path,path)
    finally:
        temporary_path.unlink(missing_ok=True)


def freeze_bundle(path, state, cohorts, trades, input_hash, source_db):
    """Freeze the exact retained analysis input in a bounded, replayable file."""
    payload={'version':1,'state':state,'cohorts':cohorts,'trades':trades,
             'source_input_sha256':input_hash,'source_db':str(source_db)}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>MAX_BUNDLE_RAW_BYTES:
        raise ValueError('frozen contingent input exceeds 64 MiB raw bound')
    compressed=gzip.compress(raw,compresslevel=6,mtime=0)
    if len(compressed)>MAX_BUNDLE_BYTES:
        raise ValueError('frozen contingent evidence exceeds 8 MiB compressed bound')
    _write_atomic_bytes(path,compressed)
    return {'sha256':hashlib.sha256(compressed).hexdigest(),
            'content_sha256':hashlib.sha256(raw).hexdigest(),
            'bytes':len(compressed),'file':Path(path).name}


def load_bundle(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>MAX_BUNDLE_BYTES:
        raise ValueError('missing or oversized contingent evidence bundle')
    compressed=path.read_bytes()
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw=stream.read(MAX_BUNDLE_RAW_BYTES+1)
    if len(raw)>MAX_BUNDLE_RAW_BYTES:
        raise ValueError('inflated contingent evidence exceeds 64 MiB bound')
    payload=json.loads(raw)
    if payload.get('version')!=1:
        raise ValueError('unsupported contingent evidence version')
    manifest={'sha256':hashlib.sha256(compressed).hexdigest(),
              'content_sha256':hashlib.sha256(raw).hexdigest(),
              'bytes':len(compressed),'file':'evidence.json.gz'}
    return (payload['state'],payload['cohorts'],payload['trades'],
            payload['source_input_sha256'],payload.get('source_db'),manifest)


def render_markdown(result):
    def fmt(value, places=4):
        return 'N/A' if value is None else f'{value:.{places}f}'
    coverage=result['coverage']; selection=result['selection']; pairs=result['pairs']
    lines=['# Contingent entry trial: stopped checkpoint analysis','',
           f"Checkpoint: `{result['checkpoint_id']}`; status: `{result['study_status']}`.",
           f"Original candidates: {selection['selected']}; mapped: {selection['mapped']}; "
           f"missing mappings: {selection['missing_cohort_rows']}.",
           f"Frozen evidence: `{result.get('evidence_bundle',{}).get('file','N/A')}` "
           f"(SHA-256 `{result.get('evidence_bundle',{}).get('sha256','N/A')}`).",'',
           '| Policy | Exact closes | Estimated | Aborted | Net, exact ledger | Fees | Reserve | Capital | Funding |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name in ('control','treatment'):
        ledger=result['policies'][name]['ledger']
        observed=ledger['entry_attempts']>0
        lines.append(f"| {name} | {ledger['closed_trades']} | {ledger['estimated_trades']} | "
            f"{ledger['aborted_trades']} | {fmt(ledger['closed_pnl_exact'] if ledger['closed_trades'] else None)} | "
            f"{fmt(ledger['fees_usd'] if observed else None)} | "
            f"{fmt(ledger['other_costs_usd'] if observed else None)} | "
            f"{fmt(ledger['capital_costs_usd'] if observed else None)} | "
            f"{fmt(ledger['funding_usd'] if observed else None)} |")
    lines += ['', 'Ledger fees and charges include positions still open or awaiting funding; exact net includes settled exact closes only.','',
              '| Policy | Outcome counts for mapped candidates | Mapped complete equivalent unmatched seconds | Mapped complete wall seconds | Open observed equivalent seconds |',
              '| --- | --- | ---: | ---: | ---: |']
    for name in ('control','treatment'):
        policy=result['policies'][name]
        outcomes=', '.join(f'{key}={value}' for key,value in sorted(policy['cohort_outcomes'].items())) or 'none'
        timing=policy['timing']
        lines.append(f"| {name} | {outcomes} | {fmt(timing.get('equivalent_seconds'),3)} | "
                     f"{fmt(timing.get('wall_seconds'),3)} | "
                     f"{fmt(timing.get('observed_to_freeze_equivalent_seconds'),3)} |")
    lines += ['', '| Policy | Entry class and outcome | Count | Recorded net USD |',
              '| --- | --- | ---: | ---: |']
    for name in ('control','treatment'):
        classes=result['policies'][name]['trade_class_outcomes']
        if not classes:
            lines.append(f'| {name} | No observed candidates | 0 | N/A |')
        for label,values in classes.items():
            lines.append(f"| {name} | {label} | {values['count']} | {fmt(values['known_net_usd'])} |")
    lines += ['', f"Mapped both exact-known original candidates: {pairs.get('both_exact_known',0)}; "
              f"treatment minus control: {fmt(pairs.get('treatment_minus_control_usd'))} USD.",
              f"Mapped both fully filled and exactly closed: {pairs.get('both_filled_exact',0)}; "
              f"difference: {fmt(pairs.get('both_filled_treatment_minus_control_usd'))} USD.",
              f"Mapped foregone control matches: {pairs.get('foregone_control_matches',0)} "
              f"(control wins: {pairs.get('foregone_control_wins',0)}).",'',
              f"Coverage: mappings complete={coverage['all_original_candidates_mapped']}; "
              f"terminal rows complete={coverage['all_terminal_trades_retained']}; "
              f"missing referenced trades={coverage['missing_trade_count']}.",
              'Equivalent unmatched seconds integrate |long remaining − short remaining| / original quantity. '
              'Same-time fills are batched; complete and observed-to-freeze times are separate.',
              'N/A means no eligible observation; a measured zero remains 0.0000.',
              'Peer fill latency is reported from the original candidate and from the later peer send as distinct clocks in analysis.json.',
              'A zero-fill abort or abstention is foregone exposure, not a profitable execution. Paired differences include these known-zero cash outcomes.',
              'Pending funding and open exposure have unknown net P&L. Timing for open positions is observed only to checkpoint time.','',
              'These are independent paper portfolios on shared public books. Their P&L must not be added; routes and events are correlated.']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--db',type=Path)
    source.add_argument('--bundle',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.db:
        state,cohorts,trades,digest=load_database(args.db)
        source_db=str(args.db.resolve())
        source_bundle=None
    else:
        state,cohorts,trades,digest,source_db,manifest=load_bundle(args.bundle)
        source_bundle=args.bundle
    result=analyze(state,cohorts,trades,input_hash=digest)
    result['source_db']=source_db
    args.out.mkdir(parents=True,exist_ok=True)
    bundle_path=args.out/'evidence.json.gz'
    if source_bundle is None:
        manifest=freeze_bundle(bundle_path,state,cohorts,trades,digest,source_db)
    elif source_bundle.resolve()!=bundle_path.resolve():
        _write_atomic_bytes(bundle_path,source_bundle.read_bytes())
    result['evidence_bundle']=manifest
    (args.out/'analysis.json').write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    (args.out/'REPORT.md').write_text(render_markdown(result))
    print(json.dumps({'selected':result['selection']['selected'],
                      'coverage':result['coverage'],'out':str(args.out)},sort_keys=True))


if __name__=='__main__':
    main()
