#!/usr/bin/env python3
"""Frozen, label-only delayed liquidation observability preflight.

No book, price, size, account, execution, or economic field is read into output.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rolling_research_capture as rolling
from scripts import single_venue_inventory_context as inventory
from scripts.maker_capture import integer, parse_epoch_ns

PLAN = ROOT / 'reports/experiment-storage/liquidation-delay-observability-v1.json'
OUT = ROOT / 'reports/single-venue-research/liquidation-delay-v1'
NS = 1_000_000_000
RAW_CAP = 64 * 1024 * 1024 + 262144
EXPECTED = dict(episode_spacing_ns=30*NS, delay_ns=400_000_000,
    window_end_ns=2_400_000_000, max_source_age_ns=500_000_000,
    source_clock='timestamp milliseconds',
    first_seen_scope='all ordinary and nonordinary rows in both arrays including subscription history, within each chunk',
    max_decoded_bytes_per_chunk=1024**3, max_records_per_chunk=1_000_000,
    max_line_bytes=8*1024**2, max_trade_ids_per_chunk=500_000,
    max_order_keys_per_chunk=500_000, max_label_rows_per_chunk=10_000)
FIELDS = ('trade_id', 'ask_id', 'bid_id')


def encoded(value):
    return (json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode()


def identity(raw, name):
    a, b = raw.get(name), raw.get(name+'_str')
    if a is None and b is None:
        raise ValueError(name+' absent')
    x = integer(a if a is not None else b, name)
    if x <= 0 or (b is not None and integer(b, name+'_str') != x):
        raise ValueError(name+' identity inconsistent')
    return x


def label(raw, venue, market, receipt, *, history=False):
    """Parse only public label, clock, and identity fields."""
    if not isinstance(raw, dict) or str(raw.get('market_id')) != market:
        raise ValueError('market or row identity malformed')
    subtype = raw.get('type')
    if subtype not in ('trade', 'liquidation', 'deleverage', 'market-settlement'):
        raise ValueError('unknown trade subtype')
    side = raw.get('is_maker_ask')
    if not isinstance(side, bool):
        raise ValueError('taker side malformed')
    trade = identity(raw, 'trade_id')
    order_side = 'bid' if side else 'ask'
    order = identity(raw, order_side+'_id')
    version = integer(raw.get(order_side+'_order_version'), 'order version')
    if version < 0:
        raise ValueError('negative order version')
    source = parse_epoch_ns(raw.get('timestamp'), 'ms')
    if source > receipt or (not history and receipt-source > EXPECTED['max_source_age_ns']):
        raise ValueError('trade source age invalid')
    return dict(trade=(venue, market, trade), key=(venue, market, order_side, order, version),
                venue=venue, market=market, side=side, subtype=subtype,
                source_ns=source, received_ns=receipt)


def empty_group(asset, venue):
    return dict(asset=asset, venue=venue, counts={})


class LabelStudy:
    """Receipt-order state; malformed evidence censors, never fabricates absence."""
    def __init__(self, selected, start, stop, chunk):
        self.selected, self.start, self.stop, self.chunk = selected, start, stop, chunk
        self.market_asset = {(venue, str(market)): asset for venue, assets in selected.items()
                             for asset, market in assets.items() if venue in ('lighter', 'rh_lighter')}
        self.active = {}
        self.retired = set()
        self.ended = set()
        self.bad = set()
        self.bad_venues = set()
        self.seen_orders = set()
        self.seen_trades = {}
        self.last_source = {}
        self.last_anchor = {}
        self.episodes = []
        self.counts = defaultdict(Counter)
        self.global_counts = Counter()
        self.label_rows = 0

    def _open(self, venue, market=None):
        return [e for e in self.episodes if e['venue'] == venue
                and (market is None or e['market'] == market) and e['censor_reason'] is None
                and e['anchor_ns'] + EXPECTED['window_end_ns'] >= self.now]

    def censor(self, venue, reason, market=None):
        for e in self._open(venue, market):
            e['censor_reason'] = reason
        self.global_counts['break:'+reason] += 1

    def process(self, row):
        self.now = receipt = row['receipt_utc_ns']
        venue, generation, kind = row.get('venue'), row.get('generation'), row.get('kind')
        if (venue not in self.selected
                or not isinstance(generation, str) or not generation
                or kind not in ('connection_open', 'frame', 'connection_close',
                                'connection_error', 'invalid_json', 'generation_invalidated')):
            raise ValueError('capture envelope unknown')
        previous = self.active.get(venue)
        if kind == 'connection_open':
            if previous == generation or (venue, generation) in self.retired | self.ended:
                raise ValueError('duplicate or retired generation opened')
            if previous is not None and previous != generation:
                self.censor(venue, 'generation_change')
                self.retired.add((venue, previous))
            self.active[venue] = generation
            self.bad = {x for x in self.bad if x[0] != venue}
            self.bad_venues.discard(venue)
            return
        if kind in ('connection_close', 'connection_error', 'invalid_json', 'generation_invalidated'):
            if previous != generation:
                raise ValueError('terminal outside active generation')
            self.censor(venue, kind)
            self.active.pop(venue, None)
            self.ended.add((venue, generation))
            return
        if previous != generation or (venue, generation) in self.ended:
            raise ValueError('frame outside active generation')
        if venue in self.bad_venues:
            self.global_counts['suppressed_unknown_market_frames'] += 1
            return
        if row.get('channel') != 'trade':
            payload = row.get('payload')
            if isinstance(payload, dict) and payload.get('type') in ('update/trade', 'subscribed/trade'):
                market = str(row.get('market'))
                self.censor(venue, 'trade_on_wrong_capture_channel',
                            market if (venue, market) in self.market_asset else None)
                if (venue, market) in self.market_asset:
                    self.bad.add((venue, market, generation))
                    self.counts[self.market_asset[venue, market], venue]['trade_on_wrong_capture_channel'] += 1
                else:
                    self.bad_venues.add(venue)
            return
        market = str(row.get('market'))
        if (venue, market) not in self.market_asset:
            self.censor(venue, 'unknown_trade_market')
            self.bad_venues.add(venue)
            return
        key = venue, market, generation
        payload, ann = row.get('payload'), row.get('annotation')
        if key in self.bad:
            self.counts[self.market_asset[venue, market], venue]['suppressed_bad_trade_frames'] += 1
            return
        try:
            if not isinstance(payload, dict) or not isinstance(ann, dict):
                raise ValueError('trade frame envelope malformed')
            if ann.get('quality') != 'wire_ok' or ann.get('source_regression_within_channel'):
                raise ValueError('trade annotation or source regression')
            typ = payload.get('type')
            if typ not in ('update/trade', 'subscribed/trade') or payload.get('channel') != 'trade:'+market:
                raise ValueError('trade channel malformed')
            if not isinstance(payload.get('trades'), list) or not isinstance(payload.get('liquidation_trades'), list):
                raise ValueError('trade arrays malformed')
            items = []
            for field in ('trades', 'liquidation_trades'):
                for raw in payload[field]:
                    item = label(raw, venue, market, receipt, history=typ == 'subscribed/trade')
                    if field == 'liquidation_trades' and item['subtype'] != 'liquidation':
                        raise ValueError('liquidation array subtype mismatch')
                    items.append(item)
            source_max = max((x['source_ns'] for x in items), default=None)
            if source_max is not None and source_max < self.last_source.get(key, 0):
                raise ValueError('trade source regression')
            same = {}
            for item in items:
                signature = (item['key'], item['side'], item['subtype'], item['source_ns'])
                if item['trade'] in same and same[item['trade']] != signature:
                    raise ValueError('cross-array identity or clock conflict')
                if item['trade'] in self.seen_trades and self.seen_trades[item['trade']] != signature:
                    raise ValueError('repeated trade identity conflict')
                same[item['trade']] = signature
        except (TypeError, ValueError, OverflowError) as exc:
            self.bad.add(key)
            self.censor(venue, 'invalid_trade_evidence', market)
            self.counts[self.market_asset[venue, market], venue]['invalid_trade_evidence'] += 1
            self.counts[self.market_asset[venue, market], venue]['invalid_reason:'+str(exc)] += 1
            return
        if source_max is not None:
            self.last_source[key] = source_max
        new = []
        local = set()
        for item in items:
            if item['trade'] in self.seen_trades or item['trade'] in local:
                self.global_counts['duplicate_cross_or_repeat'] += 1
                continue
            local.add(item['trade'])
            self.seen_trades[item['trade']] = same[item['trade']]
            if item['subtype'] == 'liquidation':
                self.label_rows += 1
            if self.label_rows > EXPECTED['max_label_rows_per_chunk'] or len(self.seen_trades) > EXPECTED['max_trade_ids_per_chunk']:
                raise ValueError('label or trade identity bound exceeded')
            new.append(item)
        first_by_key = {}
        for item in new:
            if item['key'] not in self.seen_orders:
                old = first_by_key.get(item['key'])
                if old is None or item['source_ns'] < old['source_ns']:
                    first_by_key[item['key']] = item
        for item in new:
            asset = self.market_asset[venue, market]
            c = self.counts[asset, venue]
            c['history_rows' if typ == 'subscribed/trade' else 'live_rows'] += 1
            if typ == 'subscribed/trade' or item['subtype'] != 'liquidation':
                continue
            c['live_liquidation_rows'] += 1
            for e in self.episodes:
                if (e['venue'] != venue or e['market'] != market or e['side'] != item['side']
                        or e['censor_reason'] is not None or item['key'] in e['_initial_keys']
                        or item['key'] not in first_by_key or item['key'] in e['_qualified_keys']):
                    continue
                low = e['anchor_ns'] + EXPECTED['delay_ns']
                high = e['anchor_ns'] + EXPECTED['window_end_ns']
                first = first_by_key[item['key']]
                if low < first['received_ns'] <= high and low < first['source_ns'] <= high:
                    e['_qualified_keys'].add(item['key'])
                    e['qualifying_order_count'] += 1
                    e['qualifying_orders'].append(dict(side=item['key'][2], order_id=item['key'][3],
                        order_version=item['key'][4], first_source_ns=first['source_ns'],
                        first_received_ns=first['received_ns']))
                    c['qualifying_order_firsts'] += 1
            old = self.last_anchor.get(asset)
            if old is None or receipt-old >= EXPECTED['episode_spacing_ns']:
                e = dict(asset=asset, venue=venue, market=market, side=item['side'],
                         anchor_ns=receipt, anchor_source_ns=item['source_ns'],
                         generation=generation, qualifying_order_count=0,
                         qualifying_orders=[], censor_reason=None,
                         _initial_keys={x['key'] for x in items}, _qualified_keys=set())
                self.episodes.append(e)
                self.last_anchor[asset] = receipt
                c['episodes'] += 1
        self.seen_orders.update(x['key'] for x in new)
        if len(self.seen_orders) > EXPECTED['max_order_keys_per_chunk']:
            raise ValueError('order identity bound exceeded')

    def result(self):
        groups = [empty_group(asset, venue) for asset in rolling.ASSETS for venue in ('lighter', 'rh_lighter')]
        for e in self.episodes:
            e.pop('_initial_keys')
            e.pop('_qualified_keys')
            if e['censor_reason'] is None and e['anchor_ns']+EXPECTED['window_end_ns'] > self.stop:
                e['censor_reason'] = 'capture_end_before_window'
            c = self.counts[e['asset'], e['venue']]
            c['censored_episodes' if e['censor_reason'] else 'complete_episodes'] += 1
            if e['qualifying_order_count']:
                c['observed_continuation_episodes'] += 1
                if e['censor_reason'] is None:
                    c['complete_continuation_episodes'] += 1
        for row in groups:
            row['counts'] = dict(self.counts[row['asset'], row['venue']])
        return dict(chunk=self.chunk, groups=groups, episodes=self.episodes,
                    counts=dict(self.global_counts))


def stream(record):
    cap = Path(record['capture'])
    manifest_path, raw = cap/'manifest.json', cap/'frames.jsonl.gz'
    manifest = rolling.read_json(manifest_path, 65536)
    seal = rolling.read_json(cap.parent/'seal.json', 65536)
    if (rolling.digest(manifest_path) != record['manifest_sha256']
            or rolling.digest(raw) != record['raw_sha256']
            or rolling.regular(raw) > RAW_CAP
            or manifest.get('schema') != 'single-venue-depth-public-capture-v1'
            or manifest.get('read_only') is not True
            or manifest.get('compressed_payload_bytes') != raw.stat().st_size
            or manifest.get('frames_sha256') != record['raw_sha256']
            or manifest.get('payload_records', 0) > EXPECTED['max_records_per_chunk']):
        raise ValueError('manifest or raw identity differs')
    selected = manifest['selected_markets']
    if selected != rolling.SELECTED:
        raise ValueError('market selection differs')
    study = LabelStudy(selected, record['started_ns'], record['ended_ns'], record['chunk'])
    records = decoded = 0
    prior_receipt = prior_mono = None
    with gzip.open(raw, 'rb') as handle:
        while True:
            line = handle.readline(EXPECTED['max_line_bytes']+1)
            if not line:
                break
            if len(line) > EXPECTED['max_line_bytes'] or not line.endswith(b'\n'):
                raise ValueError('record line bound or termination differs')
            records += 1; decoded += len(line)
            if records > EXPECTED['max_records_per_chunk'] or decoded > EXPECTED['max_decoded_bytes_per_chunk']:
                raise ValueError('decoded input bound exceeded')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('record is not object')
            receipt, mono = row.get('receipt_utc_ns'), row.get('receipt_monotonic_ns')
            if (isinstance(receipt, bool) or not isinstance(receipt, int)
                    or not study.start <= receipt <= study.stop+1000
                    or prior_receipt is not None and receipt < prior_receipt):
                raise ValueError('receipt clock invalid')
            if mono is not None and (isinstance(mono, bool) or not isinstance(mono, int)
                    or mono <= 0 or prior_mono is not None and mono < prior_mono):
                raise ValueError('monotonic receipt invalid')
            prior_receipt = receipt
            if mono is not None:
                prior_mono = mono
            study.process(row)
    if (records != manifest['payload_records'] or records != seal['payload_records']
            or decoded != seal['decoded_bytes']
            or seal['manifest_sha256'] != record['manifest_sha256']
            or seal['frames_sha256'] != record['raw_sha256']
            or rolling.digest(raw) != record['raw_sha256']
            or rolling.digest(manifest_path) != record['manifest_sha256']):
        raise ValueError('EOF, counts or input identity differs')
    result = study.result()
    result['input_counts'] = dict(records=records, decoded_bytes=decoded,
                                  label_rows=study.label_rows)
    return result


def sources(plan, own_hash):
    pins = plan.get('source_pins')
    if not isinstance(pins, list) or not pins:
        raise ValueError('frozen source pins required')
    names = set()
    for pin in pins:
        relative = Path(pin['path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in names:
            raise ValueError('unsafe or duplicate source pin')
        names.add(str(relative))
        if rolling.digest(ROOT/relative) != pin['sha256']:
            raise ValueError('source pin differs')
    own = str(Path(__file__).resolve().relative_to(ROOT))
    if (own not in names or not any(x.startswith('tests/') for x in names)
            or not any(x.startswith('reports/') and x != str(PLAN.relative_to(ROOT)) for x in names)
            or next(x['sha256'] for x in pins if x['path'] == own) != own_hash):
        raise ValueError('source, test and protocol pins required')


def run(batch):
    plan = rolling.read_json(PLAN, 16384)
    if (plan.get('schema') != 'liquidation-delay-observability-v1'
            or plan.get('status') != 'frozen' or plan.get('parameters') != EXPECTED
            or plan.get('input_validation_plan') != 'reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json'
            or plan.get('store_root') != 'data/rolling/market-research-v1'
            or plan.get('pin_owner') != inventory.OWNER
            or plan.get('output_root') != str(OUT.relative_to(ROOT))
            or plan.get('batches') != [{'index': i, 'chunks': inventory.BATCHES[i]} for i in (1, 2)]
            or plan.get('output_caps') != dict(gzip_per_batch=24576,
                provenance_per_batch=8192, readout=8192)):
        raise ValueError('preflight plan not frozen or method differs')
    own_hash = rolling.digest(Path(__file__))
    plan_hash = rolling.digest(PLAN)
    sources(plan, own_hash)
    validation_path = ROOT/plan['input_validation_plan']
    if rolling.digest(validation_path) != plan['input_validation_plan_sha256']:
        raise ValueError('input validation plan differs')
    validation = rolling.read_json(validation_path, 16384)
    if not validation.get('source_pins') or len(validation['source_pins']) != 45:
        raise ValueError('transitive source pins differ')
    for pin in validation['source_pins']:
        if rolling.digest(ROOT/pin['path']) != pin['sha256']:
            raise ValueError('transitive source pin differs')
    if next(x['chunks'] for x in plan['batches'] if x['index'] == batch) != inventory.BATCHES[batch]:
        raise ValueError('batch chunks differ')
    destination = OUT/f'liquidation-delay-batch{batch}.json.gz'
    provenance_path = OUT/f'liquidation-delay-batch{batch}-provenance.json'
    if destination.exists() or provenance_path.exists():
        raise FileExistsError('immutable preflight result exists')
    store = rolling.Store()
    with store.locked():
        before = inventory.check_inputs(store, validation, batch)
    chunks = [stream(x) for x in before['inputs']]
    with store.locked():
        if inventory.check_inputs(store, validation, batch) != before:
            raise ValueError('input provenance changed')
        if rolling.digest(PLAN) != plan_hash or rolling.digest(validation_path) != plan['input_validation_plan_sha256']:
            raise ValueError('plan changed')
        sources(plan, own_hash)
        for pin in validation['source_pins']:
            if rolling.digest(ROOT/pin['path']) != pin['sha256']:
                raise ValueError('transitive source changed')
        totals = defaultdict(Counter)
        for chunk in chunks:
            for row in chunk['groups']:
                totals[row['asset'], row['venue']].update(row['counts'])
        groups = [dict(asset=asset, venue=venue, counts=dict(totals[asset, venue]))
                  for asset in rolling.ASSETS for venue in ('lighter', 'rh_lighter')]
        report = dict(schema='liquidation-delay-observability-result-v1', batch=batch,
            plan_sha256=plan_hash, validation_claim=False,
            interpretation='Public label observability only; no private-flow completeness, causality, or economics.',
            groups=groups, chunks=chunks)
        packed = gzip.compress(encoded(report), mtime=0)
        if len(packed) > 24576:
            raise ValueError('gzip output cap exceeded')
        provenance = dict(schema='liquidation-delay-observability-provenance-v1',
            batch=batch, plan_sha256=plan_hash, validation_plan_sha256=plan['input_validation_plan_sha256'],
            source_pins=plan['source_pins'], **before,
            output_sha256=hashlib.sha256(packed).hexdigest())
        body = encoded(provenance)
        if len(body) > 8192:
            raise ValueError('provenance cap exceeded')
        OUT.mkdir(parents=True, exist_ok=True)
        inventory.publish(provenance_path, body)
        inventory.publish(destination, packed)
    return dict(batch=batch, gzip_bytes=len(packed), provenance_bytes=len(body),
                episodes=sum(len(x['episodes']) for x in chunks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, choices=(1, 2), required=True)
    print(json.dumps(run(parser.parse_args().batch)))


if __name__ == '__main__':
    main()
