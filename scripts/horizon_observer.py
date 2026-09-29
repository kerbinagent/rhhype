#!/usr/bin/env python3
"""Read-only paired-book research for 12-second closing-spread markouts.

This independent process reads an existing discovery plan and public WebSocket
feeds. It never sends orders or uses targeted REST refresh.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict, deque
from decimal import Decimal, ROUND_FLOOR
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import time

import aiohttp

import monitor as legacy
from paper_streams import StreamManager

ROOT = Path(__file__).resolve().parents[1]
PREFERRED_ASSETS = ('BTC', 'ETH', 'SOL', 'ZEC', 'COIN', 'XAG', 'CASHCAT',
                    'HYPE', 'XRP', 'XPL', 'NVDA', 'META')
LOG = logging.getLogger('horizon_observer')


def market_key(m):
    return f"{m['venue']}:{m['market']}"


def select_pairs(plan, preferred=PREFERRED_ASSETS, max_pairs=12, min_volume=1_000_000):
    """One liquid non-Aster pair per preferred asset, then volume-ranked fill."""
    if max_pairs < 1:
        raise ValueError('max_pairs must be positive')
    eligible = []
    for pair in plan:
        h, o = pair['hl'], pair['other']
        # Aster diff reconstruction requires an initial REST snapshot; this
        # observer is intentionally WebSocket-only.
        if h['venue'] != 'hyperliquid' or o['venue'] not in ('lighter', 'rh_lighter'):
            continue
        volume = min(float(h.get('volume', 0)), float(o.get('volume', 0)))
        if volume < min_volume:
            continue
        eligible.append((volume, pair))
    chosen = []
    used = set()
    for asset in preferred:
        matches = [(volume, p) for volume, p in eligible if p['asset'] == asset]
        if not matches:
            continue
        _, pair = max(matches, key=lambda x: (x[0], x[1]['other']['venue']))
        chosen.append(pair)
        used.add((market_key(pair['hl']), market_key(pair['other'])))
        if len(chosen) >= max_pairs:
            return chosen
    for _, pair in sorted(eligible, key=lambda x: -x[0]):
        ident = (market_key(pair['hl']), market_key(pair['other']))
        if ident not in used:
            chosen.append(pair)
            used.add(ident)
        if len(chosen) >= max_pairs:
            break
    return chosen


def executable_mark(pair, buy, sell, buy_book, sell_book, notional=1000):
    """Equal lot-matched quantity; executable entry and immediate closing quote."""
    if notional <= 0:
        raise ValueError('notional must be positive')
    budget = notional
    affordable = legacy.affordable_quantity(buy_book['asks'], budget)
    if affordable is None or not sell_book['bids']:
        return None
    qmax = min(affordable, budget/sell_book['bids'][0][0])
    step = legacy.common_step(buy['step'], sell['step'])
    quantity = float((Decimal(str(qmax))/step).to_integral_value(rounding=ROUND_FLOOR)*step)
    if quantity <= 0 or any(quantity < m.get('min_qty', 0) or
                            quantity > m.get('max_qty', math.inf) for m in (buy, sell)):
        return None
    entry_value = legacy.walk(buy_book['asks'], quantity)
    short_entry_value = legacy.walk(sell_book['bids'], quantity)
    long_liquidation_value = legacy.walk(buy_book['bids'], quantity)
    short_buyback_value = legacy.walk(sell_book['asks'], quantity)
    if any(v is None for v in (entry_value, short_entry_value,
                               long_liquidation_value, short_buyback_value)):
        return None
    if (entry_value < buy.get('min_notional', 0) or
            short_entry_value < sell.get('min_notional', 0)):
        return None
    # Positive means the short buyback costs more than long liquidation pays.
    closing_bps = (short_buyback_value-long_liquidation_value)/entry_value*10_000
    return {'quantity': quantity, 'entry_value': entry_value,
            'short_entry_value': short_entry_value,
            'long_liquidation_value': long_liquidation_value,
            'short_buyback_value': short_buyback_value,
            'closing_bps': closing_bps}


class ResearchObserver:
    def __init__(self, pairs, model, *, notional=1000, max_source_age=2.0,
                 max_source_skew=1.0, max_receipt_skew=1.0, sample_limit=200):
        self.pairs = list(pairs)
        self.model = model
        self.notional = notional
        self.max_source_age = max_source_age
        self.max_source_skew = max_source_skew
        self.max_receipt_skew = max_receipt_skew
        self.books = {}
        self.routes_by_market = defaultdict(list)
        self.routes = {}
        self.last_tokens = {}
        self.coverage = defaultdict(Counter)
        self.latest = deque(maxlen=sample_limit)
        self.feeds = {}
        self.started = time.time()
        self.stats = Counter()
        for pair in self.pairs:
            for buy, sell in ((pair['hl'], pair['other']),
                              (pair['other'], pair['hl'])):
                route = f"{pair['asset']}|{market_key(buy)}|{market_key(sell)}"
                self.routes[route] = (pair, buy, sell)
                for m in (buy, sell):
                    self.routes_by_market[market_key(m)].append(route)

    def on_status(self, venue, payload):
        status = {k: v for k, v in payload.items() if k != 'references'}
        if status:
            self.feeds.setdefault(venue, {}).update(status)

    def on_book(self, book):
        market = f"{book['venue']}:{book['market']}"
        self.stats['book_events'] += 1
        if not book.get('valid'):
            self.books.pop(market, None)
            self.stats['invalid_books'] += 1
            reason = book.get('reason', 'feed_gap')
            for route in self.routes_by_market.get(market, ()):
                self.last_tokens.pop(route, None)
                self.coverage[route]['invalidations'] += 1
                if hasattr(self.model, 'invalidate'):
                    self.model.invalidate(route, book['received'], reason)
            return
        self.books[market] = book
        for route in self.routes_by_market.get(market, ()):
            self._observe_route(route, book['received'])

    def _reject(self, route, reason):
        self.coverage[route][f'rejected_{reason}'] += 1
        self.stats[f'rejected_{reason}'] += 1

    def _observe_route(self, route, now):
        pair, buy, sell = self.routes[route]
        buy_key, sell_key = market_key(buy), market_key(sell)
        a, b = self.books.get(buy_key), self.books.get(sell_key)
        self.coverage[route]['attempts'] += 1
        if not a or not b:
            self._reject(route, 'missing_leg');return
        if not a.get('valid') or not b.get('valid'):
            self._reject(route, 'invalid_leg');return
        if any(x.get('engine_time') is None or x.get('generation') is None or
               x.get('sequence') is None for x in (a, b)):
            self._reject(route, 'missing_source_identity');return
        source_age = (now-a['engine_time'], now-b['engine_time'])
        if any(not math.isfinite(age) or age < -.25 or age > self.max_source_age
               for age in source_age):
            self._reject(route, 'stale_source');return
        source_skew = abs(a['engine_time']-b['engine_time'])
        receipt_skew = abs(a['received']-b['received'])
        if source_skew > self.max_source_skew:
            self._reject(route, 'source_skew');return
        if receipt_skew > self.max_receipt_skew:
            self._reject(route, 'receipt_skew');return
        tokens = ((a['generation'], a['sequence']),
                  (b['generation'], b['sequence']))
        previous = self.last_tokens.get(route)
        if previous is not None and (tokens[0] == previous[0] or
                                     tokens[1] == previous[1]):
            self._reject(route, 'source_not_advanced');return
        mark = executable_mark(pair, buy, sell, a, b, self.notional)
        if mark is None:
            self._reject(route, 'insufficient_depth_or_lot');return
        self.last_tokens[route] = tokens
        observation = {'route': route, 'asset': pair['asset'], 'timestamp': now,
                       'buy': buy_key, 'sell': sell_key, **mark,
                       'buy_source_time': a['engine_time'],
                       'sell_source_time': b['engine_time'],
                       'buy_received': a['received'], 'sell_received': b['received'],
                       'buy_generation': a['generation'],
                       'sell_generation': b['generation'],
                       'buy_book_source': a.get('source'),
                       'sell_book_source': b.get('source'),
                       'buy_sequence': a['sequence'], 'sell_sequence': b['sequence'],
                       'source_skew_ms': source_skew*1000,
                       'receipt_skew_ms': receipt_skew*1000,
                       'buy_source_age_ms': source_age[0]*1000,
                       'sell_source_age_ms': source_age[1]*1000}
        self.latest.append(observation)
        self.coverage[route]['accepted'] += 1
        self.stats['paired_observations'] += 1
        if self.model.observe(route, now, mark['closing_bps'], mark['quantity'],
                              mark['entry_value'], a['engine_time'], b['engine_time'],
                              a['received'], b['received'],
                              a['generation'], b['generation']):
            self.stats['model_observations'] += 1
        else:
            self.stats['model_rejections'] += 1

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        return {'updated_at': now, 'started_at': self.started,
                'status': 'running', 'pair_count': len(self.pairs),
                'route_count': len(self.routes), 'notional_usd': self.notional,
                'metric': '12-second forward executable closing-spread markout; not cash P&L',
                'source_age_limit_seconds': self.max_source_age,
                'source_skew_limit_seconds': self.max_source_skew,
                'receipt_skew_limit_seconds': self.max_receipt_skew,
                'stats': dict(self.stats),
                'coverage': {k: dict(v) for k, v in self.coverage.items()},
                'feeds': self.feeds,
                'recent_observations': list(self.latest)[-100:],
                'model': self.model.snapshot(now)}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')
    os.replace(tmp, path)


def load_plan(path, max_age_hours=24):
    body = json.loads(Path(path).read_text())
    pairs = body['pairs']
    if not pairs:
        raise ValueError('discovery plan has no pairs')
    age = time.time()-min(float(p['metadata_timestamp']) for p in pairs)
    if age > max_age_hours*3600 or age < -60:
        raise ValueError(f'discovery metadata age {age/3600:.1f}h exceeds {max_age_hours}h')
    return pairs, age


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markets', type=Path, required=True,
                        help='Read-only existing paper monitor markets.json')
    parser.add_argument('--out', type=Path, default=ROOT/'data/horizon-research')
    parser.add_argument('--duration', type=float, default=1200,
                        help='Seconds to observe; default one 20-minute interval')
    parser.add_argument('--report-seconds', type=float, default=10)
    parser.add_argument('--max-pairs', type=int, default=12)
    parser.add_argument('--min-volume', type=float, default=1_000_000)
    parser.add_argument('--notional', type=float, default=1000)
    parser.add_argument('--max-metadata-age-hours', type=float, default=24)
    parser.add_argument('--dry-run', action='store_true',
                        help='Print route plan without opening sockets or writing files')
    parser.add_argument('--hl-bbo', action='store_true',
                        help='Use faster HL best quotes alongside depth; never infer deeper liquidity')
    args = parser.parse_args(argv)
    if (args.duration <= 0 or args.report_seconds <= 0 or args.max_pairs < 1 or
            args.max_pairs > 12 or args.notional <= 0 or args.min_volume < 0 or
            args.max_metadata_age_hours <= 0):
        parser.error('invalid positive duration, report interval, pair cap, notional, volume or metadata age')
    if args.out.resolve() == args.markets.parent.resolve() or args.markets.parent.resolve() in args.out.resolve().parents:
        parser.error('--out must be separate from the source monitor directory')
    return args


async def run(args, pairs, age):
    from paper_horizon import HorizonMarkoutObserver

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    model = HorizonMarkoutObserver()
    observer = ResearchObserver(pairs, model, notional=args.notional)
    markets = list({market_key(m): m for p in pairs for m in (p['hl'], p['other'])}.values())
    atomic_json(args.out/'plan.json', {'created_at': time.time(),
                'source_markets': str(args.markets.resolve()),
                'source_metadata_age_seconds': age,
                'pairs': pairs, 'markets': markets,
                'hl_quote_mode': 'bbo_plus_depth' if args.hl_bbo else 'depth',
                'public_websocket_only': True})

    async def reports():
        while not stop.is_set():
            snap = observer.snapshot()
            atomic_json(args.out/'horizon_snapshot.json', snap)
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.report_seconds)
            except asyncio.TimeoutError:
                pass

    async with aiohttp.ClientSession(headers={'User-Agent': 'rhhype-horizon-research/1.0'}) as session:
        streams = StreamManager(session, markets, observer.on_book, observer.on_status, max_levels=100,
                                prefer_bbo=args.hl_bbo)
        tasks = [asyncio.create_task(streams.run(stop)),
                 asyncio.create_task(reports())]
        stopper = asyncio.create_task(stop.wait())
        timer = asyncio.create_task(asyncio.sleep(args.duration))
        status = 'stopped'
        try:
            done, _ = await asyncio.wait([*tasks, stopper, timer],
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done:
                    task.result()
                    raise RuntimeError('observer worker stopped unexpectedly')
        except BaseException:
            status = 'failed'
            raise
        finally:
            stop.set()
            for task in [*tasks, stopper, timer]:
                task.cancel()
            await asyncio.gather(*tasks, stopper, timer, return_exceptions=True)
            snap = observer.snapshot()
            snap['status'] = status
            atomic_json(args.out/'horizon_snapshot.json', snap)
    return observer.snapshot()


def main(argv=None):
    args = arguments(argv)
    plan, age = load_plan(args.markets, args.max_metadata_age_hours)
    pairs = select_pairs(plan, max_pairs=args.max_pairs,
                         min_volume=args.min_volume)
    if not pairs:
        raise SystemExit('No eligible Hyperliquid/Lighter public-WS pairs in discovery plan')
    if args.dry_run:
        print(json.dumps({'source_metadata_age_seconds': age,
                          'pairs': [{'asset': p['asset'], 'hl': market_key(p['hl']),
                                     'other': market_key(p['other'])} for p in pairs]}, indent=2))
        return
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out/'horizon.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another horizon observer owns this output directory')
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid())+'\n')
        lock.flush()
        handler = RotatingFileHandler(args.out/'horizon.log', maxBytes=2*1024*1024,
                                      backupCount=2)
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format='%(asctime)s %(levelname)s %(message)s')
        asyncio.run(run(args, pairs, age))


if __name__ == '__main__':
    main()
