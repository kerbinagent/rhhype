"""Bounded, causal entry selectors for exploratory paper portfolios.

The spread model is a recent distribution of executable *closing* spreads,
not an estimate of future convergence or guaranteed profit.  It is kept in
memory only: a process restart starts the forecast policies in warmup again.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import math
from statistics import median


POLICY_VERSION = 3
POLICIES = ('shadow_baseline', 'cooldown', 'convergence', 'conservative', 'confirmed')
WINDOW_SECONDS = 900.0
MAX_SAMPLES = 900
MIN_SAMPLES = 40
MIN_SPAN_SECONDS = 120.0
MIN_SAMPLE_INTERVAL = 1.0
MAX_OBSERVATION_GAP = 30.0
TRAINING_MAX_SKEW = 1.0
STRICT_ENTRY_MAX_SKEW = 0.25
COOLDOWN_SECONDS = 60.0
MAX_ROUTES = 2000
CONFIRM_SECONDS = 1.0
CONFIRM_EXPIRY_SECONDS = 4.0


def _key(m):
    return f"{m['venue']}:{m['market']}"


def _walk(levels, quantity):
    remaining = quantity
    value = 0.0
    for price, available in levels:
        if not (math.isfinite(price) and math.isfinite(available) and price > 0 and available >= 0):
            return None
        take = min(remaining, available)
        value += price * take
        remaining -= take
        if remaining <= max(1e-10, quantity * 1e-10):
            return value
    return None


def _book_ok(book, now, max_age):
    if not book or not book.get('valid') or not book.get('bids') or not book.get('asks'):
        return False
    try:
        receipt = float(book['received'])
        engine = book.get('engine_time')
        if not math.isfinite(receipt) or not -0.1 <= now - receipt <= max_age:
            return False
        if engine is not None and (not math.isfinite(float(engine)) or
                                   not -2 <= now - float(engine) <= max_age):
            return False
        return 0 < book['bids'][0][0] < book['asks'][0][0]
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def _percentile_75(values):
    """Nearest-rank 75th percentile, conservative for small samples."""
    ordered = sorted(values)
    return ordered[math.ceil(.75 * len(ordered)) - 1]


@dataclass
class _RouteWindow:
    samples: deque[tuple[float, float]] = field(default_factory=deque)
    # Last *sampled* pair. Both source observations must advance from it.
    sources: dict[str, tuple[float, float | None, object]] = field(default_factory=dict)


@dataclass
class _Candidate:
    armed_at: float
    quantity: float
    buy: str
    sell: str
    buy_received: float
    sell_received: float
    buy_source: float | None
    sell_source: float | None
    buy_generation: object
    sell_generation: object
    initial_edge_usd: float
    initial_forecast_usd: float
    initial_source_fallbacks: tuple[str, ...]


class StrategySelector:
    """Select Standard-fee shadow entries using only preceding observations.

    ``observe`` accepts both directional Standard signals, including negative
    signals.  Callers may evaluate ``allow`` before or after ``observe`` for a
    tick: the sample stamped at that tick is excluded from its own gate.
    Existing-position checks remain with the paper engine; the optional flag
    makes the selector's decision diagnostic explicit.
    """

    def __init__(self, config):
        self.max_book_age = float(config.max_book_age)
        self.training_skew_limit = min(TRAINING_MAX_SKEW, float(getattr(config, 'max_skew', 1.0)))
        self.convergence_skew_limit = self.training_skew_limit
        self.conservative_skew_limit = min(STRICT_ENTRY_MAX_SKEW, self.training_skew_limit)
        self.cooldown_skew_limit = self.conservative_skew_limit
        self.profit_target = float(getattr(config, "take_profit_usd", .10) or 0.0)
        self.routes: dict[str, _RouteWindow] = {}
        self.last_entries: dict[str, dict[str, float]] = {name: {} for name in POLICIES}
        self.counts: dict[str, Counter] = {name: Counter() for name in POLICIES}
        self.observation_counts = Counter()
        self.candidates: dict[str, _Candidate] = {}
        self.confirmation_cancel_reasons = Counter()
        self.last_maintenance = -math.inf
        self.criteria_changed_at = None
        self.migrated_from_version = None

    @staticmethod
    def _route(pair, long_market, short_market):
        return f"{pair['asset']}|{_key(long_market)}|{_key(short_market)}"

    @staticmethod
    def _trim(window, now):
        while window.samples and window.samples[0][0] < now - WINDOW_SECONDS:
            window.samples.popleft()

    def _valid_pair(self, long_book, short_book, now):
        if not (_book_ok(long_book, now, self.max_book_age) and
                _book_ok(short_book, now, self.max_book_age)):
            return False
        if abs(long_book['received'] - short_book['received']) > self.training_skew_limit:
            return False
        long_source, short_source = long_book.get('engine_time'), short_book.get('engine_time')
        if long_source is not None and short_source is not None and abs(long_source - short_source) > self.training_skew_limit:
            return False
        return True

    def _expire_idle(self, now):
        for route, window in list(self.routes.items()):
            self._trim(window, now)
            if not window.samples or now - window.samples[-1][0] > MAX_OBSERVATION_GAP:
                del self.routes[route]
        if len(self.routes) > MAX_ROUTES:
            excess = len(self.routes) - MAX_ROUTES
            for route in sorted(self.routes, key=lambda r: self.routes[r].samples[-1][0])[:excess]:
                del self.routes[route]
        for entries in self.last_entries.values():
            for route, entered_at in list(entries.items()):
                if now - entered_at >= COOLDOWN_SECONDS:
                    del entries[route]
        self._expire_candidates(now)
        self.last_maintenance = now

    def _expire_candidates(self, now):
        for route, candidate in list(self.candidates.items()):
            if now > candidate.armed_at + CONFIRM_EXPIRY_SECONDS or route not in self.routes:
                del self.candidates[route]

    def observe(self, pair, books_by_key, now, signals=()):
        """Sample each executable direction, regardless of signal sign.

        ``signals`` are the engine's Standard ``_signal`` outputs (or None).
        A missing signal has no valid engine-sized executable quantity and
        therefore cannot form a comparable observation.
        """
        signals = tuple(signals)
        if now - self.last_maintenance >= MIN_SAMPLE_INTERVAL:
            self._expire_idle(now)
        markets = {_key(pair['hl']): pair['hl'], _key(pair['other']): pair['other']}
        # The engine does not call allow for nonpositive or unexecutable routes.
        # Clear their pending confirmation here so a later quote cannot revive it.
        pair_routes = {self._route(pair, pair['hl'], pair['other']),
                       self._route(pair, pair['other'], pair['hl'])}
        observed = {s.get('route'): s for s in signals if isinstance(s, dict)}
        for route in pair_routes & self.candidates.keys():
            s = observed.get(route)
            if s is None or not isinstance(s.get('net_edge_usd'), (int, float)) or \
                    not math.isfinite(s['net_edge_usd']) or s['net_edge_usd'] < .25:
                del self.candidates[route]
        for signal in signals:
            if not signal or signal.get('buy') not in markets or signal.get('sell') not in markets:
                self.observation_counts['missing_signal'] += 1
                continue
            route = self._route(pair, markets[signal['buy']], markets[signal['sell']])
            if signal.get('route') != route:
                self.observation_counts['route_mismatch'] += 1
                continue
            long_book = books_by_key.get(signal['buy'])
            short_book = books_by_key.get(signal['sell'])
            if not self._valid_pair(long_book, short_book, now):
                # Short lived skew or a missing quote must not erase a route's
                # otherwise valid history. A prolonged gap expires it above.
                self.observation_counts['invalid_pair'] += 1
                continue
            quantity = signal.get('quantity')
            entry_value = signal.get('buy_value')
            if not isinstance(quantity, (int, float)) or not isinstance(entry_value, (int, float)) or not (
                    math.isfinite(quantity) and math.isfinite(entry_value) and quantity > 0 and entry_value > 0):
                self.observation_counts['invalid_quantity'] += 1
                continue
            window = self.routes.setdefault(route, _RouteWindow())
            if window.samples and now - window.samples[-1][0] < MIN_SAMPLE_INTERVAL:
                self.observation_counts['rate_limited'] += 1
                continue
            sources = {
                signal['buy']: (float(long_book['received']), long_book.get('engine_time'), long_book.get('generation')),
                signal['sell']: (float(short_book['received']), short_book.get('engine_time'), short_book.get('generation')),
            }
            if window.sources:
                if any(sources[k][2] != window.sources[k][2] for k in sources):
                    # A reconnection changes the source continuity guarantee.
                    window.samples.clear()
                    window.sources.clear()
                    self.observation_counts['generation_reset'] += 1
                elif any(sources[k][0] <= window.sources[k][0] or
                         (sources[k][1] is not None and window.sources[k][1] is not None and
                          sources[k][1] <= window.sources[k][1]) for k in sources):
                    self.observation_counts['source_not_advanced'] += 1
                    continue
            long_sale = _walk(long_book['bids'], quantity)
            short_buyback = _walk(short_book['asks'], quantity)
            if long_sale is None or short_buyback is None:
                if not window.samples:
                    self.routes.pop(route, None)
                self.observation_counts['insufficient_close_depth'] += 1
                continue
            closing_bps = (short_buyback - long_sale) / entry_value * 10000
            if not math.isfinite(closing_bps):
                if not window.samples:
                    self.routes.pop(route, None)
                self.observation_counts['invalid_spread'] += 1
                continue
            window.samples.append((now, closing_bps))
            window.sources = sources
            self._trim(window, now)
            while len(window.samples) > MAX_SAMPLES:
                window.samples.popleft()
            if len(self.routes) > MAX_ROUTES:
                oldest = min(self.routes, key=lambda r: self.routes[r].samples[-1][0]
                             if self.routes[r].samples else -math.inf)
                del self.routes[oldest]
            self.observation_counts['sampled'] += 1

    def _past(self, route, now):
        window = self.routes.get(route)
        if not window:
            return []
        self._trim(window, now)
        if not window.samples or now - window.samples[-1][0] > MAX_OBSERVATION_GAP:
            self.routes.pop(route, None)
            return []
        return [(ts, bps) for ts, bps in window.samples if ts < now]

    def route_history(self, route, now):
        """Return prior (timestamp, closing-spread bps) samples for evidence.

        The returned list is detached from the model, bounded to its rolling
        900-second/900-sample window, and excludes a sample stamped ``now``.
        Stale routes with no synchronized observation in 30 seconds are empty.
        """
        return self._past(route, now)

    def confirmation_quantity(self, route):
        """Quantity to use when recomputing a pending confirmation quote."""
        candidate = self.candidates.get(route)
        return candidate.quantity if candidate else None

    def cancel_confirmation(self, route, reason='invalid_quote'):
        """Discard a pending route when fixed-quantity requoting is invalid."""
        if self.candidates.pop(route, None) is None:
            return False
        known = {'invalid_quote', 'budget', 'budget_or_depth', 'generation', 'economic', 'missing',
                 'pair_removed', 'gap', 'unexecutable'}
        self.confirmation_cancel_reasons[reason if reason in known else 'other'] += 1
        return True

    def pending_confirmation_targets(self, now):
        """Bounded refresh targets; callers schedule them below execution work."""
        self._expire_candidates(now)
        return [{'route': route, 'buy': c.buy, 'sell': c.sell,
                 'due': c.armed_at + CONFIRM_SECONDS,
                 'expires': c.armed_at + CONFIRM_EXPIRY_SECONDS}
                for route, c in self.candidates.items()]

    @staticmethod
    def _confirmation_stamps(signal):
        """Validate receipt metadata; use receipt as an explicit source fallback."""
        stamps = {}
        fallbacks = []
        for side in ('buy', 'sell'):
            receipt = signal.get(f'{side}_received')
            source = signal.get(f'{side}_source_time')
            if not isinstance(receipt, (int, float)) or not math.isfinite(receipt):
                return None, ()
            if source is None:
                source = receipt
                fallbacks.append(side)
            elif not isinstance(source, (int, float)) or not math.isfinite(source):
                return None, ()
            stamps[side] = (float(receipt), float(source), signal.get(f'{side}_generation'))
        return stamps, tuple(fallbacks)

    def allow(self, policy, signal, now, *, existing_position=False):
        """Return (allowed, diagnostics). A current-tick sample never votes."""
        if policy not in POLICIES:
            raise ValueError(f'unknown entry policy: {policy}')
        counts = self.counts[policy]
        counts['checked'] += 1
        route = signal.get('route') if isinstance(signal, dict) else None
        edge = signal.get('net_edge_usd') if isinstance(signal, dict) else None
        entry_skew_limit = (self.convergence_skew_limit if policy == 'convergence' else
                            self.convergence_skew_limit if policy == 'confirmed' else
                            self.conservative_skew_limit if policy == 'conservative' else
                            self.cooldown_skew_limit if policy == 'cooldown' else
                            self.training_skew_limit)
        diagnostic = {'policy': policy, 'route': route, 'version': POLICY_VERSION,
                      'entry_skew_limit_seconds': entry_skew_limit,
                      'training_skew_limit_seconds': self.training_skew_limit,
                      'confirmation_min_seconds': CONFIRM_SECONDS if policy == 'confirmed' else None,
                      'confirmation_expiry_seconds': CONFIRM_EXPIRY_SECONDS if policy == 'confirmed' else None,
                      'forecast_is_historical_spread': policy in ('convergence', 'conservative', 'confirmed')}

        def reject(reason):
            if policy == 'confirmed' and reason != 'confirmation' and route:
                self.candidates.pop(route, None)
            counts[f'rejected_{reason}'] += 1
            return False, diagnostic | {'reason': reason}

        if existing_position:
            return reject('duplicate')
        if not route or not isinstance(edge, (int, float)) or not math.isfinite(edge):
            return reject('signal')
        if policy != 'shadow_baseline':
            skew_ms = signal.get('skew_ms', 0)
            source_skew_ms = signal.get('source_skew_ms', 0)
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) or
                   value > entry_skew_limit * 1000 or value < 0
                   for value in (skew_ms, source_skew_ms)):
                return reject('skew')
        threshold = .25 if policy != 'shadow_baseline' else 0.0
        if (edge <= threshold if policy == 'shadow_baseline' else edge < threshold):
            return reject('signal')
        if policy != 'shadow_baseline' and now - self.last_entries[policy].get(route, -math.inf) < COOLDOWN_SECONDS:
            return reject('cooldown')
        if policy in ('convergence', 'conservative', 'confirmed'):
            samples = self._past(route, now)
            diagnostic['historical_samples'] = len(samples)
            diagnostic['historical_span_seconds'] = samples[-1][0] - samples[0][0] if samples else 0.0
            if len(samples) < MIN_SAMPLES or samples[-1][0] - samples[0][0] < MIN_SPAN_SECONDS:
                return reject('warmup')
            bps = median([x[1] for x in samples]) if policy in ('convergence', 'confirmed') else _percentile_75([x[1] for x in samples])
            opening_base = signal.get('buy_value')
            if not isinstance(opening_base, (int, float)) or not math.isfinite(opening_base) or opening_base <= 0:
                return reject('signal')
            forecast = edge - bps * opening_base / 10000
            margin = .25 if policy in ('convergence', 'confirmed') else .50
            target = self.profit_target
            diagnostic.update({'historical_closing_spread_bps': bps,
                               'forecast_net_usd': forecast,
                               'target_usd': target, 'margin_usd': margin,
                               'forecast_threshold_usd': max(target, margin)})
            if forecast < diagnostic['forecast_threshold_usd']:
                return reject('forecast')
        if policy == 'confirmed':
            stamps, fallbacks = self._confirmation_stamps(signal)
            diagnostic['source_time_fallbacks'] = list(fallbacks)
            if stamps is None or not isinstance(signal.get('quantity'), (int, float)) or not (
                    math.isfinite(signal['quantity']) and signal['quantity'] > 0) or not signal.get('buy') or not signal.get('sell'):
                diagnostic['confirmation_status'] = 'missing_quote_metadata'
                self.candidates.pop(route, None)
                return reject('confirmation')
            candidate = self.candidates.get(route)
            if candidate is None:
                if len(self.candidates) >= MAX_ROUTES:
                    oldest = min(self.candidates, key=lambda key: self.candidates[key].armed_at)
                    del self.candidates[oldest]
                self.candidates[route] = _Candidate(
                    now, float(signal['quantity']), signal['buy'], signal['sell'],
                    stamps['buy'][0], stamps['sell'][0],
                    None if 'buy' in fallbacks else stamps['buy'][1],
                    None if 'sell' in fallbacks else stamps['sell'][1],
                    stamps['buy'][2], stamps['sell'][2], edge, forecast, fallbacks)
                diagnostic.update({'confirmation_status': 'armed', 'armed_at': now,
                                   'confirmation_due': now + CONFIRM_SECONDS,
                                   'confirmation_expires': now + CONFIRM_EXPIRY_SECONDS})
                return reject('confirmation')
            diagnostic.update({'armed_at': candidate.armed_at,
                               'initial_edge_usd': candidate.initial_edge_usd,
                               'initial_forecast_usd': candidate.initial_forecast_usd,
                               'initial_source_time_fallbacks': list(candidate.initial_source_fallbacks),
                               'confirmation_due': candidate.armed_at + CONFIRM_SECONDS,
                               'confirmation_expires': candidate.armed_at + CONFIRM_EXPIRY_SECONDS})
            if now > candidate.armed_at + CONFIRM_EXPIRY_SECONDS:
                self.candidates.pop(route, None)
                diagnostic['confirmation_status'] = 'expired'
                return reject('confirmation')
            if (signal['buy'] != candidate.buy or signal['sell'] != candidate.sell or
                    abs(signal['quantity'] - candidate.quantity) > max(1e-10, candidate.quantity * 1e-10)):
                self.candidates.pop(route, None)
                diagnostic['confirmation_status'] = 'quantity_or_route_changed'
                return reject('confirmation')
            if (stamps['buy'][2] != candidate.buy_generation or
                    stamps['sell'][2] != candidate.sell_generation):
                self.candidates.pop(route, None)
                diagnostic['confirmation_status'] = 'generation_changed'
                return reject('confirmation')
            for side in ('buy', 'sell'):
                receipt, source, _ = stamps[side]
                initial_receipt = getattr(candidate, f'{side}_received')
                initial_source = getattr(candidate, f'{side}_source')
                if receipt <= initial_receipt or source < candidate.armed_at + CONFIRM_SECONDS or (
                        initial_source is not None and source <= initial_source):
                    diagnostic['confirmation_status'] = 'awaiting_fresh_sources'
                    return reject('confirmation')
            if now < candidate.armed_at + CONFIRM_SECONDS:
                diagnostic['confirmation_status'] = 'awaiting_time'
                return reject('confirmation')
            diagnostic.update({'confirmation_status': 'confirmed', 'confirmed_at': now,
                               'confirmed_quantity': candidate.quantity})
        counts['allowed'] += 1
        return True, diagnostic | {'reason': 'allowed'}

    def entered(self, policy, signal, now):
        if policy not in POLICIES:
            raise ValueError(f'unknown entry policy: {policy}')
        self.counts[policy]['entered'] += 1
        if policy == 'confirmed':
            self.candidates.pop(signal['route'], None)
        if policy != 'shadow_baseline':
            self.last_entries[policy][signal['route']] = now
            if len(self.last_entries[policy]) > MAX_ROUTES:
                oldest = min(self.last_entries[policy], key=self.last_entries[policy].get)
                del self.last_entries[policy][oldest]

    def retain_routes(self, routes):
        """Discard models and cooldowns for routes removed from discovery."""
        keep = set(routes)
        for route in list(self.candidates):
            if route not in keep:
                del self.candidates[route]
        for route in list(self.routes):
            if route not in keep:
                del self.routes[route]
        for entries in self.last_entries.values():
            for route in list(entries):
                if route not in keep:
                    del entries[route]

    def snapshot(self, now):
        self._expire_idle(now)
        spans = [window.samples[-1][0] - window.samples[0][0] for window in self.routes.values()]
        warm = sum(len(window.samples) >= MIN_SAMPLES and span >= MIN_SPAN_SECONDS
                   for window, span in zip(self.routes.values(), spans))
        fields = ('checked', 'allowed', 'entered', 'rejected_signal', 'rejected_skew', 'rejected_cooldown',
                  'rejected_warmup', 'rejected_forecast', 'rejected_duplicate', 'rejected_confirmation')
        return {'version': POLICY_VERSION, 'criteria_changed_at': self.criteria_changed_at,
                'migrated_from_version': self.migrated_from_version, 'sampled_routes': len(self.routes), 'warm_routes': warm,
                'training_skew_limit_seconds': self.training_skew_limit,
                'convergence_skew_limit_seconds': self.convergence_skew_limit,
                'conservative_skew_limit_seconds': self.conservative_skew_limit,
                'cooldown_skew_limit_seconds': self.cooldown_skew_limit,
                'max_route_samples': max((len(window.samples) for window in self.routes.values()), default=0),
                'max_route_span_seconds': max(spans, default=0.0),
                'pending_confirmations': len(self.candidates),
                'confirmation_min_seconds': CONFIRM_SECONDS,
                'confirmation_expiry_seconds': CONFIRM_EXPIRY_SECONDS,
                'confirmation_cancel_reasons': dict(self.confirmation_cancel_reasons),
                'observation_counts': dict(self.observation_counts),
                'policies': {name: {field: self.counts[name][field] for field in fields} |
                             {'warm_routes': warm if name in ('convergence', 'conservative', 'confirmed') else 0,
                              'pending_confirmations': len(self.candidates) if name == 'confirmed' else 0}
                             for name in POLICIES}}

    def export_state(self):
        """Persist bounded debouncing and counters; forecasts always restart cold."""
        return {'version': POLICY_VERSION,
                'criteria_changed_at': self.criteria_changed_at,
                'migrated_from_version': self.migrated_from_version,
                'training_skew_limit_seconds': self.training_skew_limit,
                'convergence_skew_limit_seconds': self.convergence_skew_limit,
                'conservative_skew_limit_seconds': self.conservative_skew_limit,
                'cooldown_skew_limit_seconds': self.cooldown_skew_limit,
                'confirmation_min_seconds': CONFIRM_SECONDS,
                'confirmation_expiry_seconds': CONFIRM_EXPIRY_SECONDS,
                'last_entries': {name: dict(entries) for name, entries in self.last_entries.items()},
                'counts': {name: dict(counts) for name, counts in self.counts.items()},
                'confirmation_cancel_reasons': dict(self.confirmation_cancel_reasons),
                'observation_counts': dict(self.observation_counts)}

    def restore_state(self, state, now):
        if not state or state.get('version') not in (1, 2, POLICY_VERSION):
            return
        if state['version'] == 1 and any(
                state.get('counts', {}).get(name, {}).get('entered', 0) > 0
                for name in ('convergence', 'conservative')):
            raise ValueError('v1 forecast entries require a separate experiment for v2')
        self.criteria_changed_at = now if state.get('version') in (1, 2) else state.get('criteria_changed_at')
        self.migrated_from_version = state['version'] if state.get('version') in (1, 2) else state.get('migrated_from_version')
        self.routes.clear()
        self.candidates.clear()
        for name in POLICIES:
            self.counts[name] = Counter(state.get('counts', {}).get(name, {}))
            raw = state.get('last_entries', {}).get(name, {})
            self.last_entries[name] = {route: float(ts) for route, ts in raw.items()
                                       if isinstance(route, str) and isinstance(ts, (int, float)) and
                                       math.isfinite(ts) and 0 <= now - ts < COOLDOWN_SECONDS}
            if len(self.last_entries[name]) > MAX_ROUTES:
                self.last_entries[name] = dict(sorted(self.last_entries[name].items(),
                                                      key=lambda item: item[1], reverse=True)[:MAX_ROUTES])
        self.observation_counts = Counter(state.get('observation_counts', {}))
        self.confirmation_cancel_reasons = Counter(state.get('confirmation_cancel_reasons', {}))
