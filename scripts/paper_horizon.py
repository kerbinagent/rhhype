"""Standalone causal quote-markout observer for a fixed short horizon.

This scores *closing-spread bps*, not cash profit or a trading policy.  Every
observation may have its own matched quantity and entry value; a forecast from
this series is a basis-level comparison, not an original-quantity execution
forecast.  No running PaperEngine state or order endpoints are touched.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, deque
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
MODEL_VERSION = 2
MAX_EXPORT_ROWS = 5000
LINEAR_PSEUDO_OBSERVATIONS = 20.0
MAX_ABS_CLOSING_BPS = 1_000_000.0
MODELS = ('historical_median', 'persistence', 'horizon_delta', 'conditional_linear')


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


@dataclass(frozen=True)
class _Mature:
    anchor: _Observation
    outcome: _Observation

    @property
    def delta_bps(self):
        return self.outcome.closing_bps - self.anchor.closing_bps


@dataclass
class _Route:
    observations: deque[_Observation] = field(default_factory=deque)
    pending: deque[_Anchor] = field(default_factory=deque)
    matured: deque[_Mature] = field(default_factory=deque)
    last_anchor_at: float = -math.inf
    last_seen: _Observation | None = None
    segment_started_at: float | None = None
    anchors: int = 0
    matched: int = 0
    scored: int = 0
    resolved_only: int = 0
    censored: Counter = field(default_factory=Counter)
    errors: dict[str, Counter] = field(default_factory=lambda: {name: Counter() for name in MODELS})


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
                 max_paired_skew_seconds=MAX_PAIRED_SKEW_SECONDS,
                 max_export_rows=MAX_EXPORT_ROWS):
        if not (0 < horizon_seconds < outcome_deadline_seconds <= window_seconds and
                outcome_deadline_seconds < 2 * horizon_seconds and
                max_observations >= 2 and max_routes >= 1 and min_anchors >= 1 and
                min_anchor_span_seconds >= 0 and max_route_gap_seconds > 0 and
                max_book_age_seconds > 0 and max_paired_skew_seconds >= 0):
            raise ValueError('invalid horizon observer bounds')
        if not isinstance(max_export_rows, int) or not 1 <= max_export_rows <= MAX_EXPORT_ROWS:
            raise ValueError('invalid mature-row export cap')
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
        self.max_export_rows = max_export_rows
        self.routes: dict[str, _Route] = {}
        self.counts = Counter()
        self.censored = Counter()
        self.errors = {name: Counter() for name in MODELS}
        self.route_metrics: OrderedDict[str, dict] = OrderedDict()
        self.mature_export = deque(maxlen=max_export_rows)

    def _valid(self, obs):
        values = (obs.now, obs.closing_bps, obs.quantity, obs.entry_value,
                  obs.buy_source, obs.sell_source, obs.buy_received, obs.sell_received)
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values):
            return False
        if (obs.quantity <= 0 or obs.entry_value <= 0 or
                abs(obs.closing_bps) > MAX_ABS_CLOSING_BPS or
                obs.buy_generation is None or obs.sell_generation is None):
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
        while route.matured and route.matured[0].outcome.now < cutoff:
            route.matured.popleft()
        while len(route.observations) > self.max_observations:
            route.observations.popleft()
        while len(route.matured) > self.max_observations:
            route.matured.popleft()

    def _record_censor(self, route_name, route, reason, count=1):
        self.censored[reason] += count
        self.counts['censored_anchors'] += count
        route.censored[reason] += count
        metric = self._route_metric(route_name)
        metric['censored_anchors'] += count
        metric['censored'][reason] += count

    def _censor(self, route_name, route, reason):
        count = len(route.pending)
        if count:
            self._record_censor(route_name, route, reason, count)
            route.pending.clear()

    def invalidate(self, route, now, reason='feed_gap'):
        """Censor and remove one route after a feed gap or invalidation."""
        state = self.routes.pop(route, None)
        if state is None:
            return False
        known = {'feed_gap', 'generation_changed', 'route_removed', 'stale', 'evicted'}
        self._censor(route, state, reason if reason in known else 'other')
        self.counts['route_invalidations'] += 1
        return True

    def _expire_pending(self, route_name, route, now):
        while route.pending and now > route.pending[0].observation.now + self.outcome_deadline_seconds:
            route.pending.popleft()
            self._record_censor(route_name, route, 'outcome_missing')

    def _route_metric(self, route):
        metric = self.route_metrics.get(route)
        if metric is None:
            metric = {'anchors': 0, 'matched_anchors': 0, 'scored_anchors': 0,
                      'censored_anchors': 0, 'censored': Counter(),
                      'resolved_only_observations': 0,
                      'models': {name: Counter() for name in MODELS}}
            self.route_metrics[route] = metric
            if len(self.route_metrics) > self.max_routes:
                # Keep metrics for active routes; an invalidated or evicted
                # route can surrender its retained lifetime record first.
                victim = next((name for name in self.route_metrics if name not in self.routes),
                              next(iter(self.route_metrics)))
                del self.route_metrics[victim]
                self.counts['route_metric_evictions'] += 1
        else:
            self.route_metrics.move_to_end(route)
        return metric

    def _conditional_linear(self, mature, current_bps):
        """Shrink OLS slope toward persistence using 20 fixed pseudo-samples."""
        n = len(mature)
        x = [m.anchor.closing_bps for m in mature]
        y = [m.outcome.closing_bps for m in mature]
        mean_x = math.fsum(x) / n
        mean_delta = math.fsum(m.delta_bps for m in mature) / n
        base = current_bps + mean_delta
        if not math.isfinite(base) or abs(base) > 2 * MAX_ABS_CLOSING_BPS:
            self.counts['linear_finite_fallbacks'] += 1
            return current_bps
        variance = math.fsum((value - mean_x) ** 2 for value in x)
        if variance <= n * 1e-12:
            self.counts['linear_degenerate_variance'] += 1
            return base
        mean_y = math.fsum(y) / n
        covariance = math.fsum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
        raw_beta = covariance / variance
        beta = 1.0 + n / (n + LINEAR_PSEUDO_OBSERVATIONS) * (raw_beta - 1.0)
        predicted = base + (beta - 1.0) * (current_bps - mean_x)
        if not math.isfinite(predicted) or abs(predicted) > 2 * MAX_ABS_CLOSING_BPS:
            self.counts['linear_finite_fallbacks'] += 1
            return base
        return predicted

    def _prediction(self, route, obs):
        if len(route.matured) < self.min_anchors or not route.observations:
            return None
        if route.matured[-1].anchor.now - route.matured[0].anchor.now < self.min_anchor_span_seconds:
            return None
        historical = median(x.closing_bps for x in route.observations)
        change = median(x.delta_bps for x in route.matured)
        return {'historical_median': historical,
                'persistence': obs.closing_bps,
                'horizon_delta': obs.closing_bps + change,
                'conditional_linear': self._conditional_linear(route.matured, obs.closing_bps)}

    def _score(self, route, state, prediction, actual):
        route_metric = self._route_metric(route)
        for name, forecast in prediction.items():
            error = actual - forecast
            for stats in (self.errors[name], route_metric['models'][name], state.errors[name]):
                stats['count'] += 1
                stats['error_sum'] += error
                stats['absolute_error_sum'] += abs(error)
                stats['squared_error_sum'] += error * error

    def _resolve(self, route_name, route, obs):
        for anchor in list(route.pending):
            start = anchor.observation
            age = obs.now - start.now
            if age < self.horizon_seconds:
                continue
            if age > self.outcome_deadline_seconds:
                route.pending.remove(anchor)
                self._record_censor(route_name, route, 'outcome_missing')
                continue
            if (obs.buy_source < start.buy_source + self.horizon_seconds or
                    obs.sell_source < start.sell_source + self.horizon_seconds):
                continue
            route.pending.remove(anchor)
            route.matured.append(_Mature(start, obs))
            self.counts['matched_anchors'] += 1
            metric = self._route_metric(route_name)
            metric['matched_anchors'] += 1
            route.matched += 1
            if len(self.mature_export) == self.max_export_rows:
                self.counts['mature_export_dropped'] += 1
            self.mature_export.append({
                'model_version': MODEL_VERSION,
                'route': route_name,
                'anchor_time': start.now, 'outcome_time': obs.now,
                'anchor_closing_bps': start.closing_bps,
                'outcome_closing_bps': obs.closing_bps,
                'anchor_quantity': start.quantity, 'outcome_quantity': obs.quantity,
                'anchor_entry_value': start.entry_value, 'outcome_entry_value': obs.entry_value,
                'anchor_buy_source_time': start.buy_source,
                'anchor_sell_source_time': start.sell_source,
                'outcome_buy_source_time': obs.buy_source,
                'outcome_sell_source_time': obs.sell_source,
                'anchor_buy_generation': str(start.buy_generation),
                'anchor_sell_generation': str(start.sell_generation),
                'outcome_buy_generation': str(obs.buy_generation),
                'outcome_sell_generation': str(obs.sell_generation),
                'scored': anchor.predictions is not None,
                'frozen_predictions_bps': dict(anchor.predictions) if anchor.predictions else None})
            if anchor.predictions is not None:
                self._score(route_name, route, anchor.predictions, obs.closing_bps)
                self.counts['scored_anchors'] += 1
                metric['scored_anchors'] += 1
                route.scored += 1

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
        if state and state.last_seen:
            previous = state.last_seen
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
            state.segment_started_at = now
            self.routes[route] = state
        self._route_metric(route)
        self._trim(state, now)
        if (state.observations and
                now - state.observations[-1].now < MIN_SAMPLE_INTERVAL_SECONDS):
            # Outcome detection uses every fresh paired quote. The 1 Hz cap
            # applies only to observations used as anchors and model history.
            # This quote must never make a retroactive prediction for itself.
            self._resolve(route, state, obs)
            self._trim(state, now)
            state.last_seen = obs
            state.resolved_only += 1
            self._route_metric(route)['resolved_only_observations'] += 1
            self.counts['resolved_only_observations'] += 1
            self.counts['rate_limited'] += 1
            return False
        # Freeze the new anchor's forecasts before this quote matures older
        # anchors, so its own quote cannot enter its training set.
        anchor_due = now - state.last_anchor_at >= self.horizon_seconds
        prediction = self._prediction(state, obs) if anchor_due else None
        self._resolve(route, state, obs)
        state.observations.append(obs)
        state.last_seen = obs
        if anchor_due:
            if len(state.pending) >= MAX_PENDING_PER_ROUTE:
                state.pending.popleft()
                self._record_censor(route, state, 'pending_cap')
            state.pending.append(_Anchor(obs, prediction))
            state.last_anchor_at = now
            self.counts['anchors'] += 1
            state.anchors += 1
            self._route_metric(route)['anchors'] += 1
            if prediction is None:
                self.counts['warmup_anchors'] += 1
        self._trim(state, now)
        self.counts['observations'] += 1
        return True

    def snapshot(self, now):
        """Return bounded aggregate quote error and coverage diagnostics."""
        for name, state in list(self.routes.items()):
            self._expire_pending(name, state, now)
            self._trim(state, now)
            if not state.observations or now - state.observations[-1].now > self.max_route_gap_seconds:
                self.invalidate(name, now, 'stale')
        def error_summary(stats):
            count = stats['count']
            return {'count': count,
                    'mean_error_bps': stats['error_sum'] / count if count else None,
                    'mean_absolute_error_bps': stats['absolute_error_sum'] / count if count else None,
                    'root_mean_squared_error_bps': math.sqrt(stats['squared_error_sum'] / count) if count else None}
        models = {name: error_summary(stats) for name, stats in self.errors.items()}
        warm = sum(len(state.matured) >= self.min_anchors and
                   state.matured[-1].anchor.now - state.matured[0].anchor.now >= self.min_anchor_span_seconds
                   for state in self.routes.values() if state.matured)
        per_route = {}
        for name, metric in self.route_metrics.items():
            state = self.routes.get(name)
            mature_window = len(state.matured) if state else 0
            segment = None
            if state:
                last = state.last_seen
                segment = {
                    'scope': 'active_generation_segment',
                    'started_at': state.segment_started_at,
                    'generation': {'buy': str(last.buy_generation),
                                   'sell': str(last.sell_generation)} if last else None,
                    'anchors': state.anchors,
                    'matched_anchors': state.matched,
                    'scored_anchors': state.scored,
                    'censored_anchors': sum(state.censored.values()),
                    'censored_by_reason': dict(state.censored),
                    'pending_anchors': len(state.pending),
                    'mature_anchors_window': mature_window,
                    'resolved_only_observations': state.resolved_only,
                    'models': {model: error_summary(stats) for model, stats in state.errors.items()}}
            per_route[name] = {
                'scope': 'retained_route_lifetime_until_metric_eviction',
                'active': state is not None,
                'anchors': metric['anchors'],
                'matched_anchors': metric['matched_anchors'],
                'scored_anchors': metric['scored_anchors'],
                'censored_anchors': metric['censored_anchors'],
                'censored_by_reason': dict(metric['censored']),
                'resolved_only_observations': metric['resolved_only_observations'],
                'pending_anchors': len(state.pending) if state else 0,
                'mature_anchors_window': mature_window,
                'models': {model: error_summary(stats) for model, stats in metric['models'].items()},
                'active_segment': segment}
        return {'model_version': MODEL_VERSION,
                'horizon_seconds': self.horizon_seconds,
                'outcome_deadline_seconds': self.outcome_deadline_seconds,
                'window_seconds': self.window_seconds,
                'linear_pseudo_observations': LINEAR_PSEUDO_OBSERVATIONS,
                'linear_slope_shrinkage': 'n/(n+20) toward beta=1',
                'max_abs_closing_bps': MAX_ABS_CLOSING_BPS,
                'max_export_rows': self.max_export_rows,
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
                'max_route_mature_anchors': max((len(state.matured) for state in self.routes.values()), default=0),
                'counts': dict(self.counts), 'censored': dict(self.censored),
                'models': models, 'per_route': per_route,
                'mature_rows': list(self.mature_export),
                'interpretation': 'Causal basis-level quote errors; quantities vary, no fill or cash-P&L inference.'}
