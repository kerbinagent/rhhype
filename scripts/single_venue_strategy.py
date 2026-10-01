"""Receipt-ordered single-position paper hypotheses. No network or order API.

Each (rule, venue) is an independent counterfactual portfolio, never additive.
Book-conditioned IOC outcomes are conditional models, not authenticated fills.
"""
from collections import Counter, deque
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
from statistics import median
import math

NS = 10**9
VENUES = ('lighter', 'rh_lighter')
RULES = ('gap_fade', 'leader_follow', 'local_shock_fade')
PARAMS = dict(pair_skew_ms=250, book_age_seconds=2, reference_seconds=120,
              reference_embargo_seconds=2, reference_min_count=60,
              reference_min_span_seconds=89, signal_interval_seconds=1,
              admission_start_seconds=122, admission_stop_seconds=480,
              budget=100, sizing_headroom_fraction=.01, initial_cash=600,
              delay_ms=400, confirmation_timeout_seconds=2,
              entry_limit_bps=1, exit_limit_bps=10, max_exit_attempts=3,
              hold_seconds=10, cooldown_seconds=30, max_attempts=20,
              gap_min_bps=5, other_gap_min_bps=3, forecast_buffer_bps=2,
              leader_min_move_bps=3, target_max_leader_fraction=.5,
              shock_min_local_move_bps=2, shock_max_reference_move_bps=1,
              shock_flow_multiple=5, shock_imbalance=.8,
              shock_depth_fraction=.25, shock_depth_band_bps=5,
              shock_min_baseline_bins=20, shock_min_baseline_span_seconds=60,
              capital_rate=.05, stress_bps=5, funding_guard_seconds=120)


def dec(x):
    return D(str(x))


def fresh(b, now):
    return bool(b and b.get('clock_valid') and b.get('valid')
                and 0 <= now-b['received_ns'] <= 2*NS
                and 0 <= now-b['source_ns'] <= 2*NS
                and b['source_ns'] <= b['received_ns']
                and b['bids'] and b['asks'] and b['bids'][0][0] < b['asks'][0][0])


def pair_fresh(books, now):
    return (all(fresh(books.get(v), now) for v in VENUES)
            and abs(books[VENUES[0]]['source_ns']-books[VENUES[1]]['source_ns']) <= 250_000_000
            and abs(books[VENUES[0]]['received_ns']-books[VENUES[1]]['received_ns']) <= 250_000_000)


def mid(b):
    return (float(b['bids'][0][0])+float(b['asks'][0][0]))/2


def rounded(x, step, up=False):
    return (dec(x)/dec(step)).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*dec(step)


def walk_ioc(book, side, quantity, limit):
    """Consume displayed depth only through the fixed native limit; partials survive."""
    left, value, fills = dec(quantity), D(0), []
    for px, qty in book['asks' if side == 1 else 'bids']:
        px, qty = dec(px), dec(qty)
        if (side == 1 and px > limit) or (side == -1 and px < limit):
            break
        take = min(left, qty)
        if take > 0:
            fills.append({'price': str(px), 'quantity': str(take)})
            left -= take
            value += take*px
        if left == 0:
            break
    return dec(quantity)-left, value, fills


def snapshot(book):
    return {k: book[k] for k in ('venue', 'market', 'received_ns', 'source_ns', 'generation', 'sequence', 'bids', 'asks')}


class Features:
    def __init__(self):
        self.books = {}
        self.points = deque(maxlen=1400)
        self.refs = deque(maxlen=125)
        self.flows = {v: {} for v in VENUES}
        self.last_point = self.last_ref = self.last_signal = None
        self.counts = Counter()

    def process(self, event):
        kind, now = event['type'], event['received_ns']
        if kind == 'invalidate':
            self.books.pop(event['venue'], None)
            self.points.clear(); self.refs.clear()
            self.flows = {v: {} for v in VENUES}
            self.last_point = self.last_ref = self.last_signal = None
            self.counts['invalidations'] += 1
            return []
        if kind == 'trade':
            v = event['venue']
            self.counts['ordinary_trades:'+v] += 1
            if not 0 <= now-event['source_ns'] <= 2*NS:
                self.counts['old_trade'] += 1
                return []
            bucket = now//NS
            flow = self.flows[v].setdefault(bucket, dict(notional=0., buy_qty=0., sell_qty=0.,
                min_source=event['source_ns'], max_source=event['source_ns'], count=0))
            qty = float(event['qty'])
            flow['notional'] += qty*float(event['price'])
            flow['buy_qty' if event['buy_aggressor'] else 'sell_qty'] += qty
            flow['min_source'] = min(flow['min_source'], event['source_ns'])
            flow['max_source'] = max(flow['max_source'], event['source_ns'])
            flow['count'] += 1
            for old in list(self.flows[v]):
                if old < bucket-125:
                    del self.flows[v][old]
            return []
        if kind != 'book':
            return []
        self.books[event['venue']] = event
        if not pair_fresh(self.books, now):
            self.counts['nonfresh_pair_callbacks'] += 1
            return []
        mids = {v: mid(self.books[v]) for v in VENUES}
        basis = 10000*math.log(mids['lighter']/mids['rh_lighter'])
        if self.last_point is None or now-self.last_point >= 100_000_000:
            point = {'t': now, 'mids': mids, 'sources': {v:self.books[v]['source_ns'] for v in VENUES}, 'depth': {}}
            for v in VENUES:
                b = self.books[v]
                point['depth'][v] = {
                    'buy': sum(float(q) for p,q in b['asks'] if float(p) <= float(b['asks'][0][0])*1.0005),
                    'sell': sum(float(q) for p,q in b['bids'] if float(p) >= float(b['bids'][0][0])*.9995)}
            self.points.append(point); self.last_point = now
        if self.last_ref is None or now-self.last_ref >= NS:
            self.refs.append((now,basis)); self.last_ref = now
        if self.last_signal is not None and now-self.last_signal < NS:
            return []
        self.last_signal = now
        refs = [(t,x) for t,x in self.refs if now-122*NS <= t <= now-2*NS]
        if len(refs) < 60 or refs[-1][0]-refs[0][0] < 89*NS:
            self.counts['reference_warmup'] += 1
            return []
        reference = median(x for _,x in refs)
        previous = next((p for p in reversed(self.points) if p['t'] <= now-NS), None)
        if previous is not None and now-NS-previous['t'] > 250_000_000:
            previous = None
        candidates = []
        for v in VENUES:
            other = VENUES[1] if v == VENUES[0] else VENUES[0]
            residual = (basis-reference)*(1 if v == 'lighter' else -1)
            direction = -1 if residual > 0 else 1
            b = self.books[v]
            spread = (float(b['asks'][0][0])-float(b['bids'][0][0]))/mids[v]*10000
            moves = ({k:10000*math.log(mids[k]/previous['mids'][k]) for k in VENUES}
                     if previous else None)
            evidence = dict(t=now, venue=v, direction=direction, residual_bps=residual,
                reference_bps=reference, basis_bps=basis, reference_rows=refs,
                roundtrip_spread_bps=spread, moves_1s_bps=moves,
                feature_clock='local receipt time; source clocks also checked')
            # Full residual recovery is an explicit uncalibrated signal hypothesis.
            cost_gate = abs(residual) >= spread+2+PARAMS['forecast_buffer_bps']
            gap = cost_gate and abs(residual) >= 5
            leader = bool(cost_gate and abs(residual) >= 3 and moves
                and direction*moves[other] >= 3
                and direction*moves[v] <= .5*direction*moves[other])
            bucket = now//NS-1
            flow = self.flows[v].get(bucket)
            if flow:
                self.counts['shock:flow_bucket_present:'+v] += 1
            baseline = [(k,f['notional']) for k,f in self.flows[v].items() if now//NS-122 <= k <= bucket-2]
            baseline.sort()
            pre = next((p for p in reversed(self.points) if p['t'] <= bucket*NS), None)
            shock = False
            shock_detail = {'completed_receipt_second':bucket, 'flow':flow,
                            'baseline_nonempty_bins':len(baseline), 'pre':pre}
            if flow and pre and len(baseline) >= 20 and baseline[-1][0]-baseline[0][0] >= 60:
                self.counts['shock:baseline_ready:'+v] += 1
                total_qty = flow['buy_qty']+flow['sell_qty']
                imbalance = (flow['buy_qty']-flow['sell_qty'])/total_qty if total_qty else 0
                sign = 1 if imbalance > 0 else -1
                local_move = 10000*math.log(mids[v]/pre['mids'][v])
                reference_move = 10000*math.log(mids[other]/pre['mids'][other])
                depth = pre['depth'][v]['buy' if sign == 1 else 'sell']
                dominant = flow['buy_qty' if sign == 1 else 'sell_qty']
                typical = median(x for _,x in baseline)
                shock_detail.update(baseline_rows=baseline, baseline_median=typical,
                    imbalance=imbalance, local_move_bps=local_move, reference_move_bps=reference_move,
                    dominant_quantity=dominant, pre_depth_quantity=depth)
                causal_pre = (0 <= bucket*NS-pre['t'] <= 250_000_000
                              and all(pre['sources'][k] <= flow['min_source'] for k in VENUES))
                post = b['source_ns'] >= flow['max_source']
                for gate, passed in (
                    ('pre_and_post_clock',causal_pre and post),
                    ('large_flow',flow['notional'] >= 5*typical),
                    ('depth_fraction',depth > 0 and dominant >= .25*depth),
                    ('local_move',sign*local_move >= 2),
                    ('reference_stable',abs(reference_move) <= 1)):
                    if passed:self.counts['shock:'+gate+':'+v] += 1
                shock = bool(cost_gate and abs(residual) >= 3 and direction == -sign
                    and causal_pre and post and abs(imbalance) >= .8
                    and flow['notional'] >= 5*typical and depth > 0 and dominant >= .25*depth
                    and sign*local_move >= 2 and abs(reference_move) <= 1)
            for rule, passes in zip(RULES, (gap, leader, shock)):
                self.counts[rule+':evaluated:'+v] += 1
                if passes:
                    self.counts[rule+':signal:'+v] += 1
                    candidates.append(dict(evidence, rule=rule, shock=shock_detail if rule == RULES[2] else None))
        return candidates


class Portfolio:
    def __init__(self, rule, venue, market, start, emit):
        self.rule, self.venue, self.market, self.start, self.emit = rule, venue, market, start, emit
        self.label = rule+':'+venue
        self.cash = D(600)
        self.position = None
        self.pending = None
        self.unknown = None
        self.attempts = 0
        self.last_flat = -10**30
        self.episodes = []
        self.counts = Counter()

    def log(self, kind, **data):
        self.emit({'arm':self.label, 'kind':kind, **data})

    def fail(self, reason, now):
        if self.unknown is None:
            self.unknown = reason
            self.log('unknown', reason=reason, t=now, pending=self.pending, position=self.position)

    def minimum(self, qty, price):
        return (qty >= dec(self.market['min_qty']) and qty*price >= dec(self.market['min_notional'])
                and qty % dec(self.market['qty_step']) == 0)

    def submit(self, action, side, qty, book, now):
        tick = self.market['price_tick']
        bps = 1 if action == 'entry' else 10
        best = dec(book['asks' if side == 1 else 'bids'][0][0])
        limit = rounded(best*(1+dec(side*bps)/10000), tick, up=side == 1)
        if not self.minimum(qty, limit):
            if action == 'exit':
                self.fail('exit_below_published_minimum', now)
            return False
        self.pending = dict(action=action, side=side, quantity=str(qty), limit=str(limit),
            request_ns=now, due_ns=now+400_000_000, generation=book['generation'])
        self.log('request', order=dict(self.pending), book=snapshot(book))
        return True

    def admit(self, signal, book, now):
        reason = None
        if self.unknown or self.pending or self.position:
            reason = 'occupied_or_unknown'
        elif not 122*NS <= now-self.start < 480*NS:
            reason = 'outside_window'
        elif now-self.last_flat < 30*NS:
            reason = 'cooldown'
        elif self.attempts >= 20:
            reason = 'attempt_cap'
        elif now//(3600*NS) != (now+120*NS)//(3600*NS):
            reason = 'funding_guard'
        if reason:
            self.counts[reason] += 1
            return
        qty = rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')), self.market['qty_step'])
        if not self.minimum(qty, dec(book['bids'][0][0])):
            self.counts['entry_minimum'] += 1
            return
        if self.cash < D(100):
            self.counts['cash_shortfall'] += 1
            return
        self.log('signal', signal=signal)
        if self.submit('entry', signal['direction'], qty, book, now):
            self.attempts += 1

    def process(self, event):
        now, kind = event['received_ns'], event['type']
        if self.unknown:
            return
        if self.pending and now > self.pending['due_ns']+2*NS:
            self.fail('order_confirmation_timeout', now)
            return
        if kind == 'end':
            if self.position or self.pending:
                self.fail('capture_ended_with_obligation', now)
            return
        if event.get('venue') != self.venue:
            return
        if kind == 'invalidate':
            if event.get('scope') == 'book' and (self.position or self.pending):
                self.fail('execution_book_invalidated', now)
            return
        if kind != 'book' or not fresh(event, now):
            return
        order = self.pending
        if order and now >= order['due_ns'] and event['source_ns'] >= order['due_ns']:
            if event['generation'] != order['generation']:
                self.fail('order_generation_changed', now)
                return
            qty,value,fills = walk_ioc(event, order['side'], dec(order['quantity']), dec(order['limit']))
            fee = value*dec(self.market['taker_fee_bps'])/10000
            self.log('ioc', order=order, t=now, book=snapshot(event),
                     quantity=str(qty), value=str(value), fee=str(fee), fills=fills)
            self.pending = None
            if order['action'] == 'entry':
                if qty == 0:
                    self.counts['entry_no_fill'] += 1
                    self.last_flat = now
                    return
                self.cash -= fee
                self.position = dict(side=order['side'], quantity=str(qty), remaining=str(qty),
                    entry_value=str(value), entry_fee=str(fee), entry_ns=now, exit_attempts=0,
                    exit_value='0', exit_fee='0', capital='0', gross='0', marks_min=None, marks_max=None)
                if value > D(100):
                    self.fail('actual_entry_notional_above_100', now)
                    return
            else:
                p = self.position
                p['exit_attempts'] += 1
                entry_alloc = dec(p['entry_value'])*qty/dec(p['quantity'])
                gross = p['side']*(value-entry_alloc)
                capital = entry_alloc*D('.05')*dec(now-p['entry_ns'])/D(NS*365*86400)
                self.cash += gross-fee-capital
                for field, addition in (('exit_value',value),('exit_fee',fee),('capital',capital),('gross',gross)):
                    p[field] = str(dec(p[field])+addition)
                p['remaining'] = str(dec(p['remaining'])-qty)
                if dec(p['remaining']) == 0:
                    p['exit_ns'] = now
                    p['cash_after_fees'] = str(dec(p['gross'])-dec(p['entry_fee'])-dec(p['exit_fee']))
                    p['cash_after_capital'] = str(dec(p['cash_after_fees'])-dec(p['capital']))
                    p['stress'] = str(dec(p['entry_value'])*D('.0005'))
                    p['stressed_net'] = str(dec(p['cash_after_capital'])-dec(p['stress']))
                    if p['entry_ns']//(3600*NS) != now//(3600*NS):
                        self.fail('funding_crossing', now)
                        return
                    self.log('closed', episode=p.copy(), cash=str(self.cash))
                    self.episodes.append(p.copy()); self.position = None; self.last_flat = now
                elif p['exit_attempts'] >= 3:
                    self.fail('exit_attempt_cap_with_residual', now)
                    return
        if self.position and not self.pending and not self.unknown:
            p = self.position
            mark_qty, mark_value, _ = walk_ioc(event, -p['side'], dec(p['remaining']),
                D('1e30') if p['side'] == -1 else D(0))
            if mark_qty == dec(p['remaining']):
                entry_part = dec(p['entry_value'])*mark_qty/dec(p['quantity'])
                mark = (dec(p['gross'])+p['side']*(mark_value-entry_part)-dec(p['entry_fee'])
                        -dec(p['exit_fee'])-mark_value*dec(self.market['taker_fee_bps'])/10000)
                p['marks_min'] = str(min(mark,dec(p['marks_min']))) if p['marks_min'] is not None else str(mark)
                p['marks_max'] = str(max(mark,dec(p['marks_max']))) if p['marks_max'] is not None else str(mark)
            if now-p['entry_ns'] >= 10*NS:
                self.submit('exit', -p['side'], dec(p['remaining']), event, now)

    def summary(self):
        return dict(attempts=self.attempts, closed=len(self.episodes), counts=dict(self.counts),
                    cash=str(self.cash), unknown=self.unknown, pending=self.pending,
                    position=self.position, episodes=self.episodes,
                    complete=self.unknown is None and self.pending is None and self.position is None)


class Study:
    def __init__(self, metadata, start, emit):
        self.features = Features()
        self.arms = {(r,v):Portfolio(r,v,metadata[v]['LIT'],start,emit) for r in RULES for v in VENUES}
        self.probes = []
        self.generation = 0

    def process(self, event):
        for arm in self.arms.values():
            arm.process(event)
        if event['type'] == 'invalidate':
            self.generation += 1
        signals = self.features.process(event)
        now = event['received_ns']
        if event['type'] == 'book' and pair_fresh(self.features.books,now):
            for probe in self.probes:
                for h in (1,5,10,30):
                    if str(h) in probe['horizons'] or now < probe['t']+h*NS:
                        continue
                    if self.generation != probe['generation']:
                        row = {'status':'invalidation_crossing'}
                    elif now-probe['t']-h*NS > 250_000_000:
                        row = {'status':'missing_fresh_pair_in_250ms'}
                    else:
                        returns = {v:10000*math.log(mid(self.features.books[v])/probe['mids'][v]) for v in VENUES}
                        target = probe['venue'];other = VENUES[1] if target == VENUES[0] else VENUES[0]
                        row = dict(status='matched', t=now, returns_bps=returns,
                            favorable_target_return_bps=probe['direction']*returns[target],
                            favorable_reference_return_bps=probe['direction']*returns[other],
                            favorable_relative_return_bps=probe['direction']*(returns[target]-returns[other]))
                    probe['horizons'][str(h)] = row
        for signal in signals:
            arm = self.arms[signal['rule'],signal['venue']]
            before = arm.attempts
            arm.admit(signal,self.features.books[signal['venue']],signal['t'])
            if arm.attempts > before:
                self.probes.append(dict(t=signal['t'], venue=signal['venue'], rule=signal['rule'],
                    direction=signal['direction'], generation=self.generation,
                    mids={v:mid(self.features.books[v]) for v in VENUES}, horizons={}))

    def summary(self):
        for p in self.probes:
            for h in (1,5,10,30):
                p['horizons'].setdefault(str(h), {'status':'capture_ended_before_match'})
        return {'feature_counts':dict(self.features.counts), 'arms':{a.label:a.summary() for a in self.arms.values()},
                'admission_return_probes':self.probes}
