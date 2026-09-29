"""Isolated, WebSocket-only paper comparison of simultaneous and HL-first entry.

Both policies reuse PaperEngine's order observation, partial fill, fee, exit,
and funding accounting. No exchange order endpoints are used.
"""
from __future__ import annotations

from collections import Counter, deque
import copy
import math

from paper_engine import PaperEngine, EngineConfig, valid_book, taker_delay
from paper_strategies import StrategySelector


MAX_COHORT_ROWS = 500
MAX_COHORTS = 128
OTHER_BOOK_WAIT_SECONDS = 2.0


def unmatched_exposure(position):
    """Clock and original-q-equivalent seconds with unequal filled legs."""
    def unknown(reason):
        return {'one_leg_clock_seconds':None,
                'unmatched_equivalent_seconds':None,
                'exposure_metric_status':reason}

    original=position.get('signal',{}).get('quantity')
    if (not isinstance(original,(int,float)) or isinstance(original,bool) or
            not math.isfinite(original) or original<=0):
        return unknown('invalid_original_quantity')
    if position.get('funding_history_truncated'):
        return unknown('truncated_exit_history')
    if len(position.get('legs',[]))!=2:
        return unknown('missing_legs')
    events=[]
    for leg in position.get('legs',[]):
        side='hl' if leg.get('venue')=='hyperliquid' else 'peer'
        quantity=leg.get('quantity',0)
        if (not isinstance(quantity,(int,float)) or isinstance(quantity,bool) or
                not math.isfinite(quantity) or quantity<0):
            return unknown('invalid_entry_quantity')
        entered=leg.get('entry_time')
        if quantity>0:
            if not isinstance(entered,(int,float)) or not math.isfinite(entered):
                return unknown('missing_entry_time')
            events.append((float(entered),side,float(quantity)))
        exited=0.0
        fills=leg.get('exit_fills',[])
        if not isinstance(fills,list):
            return unknown('invalid_exit_history')
        for fill in fills:
            ts,q=fill.get('timestamp'),fill.get('quantity')
            if (not isinstance(ts,(int,float)) or isinstance(ts,bool) or not math.isfinite(ts) or
                    not isinstance(q,(int,float)) or isinstance(q,bool) or
                    not math.isfinite(q) or q<=0 or entered is None or ts<entered):
                return unknown('invalid_exit_fill')
            exited+=q
            events.append((float(ts),side,-float(q)))
        if exited>quantity+max(1e-9,quantity*1e-9):
            return unknown('exit_exceeds_entry')
        if position.get('status') in ('CLOSED','CLOSED_ESTIMATED') and (
                quantity-exited>max(1e-9,quantity*1e-9)):
            return unknown('missing_exit_fill')
    events.sort(key=lambda x:x[0])
    quantities={'hl':0.0,'peer':0.0}
    last=None;clock=0.0;equivalent=0.0
    for ts,side,delta in events:
        if last is not None and ts>last:
            imbalance=abs(quantities['hl']-quantities['peer'])
            if imbalance>1e-9:clock+=ts-last
            equivalent+=imbalance/original*(ts-last)
        quantities[side]+=delta
        last=ts
    return {'one_leg_clock_seconds':clock,
            'unmatched_equivalent_seconds':equivalent,
            'exposure_metric_status':'complete'}


def trial_config(base=None):
    """Keep published baseline execution parameters; freeze only study settings."""
    config = copy.deepcopy(base or EngineConfig())
    config.strategies = ('convergence',)
    config.holding_seconds = 10.0
    config.take_profit_usd = .10
    config.latency_probes_ms = ()
    return config


class HLFirstEngine(PaperEngine):
    """PaperEngine with the opposite entry intent paused until full HL fill."""

    def __init__(self, pairs, config=None, state=None, now=None):
        self.contingent_counts = Counter()
        super().__init__(pairs, trial_config(config), state=state, now=now)
        self.episode_history = deque(self.episode_history,maxlen=200)
        if state is None:
            # PaperStore keys trades by position ID. Distinguish the two
            # independent engines without altering PaperEngine's ID format.
            self.sequence = 1_000_000_000

    def _maybe_enter(self, pair, ident, signal, strategy, now):
        # tick() is retained for exits/timeouts, but only the control's chosen
        # candidate may inject an entry into this independent engine.
        return

    def accept_candidate(self, pair, ident, signal, cohort_id, now):
        before = set(self.positions)
        PaperEngine._maybe_enter(self, pair, ident, copy.deepcopy(signal), 'convergence', now)
        created = set(self.positions) - before
        if not created:
            self.contingent_counts['admission_rejected'] += 1
            return None
        position = self.positions[created.pop()]
        hl = next(leg for leg in position['legs'] if leg['venue'] == 'hyperliquid')
        peer = next(leg for leg in position['legs'] if leg['venue'] != 'hyperliquid')
        original_peer = copy.deepcopy(peer['intent'])
        peer['intent'] = None
        position['cohort_id'] = cohort_id
        position['trial_policy'] = 'hl_first'
        position['contingent'] = {'phase': 'hl_pending', 'hl_key': hl['key'],
                                  'peer_key': peer['key'], 'original_quantity': signal['quantity'],
                                  'peer_original_intent': original_peer,
                                  'first_fill_time': None, 'peer_book_deadline': None}
        self.transitions[-1] = copy.deepcopy(position)
        self.contingent_counts['admitted'] += 1
        return position['id']

    def _peer_intent(self, position, now):
        info = position['contingent']
        peer = next(leg for leg in position['legs'] if leg['key'] == info['peer_key'])
        book = self.books.get(peer['key'])
        if not valid_book(book, now, self.config) or book.get('generation') is None:
            return False
        frozen = info['peer_original_intent']
        delay = taker_delay(peer, 'convergence', self.config)
        peer['intent'] = {'kind': 'entry', 'quantity': info['original_quantity'],
                          'created': now, 'due': now + delay,
                          'expires': now + delay + self.config.fill_timeout_seconds,
                          'generation': book['generation'],
                          'price_limit': frozen['price_limit']}
        info['phase'] = 'peer_pending'
        info['peer_sent_at'] = now
        self.contingent_counts['peer_sent'] += 1
        self.transitions.append(copy.deepcopy(position))
        return True

    def _transition(self, position, now):
        info = position.get('contingent')
        if not info or position['status'] != 'ENTRY_PENDING':
            return super()._transition(position, now)
        hl = next(leg for leg in position['legs'] if leg['key'] == info['hl_key'])
        peer = next(leg for leg in position['legs'] if leg['key'] == info['peer_key'])
        phase = info['phase']
        if phase == 'hl_pending':
            if hl['entry_result'] is None:
                return
            q = hl['quantity']
            full = hl['entry_result'] == 'filled' and q >= info['original_quantity'] - 1e-9
            if not full:
                info['phase'] = 'hl_failed'
                info['hl_first_result'] = hl['entry_result']
                peer['entry_result'] = 'not_sent_hl_first'
                self.contingent_counts['hl_partial' if q > 0 else 'hl_zero'] += 1
                return super()._transition(position, now)
            info['first_fill_time'] = hl['entry_time']
            info['peer_book_deadline'] = now + OTHER_BOOK_WAIT_SECONDS
            info['phase'] = 'awaiting_peer_book'
            self.contingent_counts['hl_full'] += 1
            phase = 'awaiting_peer_book'
        if phase == 'awaiting_peer_book':
            if now > info['peer_book_deadline']:
                info['phase'] = 'peer_missing_book'
                peer['entry_result'] = 'missing_book'
                self.contingent_counts['peer_missing_book'] += 1
                return super()._transition(position, now)
            if self._peer_intent(position, now):
                return
            return
        if phase == 'peer_pending':
            if peer['entry_result'] is None:
                return
            info['phase'] = 'matched' if peer['entry_result'] == 'filled' else 'peer_failed'
            self.contingent_counts['peer_full' if peer['entry_result'] == 'filled' else 'peer_failure'] += 1
            return super()._transition(position, now)
        return super()._transition(position, now)

    def tick(self, now):
        # No independent selector or signal evaluation in the treatment arm.
        self.dirty.clear()
        return super().tick(now)

    def export_state(self):
        result = super().export_state()
        result['contingent_counts'] = dict(self.contingent_counts)
        return result

    def restore(self, state):
        super().restore(state)
        self.contingent_counts = Counter(state.get('contingent_counts', {}))


class CandidateTapEngine(PaperEngine):
    """One convergence selector chooses candidates for both paper policies."""

    def __init__(self, pairs, treatment, config=None, state=None, now=None):
        self.treatment = treatment
        self.cohort_sequence = 0
        self.cohort_counts = Counter()
        self.cohort_sums = Counter()
        self.cohorts = {}
        self.cohort_rows = deque(maxlen=MAX_COHORT_ROWS)
        super().__init__(pairs, trial_config(config), state=state, now=now)
        self.episode_history = deque(self.episode_history,maxlen=200)
        if self.selector is None:
            self.selector = StrategySelector(self.config)

    def _maybe_enter(self, pair, ident, signal, strategy, now):
        if strategy != 'convergence':
            return super()._maybe_enter(pair, ident, signal, strategy, now)
        self.cohort_sequence += 1
        cohort_id = f'{int(now * 1e6)}:{self.cohort_sequence}'
        self.cohort_counts['selected'] += 1
        if len(self.cohorts) >= MAX_COHORTS:
            self.cohort_counts['active_index_cap'] += 1
            self.cohort_counts['control_abstained'] += 1
            self.cohort_counts['treatment_abstained'] += 1
            row={'cohort_id':cohort_id,'selected_at':now,'asset':signal['asset'],
                 'pair_id':ident,'route':signal['route'],'original_quantity':signal['quantity'],
                 'control_position_id':None,'treatment_position_id':None,
                 'frozen_signal':copy.deepcopy(signal),
                 'control_result':{'status':'study_cap','net_usd':0.0},
                 'treatment_result':{'status':'study_cap','net_usd':0.0},
                 'finalized':False}
            if len(self.cohort_rows)==MAX_COHORT_ROWS:
                self.cohort_counts['cohort_export_dropped'] += 1
            self.cohort_rows.append(row)
            self._finalize_cohort(row)
            return
        treatment_id = self.treatment.accept_candidate(pair, ident, signal, cohort_id, now)
        before = set(self.positions)
        super()._maybe_enter(pair, ident, signal, strategy, now)
        created = set(self.positions) - before
        control_id = created.pop() if created else None
        if control_id:
            self.positions[control_id]['cohort_id'] = cohort_id
            self.positions[control_id]['trial_policy'] = 'simultaneous'
            self.transitions[-1] = copy.deepcopy(self.positions[control_id])
        self.cohort_counts['control_admitted' if control_id else 'control_abstained'] += 1
        self.cohort_counts['treatment_admitted' if treatment_id else 'treatment_abstained'] += 1
        row = {'cohort_id': cohort_id, 'selected_at': now, 'asset': signal['asset'],
               'pair_id': ident, 'route': signal['route'], 'original_quantity': signal['quantity'],
               'control_position_id': control_id, 'treatment_position_id': treatment_id,
               'frozen_signal': copy.deepcopy(signal),
               'control_result': None if control_id else {'status':'abstained','net_usd':0.0},
               'treatment_result': None if treatment_id else {'status':'abstained','net_usd':0.0},
               'finalized': False}
        if len(self.cohort_rows) == MAX_COHORT_ROWS:
            self.cohort_counts['cohort_export_dropped'] += 1
        self.cohort_rows.append(row)
        self.evidence.append((cohort_id + ':candidate', copy.deepcopy(row),
                              'candidate_cohort', now))
        # Active index is bounded independently of retained rows.
        if control_id or treatment_id:
            self.cohorts[cohort_id] = row
        else:
            self._finalize_cohort(row)

    def _finalize_cohort(self, row):
        if row['finalized'] or not row['control_result'] or not row['treatment_result']:
            return
        row['finalized'] = True
        self.cohort_counts['terminal_cohorts'] += 1
        for name in ('control','treatment'):
            outcome = row[name + '_result']
            self.cohort_counts[f'{name}_{outcome["status"]}'] += 1
            if outcome['net_usd'] is not None:
                self.cohort_sums[f'{name}_finalized_cohort_net_usd'] += outcome['net_usd']
            if outcome['status'] in ('abstained','study_cap'):
                self.cohort_sums[f'{name}_one_leg_clock_seconds'] += 0
                self.cohort_sums[f'{name}_unmatched_equivalent_seconds'] += 0
            elif outcome.get('one_leg_clock_seconds') is None:
                self.cohort_counts[f'{name}_exposure_metric_unknown'] += 1
            else:
                self.cohort_sums[f'{name}_one_leg_clock_seconds'] += outcome.get('one_leg_clock_seconds',0)
                self.cohort_sums[f'{name}_unmatched_equivalent_seconds'] += outcome.get('unmatched_equivalent_seconds',0)
        a,b=row['control_result'],row['treatment_result']
        if a['status']=='closed' and b['status']=='closed':
            self.cohort_counts['both_closed_exact'] += 1
            self.cohort_sums['paired_treatment_minus_control_usd'] += b['net_usd']-a['net_usd']
        self.evidence.append((row['cohort_id'] + ':outcome',copy.deepcopy(row),
                              'cohort_outcome',max(a.get('time',0),b.get('time',0),row['selected_at'])))

    def export_state(self):
        result = super().export_state()
        result['shadow_started_at'] = None  # selector is restored explicitly below
        result['contingent_selector_state'] = self.selector.export_state() if self.selector else None
        result['cohort_sequence'] = self.cohort_sequence
        result['cohort_counts'] = dict(self.cohort_counts)
        result['cohort_sums'] = dict(self.cohort_sums)
        result['cohort_rows'] = list(self.cohort_rows)
        result['cohorts'] = self.cohorts
        return result

    def restore(self, state):
        super().restore(state)
        self.selector = StrategySelector(self.config)
        if state.get('contingent_selector_state'):
            self.selector.restore_state(state['contingent_selector_state'], self.last_processed)
        self.cohort_sequence = int(state.get('cohort_sequence', 0))
        self.cohort_counts = Counter(state.get('cohort_counts', {}))
        self.cohort_sums = Counter(state.get('cohort_sums', {}))
        self.cohort_rows = deque(state.get('cohort_rows', []), maxlen=MAX_COHORT_ROWS)
        self.cohorts = dict(state.get('cohorts', {}))
        retained={row['cohort_id']:row for row in self.cohort_rows}
        for cohort_id,row in list(self.cohorts.items()):
            if cohort_id in retained:
                retained[cohort_id].update(row)
                self.cohorts[cohort_id]=retained[cohort_id]


class PairedTrial:
    """Feeds identical source books to independent control and treatment."""

    def __init__(self, pairs, config=None, control_state=None, treatment_state=None, now=None):
        self.treatment = HLFirstEngine(pairs, config, treatment_state, now)
        self.control = CandidateTapEngine(pairs, self.treatment, config, control_state, now)

    def receive(self, book):
        self.treatment.receive(book)
        self.control.receive(book)

    def tick(self, now):
        self.treatment.tick(now)
        self.control.tick(now)

    def ingest_terminal_transitions(self, batches):
        for name, batch in zip(('control','treatment'), batches):
            for position in batch[0]:
                if position.get('status') not in ('ABORTED','CLOSED','CLOSED_ESTIMATED'):
                    continue
                row=self.control.cohorts.get(position.get('cohort_id'))
                if row is None or row[name+'_result'] is not None:
                    continue
                status='closed' if position['status']=='CLOSED' else (
                    'estimated' if position['status']=='CLOSED_ESTIMATED' else 'aborted')
                row[name+'_result']={'status':status,
                    'net_usd':position.get('net_pnl_usd',0.0) if status!='aborted' else 0.0,
                    'time':position.get('settled_at',position.get('closed_at')),
                    **unmatched_exposure(position)}
                self.control._finalize_cohort(row)
                if row['finalized']:
                    self.control.cohorts.pop(row['cohort_id'],None)

    def snapshot(self, now):
        return {'version': 1, 'time': now,
                'execution_mode': 'shared WebSocket books only; no trial REST, no live orders',
                'selection': 'one convergence selector in control; original selected signals forwarded unchanged',
                'control': self.control.snapshot(now),
                'treatment': self.treatment.snapshot(now),
                'cohorts': {'counts': dict(self.control.cohort_counts),
                            'sums': dict(self.control.cohort_sums),
                            'retained_rows': list(self.control.cohort_rows),
                            'active_index_count': len(self.control.cohorts),
                            'selected_minus_finalized':self.control.cohort_counts['selected']-
                                self.control.cohort_counts['terminal_cohorts'],
                            'sums_scope':'only cohorts with both policy outcomes terminal; active and funding-unresolved excluded'},
                'treatment_counts': dict(self.treatment.contingent_counts),
                'limitations': ['Public displayed depth is a paper fill model.',
                                'No targeted REST: HL timing differs from production.',
                                'Candidate selection is conditional on the control selector route state.']}

    def export_state(self):
        return {'version': 1, 'control': self.control.export_state(),
                'treatment': self.treatment.export_state()}
