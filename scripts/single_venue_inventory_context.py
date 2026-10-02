#!/usr/bin/env python3
"""Frozen exploratory inventory-context anchors and delayed public quotes.

Position interpretation is sample-supported signed per-fill arithmetic. Public
quotes are conditional observations, not our fills or evidence of passive access.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
import ctypes
from decimal import Decimal as D, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from scripts import single_venue_depth_events as events
from scripts import single_venue_depth_capture as capture
from scripts import rolling_research_capture as rolling
from scripts.single_venue_shock_controls import QuoteProfiles
from scripts.audit_single_venue_study import clock, NS, VS
from scripts.single_venue_residual_profile import exactmid, sweep
from scripts.single_venue_strategy import dec, rounded
from scripts.single_venue_broad_quotes import distribution

PLAN = ROOT / 'reports/experiment-storage/single-venue-inventory-context-v1.json'
OUT = ROOT / 'reports/single-venue-research'
OWNER = 'inventory_context_v1'
BATCHES = {1: ['chunk-000001', 'chunk-000002', 'chunk-000003'],
           2: ['chunk-000007', 'chunk-000008', 'chunk-000009']}
PARAMS = dict(anchor_start_seconds=30, anchor_stop_seconds=570, anchor_step_seconds=30,
    latest_trade_max_age_ms=2000, decision_book_max_age_ms=2000,
    prior_return_seconds=10, prior_book_tolerance_ms=250, flow_seconds=10,
    book_history_max_points=50000, control_lookback_seconds=180,
    control_c0_caliper_bps='1', control_signed_return_caliper_bps='2',
    control_signed_flow_caliper='0.25', direction='fade_latest_aggressor',
    native_notional_cap='100', entry_delay_ms=400, hold_seconds=10,
    exit_delay_ms=400, stage_max_lateness_ms=2000, funding_exclusion_span_ms=14800,
    extra_roundtrip_stress_bps=[1, 2, 5], followup_min_pairs_each_batch=3,
    classification='sample_supported_signed_per_fill', chronology_failure='latest_source_group_unusable',
    optional_flag='descriptive_only', control_tie='earlier_anchor',
    control_distance='sum_normalized_absolute_feature_distance')
RAW_CAP = 67108864 + 262144
MAX_OUTPUT = 180224
MAX_PROVENANCE = 16384
MAX_GROUP = 50000


def decimals(value):
    if isinstance(value, D):
        return str(value)
    if isinstance(value, dict):
        return {str(k): decimals(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimals(x) for x in value]
    return value


def encode(value):
    return (json.dumps(decimals(value), separators=(',', ':'), allow_nan=False)+'\n').encode()


def publish(path, body):
    """Atomic Linux no-replace publication, including concurrent writers."""
    temporary = path.with_name('.'+path.name+'.tmp')
    with temporary.open('xb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100, os.fsencode(temporary), -100, os.fsencode(path), 1):
        error = ctypes.get_errno(); temporary.unlink()
        raise OSError(error, os.strerror(error), str(path))


def exact_string(value):
    if not isinstance(value, str):
        raise ValueError('optional position must be a numeric string')
    number = D(value)
    if not number.is_finite():
        raise ValueError('nonfinite number')
    return number


def inventory_class(position, signed_quantity):
    if position == 0 or position*signed_quantity > 0:
        return 'adding', None
    if abs(signed_quantity) <= abs(position):
        return 'reducing', None
    return 'unknown', 'reversal'


class MessageEnricher:
    """Inspect only the received message; grouping and output exclude account IDs."""
    def __init__(self, original, metadata):
        self.original, self.metadata = original, metadata
        self.last_row = None
        self.parsed = {}
        self.seen = defaultdict(set)

    def scan(self, row, asset):
        self.last_row = row
        self.parsed = {}
        groups = defaultdict(list)
        seen = self.seen[row['venue'], asset, row['generation']]
        local = set()
        for raw in row.get('payload', {}).get('trades', []):
            if raw.get('type') != 'trade':
                continue
            ident = events.integer(raw.get('trade_id_str', raw.get('trade_id')), 'trade ID')
            if ident in seen or ident in local:
                continue
            local.add(ident)
            value = dict(inventory_class='unknown', inventory_reason=None,
                         flag='absent_unknown', transaction_time=0, chronology_valid=False)
            try:
                transaction = events.integer(raw.get('transaction_time'), 'transaction time')
                if transaction <= 0 or transaction*1000 > row['receipt_utc_ns']:
                    raise ValueError('optional transaction time invalid')
                value.update(transaction_time=transaction, chronology_valid=True)
            except (ValueError, TypeError):
                value['inventory_reason'] = 'missing_malformed_chronology'
            if 'taker_position_sign_changed' in raw:
                flag = raw['taker_position_sign_changed']
                value['flag'] = ('true' if flag else 'false') if isinstance(flag, bool) else 'malformed_unknown'
            p = None
            value['position_field'] = ('absent' if 'taker_position_size_before' not in raw
                else 'null' if raw['taker_position_size_before'] is None else 'malformed')
            try:
                p = exact_string(raw.get('taker_position_size_before'))
                value['position_field'] = 'valid_numeric_string'
            except (ValueError, InvalidOperation):
                pass
            try:
                q, price = D(str(raw['size'])), D(str(raw['price']))
                m = self.metadata[row['venue']][asset]
                if (not q.is_finite() or not price.is_finite() or q <= 0 or price <= 0
                        or q % D(m['qty_step']) or price % D(m['price_tick'])):
                    raise ValueError('native trade increment failure')
                value.update(exact_qty=q, exact_price=price)
                if p is None:
                    raise ValueError('optional position absent/null/malformed')
                if p % D(m['qty_step']):
                    raise ValueError('native position increment failure')
                value.update(position=p, signed_qty=q if raw['is_maker_ask'] else -q)
                value['inventory_class'], value['inventory_reason'] = inventory_class(p, value['signed_qty'])
            except (ValueError, InvalidOperation, KeyError, TypeError):
                value.update(inventory_class='unknown', inventory_reason='missing_malformed_or_native_failure')
            # Exact quantity remains useful for receipt flow even if position is
            # unknown; original adapter independently validates ordinary prints.
            value.setdefault('exact_qty', D(str(raw['size'])))
            value.setdefault('exact_price', D(str(raw['price'])))
            self.parsed[ident] = value
            side = 'bid' if raw['is_maker_ask'] else 'ask'
            order = raw.get(side+'_id_str', raw.get(side+'_id'))
            if order is None:
                value.update(inventory_class='unknown', inventory_reason='missing_taker_order')
            else:
                groups[side, str(order)].append((ident, value))
        seen.update(local)
        if len(seen) > 500000:
            raise ValueError('trade identity bound exceeded')
        for rows in groups.values():
            ordered = sorted(rows, key=lambda x: (x[1]['transaction_time'], x[0]))
            bad = any('position' not in v or 'signed_qty' not in v or not v['transaction_time'] for _, v in ordered)
            bad = bad or any(b['position'] != a['position']+a['signed_qty']
                             for (_, a), (_, b) in zip(ordered, ordered[1:]))
            if bad:
                for _, value in ordered:
                    value.update(inventory_class='unknown', inventory_reason='message_order_arithmetic_failure')

    def __call__(self, row, raw, market, asset, hedge_venue):
        value = self.original(row, raw, market, asset, hedge_venue)
        if row is not self.last_row:
            self.scan(row, asset)
        value.update(self.parsed.get(value['trade_id'], dict(
            exact_qty=D(str(raw['size'])), exact_price=D(str(raw['price'])),
            inventory_class='unknown', inventory_reason='duplicate_not_classified',
            transaction_time=0, chronology_valid=False, flag='absent_unknown', position_field='duplicate')))
        return value


@contextmanager
def adapter_configuration():
    replacements = {
        events: dict(HARD_BYTES=RAW_CAP, METADATA_MAX_BYTES=131072,
            MAX_DECODED_BYTES=1024**3, MAX_RECORDS=1_000_000, MAX_TRADE_IDS=500000),
        capture: dict(SELECTED=rolling.SELECTED, HARD_BYTES=RAW_CAP, METADATA_MAX_BYTES=131072)}
    old = {module: {key: getattr(module, key) for key in values}
           for module, values in replacements.items()}
    try:
        for module, values in replacements.items():
            for key, value in values.items():
                setattr(module, key, value)
        yield
    finally:
        for module, values in old.items():
            for key, value in values.items():
                setattr(module, key, value)


class InventoryProfiles(QuoteProfiles):
    def process(self, event):
        pending = [r for rows in self.pending.values() for r in rows]
        super().process(event)
        for row in pending:
            if row['status'] != 'matched' or 'net_quote_bps' in row:
                continue
            entry, exit_value = dec(row['entry']['value']), dec(row['exit']['value'])
            fee = dec(self.metadata[row['venue']][row['asset']]['taker_fee_bps'])
            fees = (entry+exit_value)*fee/10000
            gross = D(row['direction'])*(exit_value-entry)
            net = (gross-fees)/entry*10000
            row.update(gross_cash=gross, fee_cash=fees, net_cash=gross-fees,
                net_quote_bps=net, net_after_extra_bps={str(bp): net-bp for bp in (1, 2, 5)})


def funding_crosses(now):
    hour = 3600*NS
    return (now//hour+1)*hour <= now+14_800_000_000


def immediate_cost(book, metadata, direction):
    qty = rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')), metadata['qty_step'])
    if qty < dec(metadata['min_qty']) or qty*dec(book['bids'][0][0]) < dec(metadata['min_notional']):
        return None, 'native_minimum_reject'
    entry, exit_value = sweep(book, direction, qty), sweep(book, -direction, qty)
    if entry is None or exit_value is None:
        return None, 'insufficient_immediate_depth'
    if entry > 100:
        return None, 'immediate_entry_quote_above_cap'
    fees = (entry+exit_value)*dec(metadata['taker_fee_bps'])/10000
    return (D(direction)*(entry-exit_value)+fees)/entry*10000, None


def select_control(earlier, row):
    if not row['features_usable']:
        return None, 'reducing_features_unusable'
    candidates = []
    for old in earlier:
        if (old['class'] != 'adding' or not old['features_usable']
                or old['aggressor'] != row['aggressor']
                or not 0 < row['anchor_ns']-old['anchor_ns'] <= 180*NS):
            continue
        diffs = [abs(old[k]-row[k]) for k in ('c0_bps', 'signed_return_bps', 'signed_flow')]
        bounds = [D(1), D(2), D('.25')]
        if all(x <= y for x, y in zip(diffs, bounds)):
            candidates.append((sum((x/y for x, y in zip(diffs, bounds)), D(0)), old['anchor_ns'], old))
    if not candidates:
        return None, 'no_earlier_adding_within_calipers'
    return min(candidates, key=lambda x: x[:2])[2], 'selected'


class ContextStudy:
    def __init__(self, metadata, start, chunk='synthetic', assets=None):
        self.metadata, self.start, self.chunk = metadata, start, chunk
        self.assets = tuple(rolling.ASSETS if assets is None else assets)
        self.profiles = InventoryProfiles(metadata)
        self.states = {}
        self.counts = defaultdict(Counter)
        self.rows = []
        self.earlier = defaultdict(list)
        self.next_anchor = start+30*NS
        self.last_time = start
        self.ended = False
        self.non_market = Counter()

    def state(self, key):
        return self.states.setdefault(key, dict(generation=None, since=None,
            books=deque(), flows=deque(), latest=None, latest_source_chronology_unknown=False))

    def reset(self, key, now, reason):
        self.states.pop(key, None)
        self.earlier[key].clear()
        self.profiles.process(dict(type='invalidate', asset=key[0], venue=key[1], received_ns=now))
        self.counts[key]['state_reset:'+reason] += 1

    def anchor(self, now):
        for asset in self.assets:
            for venue in VS:
                key = asset, venue; c = self.counts[key]; c['scheduled'] += 1
                state = self.state(key)
                row = dict(id=len(self.rows), asset=asset, venue=venue, anchor_ns=now,
                    class_='unknown', features_usable=False, feature_failure=None,
                    profile=None, control_id=None, control_selection='not_reducing')
                row['class'] = row.pop('class_')
                self.rows.append(row)
                if funding_crosses(now):
                    row['anchor_failure'] = 'funding_boundary_unknown'; c['funding_boundary_unknown'] += 1
                    continue
                book = self.profiles.books[asset].get(venue)
                if not clock(book, now):
                    row['anchor_failure'] = 'decision_book_unusable'; c['decision_book_unusable'] += 1
                    continue
                trade = state['latest']
                if (trade is None or not trade.get('clock_valid')
                        or not 0 <= now-trade['received_ns'] <= 2*NS
                        or not 0 <= now-trade['source_ns'] <= 2*NS):
                    row['anchor_failure'] = 'latest_trade_absent_or_stale'; c['latest_trade_absent_or_stale'] += 1
                    continue
                if state['latest_source_chronology_unknown']:
                    row['anchor_failure'] = 'latest_source_chronology_unknown'
                    c['latest_source_chronology_unknown'] += 1
                    continue
                sign = 1 if trade['buy_aggressor'] else -1
                row.update(aggressor=sign, **{'class': trade['inventory_class']},
                    classification_reason=trade['inventory_reason'], flag=trade['flag'],
                    trade_source_age_ns=now-trade['source_ns'], trade_receipt_age_ns=now-trade['received_ns'])
                c['class:'+row['class']] += 1; c['flag:'+row['flag']] += 1
                row['profile'] = self.profiles.request(asset, venue, -sign, now, row['class'])
                c['local_profiles'] += 1
                c0, failure = immediate_cost(book, self.metadata[venue][asset], -sign)
                row['c0_bps'] = c0
                prior = next((p for p in reversed(state['books']) if p['t'] <= now-10*NS), None)
                flows = [f for f in state['flows'] if now-10*NS < f['t'] <= now]
                total = sum((f['qty'] for f in flows), D(0))
                if failure:
                    row['feature_failure'] = failure
                elif (state['since'] is None or state['since'] > now-10*NS or prior is None
                        or now-10*NS-prior['t'] > 250_000_000
                        or not 0 <= now-10*NS-prior['source'] <= 250_000_000):
                    row['feature_failure'] = 'missing_or_interrupted_prior_book'
                elif total <= 0 or any(f['age'] > 2*NS for f in flows):
                    row['feature_failure'] = 'missing_or_stale_flow_history'
                else:
                    row.update(features_usable=True,
                        signed_return_bps=D(sign)*(exactmid(book)-prior['mid'])/prior['mid']*10000,
                        signed_flow=D(sign)*sum((f['signed_qty'] for f in flows), D(0))/total)
                c['features_usable' if row['features_usable'] else 'feature_failure:'+row['feature_failure']] += 1
                if row['class'] == 'reducing':
                    control, reason = select_control(self.earlier[key], row)
                    row['control_selection'] = reason; c['control:'+reason] += 1
                    if control is not None:
                        row['control_id'] = control['id']
                self.earlier[key].append(row)

    def fire_before(self, now, inclusive=False):
        stop = self.start+570*NS
        while self.next_anchor <= stop and (self.next_anchor <= now if inclusive else self.next_anchor < now):
            self.anchor(self.next_anchor); self.next_anchor += 30*NS

    def process_group(self, group):
        if not group:
            return
        now = group[0]['received_ns']
        if now < self.last_time or any(e['received_ns'] != now for e in group):
            raise ValueError('receipt grouping/order differs')
        if self.ended:
            raise ValueError('events after terminal')
        self.fire_before(now); self.last_time = now
        terminal = None
        for event in group:
            kind = event['type']
            if kind == 'end':
                terminal = event; continue
            if event.get('asset') not in self.assets or event.get('venue') not in VS:
                if kind != 'control':
                    raise ValueError('unexpected event without selected market')
                self.non_market[kind] += 1; continue
            key = event['asset'], event['venue']
            if kind == 'invalidate':
                self.reset(key, now, event.get('reason', 'invalidated')); continue
            state = self.state(key)
            generation = event.get('generation')
            if state['generation'] is not None and generation != state['generation']:
                self.reset(key, now, 'generation_changed'); state = self.state(key)
            state['generation'] = generation
            self.profiles.process(event)
            if kind == 'book' and clock(event, now):
                if state['since'] is None:
                    state['since'] = now
                state['books'].append(dict(t=now, source=event['source_ns'], mid=exactmid(event)))
                while state['books'] and state['books'][0]['t'] < now-12*NS:
                    state['books'].popleft()
                if len(state['books']) > MAX_GROUP:
                    raise ValueError('bounded book history exceeded')
            if kind == 'trade':
                chronology = event['source_ns'], event['transaction_time'], event['trade_id']
                old = state['latest']
                if old is None or event['source_ns'] > old['source_ns']:
                    state['latest_source_chronology_unknown'] = not event['chronology_valid']
                elif event['source_ns'] == old['source_ns']:
                    state['latest_source_chronology_unknown'] |= not event['chronology_valid']
                if old is None or chronology > (old['source_ns'], old['transaction_time'], old['trade_id']):
                    state['latest'] = event
                q = event['exact_qty']; sign = 1 if event['buy_aggressor'] else -1
                state['flows'].append(dict(t=now, qty=q, signed_qty=D(sign)*q, age=now-event['source_ns']))
                self.counts[key]['live_prints'] += 1
                self.counts[key]['print_class:'+event['inventory_class']] += 1
                self.counts[key]['print_flag:'+event['flag']] += 1
                self.counts[key]['print_position_field:'+event['position_field']] += 1
                if not event['chronology_valid']:
                    self.counts[key]['print_chronology_unknown'] += 1
                if event['inventory_reason'] is not None:
                    self.counts[key]['print_unknown_reason:'+event['inventory_reason']] += 1
                if len(state['flows']) > MAX_GROUP:
                    raise ValueError('bounded flow history exceeded')
            while state['flows'] and state['flows'][0]['t'] <= now-12*NS:
                state['flows'].popleft()
        self.fire_before(now, inclusive=True)
        if terminal is not None:
            self.profiles.process(terminal); self.ended = True; self.states.clear()

    def result(self):
        if not self.ended:
            raise ValueError('adapter terminal was not consumed')
        if any(p['status'].startswith('pending') for p in self.profiles.rows):
            raise ValueError('pending quote obligation survived terminal')
        by_id = {r['id']: r for r in self.rows}
        for row in self.rows:
            control = by_id.get(row['control_id'])
            if control is None:
                continue
            left, right = row['profile'], control['profile']
            row['control_status'] = right['status']
            if left['status'] == right['status'] == 'matched':
                row.update(pair_net_quote_delta_bps=dec(left['net_quote_bps'])-dec(right['net_quote_bps']),
                    pair_signed_midpoint_delta_bps=dec(left['midpoint_bps'])-dec(right['midpoint_bps']))
                if 'quote_minus_reference_bps' in left and 'quote_minus_reference_bps' in right:
                    row['pair_net_quote_minus_reference_delta_bps'] = (
                        dec(left['quote_minus_reference_bps'])-dec(right['quote_minus_reference_bps'])
                        -(dec(left['quote_bps'])-dec(left['net_quote_bps']))
                        +(dec(right['quote_bps'])-dec(right['net_quote_bps'])))
        return dict(chunk=self.chunk, anchors=self.rows,
            rows=summarize(self.rows, self.counts, self.assets), non_market_events=dict(self.non_market))


def summarize(anchors, counts, assets):
    rows = []
    for asset in assets:
        for venue in VS:
            chosen = [r for r in anchors if (r['asset'], r['venue']) == (asset, venue)]
            reducing = [r['profile'] for r in chosen if r['class'] == 'reducing' and r['profile'] is not None]
            complete = [p for p in reducing if p['status'] == 'matched']
            matched = [r for r in chosen if 'pair_net_quote_delta_bps' in r]
            controls = Counter(r['control_id'] for r in chosen if r['control_id'] is not None)
            rows.append(dict(asset=asset, venue=venue, counts=dict(counts[asset, venue]),
                anchor_failures=dict(Counter(r['anchor_failure'] for r in chosen if 'anchor_failure' in r)),
                local_outcomes=dict(Counter(r['profile']['status'] for r in chosen if r['profile'] is not None)),
                reducing_outcomes=dict(Counter(p['status'] for p in reducing)),
                selected_control_outcomes=dict(Counter(r['control_status'] for r in chosen if 'control_status' in r)),
                distinct_selected_controls=len(controls), reused_control_selections=sum(n-1 for n in controls.values()),
                complete_matched_pairs=len(matched),
                reducing_net_quote_bps=distribution([dec(p['net_quote_bps']) for p in complete]),
                reducing_positive_after_extra_bps={str(bp):sum(dec(p['net_quote_bps']) > bp for p in complete) for bp in (0,1,2,5)},
                paired_net_quote_delta_bps=distribution([r['pair_net_quote_delta_bps'] for r in matched]),
                paired_signed_midpoint_delta_bps=distribution([r['pair_signed_midpoint_delta_bps'] for r in matched]),
                paired_reference_available=sum('pair_net_quote_minus_reference_delta_bps' in r for r in matched),
                paired_net_quote_minus_reference_delta_bps=distribution([r['pair_net_quote_minus_reference_delta_bps'] for r in matched if 'pair_net_quote_minus_reference_delta_bps' in r])))
    return rows


def check_inputs(store, plan, batch):
    if plan.get('schema') != 'single-venue-inventory-context-v1' or plan.get('pin_owner') != OWNER:
        raise ValueError('inventory context plan schema/owner differs')
    if plan.get('store_root') != 'data/rolling/market-research-v1':
        raise ValueError('fixed rolling store differs')
    if plan.get('parameters') != PARAMS:
        raise ValueError('frozen inventory context parameters differ')
    if plan.get('output_caps') != dict(gzip_per_batch=MAX_OUTPUT,
            provenance_per_batch=MAX_PROVENANCE, readout_per_batch=16384):
        raise ValueError('frozen output caps differ')
    chosen = next((x['chunks'] for x in plan['batches'] if x['index'] == batch), None)
    if chosen != BATCHES[batch]:
        raise ValueError('fixed batch chunks differ')
    identity_path = store.root / 'identity.json'
    identity = rolling.read_json(identity_path, 16384)
    if (rolling.digest(identity_path) != plan['store_identity_sha256']
            or identity['plan_sha256'] != plan['capture_parent_plan_sha256']
            or identity.get('schema') != 'rolling-research-store-v1'
            or identity.get('budget_bytes') != 2_000_000_000):
        raise ValueError('store identity/parent hash differs')
    index = store.index()
    records = []
    for name in chosen:
        entry = index['chunks'].get(name)
        if (not entry or entry.get('state') != 'sealed_complete' or entry.get('role') != 'exploratory'
                or OWNER not in entry.get('pins', [])):
            raise ValueError('input must be sealed complete, exploratory and already pinned')
        directory = store.root / name
        files = store.files(directory)
        seal_path = directory / 'seal.json'; seal = rolling.read_json(seal_path, 65536)
        if (rolling.digest(seal_path) != entry['seal_sha256'] or seal.get('chunk_id') != name
                or seal.get('state') != 'sealed_complete' or seal.get('role') != 'exploratory'
                or set(files)-{'seal.json'} != set(seal['files'])):
            raise ValueError('seal identity/inventory differs')
        for relative, item in seal['files'].items():
            if files[relative] != item['bytes'] or rolling.digest(directory / relative) != item['sha256']:
                raise ValueError('sealed input file differs')
        manifest_path = directory / 'capture/manifest.json'
        manifest = rolling.read_json(manifest_path, 65536)
        raw = directory / 'capture/frames.jsonl.gz'
        if (manifest.get('selected_markets') != rolling.SELECTED
                or manifest.get('configured_seconds') != 600
                or manifest.get('configured_total_bytes') != RAW_CAP
                or manifest.get('end_reason') != 'duration_limit' or manifest.get('truncated') is not False
                or rolling.digest(raw) != manifest['frames_sha256']):
            raise ValueError('capture identity/complete endpoint differs')
        records.append(dict(chunk=name, capture=str(directory / 'capture'),
            seal_sha256=entry['seal_sha256'], manifest_sha256=rolling.digest(manifest_path),
            raw_sha256=manifest['frames_sha256'], started_ns=rolling.utc_ns(manifest['started_utc']),
            ended_ns=rolling.utc_ns(manifest['ended_utc']),
            metadata_sha256={relative: item['sha256'] for relative, item in seal['files'].items()
                             if relative.startswith('capture/metadata/')}))
    return dict(store_identity_sha256=plan['store_identity_sha256'],
                capture_parent_plan_sha256=plan['capture_parent_plan_sha256'], inputs=records)


def feature_stream(record):
    directory = Path(record['capture'])
    normalized = rolling.read_json(directory/'metadata/normalized.json', 131072)
    study = ContextStudy(normalized['markets'], record['started_ns'], record['chunk'])
    original = events._trade
    events._trade = MessageEnricher(original, normalized['markets'])
    group = []; last = None; terminal = None
    try:
        for event in events.iter_events(directory, expected_manifest_sha256=record['manifest_sha256'],
                expected_raw_sha256=record['raw_sha256'], max_raw_bytes=RAW_CAP,
                max_decoded_bytes=1024**3, max_records=1_000_000, max_ids=500000):
            now = event['received_ns']
            if last is not None and now != last:
                study.process_group(group); group = []
            if len(group) >= MAX_GROUP:
                raise ValueError('same-receipt event group exceeds bound')
            group.append(event); last = now
            if event['type'] == 'end':
                terminal = event
        study.process_group(group)
    finally:
        events._trade = original
    result = study.result()
    if terminal is None or terminal['truncated'] or terminal['reason'] != 'duration_limit':
        raise ValueError('adapter did not verify a complete capture')
    if len(result['anchors']) != 19*len(rolling.ASSETS)*len(VS):
        raise ValueError('complete calendar denominator differs')
    result['adapter'] = {key: terminal[key] for key in ('decoded_bytes', 'archive_bytes',
        'counts', 'metadata_sha256', 'raw_gzip_sha256', 'manifest_sha256', 'max_receipt_gap_ns')}
    return result


def run(batch, plan_path=PLAN):
    plan = rolling.read_json(plan_path, 16384)
    plan_hash = rolling.digest(plan_path)
    if not plan.get('source_pins'):
        raise ValueError('root must freeze source pins before running')
    if rolling.digest(rolling.PLAN) != plan['capture_parent_plan_sha256']:
        raise ValueError('current capture parent plan differs')
    for pin in plan['source_pins']:
        relative = Path(pin['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('source pin must be a workspace relative path')
        path = ROOT/relative; rolling.regular(path)
        if rolling.digest(path) != pin['sha256']:
            raise ValueError('frozen source pin differs')
    destination = OUT/f'inventory-context-batch{batch}.json.gz'
    provenance_path = OUT/f'inventory-context-batch{batch}-provenance.json'
    if destination.exists() or provenance_path.exists():
        raise FileExistsError('immutable inventory output already exists')
    store = rolling.Store()
    with store.locked():
        if destination.exists() or provenance_path.exists():
            raise FileExistsError('immutable inventory output already exists')
        before = check_inputs(store, plan, batch)
    with adapter_configuration():
        results = [feature_stream(record) for record in before['inputs']]
    combined_counts = defaultdict(Counter)
    for chunk in results:
        for row in chunk['rows']:
            combined_counts[row['asset'], row['venue']].update(row['counts'])
    # Chunk-local integer IDs become tuple identities for batch control reuse.
    combined = []
    for chunk in results:
        for original in chunk['anchors']:
            row = dict(original)
            row['id'] = (chunk['chunk'], row['id'])
            if row['control_id'] is not None:
                row['control_id'] = (chunk['chunk'], row['control_id'])
            combined.append(row)
    summary = summarize(combined, combined_counts, rolling.ASSETS)
    with store.locked():
        after = check_inputs(store, plan, batch)
        if before != after:
            raise ValueError('input provenance changed during analysis')
        if rolling.digest(plan_path) != plan_hash or any(
                rolling.digest(ROOT/pin['path']) != pin['sha256'] for pin in plan['source_pins']):
            raise ValueError('frozen plan/source changed during analysis')
        report = dict(schema='single-venue-inventory-context-result-v1', batch=batch,
            economic_evaluation='conditional_public_quotes_only', validation_claim=False,
            plan_sha256=plan_hash, parameters=PARAMS, rows=summary, chunks=results,
            interpretation='Sample-supported signed per-fill context. Active public quotes are not fills, passive evidence, trader intent or parent completion. Reference is conditional midpoint accounting; local observations remain when unavailable.')
        packed = gzip.compress(encode(report), mtime=0)
        if len(packed) > MAX_OUTPUT:
            raise ValueError('bounded inventory output exceeds allocation')
        provenance = dict(schema='single-venue-inventory-context-provenance-v1', batch=batch,
            plan_sha256=plan_hash, source_pins=plan['source_pins'], **before,
            output_sha256=hashlib.sha256(packed).hexdigest())
        body = encode(provenance)
        if len(body) > MAX_PROVENANCE:
            raise ValueError('provenance exceeds allocation')
        OUT.mkdir(parents=True, exist_ok=True)
        publish(provenance_path, body); publish(destination, packed)
    print(json.dumps(dict(batch=batch, gzip_bytes=len(packed), provenance_bytes=len(body),
        scheduled_anchors=len(combined), complete_matched_pairs=sum(r['complete_matched_pairs'] for r in summary))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, choices=(1, 2), required=True)
    run(parser.parse_args().batch)


if __name__ == '__main__':
    main()
