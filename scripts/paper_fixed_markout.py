"""Bounded prospective fixed-quantity quote markouts; no fills or orders."""

from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
import math

from monitor import walk
from paper_horizon import MODELS


MODEL_VERSION = 1
HORIZON_SECONDS = 12.0
DEADLINE_SECONDS = 16.0
MAX_ROUTES = 24
MAX_PENDING_PER_ROUTE = 2
MAX_TERMINAL_ROWS = 5000
MAX_ABS_BPS = 2_000_000.0
SCREEN_THRESHOLDS_USD = (0.0, .25)


def standard_fee_bps(market):
    """Freeze the Standard taker assumption supplied by discovery metadata."""
    venue = market['venue']
    if venue in ('lighter', 'rh_lighter'):
        rate = float(market.get('published_fee_floor_bps', 0))
    elif venue == 'hyperliquid':
        rate = float(market['fee_bps'])
    else:
        raise ValueError(f'unsupported WebSocket-only venue: {venue}')
    if not math.isfinite(rate) or not 0 <= rate <= 10000:
        raise ValueError('Standard fee assumption must be nonnegative and finite')
    return rate


def _finite(value, *, positive=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(value) and (value > 0 if positive else True))


@dataclass
class _Route:
    pending: deque[dict] = field(default_factory=deque)
    last_pair: dict | None = None
    last_anchor_at: float = -math.inf


class FixedQuantityMarkoutObserver:
    """Resolve original-quantity exit quotes before sizing any new anchor.

    `on_pair` must be called before a corresponding `anchor`. It consumes the
    first valid, source-advanced pair for each old anchor; if that pair has no
    original-quantity exit depth, the anchor is censored immediately.
    """

    def __init__(self, *, horizon_seconds=HORIZON_SECONDS,
                 deadline_seconds=DEADLINE_SECONDS, max_routes=MAX_ROUTES,
                 max_terminal_rows=MAX_TERMINAL_ROWS, max_book_age=2.0,
                 max_pair_skew=1.0, max_route_gap=30.0,
                 extra_cost_bps=5.0, margin_fraction=1.0,
                 capital_rate=.05):
        if not (0 < horizon_seconds < deadline_seconds < 30 and
                1 <= max_routes <= MAX_ROUTES and
                1 <= max_terminal_rows <= MAX_TERMINAL_ROWS and
                max_book_age > 0 and max_pair_skew >= 0 and max_route_gap > deadline_seconds and
                all(_finite(x) and x >= 0 for x in
                    (extra_cost_bps, margin_fraction, capital_rate))):
            raise ValueError('invalid fixed-markout bounds')
        self.horizon_seconds = float(horizon_seconds)
        self.deadline_seconds = float(deadline_seconds)
        self.max_routes = int(max_routes)
        self.max_terminal_rows = int(max_terminal_rows)
        self.max_book_age = float(max_book_age)
        self.max_pair_skew = float(max_pair_skew)
        self.max_route_gap = float(max_route_gap)
        self.extra_cost_bps = float(extra_cost_bps)
        self.margin_fraction = float(margin_fraction)
        self.capital_rate = float(capital_rate)
        self.routes: dict[str, _Route] = {}
        self.counts = Counter()
        self.censored = Counter()
        self.rejections = Counter()
        self.per_route: OrderedDict[str, Counter] = OrderedDict()
        self.terminal = deque(maxlen=max_terminal_rows)
        self.finished = False
        self.cohorts = {f'{name}_gt_{threshold:g}': Counter()
                        for name in MODELS
                        for threshold in SCREEN_THRESHOLDS_USD}
        self.sums = Counter()

    def _metric(self, route):
        metric = self.per_route.get(route)
        if metric is None:
            metric = Counter()
            self.per_route[route] = metric
            if len(self.per_route) > self.max_routes:
                self.per_route.popitem(last=False)
                self.counts['route_metric_evictions'] += 1
        else:
            self.per_route.move_to_end(route)
        return metric

    def _store_terminal(self, result):
        if len(self.terminal) == self.max_terminal_rows:
            self.counts['terminal_export_dropped'] += 1
        self.terminal.append(result)

    def _finish_censor(self, route, anchor, reason):
        self.counts['censored_anchors'] += 1
        self.censored[reason] += 1
        self._metric(route)['censored_anchors'] += 1
        if anchor['frozen_forecasts_bps'] is not None:
            self.counts['censored_scored_anchors'] += 1
            for cohort, selected in anchor['screen_flags'].items():
                if selected:
                    self.cohorts[cohort]['censored'] += 1
        self._store_terminal(dict(anchor, status='censored', censor_reason=reason))

    def invalidate(self, route, now, reason='feed_gap'):
        state = self.routes.pop(route, None)
        if state is None:
            return False
        label = reason if reason in ('feed_gap', 'generation_changed', 'route_removed',
                                     'stale', 'evicted', 'invalid_book') else 'other'
        while state.pending:
            self._finish_censor(route, state.pending.popleft(), label)
        self.counts['route_invalidations'] += 1
        return True

    def _expire(self, route, state, now):
        while state.pending and now > state.pending[0]['anchor_time'] + self.deadline_seconds:
            self._finish_censor(route, state.pending.popleft(), 'outcome_missing')

    def _pair_data(self, now, buy_book, sell_book):
        if not _finite(now):
            return None, 'invalid_time'
        if not buy_book or not sell_book:
            return None, 'missing_leg'
        if not buy_book.get('valid') or not sell_book.get('valid'):
            return None, 'invalid_book'
        fields = []
        for book in (buy_book, sell_book):
            if (book.get('engine_time') is None or book.get('received') is None or
                    book.get('generation') is None or book.get('sequence') is None):
                return None, 'missing_source_identity'
            if not book.get('bids') or not book.get('asks'):
                return None, 'missing_top'
            if not all(_finite(book[side][0][0], positive=True) for side in ('bids', 'asks')):
                return None, 'invalid_top'
            if book['bids'][0][0] >= book['asks'][0][0]:
                return None, 'crossed_book'
            source, receipt = book['engine_time'], book['received']
            if not _finite(source) or not _finite(receipt):
                return None, 'invalid_clock'
            if not -.25 <= now-source <= self.max_book_age:
                return None, 'stale_source'
            if not -.1 <= now-receipt <= self.max_book_age:
                return None, 'stale_receipt'
            fields.append((source, receipt, book['generation'], book['sequence']))
        if abs(fields[0][0]-fields[1][0]) > self.max_pair_skew:
            return None, 'source_skew'
        if abs(fields[0][1]-fields[1][1]) > self.max_pair_skew:
            return None, 'receipt_skew'
        return {'now': now,
                'buy_source': fields[0][0], 'sell_source': fields[1][0],
                'buy_received': fields[0][1], 'sell_received': fields[1][1],
                'buy_generation': fields[0][2], 'sell_generation': fields[1][2],
                'buy_sequence': fields[0][3], 'sell_sequence': fields[1][3]}, None

    def on_pair(self, route, now, buy_book, sell_book):
        """Accept a paired quote and resolve pending anchors at their saved q."""
        if self.finished:
            return False
        if not _finite(now):
            self.rejections['invalid_time'] += 1
            return False
        if not isinstance(route, str) or not route:
            self.rejections['invalid_route'] += 1
            return False
        state = self.routes.get(route)
        if state:
            self._expire(route, state, now)
        pair, reason = self._pair_data(now, buy_book, sell_book)
        if reason:
            self.rejections[reason] += 1
            return False
        if state and state.last_pair:
            previous = state.last_pair
            if now < previous['now']:
                self.rejections['out_of_order'] += 1
                return False
            if (pair['buy_generation'] != previous['buy_generation'] or
                    pair['sell_generation'] != previous['sell_generation']):
                self.invalidate(route, now, 'generation_changed')
                state = None
            elif now-previous['now'] > self.max_route_gap:
                self.invalidate(route, now, 'feed_gap')
                state = None
            elif any(pair[k] <= previous[k] for k in
                     ('buy_source', 'sell_source', 'buy_received', 'sell_received')) or any(
                         pair[k] == previous[k] for k in ('buy_sequence', 'sell_sequence')):
                self.rejections['source_not_advanced'] += 1
                return False
        if state is None:
            if len(self.routes) >= self.max_routes:
                oldest = min(self.routes, key=lambda key: self.routes[key].last_pair['now'])
                self.invalidate(oldest, now, 'evicted')
            state = _Route()
            self.routes[route] = state
        state.last_pair = pair
        self._metric(route)
        self.counts['paired_observations'] += 1
        for anchor in list(state.pending):
            age = now-anchor['anchor_time']
            if age < self.horizon_seconds:
                continue
            if (pair['buy_source'] < anchor['anchor_buy_source_time']+self.horizon_seconds or
                    pair['sell_source'] < anchor['anchor_sell_source_time']+self.horizon_seconds):
                continue
            state.pending.remove(anchor)
            q = anchor['quantity']
            long_exit = walk(buy_book['bids'], q)
            short_exit = walk(sell_book['asks'], q)
            if not (_finite(long_exit, positive=True) and _finite(short_exit, positive=True)):
                self._finish_censor(route, anchor, 'future_exit_depth')
                continue
            buy_rate = anchor['buy_fee_bps']/10000
            sell_rate = anchor['sell_fee_bps']/10000
            fees = {
                'buy_entry_fee_usd': anchor['entry_buy_value']*buy_rate,
                'sell_entry_fee_usd': anchor['entry_sell_value']*sell_rate,
                'buy_exit_fee_usd': long_exit*buy_rate,
                'sell_exit_fee_usd': short_exit*sell_rate,
            }
            gross = (anchor['entry_sell_value']-anchor['entry_buy_value']+
                     long_exit-short_exit)
            total_fees = sum(fees.values())
            net = gross-total_fees
            reserve = (self.extra_cost_bps/10000 *
                       max(anchor['entry_buy_value'], anchor['entry_sell_value']))
            capital = ((anchor['entry_buy_value']+anchor['entry_sell_value'])*
                       self.margin_fraction*self.capital_rate*age/
                       (365*86400))
            after_reserve = net-reserve-capital
            result = dict(anchor, status='matched', censor_reason=None,
                          outcome_time=now, outcome_buy_source_time=pair['buy_source'],
                          outcome_sell_source_time=pair['sell_source'],
                          outcome_buy_received=pair['buy_received'],
                          outcome_sell_received=pair['sell_received'],
                          outcome_buy_sequence=str(pair['buy_sequence']),
                          outcome_sell_sequence=str(pair['sell_sequence']),
                          exit_long_value=long_exit, exit_short_buyback_value=short_exit,
                          gross_capture_usd=gross, **fees,
                          total_four_fees_usd=total_fees,
                          net_after_four_fees_usd=net,
                          net_after_four_fees_bps=net/anchor['entry_buy_value']*10000,
                          extra_cost_reserve_usd=reserve,
                          capital_elapsed_seconds=age,
                          capital_reserve_usd=capital,
                          net_after_reserves_usd=after_reserve)
            self._store_terminal(result)
            self.counts['matched_anchors'] += 1
            metric = self._metric(route)
            metric['matched_anchors'] += 1
            self.sums['four_fee_net_usd'] += net
            self.sums['after_reserve_net_usd'] += after_reserve
            self.sums['gross_capture_usd'] += gross
            if net > 0:
                self.counts['four_fee_positive'] += 1
                metric['four_fee_positive'] += 1
            if after_reserve > 0:
                self.counts['after_reserve_positive'] += 1
            if anchor['frozen_forecasts_bps'] is not None:
                self.counts['matched_scored_anchors'] += 1
                metric['matched_scored_anchors'] += 1
                self.sums['scored_four_fee_net_usd'] += net
                self.sums['scored_after_reserve_net_usd'] += after_reserve
                if net > 0:
                    self.counts['scored_four_fee_positive'] += 1
                if after_reserve > 0:
                    self.counts['scored_after_reserve_positive'] += 1
                for cohort, selected in anchor['screen_flags'].items():
                    if selected:
                        self.cohorts[cohort]['matched'] += 1
                        self.cohorts[cohort]['four_fee_net_sum_usd'] += net
                        self.cohorts[cohort]['after_reserve_net_sum_usd'] += after_reserve
                        if net > 0:
                            self.cohorts[cohort]['four_fee_positive'] += 1
                        if after_reserve > 0:
                            self.cohorts[cohort]['after_reserve_positive'] += 1
        return True

    def anchor(self, route, now, quote, buy_fee_bps, sell_fee_bps,
               frozen_forecasts_bps=None):
        """Freeze one source-aligned anchor after `on_pair` handled old ones."""
        if self.finished:
            return False
        state = self.routes.get(route)
        if state is None or state.last_pair is None or state.last_pair['now'] != now:
            self.rejections['anchor_without_pair'] += 1
            return False
        if now-state.last_anchor_at < self.horizon_seconds:
            self.rejections['anchor_spacing'] += 1
            return False
        quote_fields = ('quantity', 'entry_value', 'short_entry_value',
                        'long_liquidation_value', 'short_buyback_value')
        if not isinstance(quote, dict) or any(not _finite(quote.get(k), positive=True)
                                               for k in quote_fields):
            self.rejections['invalid_anchor_quote'] += 1
            return False
        if any(not _finite(rate) or not 0 <= rate <= 10000
               for rate in (buy_fee_bps, sell_fee_bps)):
            self.rejections['invalid_fee'] += 1
            return False
        if frozen_forecasts_bps is not None:
            if (not isinstance(frozen_forecasts_bps, dict) or
                    set(frozen_forecasts_bps) != set(MODELS) or
                    any(not _finite(x) or abs(x) > MAX_ABS_BPS
                        for x in frozen_forecasts_bps.values())):
                self.rejections['invalid_forecasts'] += 1
                return False
        p = state.last_pair
        a0, b0 = quote['entry_value'], quote['short_entry_value']
        l0, s0 = quote['long_liquidation_value'], quote['short_buyback_value']
        buy_rate, sell_rate = buy_fee_bps/10000, sell_fee_bps/10000
        fees_estimate = a0*buy_rate+b0*sell_rate+l0*buy_rate+s0*sell_rate
        screens = ({name: b0-a0-forecast*a0/10000-fees_estimate
                    for name, forecast in frozen_forecasts_bps.items()}
                   if frozen_forecasts_bps is not None else None)
        flags = ({f'{name}_gt_{threshold:g}': screens[name] > threshold
                  for name in MODELS
                  for threshold in SCREEN_THRESHOLDS_USD}
                 if screens is not None else {})
        anchor = {
            'model_version': MODEL_VERSION, 'route': route, 'anchor_time': now,
            'quantity': quote['quantity'], 'entry_buy_value': a0,
            'entry_sell_value': b0, 'anchor_long_liquidation_value': l0,
            'anchor_short_buyback_value': s0,
            'buy_fee_bps': buy_fee_bps, 'sell_fee_bps': sell_fee_bps,
            'anchor_buy_source_time': p['buy_source'],
            'anchor_sell_source_time': p['sell_source'],
            'anchor_buy_received': p['buy_received'],
            'anchor_sell_received': p['sell_received'],
            'anchor_buy_sequence': str(p['buy_sequence']),
            'anchor_sell_sequence': str(p['sell_sequence']),
            'anchor_buy_generation': str(p['buy_generation']),
            'anchor_sell_generation': str(p['sell_generation']),
            'frozen_forecasts_bps': dict(frozen_forecasts_bps) if frozen_forecasts_bps else None,
            'prediction_screens_usd': screens, 'screen_flags': flags,
        }
        if len(state.pending) >= MAX_PENDING_PER_ROUTE:
            self._finish_censor(route, state.pending.popleft(), 'pending_cap')
        state.pending.append(anchor)
        state.last_anchor_at = now
        self.counts['anchors'] += 1
        self._metric(route)['anchors'] += 1
        if frozen_forecasts_bps is None:
            self.counts['warmup_anchors'] += 1
        else:
            self.counts['v2_scored_anchors'] += 1
            self._metric(route)['v2_scored_anchors'] += 1
            for cohort, selected in flags.items():
                if selected:
                    self.cohorts[cohort]['anchors'] += 1
        return True

    def finish(self, now):
        """Close the study before stream cancellation can mimic feed loss."""
        if self.finished:
            return
        for route, state in list(self.routes.items()):
            self._expire(route, state, now)
            while state.pending:
                self._finish_censor(route, state.pending.popleft(), 'stopped_pending')
        self.finished = True

    def snapshot(self, now):
        if not self.finished:
            for route, state in list(self.routes.items()):
                self._expire(route, state, now)
                if state.last_pair and now-state.last_pair['now'] > self.max_route_gap:
                    self.invalidate(route, now, 'stale')
        matched = self.counts['matched_anchors']
        pending_scored = sum(anchor['frozen_forecasts_bps'] is not None
                             for state in self.routes.values() for anchor in state.pending)
        selected_coverage = {}
        for cohort, stats in self.cohorts.items():
            anchors = stats['anchors']
            matched_selected = stats['matched']
            censored = stats['censored']
            selected_coverage[cohort] = {
                'anchors': anchors, 'matched': matched_selected,
                'censored': censored,
                'pending': anchors-matched_selected-censored,
                'matched_fraction': matched_selected/anchors if anchors else None,
                'censored_fraction': censored/anchors if anchors else None,
                'four_fee_positive': stats['four_fee_positive'],
                'positive_fraction_among_matched':
                    stats['four_fee_positive']/matched_selected if matched_selected else None,
                'mean_four_fee_net_usd':
                    stats['four_fee_net_sum_usd']/matched_selected if matched_selected else None,
                'after_reserve_positive': stats['after_reserve_positive'],
                'after_reserve_positive_fraction_among_matched':
                    stats['after_reserve_positive']/matched_selected if matched_selected else None,
                'mean_after_reserve_net_usd':
                    stats['after_reserve_net_sum_usd']/matched_selected if matched_selected else None,
            }
        return {
            'model_version': MODEL_VERSION,
            'metric': 'prospective fixed-original-quantity quoted 12–16s capture after four taker fees; no fills',
            'fee_assumption': 'Standard taker bps frozen from discovery metadata at pilot start, including published floors; nonnegative, not live fee updates',
            'horizon_seconds': self.horizon_seconds, 'deadline_seconds': self.deadline_seconds,
            'max_routes': self.max_routes, 'max_pending_per_route': MAX_PENDING_PER_ROUTE,
            'max_terminal_rows': self.max_terminal_rows,
            'max_book_age_seconds': self.max_book_age,
            'max_pair_source_and_receipt_skew_seconds': self.max_pair_skew,
            'max_route_gap_seconds': self.max_route_gap,
            'max_future_source_tolerance_seconds': .25,
            'extra_cost_bps': self.extra_cost_bps,
            'margin_fraction': self.margin_fraction,
            'capital_rate': self.capital_rate,
            'capital_time_basis': 'actual anchor-to-outcome elapsed seconds',
            'screen_thresholds_usd': list(SCREEN_THRESHOLDS_USD),
            'counts': dict(self.counts), 'censored': dict(self.censored),
            'rejections': dict(self.rejections),
            'finished': self.finished,
            'pending_anchors': sum(len(state.pending) for state in self.routes.values()),
            'per_route': {route: dict(counts) for route, counts in self.per_route.items()},
            'cohorts': {name: dict(stats) for name, stats in self.cohorts.items()},
            'selected_anchor_coverage': selected_coverage,
            'all_v2_scored_coverage': {
                'anchors': self.counts['v2_scored_anchors'],
                'matched': self.counts['matched_scored_anchors'],
                'censored': self.counts['censored_scored_anchors'],
                'pending': pending_scored,
                'matched_fraction': (self.counts['matched_scored_anchors']/
                                     self.counts['v2_scored_anchors'])
                if self.counts['v2_scored_anchors'] else None,
                'censored_fraction': (self.counts['censored_scored_anchors']/
                                      self.counts['v2_scored_anchors'])
                if self.counts['v2_scored_anchors'] else None,
                'four_fee_positive': self.counts['scored_four_fee_positive'],
                'positive_fraction_among_matched':
                    self.counts['scored_four_fee_positive']/self.counts['matched_scored_anchors']
                if self.counts['matched_scored_anchors'] else None,
                'mean_four_fee_net_usd':
                    self.sums['scored_four_fee_net_usd']/self.counts['matched_scored_anchors']
                if self.counts['matched_scored_anchors'] else None,
                'after_reserve_positive': self.counts['scored_after_reserve_positive'],
                'after_reserve_positive_fraction_among_matched':
                    self.counts['scored_after_reserve_positive']/self.counts['matched_scored_anchors']
                if self.counts['matched_scored_anchors'] else None,
                'mean_after_reserve_net_usd':
                    self.sums['scored_after_reserve_net_usd']/self.counts['matched_scored_anchors']
                if self.counts['matched_scored_anchors'] else None,
            },
            'aggregate_quote': {
                'matched_count': matched,
                'mean_four_fee_net_usd': self.sums['four_fee_net_usd']/matched if matched else None,
                'mean_after_reserve_net_usd': self.sums['after_reserve_net_usd']/matched if matched else None,
                'mean_gross_capture_usd': self.sums['gross_capture_usd']/matched if matched else None,
                'four_fee_positive_fraction': self.counts['four_fee_positive']/matched if matched else None,
                'after_reserve_positive_fraction': self.counts['after_reserve_positive']/matched if matched else None,
            },
            'terminal_rows': list(self.terminal),
            'interpretation': 'Optimistic zero-entry-latency quote screen. No delayed fill, queue, partial leg, or cash-P&L inference.',
        }
