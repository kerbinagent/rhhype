#!/usr/bin/env python3
"""Offline, bounded RH/Core LIT events; source identity never changes with role.

Requires an independently pinned manifest SHA and its pinned raw gzip SHA.
This future-study adapter neither modifies nor calls the frozen v1 engine.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import gzip
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from scripts.maker_book_archive import BookRebuilder, selected_markets, sha256
from scripts.maker_capture import integer, parse_epoch_ns
from scripts.core_maker_lit_capture import (
    HARD_BYTES, HARD_SECONDS, MAX_METADATA_AGE_NS, MAX_TRADE_IDS,
    METADATA_MAX_BYTES, REQUESTS, VENUES, select_three, verify_metadata,
)

MAX_MANIFEST_BYTES = 262_144
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 128 * 1024 * 1024
MAX_RECORDS = 100_000
TERMINAL = ('connection_close', 'connection_error', 'invalid_json', 'generation_invalidated')


def _epoch_ns(value):
    if not isinstance(value, str):
        raise ValueError('manifest timestamp must be ISO8601 text')
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError('manifest timestamp must include UTC offset')
    delta = timestamp - datetime.fromisoformat('1970-01-01T00:00:00+00:00')
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _archive_size(directory, limit):
    total = entries = 0
    for path in directory.rglob('*'):
        entries += 1
        if entries > 256 or path.is_symlink():
            raise ValueError('capture archive has too many entries or a symlink')
        if path.is_file():
            total += path.stat().st_size
            if total > limit:
                raise ValueError('capture archive exceeds raw-byte bound')
    return total


def _pinned(path, expected, label):
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in '0123456789abcdef' for c in expected.lower())):
        raise ValueError(f'{label}: expected SHA-256 required')
    digest = sha256(path)
    if digest != expected.lower():
        raise ValueError(f'{label}: SHA-256 mismatch')
    return digest


def _metadata(directory, manifest, start_ns):
    directory = directory / 'metadata'
    names = [f'{name}{suffix}' for name in REQUESTS for suffix in ('.json.gz', '.request.json')]
    names += ['market_plan.json', 'normalized.json']
    total = sum((directory / name).stat().st_size for name in names)
    if total > METADATA_MAX_BYTES or total != manifest.get('metadata_bytes'):
        raise ValueError('frozen metadata byte count exceeds bound or differs')
    selected, plan_hash = select_three(directory / 'market_plan.json')
    if selected != manifest.get('selected_markets') or plan_hash != manifest.get('market_plan_sha256'):
        raise ValueError('frozen market plan identity or SHA-256 differs')
    normalized = verify_metadata(directory, selected, plan_hash)
    if set(normalized['raw_requests']) != set(REQUESTS):
        raise ValueError('four raw metadata responses required')
    for name, request in normalized['raw_requests'].items():
        began, ended = request.get('request_started_utc_ns'), request.get('response_completed_utc_ns')
        if (any(isinstance(v, bool) or not isinstance(v, int) for v in (began, ended))
                or not 0 < began <= ended <= start_ns
                or start_ns - ended > MAX_METADATA_AGE_NS):
            raise ValueError(f'{name}: metadata stale or future at capture start')
        if request.get('raw_file') != f'{name}.json.gz':
            raise ValueError(f'{name}: metadata raw filename differs')
    hashes = {name: sha256(directory / name) for name in names}
    return normalized, hashes


def hedge_execution_assumptions(metadata, hedge_venue, *, network_delay_ms,
                               hyperliquid_processing_ms=150):
    """Explicit delay assumptions for later replay, never a timestamp shift.

    Core's public Standard processing floor is 300 ms; network is independent.
    HL processing is an explicitly named model assumption (default 150 ms).
    """
    if hedge_venue not in ('hyperliquid', 'lighter'):
        raise ValueError('hedge venue must be hyperliquid or lighter')
    def delay(value):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            raise ValueError('delay assumption malformed') from None
        if isinstance(value, bool) or not result.is_finite() or result < 0:
            raise ValueError('delay assumption must be finite and nonnegative')
        return result
    network = delay(network_delay_ms)
    processing = delay(hyperliquid_processing_ms) if hedge_venue == 'hyperliquid' else Decimal(300)
    markets = metadata['markets'][hedge_venue]
    if hedge_venue == 'lighter' and any(
            m.get('venue') != 'lighter' or m.get('processing_delay_ms') != 300
            or Decimal(m['maker_fee_bps']) != 0 or Decimal(m['taker_fee_bps']) != 0
            for m in markets.values()):
        raise ValueError('Core Standard own metadata profile required')
    return {'source_venue': hedge_venue, 'role': 'hedge',
            'processing_delay_ms': str(processing), 'network_delay_ms': str(network),
            'total_assumed_delay_ms': str(processing + network),
            'processing_evidence': ('published_Core_Standard_taker_base_only'
                                    if hedge_venue == 'lighter' else 'explicit_HL_model_assumption'),
            'network_evidence': 'explicit_separate_model_assumption',
            'fees_by_asset': {a: {k: m[k] for k in ('venue', 'market', 'maker_fee_bps', 'taker_fee_bps')}
                              for a, m in markets.items()}}


def _common(row, market=None, asset=None, *, hedge_venue=None):
    venue = row['venue']
    result = {'venue': venue, 'source_venue': venue, 'market': market,
              'source_market': market, 'asset': asset, 'generation': row['generation'],
              'source_generation': row['generation'], 'received_ns': row['receipt_utc_ns'],
              'receipt_ns': row['receipt_utc_ns'],
              'receipt_monotonic_ns': row.get('receipt_monotonic_ns')}
    if hedge_venue:
        result['role'] = 'maker' if venue == 'rh_lighter' else ('hedge' if venue == hedge_venue else 'reference')
    return result


def _invalidate(row, market, asset, scope, reason, hedge_venue):
    return {'type': 'invalidate', 'kind': 'invalidate',
            **_common(row, market, asset, hedge_venue=hedge_venue),
            'scope': scope, 'reason': reason, 'clock_valid': False, 'source_ns': None}


def _trade(row, raw, market, asset, hedge_venue):
    venue = row['venue']
    if not isinstance(raw, dict):
        raise ValueError('ordinary trade object missing')
    if venue == 'hyperliquid':
        if raw.get('coin') != market or raw.get('side') not in ('B', 'A'):
            raise ValueError('HL trade identity or side differs')
        ident, price, qty, timestamp = raw.get('tid'), raw.get('px'), raw.get('sz'), raw.get('time')
        buy = raw['side'] == 'B'
    else:
        if raw.get('type') != 'trade' or str(raw.get('market_id')) != market:
            raise ValueError(f'{venue} ordinary trade market identity differs')
        if not isinstance(raw.get('is_maker_ask'), bool):
            raise ValueError(f'{venue} trade aggressor side missing')
        ident = raw.get('trade_id_str', raw.get('trade_id'))
        price, qty, timestamp = raw.get('price'), raw.get('size'), raw.get('timestamp')
        buy = raw['is_maker_ask']
    ident = integer(ident, 'trade ID')
    if ident < 0:
        raise ValueError('trade ID negative')
    if isinstance(price, bool) or isinstance(qty, bool):
        raise ValueError('trade price or quantity malformed')
    price, qty = float(price), float(qty)
    if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
        raise ValueError('trade price or quantity nonpositive')
    source = parse_epoch_ns(timestamp, 'ms')
    if source > row['receipt_utc_ns']:
        raise ValueError('trade source time ahead of receipt')
    return {'type': 'trade', 'kind': 'trade',
            **_common(row, market, asset, hedge_venue=hedge_venue),
            'source_ns': source, 'clock_valid': True, 'price': price, 'qty': qty,
            'trade_id': ident, 'side': 'buy' if buy else 'sell', 'buy_aggressor': buy,
            'trade_nonce_observed': (row.get('payload') or {}).get('nonce'),
            'trade_nonce_continuity': 'not_inferred'}


def iter_events(capture_dir, *, expected_manifest_sha256, expected_raw_sha256=None,
                hedge_venue=None, max_raw_bytes=HARD_BYTES,
                max_decoded_bytes=MAX_DECODED_BYTES, max_records=MAX_RECORDS,
                max_ids=MAX_TRADE_IDS):
    """Yield receipt-ordered events only after archive and metadata verification.

    Caller must consume the final end event before trusting a complete replay.
    Errors and truncated coverage remain explicit, and no fill is inferred.
    """
    directory = Path(capture_dir)
    for value, cap in ((max_raw_bytes, HARD_BYTES), (max_decoded_bytes, MAX_DECODED_BYTES),
                       (max_records, MAX_RECORDS), (max_ids, MAX_TRADE_IDS)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= cap:
            raise ValueError('requested replay bound exceeds hard limit or is nonpositive')
    if hedge_venue is not None and hedge_venue not in ('hyperliquid', 'lighter'):
        raise ValueError('hedge role must be hyperliquid or lighter')
    archive_bytes = _archive_size(directory, max_raw_bytes)
    manifest_path, frames_path = directory / 'manifest.json', directory / 'frames.jsonl.gz'
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('manifest exceeds byte bound')
    manifest_hash = _pinned(manifest_path, expected_manifest_sha256, 'manifest')
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('schema') != 'core-maker-lit-offset-public-capture-v1' or manifest.get('read_only') is not True:
        raise ValueError('two-venue LIT capture schema required')
    start, stop = _epoch_ns(manifest['started_utc']), _epoch_ns(manifest['ended_utc'])
    if stop < start or stop - start > (HARD_SECONDS + 1) * 1_000_000_000:
        raise ValueError('capture duration exceeds bound')
    records = manifest.get('payload_records')
    if isinstance(records, bool) or not isinstance(records, int) or not 0 <= records <= max_records:
        raise ValueError('capture record count exceeds bound')
    configured = manifest.get('configured_total_bytes')
    seconds = manifest.get('configured_seconds')
    if (isinstance(configured, bool) or not isinstance(configured, int)
            or not archive_bytes <= configured <= HARD_BYTES
            or isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= HARD_SECONDS):
        raise ValueError('configured capture bounds invalid')
    if stop - start > (seconds + 1) * 1_000_000_000:
        raise ValueError('capture duration exceeds configured bound')
    if manifest.get('compressed_payload_bytes') != frames_path.stat().st_size:
        raise ValueError('gzip byte count differs')
    raw_hash = _pinned(frames_path, manifest.get('frames_sha256'), 'gzip')
    if expected_raw_sha256 is not None:
        _pinned(frames_path, expected_raw_sha256, 'external gzip')
    metadata, metadata_hashes = _metadata(directory, manifest, start)
    markets = selected_markets(manifest)
    identities = {(m['venue'], m['market']): m['asset'] for m in markets}
    pending, counts = [], Counter()
    rebuilder = BookRebuilder(markets, pending.append)
    ids, bad_trades = defaultdict(set), set()
    source_max, book_source_max = {}, {}
    active, retired, terminated = {}, set(), set()
    ids_total = decoded = 0
    prior_receipt = prior_monotonic = None
    max_receipt_gap = 0

    def invalidate_trades(row, reason):
        for asset, market in manifest['selected_markets'][row['venue']].items():
            bad_trades.add((row['venue'], market, row['generation']))
            yield _invalidate(row, market, asset, 'trade', reason, hedge_venue)

    with gzip.open(frames_path, 'rb') as handle:
        while True:
            line = handle.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES or not line.endswith(b'\n'):
                raise ValueError('NDJSON line exceeds bound or is incomplete')
            decoded += len(line)
            counts['decoded_records'] += 1
            if decoded > max_decoded_bytes or counts['decoded_records'] > records:
                raise ValueError('decoded payload exceeds bound')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('record must be an object')
            receipt, mono = row.get('receipt_utc_ns'), row.get('receipt_monotonic_ns')
            if (isinstance(receipt, bool) or not isinstance(receipt, int) or not start <= receipt <= stop + 1000
                    or prior_receipt is not None and receipt < prior_receipt):
                raise ValueError('receipt outside interval or moved backward')
            if mono is not None:
                if (isinstance(mono, bool) or not isinstance(mono, int) or mono <= 0
                        or prior_monotonic is not None and mono < prior_monotonic):
                    raise ValueError('receipt monotonic clock invalid or moved backward')
                prior_monotonic = mono
            if prior_receipt is not None:
                max_receipt_gap = max(max_receipt_gap, receipt - prior_receipt)
            prior_receipt = receipt
            venue, generation, kind = row.get('venue'), row.get('generation'), row.get('kind')
            if venue not in VENUES or not isinstance(generation, str) or not generation:
                raise ValueError('source venue or generation missing')
            if kind not in ('connection_open', 'frame', *TERMINAL):
                raise ValueError('unknown capture record kind')
            prior_gen = active.get(venue)
            if kind == 'connection_open':
                if (venue, generation) in retired or (venue, generation) in terminated:
                    raise ValueError('retired generation reopened')
                if prior_gen != generation and prior_gen is not None:
                    retired.add((venue, prior_gen))
                    old = dict(row, generation=prior_gen)
                    yield from invalidate_trades(old, 'generation_change')
                    for key in list(ids):
                        if key[0] == venue and key[2] == prior_gen:
                            ids_total -= len(ids.pop(key))
                active[venue] = generation
            elif kind == 'frame' and active.get(venue) != generation:
                raise ValueError('frame outside its open source generation')
            if kind == 'frame' and (venue, generation) in terminated:
                counts['suppressed_frames_after_connection_end'] += 1
                continue
            known_generations = retired | terminated | set(active.items())
            if len(known_generations) > 12:
                raise ValueError('capture generations exceed bound')
            payload, annotation = row.get('payload'), row.get('annotation')
            if kind == 'frame' and (not isinstance(payload, dict) or not isinstance(annotation, dict)):
                raise ValueError('frame payload or annotation malformed')
            market = str(row.get('market'))
            feed = row.get('channel')
            if kind == 'frame' and feed in ('order_book', 'l2Book'):
                data = payload.get('data')
                payload_market = (str(data.get('coin')) if venue == 'hyperliquid' and isinstance(data, dict)
                                  else 'None' if venue == 'hyperliquid'
                                  else str(payload.get('channel', '')).removeprefix('order_book:'))
                if (venue, market) not in identities or payload_market != market:
                    raise ValueError('book source market identity differs')
                source = annotation.get('source_max_ns')
                book_key = (venue, market, generation)
                if isinstance(source, int) and not isinstance(source, bool):
                    if source < book_source_max.get(book_key, 0):
                        annotation = dict(annotation, source_regression_within_channel=True,
                                          reason='book_source_regression')
                        row = dict(row, annotation=annotation)
                    elif source <= receipt:
                        book_source_max[book_key] = source
            rebuild_row = dict(row, kind='connection_close') if kind == 'generation_invalidated' else row
            rebuilder.process(rebuild_row)
            for book in pending:
                book_row = dict(row, generation=prior_gen) if kind == 'connection_open' and prior_gen else row
                common = _common(book_row, book['market'], book['asset'], hedge_venue=hedge_venue)
                if book['valid']:
                    event = {'type': 'book', 'kind': 'book', **common,
                             'source_ns': book['source_utc_ns'], 'sequence': book['sequence'],
                             'clock_valid': True, 'valid': True, 'bids': book['bids'], 'asks': book['asks'],
                             'feed': book['feed'], 'level_count': book['level_count']}
                else:
                    event = _invalidate(book_row, book['market'], book['asset'], 'book',
                                        kind if kind == 'generation_invalidated' else book['reason'], hedge_venue)
                counts[f"yield_{event['type']}:{venue}"] += 1
                yield event
            pending.clear()
            if kind == 'connection_open' or kind in TERMINAL:
                yield {'type': 'control', 'kind': 'control', **_common(row, hedge_venue=hedge_venue),
                       'source_ns': None, 'control': kind}
                if kind in TERMINAL:
                    terminated.add((venue, generation))
                    if len(retired | terminated | set(active.items())) > 12:
                        raise ValueError('capture generations exceed bound')
                    yield from invalidate_trades(row, kind)
                continue
            if feed != ('trades' if venue == 'hyperliquid' else 'trade'):
                continue
            if venue == 'hyperliquid' and payload.get('data') == [] and annotation.get('quality') == 'wire_ok':
                counts['empty_hl_trade_batches'] += 1
                continue
            asset = identities.get((venue, market))
            if asset is None:
                yield from invalidate_trades(row, 'unknown_trade_market')
                continue
            key = (venue, market, generation)
            if venue != 'hyperliquid' and payload.get('type') == 'subscribed/trade':
                counts[f'ignored_backlog_batches:{venue}'] += 1
                if not isinstance(payload.get('trades'), list) or not isinstance(payload.get('liquidation_trades'), list):
                    bad_trades.add(key)
                    yield _invalidate(row, market, asset, 'trade', 'malformed_subscribed_batch', hedge_venue)
                continue
            if key in bad_trades:
                counts['suppressed_trade_frames_after_invalidation'] += 1
                continue
            try:
                if annotation.get('quality') != 'wire_ok' or annotation.get('source_regression_within_channel'):
                    raise ValueError(annotation.get('reason') or 'trade_annotation_invalid')
                if venue == 'hyperliquid':
                    if payload.get('channel') != 'trades':
                        raise ValueError('HL trade channel differs')
                    raw_trades = payload.get('data')
                else:
                    if payload.get('type') != 'update/trade' or payload.get('channel') != f'trade:{market}':
                        raise ValueError('update trade channel differs')
                    raw_trades = payload.get('trades')
                    liquidation = payload.get('liquidation_trades')
                    if not isinstance(liquidation, list):
                        raise ValueError('liquidation list malformed')
                    counts[f'ignored_liquidations:{venue}'] += len(liquidation)
                if not isinstance(raw_trades, list):
                    raise ValueError('trade batch malformed')
                parsed = [_trade(row, raw, market, asset, hedge_venue) for raw in raw_trades]
                batch_max = max((t['source_ns'] for t in parsed), default=None)
                if batch_max is not None and batch_max < source_max.get(key, 0):
                    raise ValueError('trade source regression')
                unique = {t['trade_id'] for t in parsed} - ids[key]
                if ids_total + len(unique) > max_ids:
                    raise ValueError('dedup_capacity_exceeded')
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                bad_trades.add(key)
                counts[f'invalid_trade_batches:{venue}'] += 1
                yield _invalidate(row, market, asset, 'trade', str(exc)[:120], hedge_venue)
                continue
            if batch_max is not None:
                source_max[key] = batch_max
            for trade in parsed:
                if trade['trade_id'] in ids[key]:
                    counts[f'duplicate_trade_ids:{venue}'] += 1
                    continue
                ids[key].add(trade['trade_id'])
                ids_total += 1
                counts[f'yield_trade:{venue}'] += 1
                yield trade
    if counts['decoded_records'] != records:
        raise ValueError('decoded record count differs from manifest')
    _pinned(frames_path, raw_hash, 'gzip changed during replay')
    _pinned(manifest_path, manifest_hash, 'manifest changed during replay')
    for name, digest in metadata_hashes.items():
        _pinned(directory / 'metadata' / name, digest, 'metadata changed during replay')
    # Close any open book/flow at capture end, including sockets cancelled by a cap/signal.
    for venue, generation in active.items():
        end_row = {'venue': venue, 'generation': generation, 'receipt_utc_ns': stop}
        for asset, market in manifest['selected_markets'][venue].items():
            for scope in ('book', 'trade'):
                yield _invalidate(end_row, market, asset, scope, 'capture_end', hedge_venue)
    yield {'type': 'end', 'kind': 'end', 'received_ns': stop, 'receipt_ns': stop,
           'source_ns': None, 'started_ns': start, 'stopped_ns': stop,
           'reason': manifest.get('end_reason'), 'truncated': bool(manifest.get('truncated')),
           'capture_errors': manifest.get('errors', []), 'counts': dict(counts),
           'decoded_bytes': decoded, 'archive_bytes': archive_bytes,
           'max_receipt_gap_ns': max_receipt_gap, 'raw_gzip_sha256': raw_hash,
           'manifest_sha256': manifest_hash, 'raw_sha_verified': True,
           'manifest_sha_verified': True, 'metadata_sha256': metadata_hashes,
           'metadata': metadata, 'hedge_role_source_venue': hedge_venue,
           'book_decoder_counts': dict(rebuilder.counts),
           'adapter_sha256': sha256(Path(__file__)),
           'book_decoder_sha256': sha256(ROOT / 'scripts/maker_book_archive.py')}


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture_dir', type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--hedge-venue', choices=('hyperliquid', 'lighter'))
    args = parser.parse_args(argv)
    for event in iter_events(args.capture_dir, expected_manifest_sha256=args.manifest_sha256,
                             hedge_venue=args.hedge_venue):
        print(json.dumps(event, separators=(',', ':'), allow_nan=False))


if __name__ == '__main__':
    cli()
