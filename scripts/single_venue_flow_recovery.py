#!/usr/bin/env python3
"""Past-feature activation preflight only: no returns, quotes, fills or cash.

Root must freeze the plan and explicitly pin each named exploratory chunk before
running a batch. Book validity comes from the reused adapter, not the rolling
coverage invalid_frames counter (which includes valid initial snapshots).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
import ctypes
from decimal import Decimal as D
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

PLAN = ROOT / 'reports/experiment-storage/single-venue-flow-recovery-v1.json'
OUT = ROOT / 'reports/single-venue-research'
NS = 10**9
OWNER = 'flow_recovery_v1'
BATCHES = {1: ['chunk-000001', 'chunk-000002', 'chunk-000003'],
           2: ['chunk-000007', 'chunk-000008', 'chunk-000009']}
PARAMS = dict(receipt_bucket_seconds=1, background_seconds=60,
    min_background_live_prints=20, min_background_distinct_receipt_buckets=10,
    dominant_share='0.80', dominant_quantity_over_predepth='0.25', fixed_band_bps='5',
    minimum_depletion='0.25', prebook_max_age_ms=250, postbook_max_lateness_ms=500,
    anchor_book_max_age_ms=250,
    confirmation_seconds=2, confirmation_max_lateness_ms=500,
    max_trade_receipt_source_age_ms=500, slow_continuation_max='0.25', recovery_min='0.50',
    persistent_continuation_min='0.75', persistent_recovery_max='0',
    episode_spacing_seconds=30, admission_start_seconds=60, admission_stop_seconds=570)
RAW_CAP = 67108864 + 262144
MAX_OUTPUT = 180224
MAX_PROVENANCE = 16384
MAX_EVENTS = 1000


def decimals(value):
    if isinstance(value, D):
        return str(value)
    if isinstance(value, dict):
        return {str(k): decimals(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimals(x) for x in value]
    return value


def encode(value):
    return (json.dumps(decimals(value), separators=(',', ':'), allow_nan=False) + '\n').encode()


def publish(path, body):
    """Linux atomic publication with RENAME_NOREPLACE; never replace evidence."""
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100, os.fsencode(temporary), -100, os.fsencode(path), 1) != 0:
        error = ctypes.get_errno()
        temporary.unlink()
        raise OSError(error, os.strerror(error), str(path))


def enrich_trade(original, row, raw, market, asset, hedge_venue):
    value = original(row, raw, market, asset, hedge_venue)
    qty, price = D(str(raw['size'])), D(str(raw['price']))
    if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0:
        raise ValueError('invalid exact trade quantity/price')
    side = 'bid' if raw['is_maker_ask'] else 'ask'
    ident = raw.get(side + '_id_str', raw.get(side + '_id'))
    version = raw.get(side + '_order_version')
    value.update(exact_qty=qty, exact_price=price,
        observed_group=(side, str(ident), str(version), value['source_ns'])
            if ident is not None and version is not None else None)
    return value


@contextmanager
def adapter_configuration():
    """Isolated process-local overrides; every frozen module is restored."""
    replacements = {
        events: dict(HARD_BYTES=RAW_CAP, METADATA_MAX_BYTES=131072,
            MAX_DECODED_BYTES=1024**3, MAX_RECORDS=1_000_000, MAX_TRADE_IDS=500000),
        capture: dict(SELECTED=rolling.SELECTED, HARD_BYTES=RAW_CAP,
                      METADATA_MAX_BYTES=131072),
    }
    old = {module: {key: getattr(module, key) for key in values}
           for module, values in replacements.items()}
    original = events._trade
    try:
        for module, values in replacements.items():
            for key, value in values.items():
                setattr(module, key, value)
        events._trade = lambda *args: enrich_trade(original, *args)
        yield
    finally:
        events._trade = original
        for module, values in old.items():
            for key, value in values.items():
                setattr(module, key, value)


def levels(book, side, metadata):
    rows = book['asks' if side == 1 else 'bids']
    tick, step = D(metadata['price_tick']), D(metadata['qty_step'])
    result = [(D(str(p)), D(str(q))) for p, q in rows]
    if not result or tick <= 0 or step <= 0:
        raise ValueError('missing native levels')
    for i, (price, qty) in enumerate(result):
        if (not price.is_finite() or not qty.is_finite() or price <= 0 or qty <= 0
                or price % tick or qty % step):
            raise ValueError('invalid native price/quantity level')
        if i and (price <= result[i-1][0] if side == 1 else price >= result[i-1][0]):
            raise ValueError('native levels not strictly ordered')
    return result


def band_depth(book, side, band, metadata):
    rows = levels(book, side, metadata)
    return depth_from_levels(rows, side, band)


def depth_from_levels(rows, side, band):
    low, high = band
    # A touch beyond the band proves zero displayed depth in it, even if the
    # first available level is far outside its former boundary.
    if (side == 1 and rows[0][0] > high) or (side == -1 and rows[0][0] < low):
        return D(0)
    if (side == 1 and rows[-1][0] < high) or (side == -1 and rows[-1][0] > low):
        raise ValueError('displayed boundary does not cover fixed band')
    return sum((qty for price, qty in rows if low <= price <= high), D(0))


def point(book, metadata):
    if (not book.get('valid') or not book.get('clock_valid')
            or not isinstance(book.get('sequence'), int)
            or not 0 < book['source_ns'] <= book['received_ns']):
        raise ValueError('invalid book clock/sequence')
    bids, asks = levels(book, -1, metadata), levels(book, 1, metadata)
    bid, ask = bids[0][0], asks[0][0]
    if bid >= ask:
        raise ValueError('crossed native book')
    buy_band, sell_band = (ask, ask * D('1.0005')), (bid * D('.9995'), bid)
    depths = {}
    for side, band, rows in ((1, buy_band, asks), (-1, sell_band, bids)):
        try:
            depths[side] = depth_from_levels(rows, side, band)
        except ValueError:
            depths[side] = None
    return dict(t=book['received_ns'], source=book['source_ns'], sequence=book['sequence'],
        generation=book['generation'], bands={1: buy_band, -1: sell_band}, depths=depths,
        spread_bps=(ask-bid) / ((ask+bid)/2) * 10000,
        imbalance=(bids[0][1]-asks[0][1]) / (bids[0][1]+asks[0][1]))


def flow_bin():
    return dict(buy=D(0), sell=D(0), buy_notional=D(0), sell_notional=D(0), prints=0,
        source_min=None, source_max=None, max_age_ns=0, groups=set(), missing_groups=0,
        closed=False)


def flow_summary(flow):
    return {key: value for key, value in flow.items() if key not in ('groups', 'closed')} | {
        'observed_groups': len(flow['groups'])}


class Preflight:
    def __init__(self, metadata, start, chunk='synthetic'):
        self.metadata = metadata
        self.start = start
        self.chunk = chunk
        self.states = {}
        self.counts = defaultdict(Counter)
        self.waiting_post = []
        self.waiting_confirmation = []
        self.rows = []
        self.last_episode = {}
        self.last_time = start
        self.last_bucket_tick = -1
        self.ended = False

    def state(self, key):
        return self.states.setdefault(key, dict(generation=None, since=None,
            books=deque(maxlen=256), flows={}))

    def reject(self, candidate, reason):
        c = self.counts[candidate['key']]
        c['rejected'] += 1; c['reject:' + reason] += 1

    def fail(self, row, reason, now):
        self.counts[row['key']]['unusable'] += 1
        self.counts[row['key']]['failure:' + reason] += 1
        row.update(status='unusable', category=None, failure=reason, failure_observed_ns=now)
        self.rows.append(row)

    def reset(self, key, reason, now):
        for candidate in list(self.waiting_post):
            if candidate['key'] == key:
                self.reject(candidate, reason); self.waiting_post.remove(candidate)
        for row in list(self.waiting_confirmation):
            if row['key'] == key:
                self.fail(row, reason, now); self.waiting_confirmation.remove(row)
        self.states[key] = dict(generation=None, since=None, books=deque(maxlen=256), flows={})
        self.counts[key]['state_reset:' + reason] += 1

    def tick(self, now):
        if now < self.last_time:
            raise ValueError('receipt stream moved backward')
        self.last_time = now
        elapsed_second = (now-self.start)//NS
        if elapsed_second > self.last_bucket_tick:
            self.last_bucket_tick = elapsed_second
            for key, state in self.states.items():
                for second, flow in state['flows'].items():
                    end = self.start + (second + 1) * NS
                    if not flow['closed'] and end <= now:
                        flow['closed'] = True
                        if 60 <= second < 570:
                            self.candidate(key, second, flow)
                cutoff = elapsed_second - 63
                for second in list(state['flows']):
                    if second < cutoff:
                        del state['flows'][second]
        for candidate in list(self.waiting_post):
            if now > candidate['end'] + NS//2:
                self.reject(candidate, 'missing_post_anchor'); self.waiting_post.remove(candidate)
        for row in list(self.waiting_confirmation):
            if now > row['due'] + NS//2:
                self.fail(row, 'missing_confirmation_anchor', now)
                self.waiting_confirmation.remove(row)

    def candidate(self, key, second, flow):
        self.counts[key]['candidates_considered'] += 1
        state = self.state(key); t0 = self.start + second*NS
        seed = dict(key=key, second=second, t0=t0, end=t0+NS,
                    generation=state['generation'], burst=flow_summary(flow))
        background = [(i, x) for i, x in state['flows'].items() if second-60 <= i < second and x['prints']]
        count = sum(x['prints'] for _, x in background)
        seed.update(background_prints=count, background_bins=len(background))
        if (state['since'] is None or state['since'] > t0-60*NS
                or count < 20 or len(background) < 10):
            self.reject(seed, 'sparse_or_interrupted_background'); return
        if flow['max_age_ns'] > NS//2:
            self.reject(seed, 'stale_trade_interval'); return
        side = 1 if flow['buy'] >= flow['sell'] else -1
        dominant = flow['buy' if side == 1 else 'sell']
        if dominant < D('.8') * (flow['buy']+flow['sell']):
            self.reject(seed, 'dominant_share'); return
        pre = next((b for b in reversed(state['books'])
                    if b['t'] <= t0 and b['source'] <= flow['source_min']), None)
        if pre is None or pre['generation'] != state['generation']:
            self.reject(seed, 'missing_prebook'); return
        if not (0 <= t0-pre['t'] <= NS//4 and 0 <= t0-pre['source'] <= NS//4
                and pre['source'] <= flow['source_min']):
            self.reject(seed, 'prebook_clock'); return
        depth = pre['depths'][side]
        if depth is None:
            self.reject(seed, 'pre_band_uncovered'); return
        if depth <= 0 or dominant < D('.25') * depth:
            self.reject(seed, 'quantity_depth_fraction'); return
        seed.update(side=side, dominant_qty=dominant, pre_depth=depth, band=pre['bands'][side],
                    pre=pre, due=t0+3*NS)
        self.counts[key]['initial_filter_passed'] += 1
        self.waiting_post.append(seed)

    def trade(self, event):
        key = event['venue'], event['asset']; state = self.state(key)
        if state['generation'] not in (None, event['generation']):
            self.reset(key, 'generation_change', event['received_ns']); state = self.state(key)
        state['generation'] = event['generation']
        qty, price = event['exact_qty'], event['exact_price']
        if qty <= 0 or price <= 0 or event['source_ns'] > event['received_ns']:
            raise ValueError('invalid enriched live trade')
        second = (event['received_ns']-self.start)//NS
        if not 0 <= second <= 600:
            raise ValueError('trade outside capture')
        flow = state['flows'].setdefault(second, flow_bin())
        side = 'buy' if event['buy_aggressor'] else 'sell'
        flow[side] += qty; flow[side+'_notional'] += qty*price; flow['prints'] += 1
        flow['source_min'] = min(flow['source_min'] or event['source_ns'], event['source_ns'])
        flow['source_max'] = max(flow['source_max'] or event['source_ns'], event['source_ns'])
        age = event['received_ns']-event['source_ns']
        flow['max_age_ns'] = max(flow['max_age_ns'], age)
        if event.get('observed_group') is None:
            flow['missing_groups'] += 1
        else:
            flow['groups'].add(event['observed_group'])
        self.counts[key]['live_ordinary_prints'] += 1
        self.counts[key]['stale_background_prints'] += int(age > NS//2)

    def book(self, event):
        key = event['venue'], event['asset']; state = self.state(key)
        if state['generation'] not in (None, event['generation']):
            self.reset(key, 'generation_change', event['received_ns']); state = self.state(key)
        try:
            current = point(event, self.metadata[key[0]][key[1]])
        except ValueError:
            self.reset(key, 'native_book_or_clock_invalid', event['received_ns']); return
        state['generation'] = event['generation']
        if state['since'] is None:
            state['since'] = event['received_ns']
        state['books'].append(current)
        while state['books'] and state['books'][0]['t'] < event['received_ns']-3*NS:
            state['books'].popleft()
        self.counts[key]['valid_native_books'] += 1
        for candidate in list(self.waiting_post):
            if candidate['key'] != key or candidate['generation'] != current['generation']:
                continue
            pre = candidate['pre']
            if not (candidate['end'] <= current['t'] <= candidate['end']+NS//2
                    and 0 <= current['t']-current['source'] <= NS//4
                    and current['source'] >= candidate['burst']['source_max']
                    and current['source'] > pre['source'] and current['sequence'] > pre['sequence']):
                continue
            self.waiting_post.remove(candidate)
            try:
                depth = band_depth(event, candidate['side'], candidate['band'], self.metadata[key[0]][key[1]])
            except ValueError:
                self.reject(candidate, 'post_band_uncovered'); continue
            depletion = (candidate['pre_depth']-depth)/candidate['pre_depth']
            if depletion < D('.25'):
                self.reject(candidate, 'insufficient_first_post_depletion'); continue
            if current['t']-self.last_episode.get(key[1], -10**30) < 30*NS:
                self.reject(candidate, 'same_asset_episode_repeat'); continue
            self.last_episode[key[1]] = current['t']
            self.counts[key]['selected'] += 1
            candidate.update(post_depth=depth, initial_depletion=depletion,
                post=dict(receipt_ns=current['t'], source_ns=current['source'], sequence=current['sequence']),
                post_lateness_ns=current['t']-candidate['end'])
            self.waiting_confirmation.append(candidate)
        for row in list(self.waiting_confirmation):
            if row['key'] != key or row['generation'] != current['generation']:
                continue
            if not (row['due'] <= current['t'] <= row['due']+NS//2
                    and 0 <= current['t']-current['source'] <= NS//4
                    and current['source'] >= row['due']
                    and current['source'] > row['post']['source_ns']
                    and current['sequence'] > row['post']['sequence']):
                continue
            self.waiting_confirmation.remove(row)
            flows = [state['flows'].get(i, flow_bin()) for i in (row['second']+1, row['second']+2)]
            age = max(x['max_age_ns'] for x in flows)
            row.update(confirmation_max_trade_age_ns=age,
                confirmation_flows=[flow_summary(x) for x in flows],
                confirmation_lateness_ns=current['t']-row['due'],
                decision=dict(receipt_ns=current['t'], source_ns=current['source'], sequence=current['sequence'],
                              spread_bps=current['spread_bps']))
            if age > NS//2:
                self.fail(row, 'stale_trade_interval', current['t']); continue
            try:
                depth = band_depth(event, row['side'], row['band'], self.metadata[key[0]][key[1]])
            except ValueError:
                self.fail(row, 'confirmation_band_uncovered', current['t']); continue
            side = 'buy' if row['side'] == 1 else 'sell'
            qty = sum((x[side] for x in flows), D(0))
            continuation = (qty/2)/row['dominant_qty']
            recovery = (depth-row['post_depth'])/(row['pre_depth']-row['post_depth'])
            category = ('slow_recovered' if continuation <= D('.25') and recovery >= D('.5') else
                        'persistent_unrecovered' if continuation >= D('.75') and recovery <= 0 else 'intermediate')
            row.update(status='observed', category=category, decision_depth=depth,
                continuation=continuation, recovery=recovery, continuation_qty=qty,
                confirmation_live_prints=sum(x['prints'] for x in flows),
                observed_zero_continuation=qty == 0, trade_nonce_continuity='not_inferred',
                decision=dict(receipt_ns=current['t'], source_ns=current['source'], sequence=current['sequence'],
                              spread_bps=current['spread_bps']),
                confirmation_lateness_ns=current['t']-row['due'])
            self.counts[key][category] += 1
            self.rows.append(row)
        if len(self.rows)+len(self.waiting_confirmation) > MAX_EVENTS:
            raise ValueError('feature event cap exceeded')

    def process_group(self, group):
        if not group:
            return
        now = group[0]['received_ns']
        if any(event['received_ns'] != now for event in group):
            raise ValueError('receipt group contains different times')
        self.tick(now)
        # Same-receipt venue tie breaks are fixed; trade batching stays additive.
        priority = {'invalidate': 0, 'control': 1, 'trade': 2, 'book': 3, 'end': 4}
        for event in sorted(group, key=lambda e: (e['type'] == 'end', e.get('venue', ''), priority[e['type']])):
            kind = event['type']
            if kind == 'invalidate':
                self.reset((event['venue'], event['asset']), event['reason'], now)
            elif kind == 'trade':
                self.trade(event)
            elif kind == 'book':
                self.book(event)
            elif kind == 'end':
                for candidate in list(self.waiting_post):
                    self.reject(candidate, 'capture_end_missing_post')
                for row in list(self.waiting_confirmation):
                    self.fail(row, 'capture_end_missing_confirmation', now)
                self.waiting_post.clear(); self.waiting_confirmation.clear(); self.states.clear()
                self.ended = True

    def result(self):
        if not self.ended:
            raise ValueError('adapter terminal was not consumed')
        counts = []
        for asset in rolling.ASSETS:
            for venue in ('lighter', 'rh_lighter'):
                c = self.counts[venue, asset]
                if c['candidates_considered'] != c['rejected']+c['selected']:
                    raise ValueError('candidate counts do not reconcile')
                if c['selected'] != c['unusable']+c['slow_recovered']+c['persistent_unrecovered']+c['intermediate']:
                    raise ValueError('selected categories do not reconcile')
                counts.append(dict(asset=asset, venue=venue, counts=dict(c)))
        rows = []
        for original in self.rows:
            row = dict(original)
            row['venue'], row['asset'] = row.pop('key')
            pre = row.pop('pre')
            row['pre'] = {key: pre[key] for key in ('t', 'source', 'sequence', 'spread_bps', 'imbalance')}
            rows.append(row)
        return dict(chunk=self.chunk, rows=rows, counts=counts)


def check_inputs(store, plan, batch):
    if plan.get('schema') != 'single-venue-flow-recovery-v1' or plan.get('pin_owner') != OWNER:
        raise ValueError('flow preflight plan schema/owner differs')
    if plan.get('store_root') != 'data/rolling/market-research-v1':
        raise ValueError('fixed rolling store differs')
    if plan.get('parameters') != PARAMS:
        raise ValueError('frozen flow parameters differ')
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
    normalized = rolling.read_json(directory / 'metadata/normalized.json', 131072)
    detector = Preflight(normalized['markets'], record['started_ns'], record['chunk'])
    group = []; last = None; terminal = None
    for event in events.iter_events(directory, expected_manifest_sha256=record['manifest_sha256'],
            expected_raw_sha256=record['raw_sha256'], max_raw_bytes=RAW_CAP,
            max_decoded_bytes=1024**3, max_records=1_000_000, max_ids=500000):
        now = event['received_ns']
        if last is not None and now != last:
            detector.process_group(group); group = []
        if len(group) >= 50000:
            raise ValueError('same-receipt event group exceeds bound')
        group.append(event); last = now
        if event['type'] == 'end':
            terminal = event
    detector.process_group(group)
    result = detector.result()
    if terminal is None or terminal['truncated'] or terminal['reason'] != 'duration_limit':
        raise ValueError('adapter did not verify a complete capture')
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
        path = ROOT / relative; rolling.regular(path)
        if rolling.digest(path) != pin['sha256']:
            raise ValueError('frozen source pin differs')
    destination = OUT / f'flow-recovery-batch{batch}.json.gz'
    provenance_path = OUT / f'flow-recovery-batch{batch}-provenance.json'
    if destination.exists() or provenance_path.exists():
        raise FileExistsError('immutable preflight output already exists')
    store = rolling.Store()
    # Root-owned pins protect the whole stream; keep the collector's global lock
    # free during feature processing so its heartbeats and handoffs can proceed.
    with store.locked():
        if destination.exists() or provenance_path.exists():
            raise FileExistsError('immutable preflight output already exists')
        before = check_inputs(store, plan, batch)
    with adapter_configuration():
        results = [feature_stream(record) for record in before['inputs']]
    with store.locked():
        after = check_inputs(store, plan, batch)
        if before != after:
            raise ValueError('input provenance changed during preflight')
        if rolling.digest(plan_path) != plan_hash or any(
                rolling.digest(ROOT / pin['path']) != pin['sha256'] for pin in plan['source_pins']):
            raise ValueError('frozen plan/source changed during preflight')
        report = dict(schema='single-venue-flow-recovery-preflight-v1', batch=batch,
            feature_only=True, economic_evaluation=False, validation_claim=False,
            plan_sha256=plan_hash, parameters=PARAMS, chunks=results,
            interpretation='Observed wire flow and net displayed restoration; not parent completion or certified trade continuity.')
        packed = gzip.compress(encode(report), mtime=0)
        if len(packed) > MAX_OUTPUT:
            raise ValueError('bounded feature output exceeds allocation')
        provenance = dict(schema='single-venue-flow-recovery-provenance-v1', batch=batch,
            plan_sha256=plan_hash, source_pins=plan['source_pins'], **before,
            output_sha256=hashlib.sha256(packed).hexdigest())
        body = encode(provenance)
        if len(body) > MAX_PROVENANCE:
            raise ValueError('provenance exceeds allocation')
        OUT.mkdir(parents=True, exist_ok=True)
        publish(provenance_path, body)
        publish(destination, packed)
    print(json.dumps(dict(batch=batch, gzip_bytes=len(packed), provenance_bytes=len(body),
                         chunks=len(results), economic_evaluation=False)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    run(args.batch)


if __name__ == '__main__':
    main()
