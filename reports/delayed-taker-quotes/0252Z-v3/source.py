#!/usr/bin/env python3
"""Bounded post-capture fixed-quantity paired-book diagnostic; default dry plan."""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict, defaultdict
import csv
import datetime as dt
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import heapq
import io
import itertools
import json
import math
from pathlib import Path
import statistics
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_maker_events import iter_events

INPUT = ROOT / 'data/raw/rh-passive-exit-v1/20260930T0252Z'
PROTOCOL = ROOT / 'reports/rh-passive-exit-v1-restart/protocol.json'
ORIGINAL_PROTOCOL = ROOT / 'reports/rh-passive-exit-v1/protocol.json'
METHOD = ROOT / 'research/delayed-taker-fixed-quantity-plan.md'
TESTS = ROOT / 'tests/test_analyze_delayed_taker_quotes.py'
OUTPUT_PARENT = ROOT / 'reports/delayed-taker-quotes'
SCHEMA = 'fixed-quantity-delayed-taker-quote-diagnostic-v1'
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
BUDGETS = (100, 250, 500, 1000)
HORIZONS = (10, 30, 60, 300)
NS = 1_000_000_000
START = 1790736777958514000
AGE = 2 * NS
SKEW = NS
DELAY = NS // 2
DURATION = 3000 * NS
CAP = 4_000_000
LOG_RESERVE = 50_000
WALL_SECONDS = 1200
LEVEL_CACHE_ENTRIES = 16_384
LEVEL_CACHE_BYTES = 8 * 1024 * 1024
RESOURCE_REVISION = 'v3_cache_disabled_recovery'
EXPECTED_RAW = 'c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6'
# Exact captured manifest digest; no network discovery is performed.
EXPECTED_MANIFEST = '5a9e61438df592d895d3cfc5d550241b01f0696fdbd5c83f46666d9ff1274250'
EXPECTED_METADATA = '34249d999bf176b73a2f9e30aa1602f3ab135a7cadc9238a080bfe060f048aba'
ORIGINAL_METADATA = '15712b46e48d77fe971def33b91674173c57d649724bff66f7bcd75b95c4396d'
MARKET_IDS = {'rh_lighter': {'BTC': '1', 'ETH': '0', 'NVDA': '15', 'XAG': '41'},
              'hyperliquid': {'BTC': 'BTC', 'ETH': 'ETH', 'NVDA': 'xyz:NVDA', 'XAG': 'xyz:SILVER'}}
CANDIDATE_FIELDS = ('id', 'anchor_ns', 'stratum', 'asset', 'long_venue', 'budget', 'quantity',
    'status', 'anchor_long_buy_notional', 'anchor_notional_exceeds_budget', 'entry_ns',
    'entry_long_buy', 'entry_short_sell', 'entry_long_fee', 'entry_short_fee',
    'entry_notional_exceeds_anchor_budget', 'entry_drift_from_anchor_walk',
    'instant_adjusted_ex_funding', 'instant_deficit_to_010',
    'anchor_rh_source_ns', 'anchor_rh_received_ns', 'anchor_rh_generation',
    'anchor_hl_source_ns', 'anchor_hl_received_ns', 'anchor_hl_generation',
    'rh_source_ns', 'rh_received_ns', 'rh_generation',
    'hl_source_ns', 'hl_received_ns', 'hl_generation')
OUTCOME_FIELDS = ('candidate_id', 'horizon', 'status', 'exit_ns', 'exit_long_sell',
    'exit_short_buy', 'gross', 'entry_long_fee', 'entry_short_fee', 'exit_long_fee',
    'exit_short_fee', 'fee_only_net', 'stress', 'capital', 'adjusted_quote_net_ex_funding',
    'improvement_from_instant', 'funding_unknown', 'utc_hour_boundary_crossed',
    'funding_boundary_tie', 'rh_source_ns', 'rh_received_ns', 'rh_generation',
    'hl_source_ns', 'hl_received_ns', 'hl_generation')


def rational(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(str(value))


def number(value):
    value = rational(value)
    denominator = value.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    if denominator != 1:
        return f'{value.numerator}/{value.denominator}'
    with localcontext() as context:
        context.prec = max(50, len(str(abs(value.numerator))) + len(str(value.denominator)) + 5)
        text = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def common_step(left, right):
    left, right = rational(left), rational(right)
    denominator = math.lcm(left.denominator, right.denominator)
    return Fraction(math.lcm(int(left * denominator), int(right * denominator)), denominator)


class LevelValidationCache:
    """Pure successful level validation only; never book/timer/fill state."""
    BASE_BYTES = 4096

    def __init__(self, *, enabled=True, max_entries=LEVEL_CACHE_ENTRIES, max_bytes=LEVEL_CACHE_BYTES):
        if not 0 < max_entries <= LEVEL_CACHE_ENTRIES or not self.BASE_BYTES <= max_bytes <= LEVEL_CACHE_BYTES:
            raise ValueError('level_cache_bound')
        self.enabled=enabled
        self.max_entries=max_entries
        self.max_bytes=max_bytes
        self.entries=OrderedDict()
        self.bytes_used=self.BASE_BYTES
        self.counts=Counter()

    @staticmethod
    def _entry_bytes(key,value):
        # Count all immutable nested objects even when shared, plus 256 bytes
        # for dictionary/LRU nodes and stored accounting. This overcounts
        # shared metadata strings/rules rather than omitting their cost.
        rule,price,size=key
        return (256+sys.getsizeof(key)+sys.getsizeof(rule)+sum(sys.getsizeof(v) for v in rule)
            +sys.getsizeof(price)+sys.getsizeof(size)+sys.getsizeof(value)
            +sum(sys.getsizeof(v) for v in value)+sys.getsizeof(0))

    def check(self,price_text,size_text,rule,tick,step):
        key=(rule,price_text,size_text)
        if self.enabled and key in self.entries:
            self.counts['hits']+=1
            self.entries.move_to_end(key)
            return self.entries[key][0]
        self.counts['misses']+=1
        price,size=Decimal(price_text),Decimal(size_text)
        if (not price.is_finite() or not size.is_finite() or price<=0 or size<=0 or
            price%tick or size%step or
            (rule[0]=='hl_perp' and price!=price.to_integral_value()
             and len(price.normalize().as_tuple().digits)>5)):
            raise ValueError('quote_off_grid')
        value=(price,size)
        if self.enabled:
            cost=self._entry_bytes(key,value)
            if self.BASE_BYTES+cost>self.max_bytes:
                self.counts['oversized_skips']+=1
                return value
            while self.entries and (len(self.entries)>=self.max_entries or self.bytes_used+cost>self.max_bytes):
                _,(_,old_cost)=self.entries.popitem(last=False)
                self.bytes_used-=old_cost
                self.counts['evictions']+=1
            self.entries[key]=(value,cost)
            self.bytes_used+=cost
        return value

    def summary(self):
        return {'enabled':self.enabled,'entry_limit':self.max_entries,'byte_limit':self.max_bytes,
            'entries':len(self.entries),'conservatively_accounted_bytes':self.bytes_used,
            'counts':dict(self.counts),'semantics':'pure successful Decimal level validation only'}


def validate_raw_levels(book, side, meta, cache):
    """Eager exact decimal grid/shape checks; Fraction materialization is lazy."""
    values = book[side]
    if not isinstance(values, (list, tuple)) or not 0 < len(values) <= 5000:
        raise ValueError('empty_or_unbounded_depth')
    with localcontext() as context:
        context.prec = 128
        step = Decimal(str(meta['size_step']))
        tick = (Decimal(10) ** -(6-int(meta['sz_decimals'])) if
                meta['price_tick_semantics']=='hl_perp' else Decimal(str(meta['price_tick'])))
        rule=(meta['price_tick_semantics'],str(tick),str(step),str(meta.get('sz_decimals')),str(context.prec))
        previous = None
        for pair in values:
            if not isinstance(pair,(list,tuple)) or len(pair)!=2:
                raise ValueError('malformed_level')
            price,size=cache.check(str(pair[0]),str(pair[1]),rule,tick,step)
            if previous is not None and (previous<=price if side=='bids' else previous>=price):
                raise ValueError('unsorted_or_duplicate_depth')
            previous=price
    return values


def quantity_valid(quantity, meta):
    return (quantity > 0 and (quantity / rational(meta['size_step'])).denominator == 1
        and quantity >= rational(meta.get('min_qty') or meta['size_step'])
        and (meta.get('max_qty') is None or quantity <= rational(meta['max_qty'])))


def notional_status(value, meta):
    if value < rational(meta['min_notional']):
        return 'minimum'
    if meta.get('max_quote') is not None and value > rational(meta['max_quote']):
        return 'order_rule'
    return None


def economics(long_entry, short_entry, long_exit, short_exit, long_rate, short_rate, elapsed_ns):
    le, se, lx, sx = map(rational, (long_entry, short_entry, long_exit, short_exit))
    lr, sr = rational(long_rate) / 10000, rational(short_rate) / 10000
    gross = se - le + lx - sx
    fees = (le * lr, se * sr, lx * lr, sx * sr)
    stress = max(le, se) * Fraction(5, 10000)
    capital = (le + se) * Fraction(5, 100) * elapsed_ns / (365 * 86400 * NS)
    net = gross - sum(fees)
    return dict(zip(('gross', 'entry_long_fee', 'entry_short_fee', 'exit_long_fee',
        'exit_short_fee', 'fee_only_net', 'stress', 'capital', 'adjusted_quote_net_ex_funding'),
        map(number, (gross, *fees, net, stress, capital, net - stress - capital))))


def grid(start=START):
    ident = 0
    for offset in range(0, 3000, 5):
        for asset in ASSETS:
            for budget in BUDGETS:
                if budget != 1000 and offset % 30:
                    continue
                for long_venue in ('rh_lighter', 'hyperliquid'):
                    yield dict(id=ident, anchor_ns=start + offset * NS,
                        stratum=offset // 600, asset=asset, long_venue=long_venue, budget=budget)
                    ident += 1


class QuoteEngine:
    """Receipt-batched timeline with active-window evaluation and fixed q."""
    def __init__(self, markets, *, candidates=None, end_ns=START+DURATION, planned_close_venues=(), level_validation_cache=None):
        self.markets = markets
        self.end_ns = end_ns
        self.planned_close_venues = frozenset(planned_close_venues)
        self.rows = [dict(row) for row in (grid() if candidates is None else candidates)]
        self.by_id = {row['id']: row for row in self.rows}
        if len(self.by_id) != len(self.rows):
            raise ValueError('duplicate_candidate_id')
        self.outcomes = {(row['id'], horizon): dict(candidate_id=row['id'], horizon=horizon,
            funding_unknown=True) for row in self.rows for horizon in HORIZONS}
        self.books = {}
        self.serial = 0
        self.walk_cache = OrderedDict()
        self.level_validation_cache=(LevelValidationCache() if level_validation_cache is None else level_validation_cache)
        self.pending = set()
        self.active_entry = defaultdict(set)
        self.active_exit = defaultdict(set)
        self.last_generation = {}
        self.venue_generation = {}
        self.last_source = {}
        self.timers = []
        self.timer_serial = itertools.count()
        self.finished = False
        self.terminal = None
        self.now = None
        self.counts = Counter()
        for row in self.rows:
            self._schedule(row['anchor_ns'], 'anchor', row['id'])

    def _schedule(self, when, kind, identity):
        heapq.heappush(self.timers, (when, next(self.timer_serial), kind, identity))

    def _reference(self, asset):
        result = {}
        for venue, prefix in (('rh_lighter', 'rh'), ('hyperliquid', 'hl')):
            book = self.books[venue, asset]
            result.update({f'{prefix}_source_ns': book['source_ns'],
                f'{prefix}_received_ns': book['received_ns'], f'{prefix}_generation': book['generation']})
        return result

    def _pair(self, row, now, baseline=None, due=None):
        pair = [self.books.get((venue, row['asset'])) for venue in ('rh_lighter', 'hyperliquid')]
        if any(book is None for book in pair):
            return 'missing_book'
        for book in pair:
            if not all(0 <= now - book[key] <= AGE for key in ('source_ns', 'received_ns')):
                return 'stale_source_or_receipt'
        if any(abs(pair[0][key] - pair[1][key]) > SKEW for key in ('source_ns', 'received_ns')):
            return 'cross_venue_skew'
        if baseline is not None:
            for book, prefix in zip(pair, ('rh', 'hl')):
                if book['generation'] != baseline[f'{prefix}_generation']:
                    return 'generation_change'
                if any(book[key] <= baseline[f'{prefix}_{key}'] for key in ('source_ns', 'received_ns')):
                    return 'not_advanced'
                if any(book[key] < due for key in ('source_ns', 'received_ns')):
                    return 'before_due'
        return None

    def _walk(self, venue, asset, side, quantity):
        book = self.books[venue, asset]
        key = (book['_serial'], side, quantity)
        if key not in self.walk_cache:
            remaining, value = quantity, Fraction(0)
            for price, size in self._levels(book, side):
                used = min(remaining, size)
                value += used * price
                remaining -= used
                if remaining == 0:
                    break
            self.walk_cache[key] = value if remaining == 0 else None
            if len(self.walk_cache) > 4096:
                self.walk_cache.popitem(last=False)
        result = self.walk_cache[key]
        if result is None:
            raise ValueError('depth')
        reason = notional_status(result, self.markets[venue][asset])
        if reason:
            raise ValueError(reason)
        return result

    @staticmethod
    def _levels(book, side):
        if side not in book['_levels']:
            book['_levels'][side] = tuple((rational(price),rational(size)) for price,size in book[side])
        return book['_levels'][side]

    def _legs(self, row, entry):
        long = row['long_venue']
        short = 'hyperliquid' if long == 'rh_lighter' else 'rh_lighter'
        quantity = rational(row['quantity'])
        return (self._walk(long, row['asset'], 'asks' if entry else 'bids', quantity),
                self._walk(short, row['asset'], 'bids' if entry else 'asks', quantity))

    def _rates(self, row):
        long = row['long_venue']
        short = 'hyperliquid' if long == 'rh_lighter' else 'rh_lighter'
        return self.markets[long][row['asset']]['taker_fee_bps'], self.markets[short][row['asset']]['taker_fee_bps']

    def _fail_candidate(self, row, reason):
        row['status'] = reason
        for horizon in HORIZONS:
            self._finish(row, horizon, reason)
        self.active_entry[row['asset']].discard(row['id'])

    def _finish(self, row, horizon, status, **details):
        outcome = self.outcomes[row['id'], horizon]
        if 'status' in outcome:
            return
        outcome.update(status=status, **details)
        self.active_exit[row['asset']].discard((row['id'], horizon))
        if all('status' in self.outcomes[row['id'], h] for h in HORIZONS):
            self.pending.discard(row['id'])

    def _anchor(self, row, now):
        reason = self._pair(row, now)
        if reason:
            self._fail_candidate(row, 'anchor_' + reason)
            return
        step = common_step(self.markets['rh_lighter'][row['asset']]['size_step'],
                           self.markets['hyperliquid'][row['asset']]['size_step'])
        ask = self._levels(self.books[row['long_venue'], row['asset']], 'asks')[0][0]
        quantity = (rational(row['budget']) / ask / step).__floor__() * step
        row['quantity'] = number(quantity)
        if not all(quantity_valid(quantity, self.markets[venue][row['asset']]) for venue in ('rh_lighter', 'hyperliquid')):
            self._fail_candidate(row, 'anchor_quantity')
            return
        try:
            long_value, _ = self._legs(row, True)
        except ValueError as exc:
            self._fail_candidate(row, 'anchor_' + str(exc))
            return
        reference=self._reference(row['asset'])
        row.update(status='entry_pending', anchor_long_buy_notional=number(long_value),
            anchor_notional_exceeds_budget=long_value > row['budget'], _anchor=reference,
            **{'anchor_'+key:value for key,value in reference.items()})
        self.pending.add(row['id'])
        if len(self.pending) > 800:
            raise ValueError('pending_candidate_cap')
        self._schedule(now + DELAY, 'entry_due', row['id'])
        self._schedule(now + 2 * NS, 'entry_deadline', row['id'])

    def _entry(self, row, now):
        if self._pair(row, now, row['_anchor'], row['anchor_ns']+DELAY):
            return
        try:
            le, se = self._legs(row, True)
        except ValueError as exc:
            self._fail_candidate(row, 'entry_' + str(exc))
            return
        lr, sr = self._rates(row)
        row.update(status='entry_quote_complete', entry_ns=now, entry_long_buy=number(le),
            entry_short_sell=number(se), entry_long_fee=number(le*rational(lr)/10000),
            entry_short_fee=number(se*rational(sr)/10000),
            entry_notional_exceeds_anchor_budget=le > row['budget'],
            entry_drift_from_anchor_walk=number(le-rational(row['anchor_long_buy_notional'])),
            **self._reference(row['asset']))
        self.active_entry[row['asset']].discard(row['id'])
        try:
            lx, sx = self._legs(row, False)
            row['instant_adjusted_ex_funding'] = economics(le,se,lx,sx,lr,sr,0)['adjusted_quote_net_ex_funding']
            row['instant_deficit_to_010'] = number(Fraction(1,10)-rational(row['instant_adjusted_ex_funding']))
        except ValueError:
            row['instant_adjusted_ex_funding'] = None
            row['instant_deficit_to_010'] = None
        for horizon in HORIZONS:
            self._schedule(now+horizon*NS+DELAY, 'exit_due', (row['id'], horizon))
            self._schedule(now+horizon*NS+2*NS, 'exit_deadline', (row['id'], horizon))

    def _exit(self, row, horizon, now):
        if self._pair(row, now, row, row['entry_ns']+horizon*NS+DELAY):
            return
        try:
            lx, sx = self._legs(row, False)
        except ValueError as exc:
            self._finish(row, horizon, 'exit_' + str(exc))
            return
        values = economics(row['entry_long_buy'], row['entry_short_sell'], lx, sx,
                           *self._rates(row), now-row['entry_ns'])
        hour = 3600 * NS
        baseline = row.get('instant_adjusted_ex_funding')
        self._finish(row, horizon, 'quote_complete', exit_ns=now, exit_long_sell=number(lx),
            exit_short_buy=number(sx), **values, **self._reference(row['asset']),
            utc_hour_boundary_crossed=row['entry_ns']//hour != now//hour,
            funding_boundary_tie=row['entry_ns']%hour == 0 or now%hour == 0,
            improvement_from_instant=None if baseline is None else number(
                rational(values['adjusted_quote_net_ex_funding'])-rational(baseline)))

    def _evaluate(self, assets, now):
        for asset in assets:
            for identity in sorted(self.active_entry[asset]):
                self._entry(self.by_id[identity], now)
            for identity, horizon in sorted(self.active_exit[asset]):
                self._exit(self.by_id[identity], horizon, now)

    def _invalidate(self, asset, reason):
        for identity in tuple(self.pending):
            row = self.by_id[identity]
            if row['asset'] == asset:
                if row['status'] == 'entry_pending':
                    self._fail_candidate(row, 'entry_gap:' + reason)
                else:
                    for horizon in HORIZONS:
                        self._finish(row, horizon, 'exit_gap:' + reason)

    def _generation(self, venue, generation):
        changed=set()
        if venue in self.venue_generation and generation!=self.venue_generation[venue]:
            for asset in ASSETS:
                self.books.pop((venue,asset),None)
                self._invalidate(asset,'generation_change')
                changed.add(asset)
        self.venue_generation[venue]=generation
        return changed

    def _events(self, events):
        changed = set()
        for event in events:
            kind = event.get('type', event.get('kind'))
            venue, asset = event.get('venue'), event.get('asset')
            if venue not in MARKET_IDS:
                continue
            affected = (asset,) if asset in ASSETS else ASSETS
            if kind == 'invalidate':
                if event.get('scope') == 'trade':
                    continue
                for affected_asset in affected:
                    self.books.pop((venue, affected_asset), None)
                    self._invalidate(affected_asset, event.get('reason','invalidate'))
                    changed.add(affected_asset)
            elif kind == 'control' and event.get('control',event.get('event')) in ('connection_close','connection_error','connections_ended','invalid_json','generation_invalidated'):
                for affected_asset in affected:
                    self.books.pop((venue,affected_asset),None)
                    self._invalidate(affected_asset,event.get('control',event.get('event')))
                    changed.add(affected_asset)
            elif kind == 'control' and event.get('control')=='connection_open' and event.get('generation'):
                changed.update(self._generation(venue,event['generation']))
            elif kind == 'book' and asset in ASSETS:
                key = venue, asset
                try:
                    if event.get('valid') is False or event.get('clock_valid') is False:
                        raise ValueError('invalid_book')
                    source, receipt = event['source_ns'], event['received_ns']
                    generation = event['generation']
                    if (type(source) is not int or type(receipt) is not int or
                            not 0 < source <= receipt or not generation or event.get('sequence') is None):
                        raise ValueError('invalid_clock_or_generation_or_sequence')
                    if str(event.get('market')) != MARKET_IDS[venue][asset]:
                        raise ValueError('wrong_market')
                    changed.update(self._generation(venue,generation))
                    if key in self.last_generation and generation != self.last_generation[key]:
                        self._invalidate(asset, 'generation_change')
                    elif key in self.last_source and source < self.last_source[key]:
                        raise ValueError('source_regression')
                    raw = {side: validate_raw_levels(event, side, self.markets[venue][asset],self.level_validation_cache) for side in ('bids','asks')}
                    if Decimal(str(raw['bids'][0][0])) >= Decimal(str(raw['asks'][0][0])):
                        raise ValueError('crossed_book')
                    self.serial += 1
                    self.books[key] = {**event, '_levels':{}, '_serial':self.serial}
                    self.last_generation[key], self.last_source[key] = generation, source
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    self.books.pop(key,None)
                    self._invalidate(asset,str(exc))
                changed.add(asset)
        return changed

    def _at(self, now, events=()):
        changed = self._events(events)
        deadlines = []
        while self.timers and self.timers[0][0] == now:
            _, _, kind, identity = heapq.heappop(self.timers)
            if kind == 'anchor':
                self._anchor(self.by_id[identity], now)
            elif kind == 'entry_due':
                row = self.by_id[identity]
                if row.get('status') == 'entry_pending':
                    self.active_entry[row['asset']].add(identity)
                    changed.add(row['asset'])
            elif kind == 'exit_due':
                ident, horizon = identity
                if 'status' not in self.outcomes[identity]:
                    row = self.by_id[ident]
                    self.active_exit[row['asset']].add(identity)
                    changed.add(row['asset'])
            else:
                deadlines.append((kind,identity))
        self._evaluate(changed,now)
        for kind, identity in deadlines:
            if kind == 'entry_deadline':
                row = self.by_id[identity]
                if row.get('status') == 'entry_pending':
                    self._fail_candidate(row,'entry_missing')
            else:
                ident,horizon = identity
                self._finish(self.by_id[ident],horizon,'exit_missing')
        self.now = now

    def batch(self, now, events):
        if self.now is not None and now < self.now:
            raise ValueError('backward_receipt_batch')
        if self.finished:
            return
        while self.timers and self.timers[0][0] < min(now,self.end_ns):
            self._at(self.timers[0][0])
        if now > self.end_ns:
            self.finish()
            return
        # Suppress only manifest-declared planned closes, never genuine cutoff gaps.
        if now == self.end_ns:
            def planned_close(event):
                if event.get('venue') not in self.planned_close_venues:
                    return False
                return ((event.get('type')=='control' and event.get('control')=='connection_close') or
                    (event.get('type')=='invalidate' and event.get('scope')=='book' and
                     event.get('reason') in ('disconnect','connection_close')))
            events = [event for event in events if not planned_close(event)]
        self._at(now,events)
        if now == self.end_ns:
            self.finish()

    def finish(self):
        if self.finished:
            return
        while self.timers and self.timers[0][0] <= self.end_ns:
            self._at(self.timers[0][0])
        for row in self.rows:
            if row.get('status') == 'entry_pending':
                self._fail_candidate(row,'entry_eof')
            else:
                for horizon in HORIZONS:
                    self._finish(row,horizon,'exit_eof')
        if any('status' not in row for row in self.rows):
            raise ValueError('unvisited_anchor')
        self.finished = True

    def traverse(self, events, *, wall_start=None):
        receipt = None
        batch = []
        for event in events:
            if wall_start is not None and time.monotonic()-wall_start > WALL_SECONDS:
                raise TimeoutError('1200_second_wall_cap')
            self.counts['canonical_events'] += 1
            if event.get('type') == 'end':
                if batch:
                    self.batch(receipt,batch)
                    batch=[]
                if self.terminal is not None:
                    raise ValueError('duplicate_terminal')
                self.terminal=event
                self.finish()
                continue
            if self.terminal is not None:
                raise ValueError('events_after_terminal')
            now=event.get('received_ns',event.get('receipt_ns'))
            if type(now) is not int:
                raise ValueError('missing_receipt')
            if receipt is not None and now < receipt:
                raise ValueError('backward_event_receipt')
            if receipt is not None and now != receipt:
                self.batch(receipt,batch)
                batch=[]
            receipt=now
            batch.append(event)
            if len(batch)>10000:
                raise ValueError('receipt_batch_cap')
        if self.terminal is None:
            raise ValueError('missing_terminal')


def summarize(engine):
    def group_stats(rows):
        complete=[row for row in rows if row['status']=='quote_complete']
        values=[rational(row['adjusted_quote_net_ex_funding']) for row in complete]
        return {'original':len(rows),'statuses':dict(Counter(row['status'] for row in rows)),
            'quote_complete':len(complete),'fee_positive':sum(rational(r['fee_only_net'])>0 for r in complete),
            'adjusted_positive_ex_funding':sum(v>0 for v in values),
            'adjusted_at_least_010_ex_funding':sum(v>=Fraction(1,10) for v in values),
            'hour_crossings':sum(bool(r.get('utc_hour_boundary_crossed')) for r in complete),
            'adjusted_min_median_max_ex_funding':None if not values else list(map(number,(min(values),statistics.median(values),max(values))))}
    groups=defaultdict(list); strata=defaultdict(list)
    paired=defaultdict(list)
    for (identity,horizon),outcome in engine.outcomes.items():
        row=engine.by_id[identity]; key=(row['asset'],row['long_venue'],row['budget'],horizon)
        groups[key].append(outcome);strata[(*key,row['stratum'])].append(outcome)
    for row in engine.rows:
        control=engine.outcomes[row['id'],10]
        for horizon in HORIZONS[1:]:
            other=engine.outcomes[row['id'],horizon]
            key=(row['asset'],row['long_venue'],row['budget'],horizon)
            paired[key].append((control,other))
    paired_rows=[]
    for key,rows in sorted(paired.items()):
        common=[(a,b) for a,b in rows if a['status']==b['status']=='quote_complete']
        deltas=[rational(b['adjusted_quote_net_ex_funding'])-rational(a['adjusted_quote_net_ex_funding']) for a,b in common]
        paired_rows.append({'key':key,'original':len(rows),'both_quote_complete':len(common),
            'control_only_complete':sum(a['status']=='quote_complete' and b['status']!='quote_complete' for a,b in rows),
            'diagnostic_only_complete':sum(a['status']!='quote_complete' and b['status']=='quote_complete' for a,b in rows),
            'median_quote_difference_ex_funding':number(statistics.median(deltas)) if deltas else None})
    return {'schema':SCHEMA,'status':'complete_quote_diagnostic','classification':'exploratory_post_capture_quote_feasibility',
        'resource_revision':RESOURCE_REVISION,'level_validation_cache':engine.level_validation_cache.summary(),
        'actual_fills_observed':False,'private_ack_observed':False,'executable_profit_claim':False,
        'funding_inclusive_net':None,'summed_portfolio_net':None,'funding_observed':False,
        'candidates':len(engine.rows),'horizon_rows':len(engine.outcomes),
        'candidate_statuses':dict(Counter(row['status'] for row in engine.rows)),
        'group_key':['asset','long_venue','anchor_budget','horizon'],
        'groups':[{'key':key,**group_stats(rows)} for key,rows in sorted(groups.items())],
        'stratum_groups':[{'key':key,**group_stats(rows)} for key,rows in sorted(strata.items())],
        'shared_entry_control_contrasts':paired_rows,'terminal_event':engine.terminal,
        'limitations':['Paired endpoint quotes omit private fills, limit-price rejection, partials and hedge rescue.',
            'Explicit intervening book gaps censor; endpoint freshness does not establish continuous execution coverage.',
            'All funding-inclusive P&L unknown; boundary flags are not verified funding calendars.',
            'Sizes/directions/anchors/horizons share books, no independent trial or causal profit claim.']}


def sha(path, limit=50_000_000):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        raise ValueError('input_path_or_size')
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1<<20),b''):
            digest.update(block)
    return digest.hexdigest()


def epoch_ns(value):
    delta=dt.datetime.fromisoformat(value)-dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
    return (delta.days*86400+delta.seconds)*NS+delta.microseconds*1000


def verify_inputs():
    manifest=json.loads((INPUT/'manifest.json').read_text())
    protocol=json.loads(PROTOCOL.read_text());original=json.loads(ORIGINAL_PROTOCOL.read_text())
    if (sha(INPUT/'manifest.json')!=EXPECTED_MANIFEST or
        sha(INPUT/'metadata/normalized.json')!=EXPECTED_METADATA or
        manifest.get('frames_sha256')!=EXPECTED_RAW or manifest.get('payload_records')!=124019 or
        manifest.get('end_reason')!='duration_limit' or manifest.get('truncated') is not False or
        manifest.get('errors') or manifest.get('configured_seconds')!=3000 or
        epoch_ns(manifest['started_utc'])!=START or epoch_ns(manifest['ended_utc'])<START+DURATION or
        manifest.get('selected_markets')!=MARKET_IDS):
        raise ValueError('stopped_capture_identity_or_completion')
    if (protocol['metadata_normalized_sha256']!=EXPECTED_METADATA or
        original['metadata_normalized_sha256']!=ORIGINAL_METADATA or
        protocol['source_sha256']!=original['source_sha256'] or len(protocol['source_sha256'])!=18):
        raise ValueError('original_restart_protocol_identity')
    dependencies=[ROOT/name for name in protocol['source_sha256']]
    for path in dependencies:
        if sha(path,2_000_000)!=protocol['source_sha256'][str(path.relative_to(ROOT))]:
            raise ValueError('immutable_dependency_changed')
    files=[p for p in INPUT.rglob('*') if p.is_file() or p.is_symlink()]
    if len(files)!=10 or sum(p.stat().st_size for p in files)>50_000_000:
        raise ValueError('capture_inventory_or_byte_cap')
    meta=json.loads((INPUT/'metadata/normalized.json').read_text())
    for name,request in meta['raw_requests'].items():
        if (request['status']!=200 or request['response_completed_utc_ns']>START or
            START-request['response_completed_utc_ns']>300*NS or
            sha(INPUT/'metadata'/request['raw_file'])!=request['sha256'] or
            json.loads((INPUT/'metadata'/(name+'.request.json')).read_text())!=request):
            raise ValueError('metadata_response_identity_or_freshness')
    markets=meta['markets']
    for venue in MARKET_IDS:
        for asset in ASSETS:
            m=markets[venue][asset]
            if str(m['market'])!=MARKET_IDS[venue][asset] or common_step(m['size_step'],m['size_step'])<=0:
                raise ValueError('metadata_market_or_grid')
            expected=Fraction(0) if venue=='rh_lighter' else Fraction('4.5' if asset in ('BTC','ETH') else '.9')
            if rational(m['taker_fee_bps'])!=expected:
                raise ValueError('public_standard_fee')
            if venue=='rh_lighter' and (rational(m['contract_multiplier'])!=1 or rational(m['quote_multiplier'])!=1):
                raise ValueError('rh_units')
            if venue=='hyperliquid' and asset in ('NVDA','XAG') and (m['growth_mode']!='enabled' or rational(m['deployer_fee_scale'])!=1):
                raise ValueError('hl_growth')
    inventory=files+dependencies+[PROTOCOL,ORIGINAL_PROTOCOL,Path(__file__),METHOD,TESTS]
    hashes={str(path):sha(path) for path in inventory}
    if hashes[str(INPUT/'frames.jsonl.gz')]!=EXPECTED_RAW:
        raise ValueError('raw_digest')
    return manifest,markets,hashes


def verify_terminal(terminal, manifest, hashes):
    if (not terminal or terminal.get('raw_sha_verified') is not True or terminal.get('truncated') is not False or
        terminal.get('reason')!='duration_limit' or terminal.get('raw_gzip_sha256')!=EXPECTED_RAW or
        terminal.get('manifest_sha256')!=hashes[str(INPUT/'manifest.json')] or
        terminal.get('adapter_sha256')!=hashes[str(ROOT/'scripts/rh_maker_events.py')] or
        terminal.get('book_decoder_sha256')!=hashes[str(ROOT/'scripts/maker_book_archive.py')] or
        terminal.get('counts',{}).get('decoded_records')!=124019 or
        terminal.get('started_ns')!=START or terminal.get('stopped_ns')!=epoch_ns(manifest['ended_utc'])):
        raise ValueError('verified_terminal_required')


class OutputCapError(ValueError):
    def __init__(self,details):
        self.details=details
        super().__init__('output_cap_before_write:'+json.dumps(details,sort_keys=True))


class BoundedOutput:
    LIMITS={'candidates':450_000,'outcomes':3_250_000,'summary':300_000,'freeze':300_000,'manifest':50_000}
    def __init__(self, directory, *, cap=CAP-LOG_RESERVE):
        self.directory=Path(directory);self.cap=cap;self.used=0;self.categories=Counter()

    def _check(self,category,requested_bytes,buffered_bytes=0):
        category_projected=self.categories[category]+buffered_bytes+requested_bytes
        aggregate_projected=self.used+buffered_bytes+requested_bytes
        violations=[]
        if category_projected>self.LIMITS[category]:violations.append('category')
        if aggregate_projected>self.cap:violations.append('aggregate')
        if violations:
            raise OutputCapError({'category':category,'requested_bytes':requested_bytes,
                'buffered_bytes':buffered_bytes,'used_category_bytes':self.categories[category],
                'used_total_bytes':self.used,'projected_category_bytes':category_projected,
                'projected_total_bytes':aggregate_projected,'category_limit_bytes':self.LIMITS[category],
                'total_limit_bytes':self.cap,'violated_bounds':violations})

    def write(self,name,body,category):
        raw=body.encode() if isinstance(body,str) else body
        self._check(category,len(raw))
        path=self.directory/name
        if path.exists() or path.is_symlink():
            raise ValueError('staged_file_already_exists')
        with path.open('xb') as handle:
            handle.write(raw)
        self.used+=len(raw);self.categories[category]+=len(raw)

    def csv_gzip(self,name,fields,rows,category):
        compressor=zlib.compressobj(6,zlib.DEFLATED,31)
        pieces=[];size=0
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fields,extrasaction='ignore')
        for index,row in enumerate(itertools.chain((None,),rows)):
            if row is None:writer.writeheader()
            else:writer.writerow(row)
            chunk=compressor.compress(buffer.getvalue().encode());buffer.seek(0);buffer.truncate(0)
            self._check(category,len(chunk),size)
            pieces.append(chunk);size+=len(chunk)
        final=compressor.flush()
        self._check(category,len(final),size)
        pieces.append(final)
        self.write(name,b''.join(pieces),category)


def plan():
    return {'schema':SCHEMA,'mode':'dry_plan','candidate_count':7200,'horizon_count':28800,
        'resource_revision':RESOURCE_REVISION,'prior_attempts':[
            'reports/delayed-taker-quotes/0252Z-v1.building','reports/delayed-taker-quotes/0252Z-v2.building'],
        'maximum_authorized_total_traversals':3,'outcome_subcap_bytes':3_250_000,
        'level_validation_cache':{'enabled':False,'entries':LEVEL_CACHE_ENTRIES,'conservative_bytes':LEVEL_CACHE_BYTES},
        'horizons':HORIZONS,'input':str(INPUT),'maximum_total_bytes_including_logs':CAP,
        'reserved_external_log_bytes':LOG_RESERVE,'wall_seconds':WALL_SECONDS,'raw_traversals':0,
        'instruction':'Explicit --run only after reviewed source freeze and root authorization.'}


def run(out):
    started=time.monotonic();out=Path(out)
    if (out.exists() or out.is_symlink() or out.resolve().parent!=OUTPUT_PARENT.resolve()
            or out.parent.is_symlink() or out.name.startswith('.') or '/' in out.name):
        raise ValueError('new_output_child_required')
    stage=out.with_name(out.name+'.building')
    if stage.exists() or stage.is_symlink():
        raise ValueError('staging_already_exists')
    manifest,markets,hashes=verify_inputs()
    freeze={'schema':SCHEMA,'classification':'exploratory_post_capture_quote_feasibility',
        'resource_revision':RESOURCE_REVISION,
        'level_validation_cache':plan()['level_validation_cache'],
        'source_snapshot_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'prospective_freeze_claimed':False,
        'inputs_and_actual_dependencies_sha256':hashes,'grid':plan(),'network_calls':0,
        'observation_cutoff_ns':START+DURATION,'source_inventory_count':21}
    stage.mkdir(parents=True,exist_ok=False)
    writer=BoundedOutput(stage)
    for name,path in (('source.py',Path(__file__)),('tests.py',TESTS),('method.md',METHOD),
                      ('metadata.json',INPUT/'metadata/normalized.json')):
        writer.write(name,path.read_bytes(),'freeze')
    writer.write('freeze.json',json.dumps(freeze,sort_keys=True,indent=2)+'\n','freeze')
    if any(sha(path)!=digest for path,digest in hashes.items()):
        raise ValueError('source_changed_before_traversal')
    planned_close_venues={generation['venue'] for generation in manifest['generations']
        if generation.get('closed_utc') and epoch_ns(generation['closed_utc'])==START+DURATION}
    engine=QuoteEngine(markets,planned_close_venues=planned_close_venues,
        level_validation_cache=LevelValidationCache(enabled=False))
    engine.traverse(iter_events(INPUT,expected_raw_sha256=EXPECTED_RAW,max_raw_bytes=50_000_000,
        max_decoded_bytes=128_000_000,max_records=124019),wall_start=started)
    verify_terminal(engine.terminal,manifest,hashes)
    if (len(engine.rows)!=7200 or len(engine.outcomes)!=28800 or
        Counter(row['stratum'] for row in engine.rows)!=Counter({i:1440 for i in range(5)}) or
        any('status' not in row for row in engine.outcomes.values())):
        raise ValueError('original_grid_conservation')
    summary=summarize(engine)
    writer.csv_gzip('candidates.csv.gz',CANDIDATE_FIELDS,engine.rows,'candidates')
    writer.csv_gzip('outcomes.csv.gz',OUTCOME_FIELDS,
        (engine.outcomes[key] for key in sorted(engine.outcomes)),'outcomes')
    writer.write('summary.json.gz',gzip.compress(json.dumps(summary,sort_keys=True,separators=(',',':')).encode(),mtime=0),'summary')
    report=('# Fixed-quantity delayed taker quote diagnostic\n\n'
        'Completed post-capture paired-book quotes only; no private fills, limit-price execution, '
        'partial execution, hedge rescue or funding-inclusive profit. Production policies unchanged.\n\n'
        'All 7,200 candidates and 28,800 outcomes retained. See compressed CSV and summary groups '
        'for initial failures, gaps, deadlines, EOF and jointly observed 10/H quote contrasts.\n\n'
        '| Asset | Long venue | Budget | H | Original | Complete quotes | Positive ex funding | >= $0.10 ex funding |\n'
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n')
    for group in summary['groups']:
        if group['key'][2]==1000:
            report+='| '+' | '.join(map(str,(*group['key'],group['original'],group['quote_complete'],
                group['adjusted_positive_ex_funding'],group['adjusted_at_least_010_ex_funding'])))+' |\n'
    report+='\nAll funding-inclusive totals unknown. Matched quote economics do not resolve censored outcomes; correlated branches are not summed.\n'
    writer.write('readout.md',report,'summary')
    if any(sha(path)!=digest for path,digest in hashes.items()):
        raise ValueError('source_changed_after_traversal')
    if time.monotonic()-started>WALL_SECONDS:
        raise TimeoutError('1200_second_wall_cap')
    outputs={path.name:sha(path) for path in stage.iterdir()}
    publication={'schema':SCHEMA,'status':'complete','input_hashes_unchanged':True,
        'resource_revision':RESOURCE_REVISION,
        'level_validation_cache_enabled':engine.level_validation_cache.enabled,
        'completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'input_hashes':hashes,'output_hashes':outputs,'total_bound_including_logs':CAP,
        'reserved_external_log_bytes':LOG_RESERVE,'raw_traversals':1,'network_calls':0,
        'wall_seconds':time.monotonic()-started,'original_candidates_verified':7200,
        'original_horizon_rows_verified':28800,'verified_terminal':True}
    writer.write('manifest.json',json.dumps(publication,sort_keys=True,indent=2)+'\n','manifest')
    if out.exists() or out.is_symlink():
        raise ValueError('output_created_during_run')
    stage.rename(out)
    return {'out':str(out),'total_bytes':writer.used,'candidates':7200,'horizon_rows':28800}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true');parser.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    if args.run and args.out is None:
        parser.error('--run requires --out NEW')
    print(json.dumps(run(args.out) if args.run else plan(),sort_keys=True))


if __name__=='__main__':
    main()
