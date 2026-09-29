"""Bounded, read-only comparison of Hyperliquid fast and slow L2 WebSocket feeds.

The default is a dry run. Use --run only after reviewing the plan. No REST or
order endpoints are used, and the probe never imports the paper monitor.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import aiohttp


URL = 'wss://api.hyperliquid.xyz/ws'
COINS = ('BTC', 'xyz:NVDA', 'xyz:SILVER')
# Lot steps from the current public market discovery snapshot, used only for
# measuring whether a $1,000 matched quantity fits displayed depth.
STEPS = {'BTC': Decimal('0.00001'), 'xyz:NVDA': Decimal('0.001'),
         'xyz:SILVER': Decimal('0.01')}
MAX_SECONDS = 120
MAX_RAW_BYTES = 5_000_000
MAX_EVENTS = 20_000


def subscription(coin: str, fast: bool) -> dict:
    if coin not in COINS:
        raise ValueError(f'Unexpected coin: {coin}')
    return {'method': 'subscribe', 'subscription':
            {'type': 'l2Book', 'coin': coin, 'fast': fast}}


def _reject_json_constant(value: str):
    raise ValueError(f'Non-finite JSON constant: {value}')


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[round((len(ordered) - 1) * fraction)], 6)


def _walk_fits(levels: tuple[tuple[Decimal, Decimal], ...], quantity: Decimal) -> bool:
    left = quantity
    for _, size in levels:
        left -= min(left, size)
        if left == 0:
            return True
    return False


@dataclass(frozen=True)
class BookEvent:
    mode: str
    coin: str
    received: float
    source: float
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    @property
    def top(self) -> tuple[Decimal, Decimal]:
        return self.bids[0][0], self.asks[0][0]

    def depth(self) -> dict:
        mid = sum(self.top) / 2
        quantity = (Decimal('1000') / mid / STEPS[self.coin]).to_integral_value(
            rounding=ROUND_FLOOR) * STEPS[self.coin]
        bid_fit = _walk_fits(self.bids, quantity)
        ask_fit = _walk_fits(self.asks, quantity)
        return {'quantity': float(quantity), 'bid_fit': bid_fit,
                'ask_fit': ask_fit, 'both_fit': bid_fit and ask_fit}


def parse_book(mode: str, data: dict, received: float) -> BookEvent:
    coin = data['coin']
    if coin not in COINS:
        raise ValueError('Unexpected book coin')
    source_ms = float(data['time'])
    if not math.isfinite(source_ms) or source_ms <= 0:
        raise ValueError('Invalid book source time')
    if source_ms / 1000 > received:
        raise ValueError('Book source time exceeds receipt time')
    sides = data['levels']
    if not isinstance(sides, list) or len(sides) != 2:
        raise ValueError('Invalid book sides')
    converted = []
    for side in sides:
        if not isinstance(side, list):
            raise ValueError('Invalid book levels')
        levels = []
        for level in side:
            price, size = Decimal(str(level['px'])), Decimal(str(level['sz']))
            if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
                raise ValueError('Invalid book level')
            levels.append((price, size))
        if not levels:
            raise ValueError('Empty book side')
        prices = [price for price, _ in levels]
        if len(prices) != len(set(prices)):
            raise ValueError('Duplicate book price')
        converted.append(tuple(levels))
    if any(a[0] <= b[0] for a, b in zip(converted[0], converted[0][1:])):
        raise ValueError('Bids are not strictly descending')
    if any(a[0] >= b[0] for a, b in zip(converted[1], converted[1][1:])):
        raise ValueError('Asks are not strictly ascending')
    if converted[0][0][0] >= converted[1][0][0]:
        raise ValueError('Crossed book')
    return BookEvent(mode, coin, received, source_ms / 1000,
                     converted[0], converted[1])


class RawCapture:
    """Append whole JSONL records up to a hard byte limit; never truncate JSON."""

    def __init__(self, path: Path, limit: int = MAX_RAW_BYTES):
        self.file = path.open('wb')
        self.limit = limit
        self.bytes = 0
        self.dropped = 0

    def write(self, mode: str, received: float, payload: dict) -> None:
        row = json.dumps({'connection': mode, 'received': received, 'payload': payload},
                         separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if self.bytes + len(row) > self.limit:
            self.dropped += 1
            return
        self.file.write(row)
        self.bytes += len(row)

    def close(self) -> None:
        self.file.close()


class Probe:
    def __init__(self, capture: RawCapture | None = None):
        self.capture = capture
        self.events: list[BookEvent] = []
        self.event_overflow = 0
        self.acks: dict[str, dict[str, dict]] = {'fast': {}, 'slow': {}}
        self.messages = {'fast': 0, 'slow': 0}
        self.errors: list[dict] = []
        self.connections: dict[str, dict] = {'fast': {}, 'slow': {}}

    def record(self, mode: str, payload: dict, received: float) -> None:
        self.messages[mode] += 1
        if self.capture:
            self.capture.write(mode, received, payload)
        channel = payload.get('channel')
        if channel == 'subscriptionResponse':
            data = payload.get('data')
            subscription_data = data.get('subscription', {}) if isinstance(data, dict) else {}
            coin = subscription_data.get('coin')
            expected = mode == 'fast'
            if (subscription_data.get('type') != 'l2Book' or coin not in COINS or
                    subscription_data.get('fast') is not expected):
                self._error(mode, 'ack_mismatch', received, payload)
            elif coin in self.acks[mode]:
                self._error(mode, 'duplicate_ack', received, payload)
            else:
                # Retain the exact server ack, including the echoed fast option.
                self.acks[mode][coin] = {'received': received, 'payload': payload}
        elif channel == 'l2Book':
            try:
                event = parse_book(mode, payload['data'], received)
                if len(self.events) < MAX_EVENTS:
                    self.events.append(event)
                else:
                    self.event_overflow += 1
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                self._error(mode, 'malformed_book', received, str(exc))
        elif channel not in ('pong',):
            self._error(mode, 'unexpected_message', received, payload)

    def _error(self, mode: str, kind: str, received: float, detail: object) -> None:
        if len(self.errors) < 100:
            self.errors.append({'connection': mode, 'kind': kind,
                                'received': received, 'detail': str(detail)[:500]})

    def summary(self, started: float, ended: float) -> dict:
        grouped = defaultdict(list)
        for event in self.events:
            grouped[(event.mode, event.coin)].append(event)
        by_feed = {}
        for mode in ('fast', 'slow'):
            by_feed[mode] = {}
            for coin in COINS:
                events = sorted(grouped[(mode, coin)], key=lambda x: x.received)
                depths = [event.depth() for event in events]
                source_gaps = [b.source - a.source for a, b in zip(events, events[1:])
                               if b.source > a.source]
                receipt_gaps = [b.received - a.received for a, b in zip(events, events[1:])]
                ages = [event.received - event.source for event in events]
                by_feed[mode][coin] = {
                    'books': len(events),
                    'source_gap_median_s': _percentile(source_gaps, .5),
                    'source_gap_p95_s': _percentile(source_gaps, .95),
                    'receipt_gap_median_s': _percentile(receipt_gaps, .5),
                    'receipt_gap_p95_s': _percentile(receipt_gaps, .95),
                    'source_age_median_s': _percentile(ages, .5),
                    'source_age_p95_s': _percentile(ages, .95),
                    'levels_bid_median': _percentile([len(e.bids) for e in events], .5),
                    'levels_ask_median': _percentile([len(e.asks) for e in events], .5),
                    'depth_1000_bid_fit': sum(d['bid_fit'] for d in depths),
                    'depth_1000_ask_fit': sum(d['ask_fit'] for d in depths),
                    'depth_1000_both_fit': sum(d['both_fit'] for d in depths),
                    'acknowledged': coin in self.acks[mode],
                    'nominal_100ms_eligible_book': nominal_delay(events, ended),
                }
        paired = {}
        for coin in COINS:
            fast_events = sorted(grouped[('fast', coin)], key=lambda x: x.received)
            slow_events = sorted(grouped[('slow', coin)], key=lambda x: x.received)
            index, latest = 0, None
            stats = {'fast_books': len(fast_events), 'with_prior_slow': 0,
                     'both_source_fresh_2s_receipt_skew_1s': 0,
                     'fast_fresh_slow_source_old_over_2s': 0,
                     'fast_top_differs_from_slow': 0}
            source_lag = []
            for fast in fast_events:
                while index < len(slow_events) and slow_events[index].received <= fast.received:
                    latest = slow_events[index]
                    index += 1
                if latest is None:
                    continue
                stats['with_prior_slow'] += 1
                source_lag.append(fast.source - latest.source)
                if fast.top != latest.top:
                    stats['fast_top_differs_from_slow'] += 1
                if (0 <= fast.received - fast.source <= 2 and
                        0 <= fast.received - latest.source <= 2 and
                        fast.received - latest.received <= 1):
                    stats['both_source_fresh_2s_receipt_skew_1s'] += 1
                if (0 <= fast.received - fast.source <= 2 and
                        fast.received - latest.source > 2):
                    stats['fast_fresh_slow_source_old_over_2s'] += 1
            stats['fast_minus_slow_source_median_s'] = _percentile(source_lag, .5)
            paired[coin] = stats
        return {'started': started, 'ended': ended, 'duration_seconds': ended - started,
                'url': URL, 'subscriptions_sent':
                {mode: [subscription(coin, mode == 'fast') for coin in COINS]
                 for mode in ('fast', 'slow')},
                'acks': self.acks, 'connections': self.connections,
                'messages': self.messages, 'errors': self.errors,
                'raw_bytes': self.capture.bytes if self.capture else 0,
                'raw_records_dropped': self.capture.dropped if self.capture else 0,
                'events_retained': len(self.events), 'events_dropped': self.event_overflow,
                'feeds': by_feed, 'paired': paired}


def nominal_delay(events: list[BookEvent], ended: float, timeout: float = 3) -> dict:
    """First later book whose source and receipt both clear a 100 ms due time."""
    observed = []
    timed_out = right_censored = 0
    for index, anchor in enumerate(events):
        due = anchor.received + .1
        matched = None
        for later_index in range(index + 1, len(events)):
            later = events[later_index]
            if later.received > due + timeout:
                break
            if later.received >= due and later.source >= due:
                matched = later
                break
        if matched is not None:
            observed.append(matched.received - anchor.received)
        elif ended >= due + timeout:
            timed_out += 1
        else:
            right_censored += 1
    return {'anchors': len(events), 'eligible_within_3s': len(observed),
            'timed_out_3s': timed_out, 'end_censored': right_censored,
            'actual_delay_median_s': _percentile(observed, .5),
            'actual_delay_p95_s': _percentile(observed, .95)}


async def _connection(session: aiohttp.ClientSession, mode: str, probe: Probe,
                      deadline: float) -> None:
    connected = time.time()
    probe.connections[mode] = {'connect_started': connected, 'closed': False}
    try:
        async with session.ws_connect(URL, heartbeat=20, receive_timeout=30,
                                      max_msg_size=1_000_000) as ws:
            probe.connections[mode]['connected_at'] = time.time()
            for coin in COINS:
                await ws.send_json(subscription(coin, mode == 'fast'))
            while time.monotonic() < deadline:
                timeout = min(5, deadline - time.monotonic())
                if timeout <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                except asyncio.TimeoutError:
                    continue
                received = time.time()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data, parse_constant=_reject_json_constant)
                        if not isinstance(payload, dict):
                            raise ValueError('Non-object message')
                    except (ValueError, TypeError) as exc:
                        probe._error(mode, 'bad_json', received, str(exc))
                        continue
                    probe.record(mode, payload, received)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                  aiohttp.WSMsgType.ERROR):
                    probe._error(mode, 'disconnected', received, str(msg.data))
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    probe._error(mode, 'unexpected_binary', received, f'{len(msg.data)} bytes')
            probe.connections[mode]['close_code'] = ws.close_code
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        probe._error(mode, 'connection_error', time.time(), str(exc))
    finally:
        probe.connections[mode]['closed'] = True
        probe.connections[mode]['ended_at'] = time.time()


async def run_probe(duration: int, output_dir: Path) -> Path:
    if duration < 1 or duration > MAX_SECONDS:
        raise ValueError(f'Duration must be between 1 and {MAX_SECONDS} seconds')
    output_dir.mkdir(parents=True, exist_ok=False)
    # Freeze process identity and source bytes before the first network frame.
    (output_dir / 'launch_manifest.json').write_text(
        json.dumps(launch_manifest(), indent=2, allow_nan=False))
    capture = RawCapture(output_dir / 'raw.jsonl')
    probe = Probe(capture)
    started = time.time()
    deadline = time.monotonic() + duration
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await asyncio.wait_for(
                asyncio.gather(*(_connection(session, mode, probe, deadline)
                                 for mode in ('fast', 'slow'))),
                timeout=duration + 1)
    finally:
        ended = time.time()
        capture.close()
        summary = probe.summary(started, ended)
        (output_dir / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False))
    return output_dir / 'summary.json'


def launch_manifest() -> dict:
    root = Path(__file__).resolve().parents[1]
    paths = ('scripts/hyperliquid_fast_probe.py',
             'tests/test_hyperliquid_fast_probe.py',
             'research/hyperliquid-fast-feed.md')
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in paths}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                     text=True).strip()
    return {'pid': os.getpid(), 'command': sys.argv, 'started_utc':
            datetime.now(timezone.utc).isoformat(), 'git_commit': commit,
            'sha256': hashes, 'planned_connections': 2,
            'max_raw_bytes': MAX_RAW_BYTES, 'max_events': MAX_EVENTS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Open two public WebSockets')
    parser.add_argument('--duration', type=int, default=60, help='Seconds; hard maximum 120')
    parser.add_argument('--output-root', type=Path, default=Path('reports/hl-fast-probe'))
    args = parser.parse_args(argv)
    if not 1 <= args.duration <= MAX_SECONDS:
        parser.error(f'--duration must be 1..{MAX_SECONDS}')
    plan = {'connections': 2, 'url': URL, 'duration_seconds': args.duration,
            'max_raw_bytes': MAX_RAW_BYTES, 'max_events': MAX_EVENTS,
            'subscriptions': {mode: [subscription(c, mode == 'fast') for c in COINS]
                              for mode in ('fast', 'slow')}}
    if not args.run:
        print(json.dumps({'dry_run': True, 'plan': plan}, indent=2))
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = args.output_root / stamp
    print(asyncio.run(run_probe(args.duration, path)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
