#!/usr/bin/env python3
"""Isolated two-pass, fixed cross-asset conditional quote diagnostic.

Importing this module does not read market archives. The CLI requires a frozen,
externally hashed protocol and verifies its sources and inputs before each pass.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from decimal import Decimal as D
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from scripts import single_venue_ordinary_events as ordinary
from scripts import single_venue_depth_capture as capture
from scripts.single_venue_residual_profile import exactmid, sweep
from scripts.single_venue_strategy import dec, rounded

NS = 10**9
VENUE = 'lighter'
TARGETS = ('ETH', 'SOL', 'HYPE', 'XRP', 'SUI', 'NEAR', 'ZEC', 'VVV', 'LIT')
ASSETS = ('BTC',) + TARGETS
SELECTED = {
    'rh_lighter': dict(zip(ASSETS, ('1','0','3','2','6','9','7','4','8','5'))),
    'lighter': dict(zip(ASSETS, ('1','0','2','24','7','16','10','90','69','120')))}
PARAMS = dict(snapshot_start_second=1, control_start_second=61, signal_start_second=127,
    anchor_stop_second=534, anchor_step_seconds=1, return_seconds=10,
    return_formula='10000*ln(mid_now/mid_prior)', leader_min_abs_return_bps='10',
    target_max_abs_return_bps='2', leader_control_max_abs_return_bps_exclusive='1',
    shared_episode_seconds=90, book_max_age_ms=500, intermarket_source_skew_ms=100,
    feature_seconds=60, control_min_age_seconds=66, control_max_age_seconds=180,
    control_return_caliper_bps='1', control_cost_caliper_bps='0.5',
    control_volatility_relative_caliper='0.25', control_trade_count_relative_caliper='0.25',
    native_notional_cap='100', decision_size_headroom_multiplier='1.01',
    delays_ms=[400,800], primary_delay_ms=400, hold_seconds=60,
    endpoint_lateness_ms=2000, funding_exclusion_span_ms=65600,
    extra_roundtrip_cost_bps=[1,2,5], minimum_paired_btc_episodes_per_window=3)
BOUNDS = dict(raw_bytes_per_capture=67371008, metadata_bytes_per_capture=131072,
    decoded_bytes_per_pass_per_capture=1073741824, records_per_pass_per_capture=1000000,
    trade_ids_per_capture=500000, run_timeout_seconds=600, output_gzip_bytes=1048576,
    readout_bytes=32768, max_feature_anchors_per_window=6000,
    max_selected_target_events_per_window=45)
DEPENDENCIES = ('scripts/peer_cross_asset_diagnostic.py', 'tests/test_peer_cross_asset_diagnostic.py',
    'scripts/single_venue_ordinary_events.py', 'scripts/single_venue_depth_capture.py',
    'scripts/maker_book_archive.py', 'scripts/maker_capture.py',
    'scripts/single_venue_residual_profile.py', 'scripts/single_venue_strategy.py')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def serial(value):
    if isinstance(value, D):
        return str(value)
    if isinstance(value, dict):
        return {str(k): serial(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def encode(value):
    return (json.dumps(serial(value), separators=(',', ':'), allow_nan=False)+'\n').encode()


def log_return(later, earlier):
    return D(10000)*(dec(later)/dec(earlier)).ln()


def funding_touches(now, span_ns=65_600_000_000):
    hour = 3600*NS
    return now % hour == 0 or (now//hour+1)*hour <= now+span_ns


def book_ok(book, now, params=PARAMS):
    try:
        age = params['book_max_age_ms']*1_000_000
        return bool(book and book.get('valid') and book.get('clock_valid')
            and book['bids'] and book['asks'] and dec(book['bids'][0][0]) < dec(book['asks'][0][0])
            and 0 <= now-book['received_ns'] <= age
            and 0 <= now-book['source_ns'] <= age
            and book['source_ns'] <= book['received_ns'])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def advanced(current, prior):
    try:
        return (current['generation'] == prior['generation']
            and current['source_ns'] > prior['source_ns']
            and current['sequence'] > prior['sequence'])
    except (KeyError, TypeError):
        return False


def book_provenance(book):
    return dict(received_ns=book['received_ns'],source_ns=book['source_ns'],
        sequence=book['sequence'],generation=book['generation'],midpoint=str(exactmid(book)),
        best_bid=str(dec(book['bids'][0][0])),best_ask=str(dec(book['asks'][0][0])))


def compact_snapshot(book):
    """History needs top quotes and identity, not sixty copies of full depth."""
    return {**{key:book[key] for key in ('received_ns','source_ns','sequence','generation','valid','clock_valid')},
        'bids':[book['bids'][0]],'asks':[book['asks'][0]]}


def native_endpoint(book, market, direction, quantity, entry=False):
    """Quote one exact native leg; no resizing, capped depth, or retry."""
    try:
        qty, step = dec(quantity), dec(market['qty_step'])
        if not qty.is_finite() or step <= 0 or qty <= 0 or qty % step or qty < dec(market['min_qty']):
            return None, 'native_minimum_reject'
        value = sweep(book, direction, qty)
        if value is None:
            return None, 'insufficient_depth'
        if value < dec(market['min_notional']):
            return None, 'native_minimum_reject'
        if value > dec(market['max_quote']):
            return None, 'order_quote_limit'
        maximum = market.get('max_qty')
        if maximum is not None and qty > dec(maximum):
            return None, 'native_maximum_reject'
        if entry and value > D(100):
            return None, 'entry_quote_above_cap'
        return value, None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None, 'native_metadata_invalid'


def native_decision(book, market, direction):
    try:
        qty = rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')), market['qty_step'])
        entry, reason = native_endpoint(book, market, direction, qty, entry=True)
        if reason:
            return None, reason
        exit_value, reason = native_endpoint(book, market, -direction, qty)
        if reason:
            return None, reason
        fee = dec(market['taker_fee_bps'])
        if not fee.is_finite() or fee < 0:
            return None, 'native_metadata_invalid'
        c0 = (D(direction)*(entry-exit_value)+(entry+exit_value)*fee/10000)/entry*10000
        return dict(quantity=str(qty), c0_bps=c0, decision_midpoint=exactmid(book)), None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None, 'native_metadata_invalid'


def select_control(earlier, event, used, params=PARAMS):
    candidates = []
    for row in earlier:
        identity = row['asset'], row['direction'], row['t']
        age = event['t']-row['t']
        if (identity in used or row['asset'] != event['asset'] or row['direction'] != event['direction']
                or not params['control_min_age_seconds']*NS <= age <= params['control_max_age_seconds']*NS):
            continue
        if (abs(dec(row['leader_return_bps'])) >= dec(params['leader_control_max_abs_return_bps_exclusive'])
                or abs(dec(row['target_return_bps'])) > dec(params['target_max_abs_return_bps'])):
            continue
        if abs(dec(row['target_return_bps'])-dec(event['target_return_bps'])) > dec(params['control_return_caliper_bps']):
            continue
        if abs(dec(row['c0_bps'])-dec(event['c0_bps'])) > dec(params['control_cost_caliper_bps']):
            continue
        eligible = True
        for key, caliper in (('volatility_bps','control_volatility_relative_caliper'),
                              ('trade_count','control_trade_count_relative_caliper')):
            value, other = dec(event[key]), dec(row[key])
            if (value == 0 and other != 0) or abs(other-value) > abs(value)*dec(params[caliper]):
                eligible = False
        if eligible:
            candidates.append(row)
    if not candidates:
        return None, 'no_eligible_earlier_control'
    chosen = min(candidates, key=lambda r: (-r['t'], str(r['id'])))
    used.add((chosen['asset'], chosen['direction'], chosen['t']))
    return chosen, 'selected'


class DecisionStudy:
    """Calendar-only past features and controls; calculates no forward outcomes."""
    def __init__(self, metadata, start, params=PARAMS, targets=TARGETS):
        self.metadata, self.start, self.params = metadata, start, dict(params)
        self.targets = tuple(targets)
        self.books, self.snapshots, self.generations = {}, defaultdict(dict), {}
        self.trade_since, self.trades = {}, defaultdict(deque)
        self.catalog, self.used = defaultdict(list), set()
        self.events, self.episodes = [], []
        self.leader_counts, self.target_counts = Counter(), defaultdict(Counter)
        self.control_counts = defaultdict(Counter)
        self.non_market = Counter()
        self.next_second = params['snapshot_start_second']
        self.last_time, self.last_episode, self.ended = start, None, False
        self.catalog_count = self.snapshot_count = 0
        self.feature_anchors = set()

    def _leader(self, second):
        current = self.snapshots['BTC'].get(second)
        prior = self.snapshots['BTC'].get(second-self.params['return_seconds'])
        if current is None or prior is None:
            return None, 'leader_clock_failure'
        if not advanced(current, prior):
            return None, 'leader_source_not_advanced'
        return log_return(exactmid(current), exactmid(prior)), None

    def _feature(self, asset, direction, second, leader_return):
        now = self.start+second*NS
        previous = second-self.params['return_seconds']
        current, prior = self.snapshots[asset].get(second), self.snapshots[asset].get(previous)
        if current is None or prior is None:
            return None, 'target_clock_failure'
        if not advanced(current, prior):
            return None, 'target_source_not_advanced'
        for tick, target_book in ((second,current),(previous,prior)):
            leader_book = self.snapshots['BTC'].get(tick)
            if leader_book is None or abs(leader_book['source_ns']-target_book['source_ns']) > self.params['intermarket_source_skew_ms']*1_000_000:
                return None, 'intermarket_source_skew'
        target_return = log_return(exactmid(current), exactmid(prior))
        if abs(target_return) > dec(self.params['target_max_abs_return_bps']):
            return None, 'target_not_quiet'
        history = [self.snapshots[asset].get(t) for t in range(second-60,second+1)]
        if any(book is None or book['generation'] != current['generation'] for book in history):
            return None, 'volatility_history_missing'
        changes = [log_return(exactmid(b),exactmid(a)) for a,b in zip(history,history[1:])]
        volatility = sum((r*r for r in changes),D(0)).sqrt()
        since = self.trade_since.get(asset)
        if since is None or since > now-60*NS:
            return None, 'trade_coverage_missing'
        count = sum(now-60*NS < t <= now for t in self.trades[asset])
        if funding_touches(now,self.params['funding_exclusion_span_ms']*1_000_000):
            return None, 'funding_boundary_excluded'
        native, reason = native_decision(self.books[asset],self.metadata[VENUE][asset],direction)
        if reason:
            return None, reason
        return dict(id=f'{asset}:{direction}:{now}',t=now,asset=asset,direction=direction,
            target_return_bps=target_return,leader_return_bps=leader_return,
            volatility_bps=volatility,trade_count=count,generation=current['generation'],
            book_provenance=dict(target_current=book_provenance(current),target_prior=book_provenance(prior),
                leader_current=book_provenance(self.snapshots['BTC'][second]),
                leader_prior=book_provenance(self.snapshots['BTC'][previous])),**native), None

    def tick(self, second):
        now = self.start+second*NS
        self.snapshot_count += 1
        for asset in ('BTC',)+self.targets:
            book = self.books.get(asset)
            self.snapshots[asset][second] = compact_snapshot(book) if book_ok(book,now,self.params) else None
            for old in list(self.snapshots[asset]):
                if old < second-60:
                    del self.snapshots[asset][old]
            while self.trades[asset] and self.trades[asset][0] <= now-60*NS:
                self.trades[asset].popleft()
        move, failure = self._leader(second)
        if second >= self.params['control_start_second']:
            for asset in self.targets:
                for direction in (1,-1):
                    counts = self.control_counts[asset,direction]
                    counts['calendar_anchors'] += 1
                    if failure is not None:
                        counts[failure] += 1
                        continue
                    if abs(move) >= dec(self.params['leader_control_max_abs_return_bps_exclusive']):
                        counts['leader_not_quiet'] += 1
                        continue
                    counts['quiet_leader_feature_attempts'] += 1
                    feature, reason = self._feature(asset,direction,second,move)
                    if reason:
                        counts['feature_failure:'+reason] += 1
                    if feature is not None:
                        counts['eligible_control_feature'] += 1
                        self.catalog[asset,direction].append(feature)
                        self.feature_anchors.add((asset,now))
                        self.catalog_count = len(self.feature_anchors)
                        if self.catalog_count > BOUNDS['max_feature_anchors_per_window']:
                            raise ValueError('control feature bound exceeded')
        if second < self.params['signal_start_second']:
            return
        self.leader_counts['scheduled'] += 1
        self.leader_counts['scheduled_signal_ticks'] += 1
        for asset in self.targets:
            self.target_counts[asset]['scheduled'] += 1
        if failure is None and abs(move) < dec(self.params['leader_min_abs_return_bps']):
            failure = 'below_leader_threshold'
        if failure is None and self.last_episode is not None and now-self.last_episode < self.params['shared_episode_seconds']*NS:
            failure = 'same_btc_episode'
        if failure:
            self.leader_counts[failure] += 1
            for asset in self.targets:
                self.target_counts[asset][failure] += 1
            return
        self.last_episode = now
        direction = 1 if move > 0 else -1
        episode = dict(id=len(self.episodes),t=now,direction=direction,leader_return_bps=move)
        self.episodes.append(episode); self.leader_counts['selected_btc_episode'] += 1
        for asset in self.targets:
            counts = self.target_counts[asset]
            counts['at_selected_btc_episode'] += 1
            feature, reason = self._feature(asset,direction,second,move)
            if reason:
                counts[reason] += 1
                continue
            counts['eligible_target_event'] += 1
            control, reason = select_control(self.catalog[asset,direction],feature,self.used,self.params)
            counts['control:'+reason] += 1
            self.events.append(dict(id=len(self.events),episode_id=episode['id'],asset=asset,
                direction=direction,decision_ns=now,features=feature,control=control,control_selection=reason))
            if len(self.events) > BOUNDS['max_selected_target_events_per_window']:
                raise ValueError('selected target event bound exceeded')

    def fire_before(self, now, inclusive=False):
        while self.next_second <= self.params['anchor_stop_second']:
            due = self.start+self.next_second*NS
            if due > now or due == now and not inclusive:
                break
            self.tick(self.next_second); self.next_second += self.params['anchor_step_seconds']

    def process_group(self, group):
        if not group:
            return
        now = group[0]['received_ns']
        if self.ended or now < self.last_time or any(e['received_ns'] != now for e in group):
            raise ValueError('receipt group order or lifecycle invalid')
        self.fire_before(now); self.last_time = now
        terminal = None
        for event in group:
            kind, asset = event['type'], event.get('asset')
            if kind == 'end':
                terminal = event; continue
            if event.get('venue') != VENUE:
                continue
            if kind == 'control':
                self.non_market[event.get('control','control')] += 1
                continue
            if asset not in ('BTC',)+self.targets:
                raise ValueError('unexpected Core asset')
            generation = event.get('generation')
            if generation is not None and asset in self.generations and self.generations[asset] != generation:
                self.books.pop(asset,None); self.snapshots[asset].clear()
                self.trade_since.pop(asset,None); self.trades[asset].clear()
            if generation is not None:
                self.generations[asset] = generation
            if kind == 'invalidate':
                scope = event.get('scope')
                if scope in ('trade',None):
                    self.trade_since.pop(asset,None); self.trades[asset].clear()
                if scope in ('book',None):
                    self.books.pop(asset,None); self.snapshots[asset].clear()
                continue
            if kind == 'book':
                old = self.books.get(asset)
                if old and old['generation'] != event['generation']:
                    self.snapshots[asset].clear()
                self.books[asset] = event
            elif kind == 'trade':
                if event.get('clock_valid') and event.get('source_ns',now+1) <= now:
                    self.trade_since.setdefault(asset,now)
                    self.trades[asset].append(now)
                    if len(self.trades[asset]) > BOUNDS['trade_ids_per_capture']:
                        raise ValueError('trade feature bound exceeded')
        self.fire_before(now,inclusive=True)
        if terminal is not None:
            self.ended = True

    def result(self):
        if not self.ended:
            raise ValueError('decision pass did not consume terminal')
        return dict(events=self.events,episodes=self.episodes,leader_counts=dict(self.leader_counts),
            target_counts={a:dict(self.target_counts[a]) for a in self.targets},
            control_counts={a:{str(direction):dict(self.control_counts[a,direction]) for direction in (1,-1)} for a in self.targets},
            catalog_count=self.catalog_count,scheduled_snapshot_ticks=self.snapshot_count,
            non_market=dict(self.non_market),ended=True,
            trade_coverage_start='first valid ordinary print after own trade invalidation')


def grouped(stream):
    group, prior = [], None
    for event in stream:
        now = event['received_ns']
        if prior is not None and now < prior:
            raise ValueError('receipt stream regressed')
        if group and now != prior:
            yield group; group = []
        if len(group) >= 50000:
            raise ValueError('equal-receipt group bound exceeded')
        group.append(event); prior = now
    if group:
        yield group


def decision_pass(stream, metadata, start, params=PARAMS, targets=TARGETS):
    study = DecisionStudy(metadata,start,params,targets)
    for group in grouped(stream):
        study.process_group(group)
    return study.result()


class QuoteScheduler:
    """Only preselected profiles; deadlines advance on every received event."""
    def __init__(self, metadata, selection, params=PARAMS):
        self.metadata, self.params = metadata, dict(params)
        self.books, self.profiles = {}, []
        self.last_time, self.ended = None, False
        for event in selection['events']:
            for role in ('event','control'):
                feature = event['features'] if role == 'event' else event.get('control')
                if feature is None:
                    continue
                for delay in params['delays_ms']:
                    self.profiles.append(dict(event_id=event['id'],episode_id=event['episode_id'],
                        role=role,delay_ms=delay,asset=feature['asset'],direction=feature['direction'],
                        decision_ns=feature['t'],quantity=feature['quantity'],generation=feature['generation'],
                        decision_midpoint=str(feature['decision_midpoint']),status='scheduled',
                        due_ns=feature['t']+delay*1_000_000))
        if len(self.profiles) > BOUNDS['max_selected_target_events_per_window']*4:
            raise ValueError('selected profile count exceeded')

    def advance(self, now):
        for row in self.profiles:
            if row['status'] == 'scheduled' and row['decision_ns'] <= now:
                row['status'] = 'pending_entry'
            if row['status'] in ('pending_entry','pending_exit') and now > row['due_ns']+self.params['endpoint_lateness_ms']*1_000_000:
                row['failed_stage'] = row['status']
                row['status'] = 'missing_entry' if row['status'] == 'pending_entry' else 'missing_exit'

    def _leader_mid(self, now):
        leader = self.books.get('BTC')
        return str(exactmid(leader)) if book_ok(leader,now,self.params) else None

    def _book(self, event, now):
        self.books[event['asset']] = event
        for row in self.profiles:
            if row['asset'] != event['asset'] or row['status'] not in ('pending_entry','pending_exit'):
                continue
            if now < row['due_ns'] or event['source_ns'] < row['due_ns']:
                continue
            entry = row['status'] == 'pending_entry'
            failure = None
            if not book_ok(event,now,self.params):
                failure = 'first_eligible_book_invalid'
            elif event['generation'] != row['generation']:
                failure = 'generation_changed'
            side = row['direction'] if entry else -row['direction']
            value = None
            if failure is None:
                value, failure = native_endpoint(event,self.metadata[VENUE][row['asset']],side,row['quantity'],entry)
            if failure:
                row['failed_stage'], row['status'] = row['status'], failure
                continue
            observation = dict(received_ns=now,source_ns=event['source_ns'],due_ns=row['due_ns'],
                value=str(value),midpoint=str(exactmid(event)),leader_midpoint=self._leader_mid(now))
            if entry:
                row.update(entry=observation,status='pending_exit',
                    due_ns=now+self.params['hold_seconds']*NS+row['delay_ms']*1_000_000,
                    entry_delay_ms=D(now-row['decision_ns'])/1_000_000,
                    consumed_before_entry_bps=D(row['direction'])*(exactmid(event)-dec(row['decision_midpoint']))/dec(row['decision_midpoint'])*10000)
                continue
            row['exit'] = observation
            entry_value = dec(row['entry']['value'])
            gross = D(row['direction'])*(value-entry_value)
            fee = dec(self.metadata[VENUE][row['asset']]['taker_fee_bps'])*(entry_value+value)/10000
            row.update(status='matched',gross_cash=gross,fee_cash=fee,net_cash=gross-fee,
                net_quote_bps=(gross-fee)/entry_value*10000,
                remaining_midpoint_bps=D(row['direction'])*(exactmid(event)-dec(row['entry']['midpoint']))/dec(row['entry']['midpoint'])*10000,
                holding_seconds=D(now-row['entry']['received_ns'])/NS,collateral='USDC')
            row['net_after_extra_bps'] = {str(bp):row['net_quote_bps']-bp for bp in self.params['extra_roundtrip_cost_bps']}
            first, last = row['entry']['received_ns'], now
            if funding_touches(first,last-first):
                row['status'] = 'funding_unknown'
                for key in ('net_cash','net_quote_bps','net_after_extra_bps'):
                    row.pop(key,None)
            a, b = row['entry']['leader_midpoint'],observation['leader_midpoint']
            if a is not None and b is not None:
                row['contemporaneous_btc_bps'] = D(row['direction'])*log_return(b,a)

    def process_group(self, group):
        if not group:
            return
        now = group[0]['received_ns']
        if self.ended or self.last_time is not None and now < self.last_time or any(e['received_ns'] != now for e in group):
            raise ValueError('quote receipt group order or lifecycle invalid')
        self.advance(now); self.last_time = now
        terminal = None
        # Context uses all books available at this receipt group, with no future record.
        for event in group:
            if event.get('venue') == VENUE and event['type'] == 'book':
                self.books[event['asset']] = event
        for event in group:
            kind, asset = event['type'],event.get('asset')
            if kind == 'end':
                terminal = event; continue
            if event.get('venue') != VENUE:
                continue
            if kind == 'invalidate' and event.get('scope') in ('book',None) and event.get('reason') != 'capture_end':
                self.books.pop(asset,None)
                for row in self.profiles:
                    if row['asset'] == asset and row['status'] in ('pending_entry','pending_exit'):
                        row['failed_stage'],row['status'] = row['status'],'invalidated'
            elif kind == 'book':
                self._book(event,now)
        if terminal is not None:
            for row in self.profiles:
                if row['status'] in ('scheduled','pending_entry','pending_exit'):
                    row['failed_stage'],row['status'] = row['status'],'unresolved_at_end'
            self.ended = True

    def result(self):
        if not self.ended:
            raise ValueError('quote pass did not consume terminal')
        return dict(profiles=self.profiles,ended=True)


def outcome_pass(stream, metadata, selection, params=PARAMS):
    scheduler = QuoteScheduler(metadata,selection,params)
    for group in grouped(stream):
        scheduler.process_group(group)
    return scheduler.result()


@contextmanager
def adapter_configuration(selected=SELECTED, bounds=BOUNDS):
    changes = {
        ordinary: dict(HARD_BYTES=bounds['raw_bytes_per_capture'],
            METADATA_MAX_BYTES=bounds['metadata_bytes_per_capture'],
            MAX_DECODED_BYTES=bounds['decoded_bytes_per_pass_per_capture'],
            MAX_RECORDS=bounds['records_per_pass_per_capture'],MAX_TRADE_IDS=bounds['trade_ids_per_capture']),
        capture: dict(SELECTED=selected,HARD_BYTES=bounds['raw_bytes_per_capture'],
            METADATA_MAX_BYTES=bounds['metadata_bytes_per_capture'])}
    previous = {module:{key:getattr(module,key) for key in values} for module,values in changes.items()}
    try:
        for module,values in changes.items():
            for key,value in values.items():
                setattr(module,key,value)
        yield
    finally:
        for module,values in previous.items():
            for key,value in values.items():
                setattr(module,key,value)


def safe_relative(path):
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('pin path must be workspace relative')
    full = ROOT/relative
    if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(ROOT):
        raise ValueError('pin path is not a regular workspace file')
    return full


def verify_plan(plan_path, expected_sha):
    plan_path = Path(plan_path)
    if not isinstance(expected_sha,str) or len(expected_sha) != 64 or digest(plan_path) != expected_sha:
        raise ValueError('external protocol SHA256 differs')
    if plan_path.stat().st_size > 65536:
        raise ValueError('protocol byte cap exceeded')
    plan = json.loads(plan_path.read_bytes())
    if (plan.get('schema') != 'peer-cross-asset-v1' or plan.get('status') != 'frozen-before-outcomes'
            or plan.get('params') != PARAMS or plan.get('bounds') != BOUNDS
            or plan.get('venue') != VENUE or plan.get('leader') != 'BTC'
            or plan.get('targets') != list(TARGETS) or plan.get('selected') != SELECTED):
        raise ValueError('frozen protocol identity or parameters differ')
    pins = plan.get('source_pins',[])
    paths = [p['path'] for p in pins]
    if not pins or len(paths) != len(set(paths)) or not set(DEPENDENCIES) <= set(paths):
        raise ValueError('required unique source pins absent')
    for pin in pins:
        if digest(safe_relative(pin['path'])) != pin['sha256']:
            raise ValueError('source pin differs: '+pin['path'])
    windows = plan.get('windows',[])
    if len(windows) != 2 or [w['index'] for w in windows] != [1,2] or [w['capture'] for w in windows] != ['reports/single-venue-broad/capture','reports/single-venue-broad-relative/capture']:
        raise ValueError('fixed input windows differ')
    for window in windows:
        directory = ROOT/window['capture']
        for name,key in (('manifest.json','manifest_sha256'),('frames.jsonl.gz','raw_sha256'),('metadata/normalized.json','metadata_sha256')):
            path = safe_relative(str(Path(window['capture'])/name))
            if digest(path) != window[key]:
                raise ValueError('input pin differs: '+name)
        manifest = json.loads((directory/'manifest.json').read_bytes())
        if manifest.get('end_reason') != 'duration_limit' or manifest.get('truncated') is not False or manifest.get('selected_markets') != SELECTED:
            raise ValueError('input endpoint or markets differ')
    return plan


def archive_stream(window, terminals):
    for event in ordinary.iter_events(ROOT/window['capture'],
            expected_manifest_sha256=window['manifest_sha256'],expected_raw_sha256=window['raw_sha256'],
            max_raw_bytes=BOUNDS['raw_bytes_per_capture'],max_decoded_bytes=BOUNDS['decoded_bytes_per_pass_per_capture'],
            max_records=BOUNDS['records_per_pass_per_capture'],max_ids=BOUNDS['trade_ids_per_capture']):
        if event['type'] == 'end':
            if event.get('truncated') or event.get('reason') != 'duration_limit':
                raise ValueError('adapter endpoint incomplete')
            terminals.append(event)
        yield event


def mean(values):
    return sum(values,D(0))/len(values) if values else None


def summarize(selection, outcomes):
    profiles = outcomes['profiles']
    rows, episode_rows = [], []
    for delay in PARAMS['delays_ms']:
        arm = [r for r in profiles if r['delay_ms'] == delay]
        pairs = []
        for event in selection['events']:
            own = next((r for r in arm if r['event_id']==event['id'] and r['role']=='event'),None)
            control = next((r for r in arm if r['event_id']==event['id'] and r['role']=='control'),None)
            if own is not None and control is not None and own['status']==control['status']=='matched':
                pairs.append(dict(event_id=event['id'],episode_id=event['episode_id'],asset=event['asset'],
                    event_bps=own['net_quote_bps'],control_bps=control['net_quote_bps'],delta_bps=own['net_quote_bps']-control['net_quote_bps']))
        for asset in TARGETS:
            own = [r for r in arm if r['asset']==asset and r['role']=='event']
            complete = [r for r in own if r['status']=='matched']
            paired = [r for r in pairs if r['asset']==asset]
            rows.append(dict(asset=asset,delay_ms=delay,gates=selection['target_counts'].get(asset,{}),
                control_feature_counts=selection.get('control_counts',{}).get(asset,{}),
                requested_entries=len(own),completed_entries=sum('entry' in r for r in own),
                completed_exits=sum('exit' in r for r in own),outcomes=dict(Counter(r['status'] for r in own)),
                control_outcomes=dict(Counter(r['status'] for r in arm if r['asset']==asset and r['role']=='control')),
                complete_pairs=len(paired),absolute_event_mean_bps=mean([r['net_quote_bps'] for r in complete]),
                complete_events_without_complete_control=sum(r['event_id'] not in {p['event_id'] for p in paired} for r in complete),
                unmatched_event_mean_bps=mean([r['net_quote_bps'] for r in complete if r['event_id'] not in {p['event_id'] for p in paired}]),
                matched_event_mean_bps=mean([r['event_bps'] for r in paired]),paired_mean_delta_bps=mean([r['delta_bps'] for r in paired])))
        for episode in selection['episodes']:
            pair = [r for r in pairs if r['episode_id']==episode['id']]
            own = [r for r in arm if r['episode_id']==episode['id'] and r['role']=='event' and r['status']=='matched']
            episode_rows.append(dict(delay_ms=delay,episode_id=episode['id'],pairs=len(pair),
                absolute_event_mean_bps=mean([r['net_quote_bps'] for r in own]),
                matched_event_mean_bps=mean([r['event_bps'] for r in pair]),paired_mean_delta_bps=mean([r['delta_bps'] for r in pair])))
    arms = []
    for delay in PARAMS['delays_ms']:
        all_episodes = [r for r in episode_rows if r['delay_ms']==delay]
        episodes = [r for r in all_episodes if r['pairs']]
        metrics = ('absolute_event_mean_bps','matched_event_mean_bps','paired_mean_delta_bps')
        arms.append(dict(delay_ms=delay,distinct_paired_btc_episodes=len(episodes),
            all_requested_profiles_matched=all(r['status']=='matched' for r in profiles if r['delay_ms']==delay),
            **{key:mean([e[key] for e in all_episodes if e[key] is not None]) for key in metrics},
            leave_one_episode_out=[dict(omitted=e['episode_id'],
                **{key:mean([r[key] for r in all_episodes if r is not e and r[key] is not None]) for key in metrics}) for e in all_episodes]))
    controls = [r for r in profiles if r['role']=='control' and r['delay_ms']==PARAMS['primary_delay_ms']]
    overlaps = sum(a['decision_ns'] < b['decision_ns']+65_600_000_000 and b['decision_ns'] < a['decision_ns']+65_600_000_000
        for index,a in enumerate(controls) for b in controls[index+1:])
    return dict(rows=rows,episodes=episode_rows,arms=arms,control_interval_overlap_pairs=overlaps,
        interpretation='Conditional complete cases; alternatives are not additive cash or independent assets.')


def evaluate_results(results):
    """Fixed operational decision; quote counts do not establish independence."""
    metrics = ('absolute_event_mean_bps','matched_event_mean_bps','paired_mean_delta_bps')
    arms = [a for result in results for a in result['summary']['arms']]
    adequate = (len(results)==2 and len(arms)==4 and all(
        a['distinct_paired_btc_episodes'] >= PARAMS['minimum_paired_btc_episodes_per_window']
        and a['all_requested_profiles_matched'] for a in arms))
    if not adequate:
        return dict(classification='inconclusive_coverage',followup_proposal=False,
                    reason='Every requested profile and at least three paired BTC episodes per window/arm are required.')
    positive = all(a[key] is not None and a[key] > 0 for a in arms for key in metrics)
    robust = positive and all(leave[key] is not None and leave[key] > 0
        for a in arms for leave in a['leave_one_episode_out'] for key in metrics)
    return dict(classification='propose_frozen_untouched_followup' if robust else 'park_observed_version',
        followup_proposal=bool(robust),adequate_coverage=True,
        all_three_means_positive_both_windows_and_arms=positive,
        all_leave_one_episode_out_means_positive=bool(robust),strategy_promotion=False)


def publish_exclusive(path, body):
    """Atomic same-filesystem no-overwrite publication on macOS and Linux."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def render_readout(results, decision):
    """Compact text companion; exact values and complete funnels remain in JSON."""
    def bp(value):
        return 'NA' if value is None else format(dec(value), '.6f')
    lines = ['Cross-asset fixed diagnostic: exploratory conditional public quotes.',
        'No private fills, causal leadership, beta-one catch-up, realized closed cash or portfolio claims.',
        'Full exact means, profile failures, provenance and control feature funnels are in the result JSON.',
        'Text bp fields are absolute event / paired event / paired improvement / unmatched event; NA means missing.',
        json.dumps(serial(decision),sort_keys=True)]
    metrics = ('absolute_event_mean_bps','matched_event_mean_bps','paired_mean_delta_bps')
    for result in results:
        selection, summary = result['selection'],result['summary']
        lines.append(f"Window {result['window']}: leader anchors 408; episodes {len(selection['episodes'])}; selected targets {len(selection['events'])}.")
        for asset in TARGETS:
            gates = selection.get('target_counts',{}).get(asset)
            if gates is None:
                gates = next((row.get('gates',{}) for row in summary['rows'] if row['asset']==asset),{})
            lines.append(f"{asset} target gates: "+json.dumps(gates,sort_keys=True))
        for arm in summary['arms']:
            values = ' / '.join(bp(arm[key]) for key in metrics)
            lines.append(f"{arm['delay_ms']} ms episode means: {values}; paired BTC episodes {arm['distinct_paired_btc_episodes']}; all profiles matched {arm['all_requested_profiles_matched']}.")
            for leave in arm['leave_one_episode_out']:
                lines.append(f"  omit BTC episode {leave['omitted']}: "+' / '.join(bp(leave[key]) for key in metrics))
        for row in summary['rows']:
            values = ' / '.join(bp(row.get(key)) for key in metrics+('unmatched_event_mean_bps',))
            lines.append(f"{row['asset']} {row['delay_ms']} ms: {values}; entries requested/completed {row['requested_entries']}/{row['completed_entries']}; exits {row['completed_exits']}; pairs {row['complete_pairs']}.")
        lines.append(f"Selected control interval overlaps: {summary['control_interval_overlap_pairs']}; shared BTC and asset dependence remains.")
    return ('\n'.join(lines)+'\n').encode()


def run(plan_path, expected_sha, output, readout):
    started = time.monotonic()
    plan = verify_plan(plan_path,expected_sha)
    results = []
    for window in plan['windows']:
        verify_plan(plan_path,expected_sha)
        directory = ROOT/window['capture']
        manifest = json.loads((directory/'manifest.json').read_bytes())
        metadata = json.loads((directory/'metadata/normalized.json').read_bytes())['markets']
        start = ordinary._epoch_ns(manifest['started_utc'])
        terminals = []
        with adapter_configuration(plan['selected'],plan['bounds']):
            selection = decision_pass(archive_stream(window,terminals),metadata,start)
        if len(terminals) != 1:
            raise ValueError('decision adapter terminal missing')
        verify_plan(plan_path,expected_sha)
        second_terminals = []
        with adapter_configuration(plan['selected'],plan['bounds']):
            outcomes = outcome_pass(archive_stream(window,second_terminals),metadata,selection)
        if len(second_terminals) != 1 or encode(terminals[0]) != encode(second_terminals[0]):
            raise ValueError('two-pass adapter provenance differs')
        if selection['leader_counts'].get('scheduled') != 408 or any(selection['target_counts'][a].get('scheduled') != 408 for a in TARGETS):
            raise ValueError('complete calendar denominator differs')
        terminal = terminals[0]
        provenance = {key:terminal[key] for key in ('decoded_bytes','archive_bytes','counts','metadata_sha256',
            'raw_gzip_sha256','manifest_sha256','max_receipt_gap_ns','adapter_sha256','book_decoder_sha256')}
        results.append(dict(window=window['index'],started_utc=manifest['started_utc'],ended_utc=manifest['ended_utc'],
            selection=selection,outcomes=outcomes,summary=summarize(selection,outcomes),provenance=provenance))
        if time.monotonic()-started > BOUNDS['run_timeout_seconds']:
            raise TimeoutError('bounded diagnostic runtime exceeded')
    decision = evaluate_results(results)
    report = dict(schema='peer-cross-asset-result-v1',protocol_sha256=expected_sha,params=PARAMS,
        validation_claim=False,windows=results,decision=decision,interpretation=plan['interpretation'])
    packed = gzip.compress(encode(report),mtime=0)
    body = render_readout(results,decision)
    if len(packed) > BOUNDS['output_gzip_bytes'] or len(body) > BOUNDS['readout_bytes']:
        raise ValueError('derived output exceeds frozen caps')
    verify_plan(plan_path,expected_sha)
    output, readout = Path(output),Path(readout)
    if output == readout or output.exists() or readout.exists():
        raise FileExistsError('immutable output exists or paths coincide')
    publish_exclusive(output,packed); publish_exclusive(readout,body)
    return dict(gzip_bytes=len(packed),readout_bytes=len(body),protocol_sha256=expected_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--expected-plan-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--readout',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan,args.expected_plan_sha256,args.output,args.readout)))


if __name__ == '__main__':
    main()
