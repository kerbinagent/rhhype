#!/usr/bin/env python3
"""Bounded public RH/Hyperliquid maker-research feed capture.

This program never authenticates, signs, or sends an order. The default is a
dry plan. `--run` requires a separately frozen public metadata snapshot.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import time
import uuid

import aiohttp

from maker_capture import BoundedGzip, Capture, compact_counts, utc_iso_ns


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKETS = ROOT / 'data/paper-monitor/markets.json'
DEFAULT_OUTPUT = ROOT / 'data/raw/rh-small-maker'
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
VENUES = ('hyperliquid', 'rh_lighter')
URLS = {'hyperliquid': 'wss://api.hyperliquid.xyz/ws',
        'rh_lighter': 'wss://api.rh.lighter.xyz/stream?readonly=true'}
REQUESTS = {
    'rh_order_book_details': ('GET', 'https://api.rh.lighter.xyz/api/v1/orderBookDetails', None),
    'hl_meta_native': ('POST', 'https://api.hyperliquid.xyz/info', {'type': 'meta'}),
    'hl_meta_xyz': ('POST', 'https://api.hyperliquid.xyz/info', {'type': 'meta', 'dex': 'xyz'}),
}
HARD_SECONDS = 3_000
CALIBRATION_SECONDS = 1_800
HARD_BYTES = 512_000_000
DEFAULT_BYTES = 384_000_000
METADATA_MAX_BYTES = 5_000_000
MANIFEST_RESERVE = 1_000_000
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_CONNECTIONS_PER_VENUE = 256
MAX_BACKOFF_SECONDS = 30


def subscriptions(venue: str, markets: dict[str, str]) -> list[dict]:
    if venue == 'hyperliquid':
        return [{'method': 'subscribe', 'subscription':
                 {'type': 'l2Book', 'coin': coin, 'fast': True}}
                for coin in markets.values()] + [
                    {'method': 'subscribe', 'subscription': {'type': 'trades', 'coin': coin}}
                    for coin in markets.values()]
    if venue == 'rh_lighter':
        return [{'type': 'subscribe', 'channel': f'{feed}/{market}'}
                for market in markets.values() for feed in ('order_book', 'trade')]
    raise ValueError(f'Unsupported venue: {venue}')


def valid_hl_ack(payload: dict, markets: dict[str, str]) -> bool:
    data = payload.get('data')
    sub = data.get('subscription') if isinstance(data, dict) else None
    if not isinstance(sub, dict) or sub.get('coin') not in set(markets.values()):
        return False
    if sub.get('type') == 'l2Book':
        return sub.get('fast') is True
    return sub.get('type') == 'trades'


def selected_markets(path: Path) -> tuple[dict[str, dict[str, str]], str]:
    if path.stat().st_size > METADATA_MAX_BYTES:
        raise ValueError('Market plan exceeds 5 MB')
    raw = path.read_bytes()
    plan = json.loads(raw)
    selected = {venue: {} for venue in VENUES}
    for pair in plan['pairs']:
        asset = pair.get('asset')
        hl, rh = pair.get('hl', {}), pair.get('other', {})
        if (asset in ASSETS and hl.get('venue') == 'hyperliquid'
                and rh.get('venue') == 'rh_lighter'
                and hl.get('asset') == asset and rh.get('asset') == asset):
            if (asset in selected['hyperliquid'] and
                    (selected['hyperliquid'][asset], selected['rh_lighter'][asset]) !=
                    (str(hl['market']), str(rh['market']))):
                raise ValueError(f'Conflicting RH/HL route for {asset}')
            selected['hyperliquid'][asset] = str(hl['market'])
            selected['rh_lighter'][asset] = str(rh['market'])
    if any(set(markets) != set(ASSETS) for markets in selected.values()):
        raise ValueError('BTC, ETH, NVDA, XAG RH/HL routes required in market plan')
    return selected, hashlib.sha256(raw).hexdigest()


def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f'{field} is not a decimal') from exc
    if not result.is_finite():
        raise ValueError(f'{field} is nonfinite')
    return result


def _positive(value, field):
    result = _decimal(value, field)
    if result <= 0:
        raise ValueError(f'{field} must be positive')
    return result


def _lot(decimals: int) -> str:
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 12:
        raise ValueError('Invalid decimal count')
    return str(Decimal(10) ** -decimals)


def _raw_response(metadata_dir: Path, name: str) -> tuple[dict, dict]:
    raw_path = metadata_dir / f'{name}.json'
    request_path = metadata_dir / f'{name}.request.json'
    if raw_path.stat().st_size > METADATA_MAX_BYTES or request_path.stat().st_size > 65_536:
        raise ValueError(f'{name}: metadata input exceeds bound')
    raw = raw_path.read_bytes()
    request = json.loads(request_path.read_bytes())
    method, url, body = REQUESTS[name]
    if (request.get('method'), request.get('url'), request.get('json_body')) != (method, url, body):
        raise ValueError(f'{name}: request provenance mismatch')
    if request.get('status') != 200 or request.get('raw_bytes') != len(raw):
        raise ValueError(f'{name}: unsuccessful or incomplete response')
    if hashlib.sha256(raw).hexdigest() != request.get('sha256'):
        raise ValueError(f'{name}: raw SHA-256 mismatch')
    return json.loads(raw), request


def normalize_metadata(metadata_dir: Path, selected: dict[str, dict[str, str]],
                       market_plan_hash: str) -> dict:
    """Validate frozen raw responses and build a fail-closed order grid map."""
    input_paths = [metadata_dir / f'{name}{suffix}' for name in REQUESTS
                   for suffix in ('.json', '.request.json')]
    if sum(path.stat().st_size for path in input_paths) > METADATA_MAX_BYTES:
        raise ValueError('Combined raw metadata exceeds 5 MB')
    responses = {name: _raw_response(metadata_dir, name) for name in REQUESTS}
    rh = responses['rh_order_book_details'][0]
    if rh.get('code') != 200 or not isinstance(rh.get('order_book_details'), list):
        raise ValueError('RH orderBookDetails response invalid')
    hl_native, hl_xyz = responses['hl_meta_native'][0], responses['hl_meta_xyz'][0]
    if not all(isinstance(x.get('universe'), list) for x in (hl_native, hl_xyz)):
        raise ValueError('HL meta response invalid')
    rh_by_id = {str(row['market_id']): row for row in rh['order_book_details']}
    hl_by_name = {row['name']: row for source in (hl_native, hl_xyz)
                  for row in source['universe']}
    markets = {'rh_lighter': {}, 'hyperliquid': {}}
    for asset in ASSETS:
        rh_market = selected['rh_lighter'][asset]
        hl_market = selected['hyperliquid'][asset]
        r = rh_by_id.get(rh_market)
        h = hl_by_name.get(hl_market)
        if not r or not h or r.get('symbol') != asset or h.get('name') != hl_market:
            raise ValueError(f'Metadata route mismatch: {asset}')
        if r.get('status') != 'active' or r.get('market_type') != 'perp':
            raise ValueError(f'Inactive or non-perp RH market: {asset}')
        if _positive(r.get('multiplier'), 'RH multiplier') != 1:
            raise ValueError(f'Unverified RH contract multiplier: {asset}')
        if r.get('quote_multiplier') != 1:
            raise ValueError(f'Unverified RH quote multiplier: {asset}')
        rh_price_decimals = r['supported_price_decimals']
        rh_size_decimals = r['supported_size_decimals']
        if r.get('price_decimals') != rh_price_decimals or r.get('size_decimals') != rh_size_decimals:
            raise ValueError(f'RH supported/current decimal mismatch: {asset}')
        if r.get('supported_quote_decimals') != rh_price_decimals + rh_size_decimals:
            raise ValueError(f'RH quote decimal scale mismatch: {asset}')
        price_tick, size_step = _lot(rh_price_decimals), _lot(rh_size_decimals)
        min_qty = _positive(r['min_base_amount'], 'RH min_base_amount')
        min_quote = _positive(r['min_quote_amount'], 'RH min_quote_amount')
        max_quote = _positive(r['order_quote_limit'], 'RH order_quote_limit')
        markets['rh_lighter'][asset] = {
            'venue': 'rh_lighter', 'market': rh_market, 'asset': asset,
            'base_unit': asset, 'contract_multiplier': str(r['multiplier']),
            'quote_multiplier': r['quote_multiplier'],
            'payout': 'linear_perpetual_assumed_from_market_type',
            'price_tick': price_tick,
            'price_tick_semantics': 'decimal_grid_from_supported_price_decimals',
            'price_sig_figs': None, 'price_max_decimals': rh_price_decimals,
            'quote_decimals': r.get('supported_quote_decimals'),
            'size_step': size_step, 'min_qty': str(min_qty), 'max_qty': None,
            'min_notional': str(min_quote), 'min_notional_currency': 'USDG',
            'min_quote': str(min_quote), 'max_quote': str(max_quote),
            'maker_fee_bps': str(_decimal(r['maker_fee'], 'RH maker_fee') * 100),
            'taker_fee_bps': str(_decimal(r['taker_fee'], 'RH taker_fee') * 100),
            'fee_raw_unit': 'percentage_per_official_Lighter_SDK',
            'processing_delay_ms': None,
            'raw_response': 'rh_order_book_details.json', 'raw_market_id': r['market_id'],
            'unknowns': ['max_qty', 'published_processing_delay_ms', 'base_unit_oracle_contract_spec'],
        }
        hl_sz_decimals = h['szDecimals']
        hl_size_step = _lot(hl_sz_decimals)
        growth = h.get('growthMode') == 'enabled'
        scale = _positive(h.get('deployerFeeScale', 1), 'HL deployerFeeScale')
        fee_multiplier = (scale + 1 if scale < 1 else 2 * scale) * (Decimal('.1') if growth else 1)
        fee_multiplier = fee_multiplier if hl_market.startswith('xyz:') else Decimal(1)
        collateral_id = hl_xyz.get('collateralToken') if hl_market.startswith('xyz:') else hl_native.get('collateralToken')
        markets['hyperliquid'][asset] = {
            'venue': 'hyperliquid', 'market': hl_market, 'asset': asset,
            'base_unit': asset, 'contract_multiplier': None,
            'payout': 'linear_perpetual_assumed_from_market_type',
            'price_tick': None, 'price_tick_semantics': 'hl_perp',
            'price_rule_detail':
            'dynamic_5_significant_figures_max_6_minus_szDecimals_places_integer_exemption',
            'price_sig_figs': 5, 'price_max_decimals': 6 - hl_sz_decimals,
            'size_step': hl_size_step, 'min_qty': None, 'max_qty': None,
            'min_notional': '10', 'min_notional_currency': 'USDC',
            'min_quote': None, 'max_quote': None,
            'maker_fee_bps': str(Decimal('1.5') * fee_multiplier),
            'taker_fee_bps': str(Decimal('4.5') * fee_multiplier),
            'fee_assumption': 'standard_base_perp_schedule_no_account_discounts',
            'fee_multiplier_from_meta': str(fee_multiplier),
            'fee_raw_unit': 'basis_points_assumption_from_published_standard_schedule',
            'processing_delay_ms': None, 'collateral_token_id': collateral_id,
            'raw_response': 'hl_meta_native.json' if hl_market in {'BTC', 'ETH'} else 'hl_meta_xyz.json',
            'raw_market_name': h['name'], 'sz_decimals': hl_sz_decimals,
            'growth_mode': h.get('growthMode'),
            'deployer_fee_scale': h.get('deployerFeeScale'),
            'unknowns': ['contract_multiplier', 'account_specific_fee_tier',
                         'published_processing_delay_ms', 'max_qty'],
        }
    return {'schema': 'rh-maker-public-metadata-v1', 'market_plan_sha256': market_plan_hash,
            'raw_requests': {name: request for name, (_, request) in responses.items()},
            'markets': markets,
            'sources': {
                'rh_decimals': 'https://github.com/elliottech/lighter-python/blob/main/lighter/api/order_api.py',
                'hl_price_rule': 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size',
                'hl_min_notional': 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses',
                'hl_fees': 'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees',
            },
            'notional_budgets_usd': [100, 250, 500, 1000], 'primary_budget_usd': 1000,
            'notes': ['No RH price tick is inferred from displayed book prices.',
                      'HL has a dynamic price validator, not one fixed tick.',
                      'HL fees are Standard schedule assumptions, not account-specific measurements.',
                      'Missing account-specific fees and processing delays remain unknown.']}


async def fetch_metadata(out: Path) -> Path:
    """One public request per endpoint; preserve exact response bytes and timing."""
    out.mkdir(parents=True, exist_ok=False)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        total_response_bytes = 0
        for name, (method, url, body) in REQUESTS.items():
            started = time.time_ns()
            async with session.request(method, url, json=body) as response:
                raw = await bounded_response(response, METADATA_MAX_BYTES - total_response_bytes)
                ended = time.time_ns()
                status = response.status
            total_response_bytes += len(raw)
            (out / f'{name}.json').write_bytes(raw)
            request = {'name': name, 'method': method, 'url': url, 'json_body': body,
                       'request_started_utc_ns': started, 'response_completed_utc_ns': ended,
                       'status': status, 'raw_file': f'{name}.json', 'raw_bytes': len(raw),
                       'sha256': hashlib.sha256(raw).hexdigest()}
            (out / f'{name}.request.json').write_text(json.dumps(request, indent=2))
            if status != 200:
                raise ValueError(f'{name} returned HTTP {status}')
    return out


async def bounded_response(response, remaining_limit: int) -> bytes:
    """Read only a capped public response, including before any allocation."""
    chunks = []
    count = 0
    async for chunk in response.content.iter_chunked(65_536):
        count += len(chunk)
        if count > remaining_limit:
            raise ValueError('Combined metadata response exceeds 5 MB')
        chunks.append(chunk)
    return b''.join(chunks)


def freeze_normalization(metadata_dir: Path, selected: dict, plan_hash: str,
                         market_plan_path: Path) -> dict:
    frozen_plan = metadata_dir / 'market_plan.json'
    if market_plan_path.stat().st_size > METADATA_MAX_BYTES:
        raise ValueError('Market plan exceeds metadata limit')
    plan_bytes = market_plan_path.read_bytes()
    if hashlib.sha256(plan_bytes).hexdigest() != plan_hash:
        raise ValueError('Market plan changed during freeze')
    if frozen_plan.exists():
        if frozen_plan.read_bytes() != plan_bytes:
            raise ValueError('Frozen market plan differs from current source')
    else:
        frozen_plan.write_bytes(plan_bytes)
    normalized = normalize_metadata(metadata_dir, selected, plan_hash)
    path = metadata_dir / 'normalized.json'
    if path.exists():
        existing = json.loads(path.read_bytes())
        if existing != normalized:
            raise ValueError('Frozen normalized metadata differs from current inputs')
    else:
        path.write_text(json.dumps(normalized, indent=2, sort_keys=True, allow_nan=False))
    return normalized


def verify_metadata(metadata_dir: Path, selected: dict, plan_hash: str) -> dict:
    normalized = normalize_metadata(metadata_dir, selected, plan_hash)
    frozen = json.loads((metadata_dir / 'normalized.json').read_bytes())
    if normalized != frozen:
        raise ValueError('Metadata normalization or market plan changed since freeze')
    return frozen


class RhMakerCapture(Capture):
    """Reuse the frozen writer/quality/counter machinery with a narrower feed plan."""

    def __init__(self, writer, selected, seconds, total_cap):
        super().__init__(writer, selected, seconds, total_cap)
        self.connection_attempts = Counter()

    async def venue_loop(self, venue):
        markets = self.selected[venue]
        for attempt in range(1, MAX_CONNECTIONS_PER_VENUE + 1):
            if self.stop.is_set():
                break
            self.connection_attempts[venue] += 1
            generation = f'{venue}:{attempt}:{uuid.uuid4().hex[:12]}'
            opened_ns = time.time_ns()
            generation_record = {'venue': venue, 'generation': generation,
                                 'opened_utc': utc_iso_ns(opened_ns)}
            self.generations.append(generation_record)
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(URLS[venue], heartbeat=30,
                                                  receive_timeout=10,
                                                  max_msg_size=MAX_FRAME_BYTES) as ws:
                        self.record({'kind': 'connection_open', 'venue': venue,
                                     'generation': generation, 'receipt_utc_ns': time.time_ns(),
                                     'markets': markets})
                        for sub in subscriptions(venue, markets):
                            await ws.send_json(sub)
                        next_ping = time.monotonic() + 45
                        last_resubscribe = {}
                        while not self.stop.is_set():
                            if time.monotonic() >= next_ping:
                                await ws.send_json({'method': 'ping'} if venue == 'hyperliquid'
                                                   else {'type': 'ping'})
                                self.counts[f'{venue}|outbound_keepalive'] += 1
                                next_ping = time.monotonic() + 45
                            try:
                                frame = await ws.receive(timeout=1)
                            except asyncio.TimeoutError:
                                continue
                            receipt_ns, monotonic_ns = time.time_ns(), time.monotonic_ns()
                            if frame.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                              aiohttp.WSMsgType.ERROR):
                                self.error(venue, f'socket closed: {frame.type.name}, {str(frame.data)[:100]}')
                                break
                            if frame.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                payload = json.loads(frame.data, parse_constant=_reject_constant)
                            except (TypeError, ValueError) as exc:
                                self.record({'kind': 'invalid_json', 'venue': venue,
                                             'generation': generation, 'receipt_utc_ns': receipt_ns,
                                             'receipt_monotonic_ns': monotonic_ns,
                                             'detail': str(exc)[:100]})
                                self.error(venue, 'invalid JSON frame')
                                break
                            if venue == 'rh_lighter' and isinstance(payload, dict) and payload.get('type') == 'ping':
                                await ws.send_json({'type': 'pong'})
                            annotation = self.quality.inspect(venue, payload, generation)
                            bad_fast_ack = (venue == 'hyperliquid' and isinstance(payload, dict)
                                            and payload.get('channel') == 'subscriptionResponse'
                                            and not valid_hl_ack(payload, markets))
                            if bad_fast_ack:
                                annotation = {'quality': 'invalid', 'reason': 'subscription_ack_mismatch',
                                              'market': None, 'channel': 'subscriptionResponse'}
                            if (venue == 'hyperliquid' and annotation.get('quality') == 'invalid'
                                    and annotation.get('channel') == 'trades' and annotation.get('market') is None):
                                for affected in markets.values():
                                    self.quality.trade_valid[(venue, affected, generation)] = False
                                annotation['all_venue_trade_markets_invalidated'] = True
                            self.note_source_order(venue, generation, annotation)
                            if ((venue == 'hyperliquid' and isinstance(payload, dict)
                                 and payload.get('channel') == 'subscriptionResponse') or
                                (venue == 'rh_lighter' and isinstance(payload, dict)
                                 and str(payload.get('type', '')).startswith('subscribed/'))):
                                self.counts[f'{venue}|subscription_acks'] += 1
                            row = {'kind': 'frame', 'venue': venue, 'generation': generation,
                                   'receipt_utc_ns': receipt_ns,
                                   'receipt_monotonic_ns': monotonic_ns,
                                   'market': annotation.get('market'),
                                   'channel': annotation.get('channel'),
                                   'annotation': annotation, 'payload': payload}
                            if not self.record(row):
                                break
                            if annotation.get('quality') == 'invalid':
                                self.counts[f'{venue}|invalid_frames'] += 1
                            if bad_fast_ack:
                                self.error(venue, 'Fast L2/trade subscription acknowledgement mismatch')
                                self.finish('subscription_ack_mismatch')
                                break
                            market = annotation.get('market')
                            if (venue == 'rh_lighter' and annotation.get('resubscribe')
                                    and market in set(markets.values())):
                                now = time.monotonic()
                                if now - last_resubscribe.get(market, -1e9) >= 2:
                                    channel = f'order_book/{market}'
                                    await ws.send_json({'type': 'unsubscribe', 'channel': channel})
                                    await ws.send_json({'type': 'subscribe', 'channel': channel})
                                    last_resubscribe[market] = now
                                    self.counts[f'{venue}|book_resubscribe'] += 1
                        if not self.stop.is_set():
                            self.record({'kind': 'connection_close', 'venue': venue,
                                         'generation': generation, 'receipt_utc_ns': time.time_ns(),
                                         'close_code': ws.close_code})
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
                self.error(venue, exc)
                self.record({'kind': 'connection_error', 'venue': venue,
                             'generation': generation, 'receipt_utc_ns': time.time_ns(),
                             'detail': str(exc)[:240], 'markets': markets})
            finally:
                self.quality.disconnect(venue, markets.values(), generation)
                self.record({'kind': 'generation_invalidated', 'venue': venue,
                             'generation': generation, 'receipt_utc_ns': time.time_ns(),
                             'markets': markets, 'reason': 'connection_end'})
                self.counts[f'{venue}|connections_ended'] += 1
                generation_record['closed_utc'] = utc_iso_ns(time.time_ns())
            if not self.stop.is_set():
                await asyncio.sleep(min(MAX_BACKOFF_SECONDS, 2 * attempt))
        if not self.stop.is_set():
            self.finish(f'{venue}_reconnect_limit')


def _reject_constant(value):
    raise ValueError(f'nonfinite JSON constant: {value}')


def _copy_metadata(source: Path, destination: Path) -> int:
    names = [f'{name}{suffix}' for name in REQUESTS for suffix in ('.json', '.request.json')]
    names.extend(('normalized.json', 'market_plan.json'))
    total = sum((source / name).stat().st_size for name in names)
    if total > METADATA_MAX_BYTES:
        raise ValueError('Frozen metadata exceeds 5 MB')
    data = {name: (source / name).read_bytes() for name in names}
    destination.mkdir()
    for name, raw in data.items():
        (destination / name).write_bytes(raw)
    return total


async def capture(args, selected, plan_hash, normalized):
    out = args.out or DEFAULT_OUTPUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    metadata_bytes = _copy_metadata(args.metadata_dir, out / 'metadata')
    writer = BoundedGzip(out / 'frames.jsonl.gz', args.max_bytes - metadata_bytes,
                         reserve=MANIFEST_RESERVE)
    run = RhMakerCapture(writer, selected, args.seconds, args.max_bytes)
    loop = asyncio.get_running_loop()
    installed_signals = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, run.finish, f'signal_{sig.name.lower()}')
            installed_signals.append(sig)
        except (NotImplementedError, RuntimeError):
            pass
    tasks = [asyncio.create_task(run.venue_loop(venue)) for venue in VENUES]
    deadline = time.monotonic() + args.seconds
    try:
        while not run.stop.is_set():
            if time.monotonic() >= deadline:
                run.finish('duration_limit')
            elif all(task.done() for task in tasks):
                run.finish('all_connections_ended')
            else:
                await asyncio.sleep(.2)
    finally:
        for sig in installed_signals:
            loop.remove_signal_handler(sig)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        counts, omitted_count_keys = compact_counts(run.counts, 128)
        invalidations, omitted_invalidation_keys = compact_counts(run.quality.invalidations, 64)
        with (out / 'frames.jsonl.gz').open('rb') as frames_file:
            frames_hash = hashlib.file_digest(frames_file, 'sha256').hexdigest()
        manifest = {
            'schema': 'rh-maker-public-capture-v1', 'read_only': True,
            'started_utc': utc_iso_ns(run.started_ns),
            'ended_utc': utc_iso_ns(time.time_ns()),
            'end_reason': run.end_reason or 'unexpected_finalization',
            'truncated': run.end_reason == 'compressed_size_cap',
            'configured_seconds': args.seconds,
            'calibration_seconds': min(CALIBRATION_SECONDS, args.seconds),
            'holdout_seconds': max(0, args.seconds - CALIBRATION_SECONDS),
            'configured_total_bytes': args.max_bytes,
            'compressed_payload_bytes': writer.bytes_written,
            'frames_sha256': frames_hash,
            'metadata_bytes': metadata_bytes, 'payload_records': writer.records,
            'dropped_complete_frame_on_cap': run.dropped_on_cap,
            'market_plan': str(args.markets), 'market_plan_sha256': plan_hash,
            'metadata_source': str(args.metadata_dir),
            'metadata_normalized_sha256': hashlib.sha256(
                (out / 'metadata/normalized.json').read_bytes()).hexdigest(),
            'selected_markets': selected, 'endpoints': URLS,
            'subscriptions': {v: subscriptions(v, selected[v]) for v in VENUES},
            'connection_attempts': dict(run.connection_attempts),
            'generations': run.generations[:MAX_CONNECTIONS_PER_VENUE * len(VENUES)],
            'record_counts': counts, 'omitted_record_count_keys': omitted_count_keys,
            'invalidations': invalidations,
            'omitted_invalidation_keys': omitted_invalidation_keys,
            'errors': run.errors,
            'clock_sync_check': 'not performed; source UTC is not calibrated one-way latency',
            'notes': ['Raw public frames preserve receipt/source/generation and nonce annotations.',
                      'No private fills, orders, or P&L are observed or inferred.',
                      'RH order-book deltas require same-generation nonce continuity.',
                      'HL fast L2 is a 5-level snapshot feed; no BBO merge.']}
        body = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
        if writer.bytes_written + metadata_bytes + len(body) > args.max_bytes:
            raise RuntimeError('Manifest reserve exhausted')
        (out / 'manifest.json').write_bytes(body)
    print(out)
    print(f"reason={manifest['end_reason']} records={writer.records} "
          f"total_bytes={writer.bytes_written + metadata_bytes + len(body)}")
    return out


def cli(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--markets', type=Path,
                    help='Market plan; defaults to frozen metadata market_plan.json when present')
    ap.add_argument('--metadata-dir', type=Path,
                    help='Directory with frozen raw responses and normalized.json')
    ap.add_argument('--out', type=Path, help='New output directory')
    ap.add_argument('--seconds', type=int, default=HARD_SECONDS)
    ap.add_argument('--max-bytes', type=int, default=DEFAULT_BYTES)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true', help='Start read-only WebSocket capture')
    mode.add_argument('--fetch-metadata', action='store_true',
                      help='Make only three public metadata requests')
    mode.add_argument('--normalize-metadata', action='store_true',
                      help='Normalize already-frozen raw metadata; no network')
    args = ap.parse_args(argv)
    if not 1 <= args.seconds <= HARD_SECONDS:
        ap.error(f'--seconds must be 1..{HARD_SECONDS}')
    if not METADATA_MAX_BYTES + MANIFEST_RESERVE + 1024 <= args.max_bytes <= HARD_BYTES:
        ap.error(f'--max-bytes must be <= {HARD_BYTES} with metadata/manifest reserve')
    args.markets = args.markets or (
        args.metadata_dir / 'market_plan.json'
        if args.metadata_dir and (args.metadata_dir / 'market_plan.json').exists()
        else DEFAULT_MARKETS)
    selected, plan_hash = selected_markets(args.markets)
    if args.fetch_metadata:
        out = args.out or ROOT / 'data/raw/rh-maker-metadata' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        asyncio.run(fetch_metadata(out))
        freeze_normalization(out, selected, plan_hash, args.markets)
        print(out)
        return
    if args.normalize_metadata:
        if args.metadata_dir is None:
            ap.error('--normalize-metadata requires --metadata-dir')
        freeze_normalization(args.metadata_dir, selected, plan_hash, args.markets)
        print(args.metadata_dir / 'normalized.json')
        return
    if args.metadata_dir is None:
        ap.error('--metadata-dir is required for the dry plan or capture')
    normalized = verify_metadata(args.metadata_dir, selected, plan_hash)
    if not args.run:
        print(json.dumps({'dry_run': True, 'read_only': True,
                          'selected_markets': selected, 'market_plan_sha256': plan_hash,
                          'metadata_dir': str(args.metadata_dir),
                          'metadata_schema': normalized['schema'],
                          'seconds': args.seconds,
                          'calibration_seconds': min(CALIBRATION_SECONDS, args.seconds),
                          'holdout_seconds': max(0, args.seconds - CALIBRATION_SECONDS),
                          'total_byte_cap': args.max_bytes,
                          'subscriptions': {v: subscriptions(v, selected[v]) for v in VENUES}},
                         indent=2))
        return
    asyncio.run(capture(args, selected, plan_hash, normalized))


if __name__ == '__main__':
    cli()
