#!/usr/bin/env python3
"""Label-only delayed liquidation coverage successor; frozen-plan gated.

No book, price, size, account, execution, or economic field is read into output.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rolling_research_capture as rolling
from scripts import single_venue_inventory_context as inventory
from scripts.maker_capture import integer, parse_epoch_ns

PLAN = ROOT / 'reports/experiment-storage/liquidation-delay-coverage-v2.json'
OUT = ROOT / 'reports/single-venue-research/liquidation-coverage-v2'
PROJECTION = ROOT / 'reports/experiment-storage/liquidation-delay-coverage-v2-inputs.json'
BATCHES = {i: [f'chunk-{n:06d}' for n in range(13+6*(i-1), 16+6*(i-1))]
           for i in range(1, 7)}
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


def encoded_bounded(value, cap):
    """Stop serialization before derived plaintext can exceed its cap."""
    blocks, used = [], 0
    for piece in json.JSONEncoder(separators=(',', ':'), allow_nan=False).iterencode(value):
        block = piece.encode()
        used += len(block)
        if used+1 > cap:
            raise ValueError('derived plaintext cap exceeded')
        blocks.append(block)
    return b''.join(blocks)+b'\n'


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
    if source > receipt:
        raise ValueError('trade source age invalid')
    return dict(trade=(venue, market, trade), key=(venue, market, order_side, order, version),
                venue=venue, market=market, side=side, subtype=subtype,
                source_ns=source, received_ns=receipt,
                stale=not history and receipt-source > EXPECTED['max_source_age_ns'])


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
        self.quarantine_until = {}
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
            self.quarantine_until = {k: t for k, t in self.quarantine_until.items() if k[0] != venue}
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
        stale = [item for item in items if item['stale']]
        if stale:
            self.censor(venue, 'valid_stale_trade', market)
            self.quarantine_until[key] = max(self.quarantine_until.get(key, 0),
                                              receipt + EXPECTED['window_end_ns'])
            # Array rows, before cross-array trade-ID deduplication.
            self.counts[self.market_asset[venue, market], venue]['valid_stale_array_rows'] += len(stale)
            self.counts[self.market_asset[venue, market], venue]['valid_stale_frames'] += 1
        quarantined = receipt <= self.quarantine_until.get(key, 0)
        if quarantined:
            self.counts[self.market_asset[venue, market], venue]['quarantined_trade_frames'] += 1
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
            if quarantined:
                c['quarantined_liquidation_rows'] += 1
                continue
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
    cap = ROOT/'data/rolling/market-research-v1'/record['chunk']/'capture'
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
    result['available'] = True
    result['state'] = 'sealed_complete'
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


def frozen(plan_sha):
    """Validate every source and immutable input identity before opening raw."""
    if rolling.digest(PLAN) != plan_sha:
        raise ValueError('exact plan SHA differs')
    plan = rolling.read_json(PLAN, 16384)
    if (plan.get('schema') != 'liquidation-delay-coverage-v2' or plan.get('status') != 'frozen'
            or plan.get('parameters') != EXPECTED or plan.get('quarantine_ns') != EXPECTED['window_end_ns']
            or plan.get('store_root') != 'data/rolling/market-research-v1'
            or plan.get('pin_owner') != 'liquidation_coverage_v2'
            or plan.get('output_root') != str(OUT.relative_to(ROOT))
            or plan.get('batches') != [{'index': i, 'chunks': BATCHES[i]} for i in BATCHES]
            or plan.get('outputs') != dict(gzip_per_batch=24576, provenance_per_batch=8192,
                derived_plaintext_bytes_per_batch=1048576, one_batch_wall_seconds=240,
                overall_wall_seconds=1500, receipt_total_bytes=32768)):
        raise ValueError('coverage plan not frozen or method differs')
    pin = plan.get('input_identity_projection', {})
    if (pin.get('path') != str(PROJECTION.relative_to(ROOT))
            or rolling.regular(PROJECTION) != pin.get('bytes')
            or rolling.digest(PROJECTION) != pin.get('sha256')):
        raise ValueError('input projection differs')
    projection = rolling.read_json(PROJECTION, 65536)
    if (projection.get('schema') != 'liquidation-coverage-v2-input-identity-v1'
            or projection.get('store_root') != plan['store_root']
            or projection.get('pin_owner') != plan['pin_owner']
            or [x.get('chunk') for x in projection.get('inputs', [])] != sum(BATCHES.values(), [])
            or len(projection['inputs']) != 18):
        raise ValueError('input projection schema/calendar differs')
    for item in projection['inputs']:
        complete = item['chunk'] not in ('chunk-000033', 'chunk-000039')
        if (item.get('available') is not complete or item.get('role') != 'exploratory'
                or item.get('state') != ('sealed_complete' if complete else 'sealed_failed')):
            raise ValueError('input availability differs')
    sources(plan, rolling.digest(Path(__file__)))
    from scripts import liquidation_delay_observability as parent
    if (plan.get('parent_method') != str(parent.PLAN.relative_to(ROOT))
            or rolling.digest(parent.PLAN) != plan.get('parent_method_sha256')):
        raise ValueError('parent method differs')
    prior = rolling.read_json(parent.PLAN, 16384)
    parent.sources(prior, rolling.digest(Path(parent.__file__)))
    validation_path = ROOT/prior['input_validation_plan']
    if rolling.digest(validation_path) != prior['input_validation_plan_sha256']:
        raise ValueError('transitive validation plan differs')
    validation = rolling.read_json(validation_path, 16384)
    if len(validation.get('source_pins', [])) != 45:
        raise ValueError('transitive source pin count differs')
    for old in validation['source_pins']:
        if rolling.digest(ROOT/old['path']) != old['sha256']:
            raise ValueError('transitive source differs')
    return plan, projection


def check_inputs(store, projection, batch):
    """Check only the three projected inputs, preserving failed inputs as unknown."""
    identity_path = store.root/'identity.json'
    ident = rolling.read_json(identity_path, 16384)
    if (rolling.digest(identity_path) != projection['store_identity_sha256']
            or ident.get('plan_sha256') != projection['capture_parent_plan_sha256']
            or ident.get('schema') != 'rolling-research-store-v1'):
        raise ValueError('store identity differs')
    index = store.index()['chunks']
    rows = [x for x in projection['inputs'] if x['chunk'] in BATCHES[batch]]
    if [x['chunk'] for x in rows] != BATCHES[batch]:
        raise ValueError('batch projection differs')
    for row in rows:
        name = row['chunk']; entry = index.get(name)
        if (not entry or entry.get('state') != row['state'] or entry.get('role') != row['role']
                or entry.get('seal_sha256') != row['seal_sha256']):
            raise ValueError('store index input differs')
        if not row['available']:
            failed_dir = store.root/name
            failed_seal = rolling.read_json(failed_dir/'seal.json', 65536)
            failed_manifest = rolling.read_json(failed_dir/'capture/manifest.json', 65536)
            if (rolling.digest(failed_dir/'seal.json') != row['seal_sha256']
                    or failed_seal.get('state') != 'sealed_failed'
                    or failed_seal.get('chunk_id') != name
                    or failed_seal.get('failure') != row['failure']
                    or rolling.digest(failed_dir/'capture/manifest.json') != row['manifest_sha256']
                    or failed_manifest.get('end_reason') != row['manifest_end_reason']
                    or failed_manifest.get('truncated') is not row['manifest_truncated']):
                raise ValueError('failed input identity differs')
            continue
        if projection['pin_owner'] not in entry.get('pins', []):
            raise ValueError('complete input is not pinned')
        directory = store.root/name
        seal_path = directory/'seal.json'
        seal = rolling.read_json(seal_path, 65536)
        if (rolling.digest(seal_path) != row['seal_sha256']
                or seal.get('state') != 'sealed_complete'
                or seal.get('role') != 'exploratory'
                or seal.get('chunk_id') != name
                or seal.get('files') != row['files']
                or set(store.files(directory)) != set(row['files'])|{'seal.json'}):
            raise ValueError('sealed file inventory differs')
        for relative, item in row['files'].items():
            path = directory/relative
            if rolling.regular(path) != item['bytes'] or rolling.digest(path) != item['sha256']:
                raise ValueError('sealed file differs')
        manifest = rolling.read_json(directory/'capture/manifest.json', 65536)
        if (rolling.digest(directory/'capture/manifest.json') != row['manifest_sha256']
                or manifest.get('frames_sha256') != row['raw_sha256']
                or manifest.get('payload_records') != row['payload_records']
                or manifest.get('selected_markets') != rolling.SELECTED
                or manifest.get('end_reason') != 'duration_limit'
                or manifest.get('truncated') is not False):
            raise ValueError('capture manifest differs')
    return rows


def run_batch(batch, plan_sha, plan, projection):
    destination = OUT/f'liquidation-coverage-batch{batch}.json.gz'
    provenance_path = OUT/f'liquidation-coverage-batch{batch}-provenance.json'
    if destination.exists() or provenance_path.exists():
        raise FileExistsError('immutable batch output exists')
    store = rolling.Store()
    with store.locked():
        before = check_inputs(store, projection, batch)
    chunks = [stream(x) if x['available'] else dict(chunk=x['chunk'], available=False,
               state=x['state'], failure=x['failure'], groups=[empty_group(a, v)
               for a in rolling.ASSETS for v in ('lighter', 'rh_lighter')], episodes=[])
              for x in before]
    with store.locked():
        if check_inputs(store, projection, batch) != before or rolling.digest(PLAN) != plan_sha:
            raise ValueError('input or plan changed')
        frozen(plan_sha)
        totals = defaultdict(Counter)
        for chunk in chunks:
            for row in chunk['groups']:
                totals[row['asset'], row['venue']].update(row['counts'])
        missing = sum(not x['available'] for x in before)
        groups = [dict(asset=a, venue=v, unavailable_chunks=missing,
                       counts=dict(totals[a, v])) for a in rolling.ASSETS
                  for v in ('lighter', 'rh_lighter')]
        report = dict(schema='liquidation-delay-coverage-result-v2', batch=batch,
            plan_sha256=plan_sha, validation_claim=False, unavailable_chunks=missing,
            interpretation='First retained public observation only; unavailable chunks are unknown.',
            groups=groups, chunks=chunks)
        plain = encoded_bounded(report, 1048576)
        packed = gzip.compress(plain, mtime=0)
        if len(packed) > 24576:
            raise ValueError('gzip output cap exceeded')
        provenance = dict(schema='liquidation-delay-coverage-provenance-v2',
            batch=batch, plan_sha256=plan_sha,
            projection_sha256=plan['input_identity_projection']['sha256'],
            source_pins=plan['source_pins'], inputs=[dict(chunk=x['chunk'],
                available=x['available'], state=x['state'], seal_sha256=x['seal_sha256']) for x in before],
            output_sha256=hashlib.sha256(packed).hexdigest())
        body = encoded(provenance)
        if len(body) > 8192:
            raise ValueError('provenance cap exceeded')
        OUT.mkdir(parents=True, exist_ok=True)
        inventory.publish(provenance_path, body)
        inventory.publish(destination, packed)
    return dict(batch=batch, state='partial' if missing else 'complete', available_chunks=3-missing,
                unavailable_chunks=missing, gzip_bytes=len(packed),
                episodes=sum(len(x['episodes']) for x in chunks))


def supervise(plan_sha):
    plan, projection = frozen(plan_sha)
    if (OUT/'run-receipt.json').exists() or any((OUT/f'liquidation-coverage-batch{i}.json.gz').exists() or
           (OUT/f'liquidation-coverage-batch{i}-provenance.json').exists() for i in BATCHES):
        raise FileExistsError('existing batch output; refusing all-six run')
    deadline = time.monotonic()+1500
    rows = []
    def unavailable_groups():
        return [dict(asset=a, venue=v, counts=None, unavailable_chunks=3)
                for a in rolling.ASSETS for v in ('lighter', 'rh_lighter')]
    def timeout(_signum, _frame):
        raise TimeoutError('batch wall deadline exceeded')
    previous = signal.signal(signal.SIGALRM, timeout)
    try:
        for batch in BATCHES:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                rows.append(dict(batch=batch, state='pending_overall_timeout',
                                 groups=unavailable_groups()))
                continue
            signal.setitimer(signal.ITIMER_REAL, min(240, remaining))
            try:
                rows.append(run_batch(batch, plan_sha, plan, projection))
            except Exception as exc:
                rows.append(dict(batch=batch, state='failed', reason=type(exc).__name__+': '+str(exc)[:240],
                                 groups=unavailable_groups()))
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous)
    receipt = dict(schema='liquidation-delay-coverage-receipt-v2', plan_sha256=plan_sha,
                   batches=rows, validation_claim=False)
    body = encoded(receipt)
    if len(body) > 32768:
        raise ValueError('receipt cap exceeded')
    OUT.mkdir(parents=True, exist_ok=True)
    inventory.publish(OUT/'run-receipt.json', body)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha')
    args = parser.parse_args()
    if not args.run:
        print(json.dumps(dict(mode='dry', plan_status=rolling.read_json(PLAN, 16384).get('status'),
                              raw_opened=False)))
        return
    if not args.plan_sha or len(args.plan_sha) != 64:
        raise ValueError('run requires exact --plan-sha')
    print(json.dumps(supervise(args.plan_sha)))


if __name__ == '__main__':
    main()
