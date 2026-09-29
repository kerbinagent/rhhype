"""Standalone causal quote-markout observer for a fixed short horizon.

This scores *closing-spread bps*, not cash profit or a trading policy.  Every
observation may have its own matched quantity and entry value; a forecast from
this series is a basis-level comparison, not an original-quantity execution
forecast.  No running PaperEngine state or order endpoints are touched.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import math
from statistics import median


HORIZON_SECONDS = 12.0
OUTCOME_DEADLINE_SECONDS = 16.0
WINDOW_SECONDS = 900.0
MAX_OBSERVATIONS = 900
MAX_ROUTES = 2000
MAX_PENDING_PER_ROUTE = 2
MIN_ANCHORS = 40
MIN_ANCHOR_SPAN_SECONDS = 480.0
MAX_ROUTE_GAP_SECONDS = 30.0
MAX_BOOK_AGE_SECONDS = 2.0
MAX_PAIRED_SKEW_SECONDS = 1.0
MIN_SAMPLE_INTERVAL_SECONDS = 1.0
MODELS = ('historical_median', 'persistence', 'horizon_delta')


@dataclass(frozen=True)
class _Observation:
    now: float
    closing_bps: float
    quantity: float
    entry_value: float
    buy_source: float
    sell_source: float
    buy_received: float
    sell_received: float
    buy_generation: object
    sell_generation: object


@dataclass
class _Anchor:
    observation: _Observation
    predictions: dict[str, float] | None


@dataclass
class _Route:
    observations: deque[_Observation] = field(default_factory=deque)
    pending: deque[_Anchor] = field(default_factory=deque)
    # (anchor decision time, outcome receipt time, future-minus-current bps)
    matured: deque[tuple[float, float, float]] = field(default_factory=deque)
    last_anchor_at: float = -math.inf


class HorizonMarkoutObserver:
    """Chronological, bounded observer of 12-second executable spread changes.

    `observe` requires two already paired, executable books for one directed
    physical route.  It validates their timestamps and generations again for
    independent use.  Predictions are frozen before the current observation
    resolves any older anchor, so the current sample cannot train itself.
    """

    def __init__(self, *, horizon_seconds=HORIZON_SECONDS,
                 outcome_deadline_seconds=OUTCOME_DEADLINE_SECONDS,
                 window_seconds=WINDOW_SECONDS, max_observations=MAX_OBSERVATIONS,
                 max_routes=MAX_ROUTES, min_anchors=MIN_ANCHORS,
                 min_anchor_span_seconds=MIN_ANCHOR_SPAN_SECONDS,
                 max_route_gap_seconds=MAX_ROUTE_GAP_SECONDS,
                 max_book_age_seconds=MAX_BOOK_AGE_SECONDS,
                 max_paired_skew_seconds=MAX_PAIRED_SKEW_SECONDS):
        if not (0 < horizon_seconds < outcome_deadline_seconds <= window_seconds and
                outcome_deadline_seconds < 2 * horizon_seconds and
                max_observations >= 2 and max_routes >= 1 and min_anchors >= 1 and
                min_anchor_span_seconds >= 0 and max_route_gap_seconds > 0 and
                max_book_age_seconds > 0 and max_paired_skew_seconds >= 0):
            raise ValueError('invalid horizon observer bounds')
        self.horizon_seconds = float(horizon_seconds)
        self.outcome_deadline_seconds = float(outcome_deadline_seconds)
        self.window_seconds = float(window_seconds)
        self.max_observations = int(max_observations)
        self.max_routes = int(max_routes)
        self.min_anchors = int(min_anchors)
        self.min_anchor_span_seconds = float(min_anchor_span_seconds)
        self.max_route_gap_seconds = float(max_route_gap_seconds)
        self.max_book_age_seconds = float(max_book_age_seconds)
        self.max_paired_skew_seconds = float(max_paired_skew_seconds)
        self.routes: dict[str, _Route] = {}
        self.counts = Counter()
        self.censored = Counter()
        self.errors = {name: Counter() for name in MODELS}

    def _valid(self, obs):
        values = (obs.now, obs.closing_bps, obs.quantity, obs.entry_value,
                  obs.buy_source, obs.sell_source, obs.buy_received, obs.sell_received)
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values):
            return False
        if obs.quantity <= 0 or obs.entry_value <= 0 or obs.buy_generation is None or obs.sell_generation is None:
            return False
        if any(not -.1 <= obs.now - receipt <= self.max_book_age_seconds
               for receipt in (obs.buy_received, obs.sell_received)):
            return False
        if any(not -2 <= obs.now - source <= self.max_book_age_seconds
               for source in (obs.buy_source, obs.sell_source)):
            return False
        if abs(obs.buy_received - obs.sell_received) > self.max_paired_skew_seconds:
            return False
        if abs(obs.buy_source - obs.sell_source) > self.max_paired_skew_seconds:
            return False
        return True

    def _trim(self, route, now):
        cutoff = now - self.window_seconds
        while route.observations and route.observations[0].now < cutoff:
            route.observations.popleft()
        while route.matured and route.matured[0][1] < cutoff:
            route.matured.popleft()
        while len(route.observations) > self.max_observations:
            route.observations.popleft()
        while len(route.matured) > self.max_observations:
            route.matured.popleft()

    def _censor(self, route, reason):
        count = len(route.pending)
        if count:
            self.censored[reason] += count
            self.counts['censored_anchors'] += count
            route.pending.clear()

    def invalidate(self, route, now, reason='feed_gap'):
        """Censor and remove one route after a feed gap or invalidation."""
        state = self.routes.pop(route, None)
        if state is None:
            return False
        known = {'feed_gap', 'generation_changed', 'route_removed', 'stale', 'evicted'}
        self._censor(state, reason if reason in known else 'other')
        self.counts['route_invalidations'] += 1
        return True

    def _expire_pending(self, route, now):
        while route.pending and now > route.pending[0].observation.now + self.outcome_deadline_seconds:
            route.pending.popleft()
            self.censored['outcome_missing'] += 1
            self.counts['censored_anchors'] += 1

    def _prediction(self, route, obs):
        if len(route.matured) < self.min_anchors or not route.observations:
            return None
        if route.matured[-1][0] - route.matured[0][0] < self.min_anchor_span_seconds:
            return None
        historical = median(x.closing_bps for x in route.observations)
        change = median(x[2] for x in route.matured)
        return {'historical_median': historical,
                'persistence': obs.closing_bps,
                'horizon_delta': obs.closing_bps + change}

    def _score(self, prediction, actual):
        for name, forecast in prediction.items():
            error = actual - forecast
            stats = self.errors[name]
            stats['count'] += 1
            stats['error_sum'] += error
            stats['absolute_error_sum'] += abs(error)
            stats['squared_error_sum'] += error * error

    def _resolve(self, route, obs):
        for anchor in list(route.pending):
            start = anchor.observation
            age = obs.now - start.now
            if age < self.horizon_seconds:
                continue
            if age > self.outcome_deadline_seconds:
                route.pending.remove(anchor)
                self.censored['outcome_missing'] += 1
                self.counts['censored_anchors'] += 1
                continue
            if (obs.buy_source < start.buy_source + self.horizon_seconds or
                    obs.sell_source < start.sell_source + self.horizon_seconds):
                continue
            route.pending.remove(anchor)
            delta = obs.closing_bps - start.closing_bps
            route.matured.append((start.now, obs.now, delta))
            self.counts['matched_anchors'] += 1
            if anchor.predictions is not None:
                self._score(anchor.predictions, obs.closing_bps)
                self.counts['scored_anchors'] += 1

    def observe(self, route, now, closing_bps, quantity, entry_value,
                buy_source_time, sell_source_time, buy_received, sell_received,
                buy_generation, sell_generation):
        """Record one directed paired quote and resolve eligible old anchors."""
        obs = _Observation(now, closing_bps, quantity, entry_value,
                           buy_source_time, sell_source_time, buy_received, sell_received,
                           buy_generation, sell_generation)
        if not isinstance(route, str) or not route or not self._valid(obs):
            self.counts['invalid_observation'] += 1
            return False
        state = self.routes.get(route)
        if state and state.observations:
            previous = state.observations[-1]
            if now < previous.now:
                self.counts['out_of_order'] += 1
                return False
            if (obs.buy_generation != previous.buy_generation or
                    obs.sell_generation != previous.sell_generation):
                self.invalidate(route, now, 'generation_changed')
                state = None
            elif now - previous.now > self.max_route_gap_seconds:
                self.invalidate(route, now, 'feed_gap')
                state = None
            elif now - previous.now < MIN_SAMPLE_INTERVAL_SECONDS:
                self.counts['rate_limited'] += 1
                return False
            elif (obs.buy_received <= previous.buy_received or
                  obs.sell_received <= previous.sell_received or
                  obs.buy_source <= previous.buy_source or
                  obs.sell_source <= previous.sell_source):
                self.counts['source_not_advanced'] += 1
                return False
        if state is None:
            if len(self.routes) >= self.max_routes:
                oldest = min(self.routes, key=lambda name: self.routes[name].observations[-1].now)
                self.invalidate(oldest, now, 'evicted')
            state = _Route()
            self.routes[route] = state
        self._trim(state, now)
        # Freeze the new anchor's forecasts before this quote matures older
        # anchors, so its own quote cannot enter its training set.
        anchor_due = now - state.last_anchor_at >= self.horizon_seconds
        prediction = self._prediction(state, obs) if anchor_due else None
        self._resolve(state, obs)
        state.observations.append(obs)
        if anchor_due:
            if len(state.pending) >= MAX_PENDING_PER_ROUTE:
                state.pending.popleft()
                self.censored['pending_cap'] += 1
                self.counts['censored_anchors'] += 1
            state.pending.append(_Anchor(obs, prediction))
            state.last_anchor_at = now
            self.counts['anchors'] += 1
            if prediction is None:
                self.counts['warmup_anchors'] += 1
        self._trim(state, now)
        self.counts['observations'] += 1
        return True

    def snapshot(self, now):
        """Return bounded aggregate quote error and coverage diagnostics."""
        for name, state in list(self.routes.items()):
            self._expire_pending(state, now)
            self._trim(state, now)
            if not state.observations or now - state.observations[-1].now > self.max_route_gap_seconds:
                self.invalidate(name, now, 'stale')
        models = {}
        for name, stats in self.errors.items():
            count = stats['count']
            models[name] = {'count': count,
                            'mean_error_bps': stats['error_sum'] / count if count else None,
                            'mean_absolute_error_bps': stats['absolute_error_sum'] / count if count else None,
                            'root_mean_squared_error_bps': math.sqrt(stats['squared_error_sum'] / count) if count else None}
        warm = sum(len(state.matured) >= self.min_anchors and
                   state.matured[-1][0] - state.matured[0][0] >= self.min_anchor_span_seconds
                   for state in self.routes.values() if state.matured)
        return {'horizon_seconds': self.horizon_seconds,
                'outcome_deadline_seconds': self.outcome_deadline_seconds,
                'window_seconds': self.window_seconds,
                'max_observations_per_route': self.max_observations,
                'max_routes': self.max_routes,
                'min_mature_anchors': self.min_anchors,
                'min_anchor_span_seconds': self.min_anchor_span_seconds,
                'max_route_gap_seconds': self.max_route_gap_seconds,
                'max_book_age_seconds': self.max_book_age_seconds,
                'max_paired_skew_seconds': self.max_paired_skew_seconds,
                'min_sample_interval_seconds': MIN_SAMPLE_INTERVAL_SECONDS,
                'sampled_routes': len(self.routes), 'warm_routes': warm,
                'pending_anchors': sum(len(state.pending) for state in self.routes.values()),
                'max_route_observations': max((len(state.observations) for state in self.routes.values()), default=0),
                'counts': dict(self.counts), 'censored': dict(self.censored),
                'models': models,
                'interpretation': 'Causal basis-level quote errors; quantities vary, no fill or cash-P&L inference.'}
