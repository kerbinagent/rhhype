#!/usr/bin/env python3
"""Read-only bounded WebSocket pilot for paired impulse-dislocation quotes."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
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

from horizon_observer import ROOT, atomic_json, load_plan, market_key
from paper_fixed_markout import standard_fee_bps
from paper_impulse import ImpulseObserver
from paper_streams import StreamManager


ASSETS = ('BTC','ETH','NVDA','XAG')


def select_impulse_pairs(plan, *, max_pairs=8, min_volume=1_000_000):
    if not 1 <= max_pairs <= 8:
        raise ValueError('pair cap must be 1–8')
    selected = []
    for asset in ASSETS:
        for venue in ('lighter','rh_lighter'):
            matches = [p for p in plan if p.get('asset') == asset and
                       p['hl']['venue'] == 'hyperliquid' and
                       p['other']['venue'] == venue and
                       min(float(p['hl'].get('volume',0)),
                           float(p['other'].get('volume',0))) >= min_volume]
            if matches:
                selected.append(max(matches, key=lambda p: min(
                    float(p['hl']['volume']),float(p['other']['volume']))))
            if len(selected) >= max_pairs:
                return selected
    return selected


class ImpulseResearch:
    def __init__(self, pairs, *, notional=1000, prefer_bbo=True):
        if not 1 <= len(pairs) <= 8:
            raise ValueError('impulse pilot requires 1–8 pairs')
        self.pairs = {}
        self.routes_by_market = defaultdict(list)
        self.books = {}
        self.feeds = {}
        self.stats = Counter()
        self.started = time.time()
        self.closing = False
        self.prefer_bbo = prefer_bbo
        self.model = ImpulseObserver(notional=notional)
        self.frozen_fees_bps = {}
        for pair in pairs:
            hl, other = pair['hl'], pair['other']
            identity = f"{pair['asset']}|{market_key(hl)}|{market_key(other)}"
            if identity in self.pairs:
                raise ValueError('duplicate physical pair')
            self.pairs[identity] = pair
            for m in (hl, other):
                key = market_key(m)
                self.routes_by_market[key].append(identity)
                self.frozen_fees_bps[key] = standard_fee_bps(m)

    def on_status(self, venue, payload):
        status = {k:v for k,v in payload.items() if k != 'references'}
        if status:
            self.feeds.setdefault(venue, {}).update(status)

    def on_book(self, book):
        if self.closing:
            return
        key = f"{book['venue']}:{book['market']}"
        self.stats['book_events'] += 1
        if not book.get('valid'):
            self.books.pop(key, None)
            self.stats['invalid_books'] += 1
            for pair in self.routes_by_market.get(key, ()):
                self.model.invalidate(pair, book.get('received',time.time()), 'feed_gap')
            return
        self.books[key] = book
        for identity in self.routes_by_market.get(key, ()):
            pair = self.pairs[identity]
            hl_key, other_key = market_key(pair['hl']), market_key(pair['other'])
            hl, other = self.books.get(hl_key), self.books.get(other_key)
            side = 'hl' if key == hl_key else 'other'
            if self.model.on_event(identity, book['received'], hl, other, side, pair):
                self.stats['model_valid_events'] += 1
            else:
                self.stats['model_rejected_events'] += 1

    def finish(self, now=None):
        if self.closing:
            return
        self.closing = True
        self.model.finish(time.time() if now is None else now)

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        return {'status': 'stopped' if self.closing else 'running',
                'updated_at': now, 'started_at': self.started,
                'pair_count': len(self.pairs),
                'pairs': list(self.pairs),
                'hl_quote_mode': 'bbo_only_for_new_top_or_l2_snapshot' if self.prefer_bbo else 'l2_only',
                'frozen_standard_fee_bps_by_market': dict(self.frozen_fees_bps),
                'rh_usdg_usdc_assumption': 'parity quote screen only; no conversion claim',
                'stats': dict(self.stats), 'feeds': self.feeds,
                'model': self.model.snapshot(now)}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markets', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT/'data/impulse-research')
    parser.add_argument('--duration', type=float, default=1200)
    parser.add_argument('--report-seconds', type=float, default=10)
    parser.add_argument('--max-pairs', type=int, default=8)
    parser.add_argument('--min-volume', type=float, default=1_000_000)
    parser.add_argument('--notional', type=float, default=1000)
    parser.add_argument('--max-metadata-age-hours', type=float, default=24)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    numeric = (args.duration,args.report_seconds,args.min_volume,args.notional,
               args.max_metadata_age_hours)
    if (not all(math.isfinite(x) for x in numeric) or
            not 0 < args.duration <= 2400 or args.report_seconds <= 0 or
            not 1 <= args.max_pairs <= 8 or args.min_volume < 0 or
            args.notional <= 0 or args.max_metadata_age_hours <= 0):
        parser.error('invalid duration, interval, pair cap, volume, notional or metadata age')
    if (args.out.resolve() == args.markets.parent.resolve() or
            args.markets.parent.resolve() in args.out.resolve().parents):
        parser.error('output must be separate from source monitor directory')
    return args


async def run(args, pairs, age):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT,signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    observer = ImpulseResearch(pairs, notional=args.notional)
    markets = list({market_key(m):m for p in pairs
                    for m in (p['hl'],p['other'])}.values())
    atomic_json(args.out/'plan.json', {
        'created_at':time.time(), 'source_markets':str(args.markets.resolve()),
        'source_metadata_age_seconds':age, 'pairs':pairs, 'markets':markets,
        'frozen_standard_fee_bps_by_market':observer.frozen_fees_bps,
        'model_version':1, 'public_websocket_only':True, 'orders_enabled':False,
        'rh_usdg_usdc_assumption':'parity quote screen only; no conversion claim'})

    async def reports():
        while not stop.is_set():
            atomic_json(args.out/'impulse_snapshot.json',observer.snapshot())
            try:
                await asyncio.wait_for(stop.wait(),timeout=args.report_seconds)
            except asyncio.TimeoutError:
                pass

    status = 'stopped'
    async with aiohttp.ClientSession(headers={'User-Agent':'rhhype-impulse-research/1.0'}) as session:
        streams = StreamManager(session,markets,observer.on_book,observer.on_status,
                                max_levels=100,prefer_bbo=True)
        tasks = [asyncio.create_task(streams.run(stop)),asyncio.create_task(reports())]
        stopper, timer = asyncio.create_task(stop.wait()),asyncio.create_task(asyncio.sleep(args.duration))
        try:
            done,_ = await asyncio.wait([*tasks,stopper,timer],return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done:
                    task.result()
                    raise RuntimeError('impulse observer worker stopped unexpectedly')
        except BaseException:
            status = 'failed'
            raise
        finally:
            observer.finish()
            stop.set()
            for task in [*tasks,stopper,timer]: task.cancel()
            await asyncio.gather(*tasks,stopper,timer,return_exceptions=True)
            snap = observer.snapshot()
            snap['status'] = status
            atomic_json(args.out/'impulse_snapshot.json',snap)


def main(argv=None):
    args = arguments(argv)
    plan,age = load_plan(args.markets,args.max_metadata_age_hours)
    pairs = select_impulse_pairs(plan,max_pairs=args.max_pairs,min_volume=args.min_volume)
    if not pairs:
        raise SystemExit('No eligible HL/Lighter BTC, ETH, NVDA or XAG pairs')
    if args.dry_run:
        print(json.dumps({'source_metadata_age_seconds':age,
                          'pairs':[{'asset':p['asset'], 'hl':market_key(p['hl']),
                                    'other':market_key(p['other'])} for p in pairs]},indent=2))
        return
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'impulse.lock').open('a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another impulse observer owns this output directory')
        lock.seek(0);lock.truncate();lock.write(str(os.getpid())+'\n');lock.flush()
        handler = RotatingFileHandler(args.out/'impulse.log',maxBytes=2*1024*1024,backupCount=2)
        logging.basicConfig(level=logging.INFO,handlers=[handler],
                            format='%(asctime)s %(levelname)s %(message)s')
        asyncio.run(run(args,pairs,age))


if __name__ == '__main__':
    main()
