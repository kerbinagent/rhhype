"""Causal bounded two-leg impulse-dislocation quote experiment; no orders."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import math
from statistics import median

from horizon_observer import executable_mark
from monitor import walk
from paper_fixed_markout import standard_fee_bps

VERSION = 1
MAX_PAIRS = 8
MAX_TERMINAL = 5000
WINDOW = 60.0
EMBARGO = 2.0
TARGET_USD = .25
ENTRY_DELAYS = (.5, 1.0)


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def token(book):
    return (book['generation'], book['sequence'], book['engine_time'], book['received'])


def advanced(book, previous):
    return (book['generation'] == previous[0] and
            book['sequence'] != previous[1] and
            book['engine_time'] > previous[2] and
            book['received'] > previous[3])


def mid(book):
    return (book['bids'][0][0]+book['asks'][0][0])/2


def close_bps(mark):
    return mark['closing_bps']


@dataclass
class PairState:
    history: deque = field(default_factory=lambda: deque(maxlen=60))
    side_history: dict = field(default_factory=lambda: {'hl': deque(maxlen=128), 'other': deque(maxlen=128)})
    side_token: dict = field(default_factory=dict)
    sample_tokens: tuple | None = None
    last_sample_at: float = -math.inf
    last_pair_at: float | None = None
    arm: dict | None = None
    active: dict | None = None


class ImpulseObserver:
    """One physical pair, two directions, two frozen arrival-delay scenarios."""

    def __init__(self, *, max_pairs=MAX_PAIRS, max_terminal=MAX_TERMINAL,
                 notional=1000.0, extra_cost_bps=5.0,
                 margin_fraction=1.0, capital_rate=.05):
        if (not isinstance(max_pairs, int) or not 1 <= max_pairs <= MAX_PAIRS or
                not isinstance(max_terminal, int) or not 1 <= max_terminal <= MAX_TERMINAL or
                not all(finite(x) and x >= 0 for x in
                        (notional, extra_cost_bps, margin_fraction, capital_rate)) or
                notional <= 0):
            raise ValueError('invalid impulse observer bounds')
        self.max_pairs, self.max_terminal = max_pairs, max_terminal
        self.notional = notional
        self.extra_cost_bps = extra_cost_bps
        self.margin_fraction = margin_fraction
        self.capital_rate = capital_rate
        self.states: dict[str, PairState] = {}
        self.counts = Counter()
        self.gates = Counter()
        self.censored = Counter()
        self.by_pair: dict[str, Counter] = {}
        self.by_delay = {d: Counter() for d in ENTRY_DELAYS}
        self.by_pair_direction_delay: dict[str, Counter] = {}
        self.arm_outcomes = Counter()
        self.next_candidate_id = 0
        self.rows = deque(maxlen=max_terminal)
        self.sums = Counter()
        self.finished = False

    def _metric(self, pair):
        return self.by_pair.setdefault(pair, Counter())

    def _store(self, row):
        if len(self.rows) == self.max_terminal:
            self.counts['terminal_export_dropped'] += 1
        self.rows.append(row)

    def _finish_scenario(self, pair, candidate, scenario, reason, now, **values):
        if scenario['status'] != 'pending':
            return
        scenario['status'] = 'complete' if reason is None else 'censored'
        label = 'complete' if reason is None else reason
        self.counts[f'scenario_{label}'] += 1
        self._metric(pair)[f'scenario_{label}'] += 1
        self.by_delay[scenario['delay']][f'scenario_{label}'] += 1
        pd_key = f"{pair}|{candidate['direction']}|{scenario['delay']:g}"
        self.by_pair_direction_delay[pd_key][f'scenario_{label}'] += 1
        if reason is not None:
            self.censored[reason] += 1
        row = {k: v for k, v in candidate.items() if k != 'scenarios'}
        row.update({'model_version': VERSION, 'pair': pair,
                    'delay_seconds': scenario['delay'],
                    'entry_due': scenario['entry_due'],
                    'status': scenario['status'], 'censor_reason': reason,
                    'terminal_time': now})
        row.update(values)
        if scenario.get('entry'):
            row.update(scenario['entry'])
        self._store(row)

    def _end_arm(self, state, reason):
        if state.arm is None:
            return
        self.counts['arm_terminal'] += 1
        self.arm_outcomes[reason] += 1
        state.arm = None

    def invalidate(self, pair, now, reason='feed_gap'):
        state = self.states.pop(pair, None)
        if state is None:
            return
        if state.arm is not None:
            self.gates[f'arm_{reason}'] += 1
            self._end_arm(state, reason)
        if state.active is not None:
            for scenario in state.active['scenarios']:
                self._finish_scenario(pair, state.active, scenario, reason, now)
        self.counts['invalidations'] += 1

    def finish(self, now):
        if self.finished:
            return
        for pair in list(self.states):
            self.invalidate(pair, now, 'stopped_pending')
        self.finished = True

    def _valid_pair(self, now, hl, other):
        if not finite(now):
            return 'invalid_time'
        if not hl or not other:
            return 'missing_leg'
        for book in (hl, other):
            if not book.get('valid') or not book.get('bids') or not book.get('asks'):
                return 'invalid_book'
            if any(book.get(k) is None for k in ('engine_time','received','generation','sequence')):
                return 'missing_identity'
            if not all(finite(book[side][0][0]) and finite(book[side][0][1]) and
                       book[side][0][0] > 0 and book[side][0][1] > 0
                       for side in ('bids','asks')):
                return 'invalid_top'
            if book['bids'][0][0] >= book['asks'][0][0]:
                return 'crossed'
            if not finite(book['engine_time']) or not finite(book['received']):
                return 'invalid_clock'
            if not -.25 <= now-book['engine_time'] <= 2:
                return 'source_age'
            if not -.1 <= now-book['received'] <= 2:
                return 'receipt_age'
        if abs(hl['engine_time']-other['engine_time']) > 1:
            return 'source_skew'
        if abs(hl['received']-other['received']) > 1:
            return 'receipt_skew'
        return None

    def _marks(self, pair_meta, hl, other):
        h, o = pair_meta['hl'], pair_meta['other']
        return {
            'hl_buy': executable_mark(pair_meta, h, o, hl, other, self.notional),
            'other_buy': executable_mark(pair_meta, o, h, other, hl, self.notional),
        }

    def _reference(self, state, now):
        prior = [item for item in state.history if now-WINDOW <= item['time'] <= now-EMBARGO]
        if len(prior) < 30 or prior[-1]['time']-prior[0]['time'] < 30:
            return None
        return {'basis': median(x['basis'] for x in prior),
                'hl_buy_closing': median(x['hl_buy_closing'] for x in prior),
                'other_buy_closing': median(x['other_buy_closing'] for x in prior),
                'count': len(prior), 'span': prior[-1]['time']-prior[0]['time']}

    def _hurdle(self, mark, buy_fee_bps, sell_fee_bps):
        a, b = mark['entry_value'], mark['short_entry_value']
        l, s = mark['long_liquidation_value'], mark['short_buyback_value']
        fees = ((a+l)*buy_fee_bps+(b+s)*sell_fee_bps)/10000
        reserve = max(a,b)*self.extra_cost_bps/10000
        return {'fees': fees, 'reserve': reserve,
                'bps': (fees+reserve+TARGET_USD)/a*10000}

    def _expire(self, pair, state, now):
        if state.arm and now > state.arm['time']+1:
            self.gates['arm_expired'] += 1
            self._end_arm(state, 'expired')
        candidate = state.active
        if candidate is None:
            return
        for sc in candidate['scenarios']:
            if sc['status'] != 'pending':
                continue
            if sc.get('entry') is None and now > candidate['trigger_time']+2:
                self._finish_scenario(pair, candidate, sc, 'entry_missing', now)
            elif sc.get('entry') is not None and now > candidate['trigger_time']+10:
                self._finish_scenario(pair, candidate, sc, 'exit_missing', now)
        if all(sc['status'] != 'pending' for sc in candidate['scenarios']):
            state.active = None

    def _outcomes(self, pair, state, now, hl, other):
        cand = state.active
        if cand is None:
            return
        buy, sell = ((hl, other) if cand['direction'] == 'hl_buy' else (other, hl))
        for sc in cand['scenarios']:
            if sc['status'] != 'pending':
                continue
            if sc.get('entry') is None:
                if now < sc['entry_due'] or now > cand['trigger_time']+2:
                    continue
                if not (advanced(hl, cand['confirm_hl_token']) and
                        advanced(other, cand['confirm_other_token']) and
                        hl['engine_time'] >= sc['entry_due'] and
                        other['engine_time'] >= sc['entry_due'] and
                        hl['received'] >= sc['entry_due'] and
                        other['received'] >= sc['entry_due']):
                    continue
                q = cand['quantity']
                a, b = walk(buy['asks'], q), walk(sell['bids'], q)
                if not all(finite(x) and x > 0 for x in (a,b)):
                    self._finish_scenario(pair, cand, sc, 'entry_depth', now)
                    continue
                if (a < cand['buy_min_notional'] or
                        b < cand['sell_min_notional']):
                    self._finish_scenario(pair, cand, sc, 'entry_minimum', now)
                    continue
                sc['entry'] = {'entry_time': now, 'entry_buy_value': a,
                               'entry_sell_value': b,
                               'entry_hl_source_time': hl['engine_time'],
                               'entry_other_source_time': other['engine_time'],
                               'entry_hl_received': hl['received'],
                               'entry_other_received': other['received'],
                               'entry_hl_source_delay_seconds': hl['engine_time']-sc['entry_due'],
                               'entry_other_source_delay_seconds': other['engine_time']-sc['entry_due'],
                               'entry_hl_token': token(hl),
                               'entry_other_token': token(other)}
                self.counts['paired_entry_quotes'] += 1
                self._metric(pair)['paired_entry_quotes'] += 1
                self.by_delay[sc['delay']]['paired_entry_quotes'] += 1
                pd_key = f"{pair}|{cand['direction']}|{sc['delay']:g}"
                self.by_pair_direction_delay[pd_key]['paired_entry_quotes'] += 1
            else:
                entry = sc['entry']
                exit_due = entry['entry_time']+5.5
                if now < exit_due or now > cand['trigger_time']+10:
                    continue
                if not (advanced(hl, entry['entry_hl_token']) and
                        advanced(other, entry['entry_other_token']) and
                        hl['engine_time'] >= exit_due and
                        other['engine_time'] >= exit_due and
                        hl['received'] >= exit_due and
                        other['received'] >= exit_due):
                    continue
                q = cand['quantity']
                l, s = walk(buy['bids'], q), walk(sell['asks'], q)
                if not all(finite(x) and x > 0 for x in (l,s)):
                    self._finish_scenario(pair, cand, sc, 'exit_depth', now)
                    continue
                if (l < cand['buy_min_notional'] or
                        s < cand['sell_min_notional']):
                    self._finish_scenario(pair, cand, sc, 'exit_minimum', now)
                    continue
                if int(entry['entry_time']//3600) != int(now//3600):
                    self._finish_scenario(pair, cand, sc, 'funding_unknown', now)
                    continue
                a, b = entry['entry_buy_value'], entry['entry_sell_value']
                bf, sf = cand['buy_fee_bps']/10000, cand['sell_fee_bps']/10000
                fees = {'buy_entry_fee': a*bf, 'sell_entry_fee': b*sf,
                        'buy_exit_fee': l*bf, 'sell_exit_fee': s*sf}
                gross = b-a+l-s
                reserve = max(a,b)*self.extra_cost_bps/10000
                capital = ((a+b)*self.margin_fraction*self.capital_rate*
                           (now-entry['entry_time'])/(365*86400))
                net = gross-sum(fees.values())-reserve-capital
                self.sums['net_after_reserve_usd'] += net
                if net > 0:
                    self.counts['positive_quote_outcomes'] += 1
                self._finish_scenario(pair, cand, sc, None, now,
                    exit_time=now, exit_due=exit_due,
                    exit_hl_source_time=hl['engine_time'],
                    exit_other_source_time=other['engine_time'],
                    exit_hl_received=hl['received'],
                    exit_other_received=other['received'],
                    exit_hl_source_delay_seconds=hl['engine_time']-exit_due,
                    exit_other_source_delay_seconds=other['engine_time']-exit_due,
                    entry_observed_delay_seconds=entry['entry_time']-cand['trigger_time'],
                    exit_observed_delay_seconds=now-exit_due,
                    exit_long_value=l, exit_short_buyback_value=s,
                    gross_capture_usd=gross, **fees, four_fees_usd=sum(fees.values()),
                    reserve_usd=reserve, capital_usd=capital,
                    net_after_reserve_usd=net)
        if all(sc['status'] != 'pending' for sc in cand['scenarios']):
            state.active = None

    def on_event(self, pair, now, hl, other, changed_side, pair_meta):
        """Process one newly received venue book; return only diagnostic state."""
        if self.finished:
            return False
        if not finite(now) or changed_side not in ('hl','other'):
            self.gates['invalid_event'] += 1
            return False
        state = self.states.get(pair)
        if state is None:
            if len(self.states) >= self.max_pairs:
                self.gates['pair_cap'] += 1
                return False
            state = PairState()
            self.states[pair] = state
        self._expire(pair, state, now)
        reason = self._valid_pair(now, hl, other)
        if reason:
            self.gates[reason] += 1
            return False
        if state.last_pair_at is not None and now-state.last_pair_at > 30:
            self.invalidate(pair, now, 'feed_gap')
            state = PairState()
            self.states[pair] = state
        for side, book in (('hl',hl),('other',other)):
            prev = state.side_token.get(side)
            if prev is not None and book['generation'] != prev[0]:
                self.invalidate(pair, now, 'generation_changed')
                state = PairState()
                self.states[pair] = state
                break
            if prev is not None and (book['engine_time'] < prev[2] or
                                     book['received'] < prev[3]):
                self.gates['clock_regression'] += 1
                return False
        state.last_pair_at = now
        changed_advanced = False
        for side, book in (('hl',hl),('other',other)):
            prev = state.side_token.get(side)
            if prev is not None and not advanced(book, prev):
                continue
            state.side_token[side] = token(book)
            hist = state.side_history[side]
            hist.append((book['received'], mid(book)))
            while hist and hist[0][0] < now-1:
                hist.popleft()
            if side == changed_side:
                changed_advanced = True
        if not changed_advanced:
            self.gates['source_not_advanced'] += 1
            return False
        self.counts['valid_events'] += 1
        self._outcomes(pair, state, now, hl, other)
        basis = (mid(hl)-mid(other))/mid(other)*10000
        if state.active is not None:
            self.gates['active_suppressed'] += 1
        elif state.arm is not None:
            arm = state.arm
            if changed_side != arm['impulse_side'] and now <= arm['time']+1 and (
                    state.side_token[changed_side][2] > arm['other_source'] and
                    state.side_token[changed_side][3] > arm['time']):
                marks = self._marks(pair_meta, hl, other)
                direction = arm['direction']
                mark = marks[direction]
                if mark is None:
                    self.gates['confirm_depth'] += 1
                    self._end_arm(state, 'confirm_depth')
                else:
                    buy_meta = pair_meta['hl'] if direction == 'hl_buy' else pair_meta['other']
                    sell_meta = pair_meta['other'] if direction == 'hl_buy' else pair_meta['hl']
                    bf, sf = standard_fee_bps(buy_meta), standard_fee_bps(sell_meta)
                    hurdle = self._hurdle(mark, bf, sf)
                    deviation = basis-arm['reference']['basis']
                    anticipated = (mark['short_entry_value']-mark['entry_value']-
                        arm['reference'][direction+'_closing']*mark['entry_value']/10000-
                        hurdle['fees']-hurdle['reserve'])
                    if deviation*arm['basis_sign'] <= 0 or abs(deviation) < hurdle['bps']:
                        self.gates['confirm_basis'] += 1
                        self._end_arm(state, 'confirm_basis')
                    elif anticipated < TARGET_USD:
                        self.gates['confirm_closing_sanity'] += 1
                        self._end_arm(state, 'confirm_closing_sanity')
                    else:
                        self.next_candidate_id += 1
                        candidate = {'trigger_time': arm['time'], 'confirmation_time': now,
                            'candidate_id': f'{pair}#{self.next_candidate_id}',
                            'direction': direction, 'quantity': mark['quantity'],
                            'basis_bps': basis, 'prior_basis_bps': arm['reference']['basis'],
                            'prior_closing_bps': arm['reference'][direction+'_closing'],
                            'hurdle_bps': hurdle['bps'], 'anticipated_capture_usd': anticipated,
                            'impulse_side': arm['impulse_side'], 'impulse_bps': arm['impulse_bps'],
                            'buy_fee_bps': bf, 'sell_fee_bps': sf,
                            'buy_min_notional': buy_meta.get('min_notional',0),
                            'sell_min_notional': sell_meta.get('min_notional',0),
                            'confirm_hl_token': token(hl), 'confirm_other_token': token(other),
                            'scenarios': [{'delay': d, 'entry_due': now+d,
                                           'status': 'pending'} for d in ENTRY_DELAYS]}
                        state.active = candidate
                        self.counts['confirmed_candidates'] += 1
                        self._metric(pair)['confirmed_candidates'] += 1
                        for sc in candidate['scenarios']:
                            self.by_delay[sc['delay']]['candidates'] += 1
                            pd_key = f"{pair}|{direction}|{sc['delay']:g}"
                            self.by_pair_direction_delay.setdefault(pd_key, Counter())['candidates'] += 1
                        self._end_arm(state, 'confirmed')
            else:
                self.gates['waiting_opposing_update'] += 1
        else:
            reference = self._reference(state, now)
            if reference is None:
                self.gates['history_warmup'] += 1
            else:
                own = state.side_history[changed_side]
                other_side = 'other' if changed_side == 'hl' else 'hl'
                peer = state.side_history[other_side]
                for hist in (own, peer):
                    while hist and hist[0][0] < now-1:
                        hist.popleft()
                if (len(own) < 2 or len(peer) < 2 or
                        own[-1][0]-own[0][0] < .5 or
                        peer[-1][0]-peer[0][0] < .5):
                    self.gates['impulse_history_short'] += 1
                else:
                    own_delta = (own[-1][1]-own[0][1])/own[0][1]*10000
                    peer_delta = (peer[-1][1]-peer[0][1])/peer[0][1]*10000
                    deviation = basis-reference['basis']
                    basis_sign = 1 if deviation > 0 else -1
                    direction = 'other_buy' if basis_sign > 0 else 'hl_buy'
                    mark = self._marks(pair_meta, hl, other)[direction]
                    if mark is None:
                        self.gates['trigger_depth'] += 1
                    else:
                        buy_meta = pair_meta['other'] if direction == 'other_buy' else pair_meta['hl']
                        sell_meta = pair_meta['hl'] if direction == 'other_buy' else pair_meta['other']
                        hurdle = self._hurdle(mark, standard_fee_bps(buy_meta),
                                              standard_fee_bps(sell_meta))
                        impulse_basis_sign = 1 if (own_delta > 0) == (changed_side == 'hl') else -1
                        if abs(own_delta) < hurdle['bps']/2:
                            self.gates['impulse_small'] += 1
                        elif abs(peer_delta) > abs(own_delta)*.25:
                            self.gates['other_moved'] += 1
                        elif basis_sign != impulse_basis_sign:
                            self.gates['impulse_wrong_sign'] += 1
                        else:
                            state.arm = {'time': now, 'impulse_side': changed_side,
                                'other_source': state.side_token[other_side][2],
                                'reference': reference, 'direction': direction,
                                'basis_sign': basis_sign, 'impulse_bps': own_delta}
                            self.counts['armed'] += 1
                            self._metric(pair)['armed'] += 1
        # The current quote is appended only after every decision above.
        if (now-state.last_sample_at >= 1 and len(state.side_token) == 2 and
                (state.sample_tokens is None or
                 (advanced(hl, state.sample_tokens[0]) and
                  advanced(other, state.sample_tokens[1])))):
            marks = self._marks(pair_meta, hl, other)
            if all(marks.values()):
                state.history.append({'time': now, 'basis': basis,
                    'hl_buy_closing': close_bps(marks['hl_buy']),
                    'other_buy_closing': close_bps(marks['other_buy'])})
                state.sample_tokens = (token(hl), token(other))
                state.last_sample_at = now
                while state.history and state.history[0]['time'] < now-WINDOW:
                    state.history.popleft()
                self.counts['history_samples'] += 1
        return True

    def snapshot(self, now):
        if not self.finished and finite(now):
            for pair, state in list(self.states.items()):
                self._expire(pair, state, now)
                if state.last_pair_at is not None and now-state.last_pair_at > 30:
                    self.invalidate(pair, now, 'stale')
        done = self.counts['scenario_complete']
        return {'model_version': VERSION,
            'metric': 'same-asset paired impulse-dislocation quote, no fills',
            'max_pairs': self.max_pairs, 'max_terminal_rows': self.max_terminal,
            'history_window_seconds': WINDOW, 'history_embargo_seconds': EMBARGO,
            'entry_delays_seconds': list(ENTRY_DELAYS), 'entry_deadline_seconds': 2,
            'entry_delay_origin': 'opposing-venue confirmation time',
            'paired_quote_clock_rule': 'both source and receipt timestamps at or after each due time; source future tolerance 0.25s and receipt future tolerance 0.1s against local UTC now',
            'exit_request_after_entry_seconds': 5, 'exit_observation_delay_seconds': .5,
            'hard_trigger_to_exit_seconds': 10, 'target_usd': TARGET_USD,
            'extra_cost_bps': self.extra_cost_bps,
            'rh_usdg_usdc_assumption': 'parity quote screen only; no conversion or collateral claim',
            'fee_assumption': 'Standard taker rates frozen from discovery metadata; four fees per complete quote',
            'comparison_control': 'same frozen candidates at 0.5s and 1s only; no no-impulse control in v1',
            'counts': dict(self.counts), 'gates': dict(self.gates),
            'censored': dict(self.censored),
            'by_pair': {k:dict(v) for k,v in self.by_pair.items()},
            'by_delay': {str(k):dict(v) for k,v in self.by_delay.items()},
            'by_pair_direction_delay': {k:dict(v) for k,v in self.by_pair_direction_delay.items()},
            'arm_outcomes': dict(self.arm_outcomes),
            'pending_arms': sum(s.arm is not None for s in self.states.values()),
            'pending_scenarios': sum(sc['status']=='pending' for s in self.states.values()
                                     if s.active for sc in s.active['scenarios']),
            'mean_complete_net_after_reserve_usd':
                self.sums['net_after_reserve_usd']/done if done else None,
            'terminal_rows': list(self.rows), 'finished': self.finished,
            'interpretation': 'Prospective paired quotes only; no execution, paired-fill, funding-cash, or profit inference.'}
