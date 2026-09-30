#!/usr/bin/env python3
"""Prepare a bounded, read-only RH/HL/Lighter Core public feed capture.

The default prints a plan.  No private API, signature, or order path exists here.
This is a separate future-study capture, not the frozen passive-exit v1 feed.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import signal
import time

import aiohttp

from maker_capture import BoundedGzip, Capture, FeedQuality, URLS, compact_counts, subscriptions, utc_iso_ns
from rh_maker_capture import (ASSETS, DEFAULT_MARKETS, METADATA_MAX_BYTES,
                              REQUESTS as TWO_REQUESTS, bounded_response,
                              normalize_metadata as normalize_two)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'data/raw/passive-three-venue'
VENUES = ('rh_lighter', 'hyperliquid', 'lighter')
CORE_REQUEST = ('GET', 'https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails', None)
RH_ASSETS_REQUEST = ('GET', 'https://api.rh.lighter.xyz/api/v1/assetDetails', None)
CORE_ASSETS_REQUEST = ('GET', 'https://mainnet.zklighter.elliot.ai/api/v1/assetDetails', None)
REQUESTS = TWO_REQUESTS | {
    'core_order_book_details': CORE_REQUEST,
    'rh_asset_details': RH_ASSETS_REQUEST,
    'core_asset_details': CORE_ASSETS_REQUEST,
}
HARD_SECONDS = 3_000
HARD_BYTES = 384_000_000
MANIFEST_RESERVE = 262_144
MAX_TRADE_IDS = 750_000
MAX_METADATA_AGE_NS = 30 * 60 * 1_000_000_000


def select_three(path: Path) -> tuple[dict[str, dict[str, str]], str]:
    raw = path.read_bytes()
    plan = json.loads(raw)
    selected = {v: {} for v in VENUES}
    for row in plan['pairs']:
        asset = row.get('asset')
        if asset not in ASSETS:
            continue
        hl, other = row.get('hl', {}), row.get('other', {})
        if hl.get('venue') != 'hyperliquid' or other.get('venue') not in VENUES:
            continue
        venue = other['venue']
        if other.get('asset') != asset or hl.get('asset') != asset:
            continue
        hmarket, market = str(hl['market']), str(other['market'])
        old_hl = selected['hyperliquid'].get(asset)
        old_other = selected[venue].get(asset)
        if (old_hl is not None and old_hl != hmarket) or (old_other is not None and old_other != market):
            raise ValueError(f'Conflicting market route for {asset}/{venue}')
        selected['hyperliquid'][asset] = hmarket
        selected[venue][asset] = market
    for venue, markets in selected.items():
        if set(markets) != set(ASSETS):
            raise ValueError(f'{venue} lacks an explicit BTC/ETH/NVDA/XAG route')
        if len(set(markets.values())) != len(markets):
            raise ValueError(f'{venue} market IDs are not unique')
    return selected, hashlib.sha256(raw).hexdigest()


def _positive(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f'{field} is not decimal') from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f'{field} must be finite and positive')
    return result


def _raw_response(directory: Path, name: str) -> tuple[dict, dict]:
    raw = (directory / f'{name}.json').read_bytes()
    request = json.loads((directory / f'{name}.request.json').read_bytes())
    method, url, body = REQUESTS[name]
    if (request.get('method'), request.get('url'), request.get('json_body')) != (method, url, body):
        raise ValueError(f'{name}: request provenance differs')
    if request.get('status') != 200 or request.get('raw_bytes') != len(raw):
        raise ValueError(f'{name}: HTTP status or byte count differs')
    if request.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError(f'{name}: SHA-256 differs')
    return json.loads(raw), request


def normalize_metadata(directory: Path, selected: dict, plan_hash: str) -> dict:
    inputs = [directory / f'{name}{suffix}' for name in REQUESTS
              for suffix in ('.json', '.request.json')]
    if sum(path.stat().st_size for path in inputs) > METADATA_MAX_BYTES:
        raise ValueError('Combined raw metadata exceeds 5 MB')
    two = normalize_two(directory, {v: selected[v] for v in ('rh_lighter', 'hyperliquid')}, plan_hash)
    core, request = _raw_response(directory, 'core_order_book_details')
    rh_assets, rh_assets_request = _raw_response(directory, 'rh_asset_details')
    core_assets, core_assets_request = _raw_response(directory, 'core_asset_details')
    for venue, response, symbol in (('rh_lighter', rh_assets, 'USDG'),
                                    ('lighter', core_assets, 'USDC')):
        if response.get('code') != 200 or not isinstance(response.get('asset_details'), list):
            raise ValueError(f'{venue} assetDetails response invalid')
        eligible = [r for r in response['asset_details']
                    if r.get('symbol') == symbol and r.get('margin_mode') == 'enabled']
        if len(eligible) != 1:
            raise ValueError(f'{venue} expected enabled {symbol} margin asset not verified')
    if core.get('code') != 200 or not isinstance(core.get('order_book_details'), list):
        raise ValueError('Core orderBookDetails response invalid')
    by_id = {str(r['market_id']): r for r in core['order_book_details']}
    if len(by_id) != len(core['order_book_details']):
        raise ValueError('Core market IDs duplicated')
    markets = two['markets'] | {'lighter': {}}
    for asset in ASSETS:
        two['markets']['rh_lighter'][asset]['collateral'] = 'USDG'
        two['markets']['rh_lighter'][asset]['collateral_evidence'] = 'rh_asset_details_margin_enabled'
    for asset in ASSETS:
        market_id = selected['lighter'][asset]
        row = by_id.get(market_id)
        if row is None or row.get('symbol') != asset:
            raise ValueError(f'Core market identity differs for {asset}')
        if row.get('status') != 'active' or row.get('market_type') != 'perp':
            raise ValueError(f'Core {asset} is not an active perp')
        if _positive(row.get('multiplier'), 'Core multiplier') != 1 or row.get('quote_multiplier') != 1:
            raise ValueError(f'Core {asset} has unverified contract/quote multiplier')
        pd, sd = row.get('supported_price_decimals'), row.get('supported_size_decimals')
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 12 for v in (pd, sd)):
            raise ValueError(f'Core {asset} decimal grid invalid')
        if (row.get('price_decimals'), row.get('size_decimals'), row.get('supported_quote_decimals')) != (pd, sd, pd + sd):
            raise ValueError(f'Core {asset} current/supported decimal grid differs')
        min_qty = _positive(row.get('min_base_amount'), 'Core min_base_amount')
        min_quote = _positive(row.get('min_quote_amount'), 'Core min_quote_amount')
        max_quote = _positive(row.get('order_quote_limit'), 'Core order_quote_limit')
        maker, taker = Decimal(str(row.get('maker_fee'))), Decimal(str(row.get('taker_fee')))
        if not maker.is_finite() or not taker.is_finite() or maker != 0 or taker != 0:
            raise ValueError(f'Core {asset} metadata is not the Standard zero-fee profile')
        markets['lighter'][asset] = {
            'venue': 'lighter', 'market': market_id, 'asset': asset, 'market_type': 'perp',
            'base_unit': asset, 'contract_multiplier': str(row['multiplier']),
            'quote_multiplier': row['quote_multiplier'],
            'price_tick': str(Decimal(10) ** -pd), 'size_step': str(Decimal(10) ** -sd),
            'price_decimals': pd, 'size_decimals': sd, 'quote_decimals': pd + sd,
            'min_qty': str(min_qty), 'min_notional': str(min_quote), 'max_quote': str(max_quote),
            'maker_fee_bps': str(maker * 100), 'taker_fee_bps': str(taker * 100),
            'fee_raw_unit': 'percentage_per_official_Lighter_SDK',
            'collateral': 'USDC', 'collateral_evidence': 'core_asset_details_margin_enabled',
            'processing_delay_ms': 300, 'delay_evidence': 'published_Core_Standard_taker_base_only',
            'raw_response': 'core_order_book_details.json', 'raw_market_id': row['market_id'],
            'unknowns': ['account_specific_tier', 'network_delay_ms', 'funding_cashflows'],
        }
    return {
        'schema': 'passive-three-venue-public-metadata-v1', 'market_plan_sha256': plan_hash,
        'raw_requests': two['raw_requests'] | {
            'core_order_book_details': request,
            'rh_asset_details': rh_assets_request,
            'core_asset_details': core_assets_request,
        },
        'markets': markets,
        'sources': two['sources'] | {
            'core_account_types': 'https://apidocs.lighter.xyz/docs/account-types',
            'core_market_metadata': CORE_REQUEST[1],
            'rh_asset_metadata': RH_ASSETS_REQUEST[1],
            'core_asset_metadata': CORE_ASSETS_REQUEST[1],
        },
        'notes': ['Core and RH Lighter are separate domains, IDs, collateral wallets and books.',
                  'Core/RH price and quantity are per one base perp unit only after multiplier checks.',
                  'Core Standard fee/processing profile is public; account-specific settings are unverified.',
                  'No cross-venue clock synchronization or executable fill is established.'],
    }


def freeze_metadata(directory: Path, plan: Path, selected: dict, plan_hash: str) -> dict:
    raw_plan = plan.read_bytes()
    if len(raw_plan) > METADATA_MAX_BYTES or hashlib.sha256(raw_plan).hexdigest() != plan_hash:
        raise ValueError('Market plan changed or exceeds metadata bound')
    frozen = directory / 'market_plan.json'
    if frozen.exists() and frozen.read_bytes() != raw_plan:
        raise ValueError('Frozen market plan differs')
    if not frozen.exists():
        frozen.write_bytes(raw_plan)
    normalized = normalize_metadata(directory, selected, plan_hash)
    target = directory / 'normalized.json'
    if target.exists() and json.loads(target.read_bytes()) != normalized:
        raise ValueError('Frozen normalization differs')
    if not target.exists():
        target.write_text(json.dumps(normalized, indent=2, sort_keys=True, allow_nan=False))
    return normalized


def verify_metadata(directory: Path, selected: dict, plan_hash: str, *, fresh: bool = False) -> dict:
    normalized = normalize_metadata(directory, selected, plan_hash)
    if json.loads((directory / 'normalized.json').read_bytes()) != normalized:
        raise ValueError('Frozen normalization differs')
    if hashlib.sha256((directory / 'market_plan.json').read_bytes()).hexdigest() != plan_hash:
        raise ValueError('Frozen market plan hash differs')
    if fresh:
        now = time.time_ns()
        for name, request in normalized['raw_requests'].items():
            started = request.get('request_started_utc_ns')
            completed = request.get('response_completed_utc_ns')
            if (not isinstance(started, int) or not isinstance(completed, int)
                    or started > completed or not 0 <= now - completed <= MAX_METADATA_AGE_NS):
                raise ValueError(f'{name}: metadata older than 30 minutes or future dated')
    return normalized


async def fetch_metadata(directory: Path) -> None:
    """Future opt-in: six bounded public HTTP reads, never called by dry plan."""
    directory.mkdir(parents=True, exist_ok=False)
    total = 0
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, (method, url, body) in REQUESTS.items():
            started = time.time_ns()
            async with session.request(method, url, json=body) as response:
                raw = await bounded_response(response, METADATA_MAX_BYTES - total)
                completed = time.time_ns()
                status = response.status
            total += len(raw)
            (directory / f'{name}.json').write_bytes(raw)
            provenance = {'name': name, 'method': method, 'url': url, 'json_body': body,
                          'request_started_utc_ns': started, 'response_completed_utc_ns': completed,
                          'status': status, 'raw_file': f'{name}.json', 'raw_bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest()}
            (directory / f'{name}.request.json').write_text(json.dumps(provenance, indent=2))
            if status != 200:
                raise ValueError(f'{name} returned HTTP {status}')


class ThreeVenueQuality(FeedQuality):
    """Keep bounded, exact update-trade ID dedupe separately per source generation."""

    def __init__(self):
        super().__init__()
        self.ids: dict[tuple[str, str, str], set[str]] = {}
        self.seen_count = 0

    def inspect(self, venue, payload, generation):
        annotation = super().inspect(venue, payload, generation)
        if (venue not in ('rh_lighter', 'lighter') or not isinstance(payload, dict)
                or payload.get('type') != 'update/trade' or annotation.get('channel') != 'trade'):
            return annotation
        trades = payload.get('trades')
        if not isinstance(trades, list):
            return annotation
        market = annotation.get('market')
        if market is None:
            return annotation
        if annotation.get('quality') != 'wire_ok':
            return annotation
        key = (venue, market, generation)
        existing = self.ids.setdefault(key, set())
        new = set()
        duplicate = 0
        for trade in trades:
            ident = trade.get('trade_id_str', trade.get('trade_id')) if isinstance(trade, dict) else None
            if ident is None or not str(ident).isascii() or not str(ident).isdigit():
                self.trade_valid[(venue, market, generation)] = False
                return annotation | {'quality': 'invalid', 'reason': 'missing_trade_id'}
            ident = str(ident)
            if ident in existing or ident in new:
                duplicate += 1
            else:
                new.add(ident)
        if self.seen_count + len(new) > MAX_TRADE_IDS:
            self.trade_valid[(venue, market, generation)] = False
            return annotation | {'quality': 'invalid', 'reason': 'trade_id_dedupe_cap'}
        existing.update(new)
        self.seen_count += len(new)
        return annotation | {'duplicate_trade_ids': duplicate, 'new_trade_ids': len(new),
                             'trade_id_dedupe_scope': 'venue_market_generation_update_only'}


class ThreeVenueCapture(Capture):
    def __init__(self, writer, selected, seconds, total_cap):
        super().__init__(writer, selected, seconds, total_cap)
        self.quality = ThreeVenueQuality()
        self.last_monotonic_by_venue = {}

    def record(self, row):
        venue = row.get('venue')
        clock = row.get('receipt_monotonic_ns')
        if venue in VENUES and isinstance(clock, int):
            previous = self.last_monotonic_by_venue.get(venue)
            if previous is not None and clock < previous:
                row['receipt_monotonic_regression'] = True
                self.counts[f'{venue}|receipt_monotonic_regressions'] += 1
            self.last_monotonic_by_venue[venue] = clock
        annotation = row.get('annotation') or {}
        if annotation.get('duplicate_trade_ids'):
            self.counts[f'{venue}|{row.get("market")}|duplicate_update_trade_ids'] += annotation['duplicate_trade_ids']
        written = super().record(row)
        if annotation.get('reason') == 'trade_id_dedupe_cap':
            self.finish('trade_id_dedupe_cap')
        return written


def _copy_metadata(source: Path, target: Path) -> int:
    names = [f'{name}{suffix}' for name in REQUESTS for suffix in ('.json', '.request.json')]
    names += ['normalized.json', 'market_plan.json']
    content = {name: (source / name).read_bytes() for name in names}
    total = sum(map(len, content.values()))
    if total > METADATA_MAX_BYTES:
        raise ValueError('Frozen metadata exceeds 5 MB')
    target.mkdir()
    for name, raw in content.items():
        (target / name).write_bytes(raw)
    return total


async def capture(args, selected: dict, plan_hash: str) -> Path:
    out = args.out or DEFAULT_OUTPUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    metadata_bytes = _copy_metadata(args.metadata_dir, out / 'metadata')
    writer = BoundedGzip(out / 'frames.jsonl.gz', args.max_bytes - metadata_bytes,
                         reserve=MANIFEST_RESERVE)
    run = ThreeVenueCapture(writer, selected, args.seconds, args.max_bytes)
    loop = asyncio.get_running_loop()
    installed = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, run.finish, f'signal_{sig.name.lower()}')
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            pass
    tasks = {venue: asyncio.create_task(run.venue_loop(venue)) for venue in VENUES}
    deadline = time.monotonic() + args.seconds
    try:
        while not run.stop.is_set():
            if time.monotonic() >= deadline:
                run.finish('duration_limit')
            else:
                ended = [v for v, task in tasks.items() if task.done()]
                if ended:
                    run.finish('venue_ended:' + ','.join(ended))
                else:
                    await asyncio.sleep(.2)
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        writer.close()
    with (out / 'frames.jsonl.gz').open('rb') as handle:
        frames_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    counts, omitted_counts = compact_counts(run.counts, 128)
    invalidations, omitted_invalidations = compact_counts(run.quality.invalidations, 64)
    manifest = {
        'schema': 'passive-three-venue-public-capture-v1', 'read_only': True,
        'started_utc': utc_iso_ns(run.started_ns), 'ended_utc': utc_iso_ns(time.time_ns()),
        'end_reason': run.end_reason, 'truncated': run.end_reason == 'compressed_size_cap',
        'configured_seconds': args.seconds, 'configured_total_bytes': args.max_bytes,
        'compressed_payload_bytes': writer.bytes_written, 'metadata_bytes': metadata_bytes,
        'payload_records': writer.records, 'frames_sha256': frames_hash,
        'market_plan_sha256': plan_hash, 'selected_markets': selected,
        'endpoints': {v: URLS[v] for v in VENUES},
        'subscriptions': {v: subscriptions(v, selected[v]) for v in VENUES},
        'generations': run.generations[:12], 'record_counts': counts,
        'omitted_record_count_keys': omitted_counts,
        'invalidations': invalidations, 'omitted_invalidation_keys': omitted_invalidations,
        'unique_update_trade_ids': run.quality.seen_count,
        'dropped_complete_frame_on_cap': run.dropped_on_cap, 'errors': run.errors,
        'clock_sync_check': 'not performed; source UTC and local receipt clocks are not calibrated',
        'notes': ['RH Lighter and Lighter Core retain distinct venue labels and market IDs.',
                  'Book quality is generation/nonce scoped; update-trade IDs are deduped per venue/market/generation.',
                  'Subscribed trade backlog and liquidation prints remain raw and must not be treated as new flow.',
                  'No observed order, fill, hedge, or P&L is inferred.'],
    }
    body = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
    if writer.bytes_written + metadata_bytes + len(body) > args.max_bytes:
        raise RuntimeError('Manifest reserve exhausted')
    (out / 'manifest.json').write_bytes(body)
    return out


def cli(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--markets', type=Path)
    ap.add_argument('--metadata-dir', type=Path)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--seconds', type=int, default=HARD_SECONDS)
    ap.add_argument('--max-bytes', type=int, default=HARD_BYTES)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--fetch-metadata', action='store_true')
    mode.add_argument('--normalize-metadata', action='store_true')
    mode.add_argument('--run', action='store_true')
    args = ap.parse_args(argv)
    if not 1 <= args.seconds <= HARD_SECONDS:
        ap.error('--seconds must be 1..3000')
    if not METADATA_MAX_BYTES + MANIFEST_RESERVE + 1024 <= args.max_bytes <= HARD_BYTES:
        ap.error('--max-bytes exceeds 384 MB or leaves no metadata/manifest reserve')
    args.markets = args.markets or (
        args.metadata_dir / 'market_plan.json'
        if args.metadata_dir and (args.metadata_dir / 'market_plan.json').exists()
        else DEFAULT_MARKETS)
    selected, plan_hash = select_three(args.markets)
    if args.fetch_metadata:
        out = args.out or DEFAULT_OUTPUT / ('metadata-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        asyncio.run(fetch_metadata(out))
        freeze_metadata(out, args.markets, selected, plan_hash)
        print(out)
        return
    if args.normalize_metadata:
        if args.metadata_dir is None:
            ap.error('--normalize-metadata requires --metadata-dir')
        freeze_metadata(args.metadata_dir, args.markets, selected, plan_hash)
        print(args.metadata_dir / 'normalized.json')
        return
    if args.run:
        if args.metadata_dir is None:
            ap.error('--run requires fresh frozen --metadata-dir')
        verify_metadata(args.metadata_dir, selected, plan_hash, fresh=True)
        print(asyncio.run(capture(args, selected, plan_hash)))
        return
    print(json.dumps({'dry_plan': True, 'read_only': True, 'selected_markets': selected,
                      'market_plan_sha256': plan_hash, 'seconds': args.seconds,
                      'total_byte_cap': args.max_bytes,
                      'metadata_required_before_run': list(REQUESTS),
                      'subscriptions': {v: subscriptions(v, selected[v]) for v in VENUES}},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    cli()
