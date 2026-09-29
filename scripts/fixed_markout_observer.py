#!/usr/bin/env python3
"""Separate public-WebSocket pilot for fixed-quantity prospective quote markouts.

The process never sends orders or targeted REST requests. Selected venues are
Hyperliquid and Lighter only; Aster's REST bootstrap is excluded.
"""

from __future__ import annotations

import argparse
import asyncio
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

from horizon_observer import (ROOT, ResearchObserver, atomic_json,
                              executable_mark, load_plan, market_key, select_pairs)
from paper_fixed_markout import FixedQuantityMarkoutObserver, standard_fee_bps
from paper_horizon import HorizonMarkoutObserver
from paper_streams import StreamManager


class FixedResearchObserver(ResearchObserver):
    """One accepted paired quote feeds the fixed observer before v2 sizing."""

    def __init__(self, pairs, *, notional=1000, max_source_age=2.0,
                 max_source_skew=1.0, max_receipt_skew=1.0,
                 hl_bbo=False):
        if len(pairs) > 12:
            raise ValueError('fixed pilot permits at most 12 pairs')
        self.fixed = FixedQuantityMarkoutObserver(
            max_book_age=max_source_age,
            max_pair_skew=min(max_source_skew, max_receipt_skew))
        self.frozen_fees_bps = {
            market_key(m): standard_fee_bps(m)
            for pair in pairs for m in (pair['hl'], pair['other'])}
        self.metadata_timestamps = [float(pair['metadata_timestamp'])
                                    for pair in pairs if pair.get('metadata_timestamp') is not None]
        self.hl_quote_mode = 'bbo_plus_depth' if hl_bbo else 'depth'
        self._anchor_context = {}
        self.closing = False
        model = HorizonMarkoutObserver(on_anchor=self._on_horizon_anchor)
        super().__init__(pairs, model, notional=notional,
                         max_source_age=max_source_age,
                         max_source_skew=max_source_skew,
                         max_receipt_skew=max_receipt_skew)

    def _on_horizon_anchor(self, route, observation, predictions):
        context = self._anchor_context.get(route)
        if context is None or context['now'] != observation.now:
            raise RuntimeError('v2 anchor has no contemporaneous fixed quote')
        if self.fixed.anchor(route, observation.now, context['quote'],
                             context['buy_fee_bps'], context['sell_fee_bps'],
                             predictions):
            self.stats['fixed_anchors'] += 1
        else:
            self.stats['fixed_anchor_rejections'] += 1

    def on_book(self, book):
        if self.closing:
            return
        if not book.get('valid'):
            market = f"{book['venue']}:{book['market']}"
            for route in self.routes_by_market.get(market, ()):
                self.fixed.invalidate(route, book['received'], 'feed_gap')
        super().on_book(book)

    def _observe_route(self, route, now):
        pair, buy, sell = self.routes[route]
        buy_key, sell_key = market_key(buy), market_key(sell)
        buy_book, sell_book = self.books.get(buy_key), self.books.get(sell_key)
        self.coverage[route]['attempts'] += 1
        # Crucially, original-q outcome resolution happens before an adaptive
        # new-entry quote can fail due to current asks/bids or lot limits.
        if not self.fixed.on_pair(route, now, buy_book, sell_book):
            self._reject(route, 'fixed_pair_invalid_or_unadvanced')
            return
        mark = executable_mark(pair, buy, sell, buy_book, sell_book, self.notional)
        if mark is None:
            self._reject(route, 'new_anchor_depth_or_lot')
            return
        context = {'now': now, 'quote': mark,
                   'buy_fee_bps': self.frozen_fees_bps[buy_key],
                   'sell_fee_bps': self.frozen_fees_bps[sell_key]}
        self._anchor_context[route] = context
        try:
            accepted = self.model.observe(
                route, now, mark['closing_bps'], mark['quantity'],
                mark['entry_value'], buy_book['engine_time'],
                sell_book['engine_time'], buy_book['received'],
                sell_book['received'], buy_book['generation'],
                sell_book['generation'])
        finally:
            self._anchor_context.pop(route, None)
        self.coverage[route]['accepted_adaptive_quote'] += 1
        self.stats['paired_adaptive_quotes'] += 1
        if accepted:
            self.stats['v2_model_observations'] += 1
        else:
            self.stats['v2_model_rejections_or_resolve_only'] += 1

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        result = super().snapshot(now)
        result['metric'] = 'fixed-original-quantity 12–16s quoted capture after four frozen Standard taker fees; no fills'
        result['fixed_fee_assumption'] = 'Standard fee bps frozen from discovery metadata at pilot start, including published floors; not live updates'
        result['frozen_fee_bps_by_market'] = dict(self.frozen_fees_bps)
        result['metadata_oldest_timestamp'] = min(self.metadata_timestamps) if self.metadata_timestamps else None
        result['hl_quote_mode'] = self.hl_quote_mode
        result['pair_source_assumption'] = 'both source and receipt timestamps advance; source/receipt skew <=1s, age <=2s; source future tolerance 0.25s'
        result['fixed_markout'] = self.fixed.snapshot(now)
        return result

    def finish(self, now=None):
        if self.closing:
            return
        self.closing = True
        self.fixed.finish(time.time() if now is None else now)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markets', type=Path, required=True,
                        help='Existing read-only discovery markets.json')
    parser.add_argument('--out', type=Path, default=ROOT/'data/fixed-markout-research')
    parser.add_argument('--duration', type=float, default=1200,
                        help='Seconds to observe; default 1200, hard maximum 2400')
    parser.add_argument('--report-seconds', type=float, default=10)
    parser.add_argument('--max-pairs', type=int, default=12)
    parser.add_argument('--min-volume', type=float, default=1_000_000)
    parser.add_argument('--notional', type=float, default=1000)
    parser.add_argument('--max-metadata-age-hours', type=float, default=24)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--hl-bbo', action='store_true',
                        help='Use HL BBO plus depth; no inferred deeper liquidity')
    args = parser.parse_args(argv)
    if (not all(math.isfinite(value) for value in
                (args.duration, args.report_seconds, args.notional,
                 args.min_volume, args.max_metadata_age_hours)) or
            not 0 < args.duration <= 2400 or args.report_seconds <= 0 or
            not 1 <= args.max_pairs <= 12 or args.notional <= 0 or
            args.min_volume < 0 or args.max_metadata_age_hours <= 0):
        parser.error('invalid pilot duration, report interval, pair cap, notional, volume, or metadata age')
    if (args.out.resolve() == args.markets.parent.resolve() or
            args.markets.parent.resolve() in args.out.resolve().parents):
        parser.error('--out must be separate from the source monitor directory')
    return args


async def run(args, pairs, age):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    observer = FixedResearchObserver(pairs, notional=args.notional,
                                     hl_bbo=args.hl_bbo)
    markets = list({market_key(m): m for pair in pairs
                    for m in (pair['hl'], pair['other'])}.values())
    atomic_json(args.out/'plan.json', {
        'created_at': time.time(),
        'source_markets': str(args.markets.resolve()),
        'source_metadata_age_seconds': age,
        'pairs': pairs, 'markets': markets,
        'frozen_standard_fee_bps_by_market': observer.frozen_fees_bps,
        'fixed_model_version': 1, 'horizon_model_version': 2,
        'hl_quote_mode': 'bbo_plus_depth' if args.hl_bbo else 'depth',
        'public_websocket_only': True, 'orders_enabled': False,
    })

    async def reports():
        while not stop.is_set():
            atomic_json(args.out/'fixed_markout_snapshot.json', observer.snapshot())
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.report_seconds)
            except asyncio.TimeoutError:
                pass

    status = 'stopped'
    async with aiohttp.ClientSession(headers={'User-Agent': 'rhhype-fixed-markout-research/1.0'}) as session:
        streams = StreamManager(session, markets, observer.on_book, observer.on_status,
                                max_levels=100, prefer_bbo=args.hl_bbo)
        tasks = [asyncio.create_task(streams.run(stop)),
                 asyncio.create_task(reports())]
        stopper = asyncio.create_task(stop.wait())
        timer = asyncio.create_task(asyncio.sleep(args.duration))
        try:
            done, _ = await asyncio.wait([*tasks, stopper, timer],
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done:
                    task.result()
                    raise RuntimeError('fixed observer worker stopped unexpectedly')
        except BaseException:
            status = 'failed'
            raise
        finally:
            # StreamManager may emit invalid books while closing sockets.
            # Freeze the research outcome first so these are not feed censures.
            observer.finish()
            stop.set()
            for task in [*tasks, stopper, timer]:
                task.cancel()
            await asyncio.gather(*tasks, stopper, timer, return_exceptions=True)
            snap = observer.snapshot()
            snap['status'] = status
            atomic_json(args.out/'fixed_markout_snapshot.json', snap)
    return observer.snapshot()


def main(argv=None):
    args = arguments(argv)
    plan, age = load_plan(args.markets, args.max_metadata_age_hours)
    pairs = select_pairs(plan, max_pairs=args.max_pairs, min_volume=args.min_volume)
    if not pairs:
        raise SystemExit('No eligible Hyperliquid/Lighter public-WS pairs')
    if args.dry_run:
        print(json.dumps({'source_metadata_age_seconds': age,
                          'pairs': [{'asset': pair['asset'],
                                     'hl': market_key(pair['hl']),
                                     'other': market_key(pair['other'])}
                                    for pair in pairs]}, indent=2))
        return
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out/'fixed_markout.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another fixed observer owns this output directory')
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid())+'\n')
        lock.flush()
        handler = RotatingFileHandler(args.out/'fixed_markout.log',
                                      maxBytes=2*1024*1024, backupCount=2)
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format='%(asctime)s %(levelname)s %(message)s')
        asyncio.run(run(args, pairs, age))


if __name__ == '__main__':
    main()
