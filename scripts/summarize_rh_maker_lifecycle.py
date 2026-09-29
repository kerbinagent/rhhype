#!/usr/bin/env python3
"""Bounded, descriptive lifecycle report for an existing RH maker paper replay.

Reads only replay analysis.json and its gzip audit stream. It does not inspect
the raw capture, place orders, infer private fills, or change the frozen model.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path


NS = 1_000_000_000
MAX_ANALYSIS_BYTES = 32_000_000
MAX_AUDIT_BYTES = 96_000_000
MAX_DECODED_BYTES = 512_000_000
MAX_AUDIT_RECORDS = 2_000_000
MAX_LINE_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 4_000_000
BUCKET_SECONDS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def identity(row):
    return (str(row['tier']), str(row['asset']), str(row['budget_usd']),
            str(row['policy']))


class Durations:
    """Exact count/sum/extrema and fixed buckets; never keeps every interval."""

    def __init__(self):
        self.count = self.sum_ns = 0
        self.min_ns = self.max_ns = None
        self.buckets = [0] * (len(BUCKET_SECONDS) + 1)

    def add(self, start, stop):
        if stop < start:
            raise ValueError('negative lifecycle interval')
        span = stop - start
        self.count += 1
        self.sum_ns += span
        self.min_ns = span if self.min_ns is None else min(self.min_ns, span)
        self.max_ns = span if self.max_ns is None else max(self.max_ns, span)
        i = next((i for i, bound in enumerate(BUCKET_SECONDS)
                  if span <= bound * NS), len(BUCKET_SECONDS))
        self.buckets[i] += 1

    def as_dict(self):
        def quantile_upper(p):
            if not self.count:
                return None
            target = max(1, int((self.count * p) + .999999999))
            seen = 0
            for bound, count in zip((*BUCKET_SECONDS, None), self.buckets):
                seen += count
                if seen >= target:
                    return bound
            raise AssertionError('duration histogram lost observations')
        return {'count': self.count,
                'mean_seconds': self.sum_ns / (self.count * NS) if self.count else None,
                'min_seconds': self.min_ns / NS if self.min_ns is not None else None,
                'max_seconds': self.max_ns / NS if self.max_ns is not None else None,
                'p50_bucket_upper_seconds': quantile_upper(.5),
                'p90_bucket_upper_seconds': quantile_upper(.9),
                'bucket_upper_seconds': [*BUCKET_SECONDS, None],
                'bucket_counts': self.buckets}


class BranchTimeline:
    def __init__(self, cutoff, end):
        self.cutoff, self.end = cutoff, end
        self.quote = None
        self.unscheduled_flows = deque()
        self.scheduled_flows = deque()
        self.exit_requested = None
        self.intervals = {name: Durations() for name in
                          ('decision_to_activation', 'public_flow_to_hedge_result',
                           'modeled_exit_request_to_flat',
                           'decision_to_post_only_reject')}
        self.by_competitiveness = {
            label: {'modeled_quote_residence': Durations(),
                    'activation_to_cancel_effectiveness_book': Durations(),
                    'censored_modeled_quote_residence_lower_bound': Durations(),
                    'censored_activation_to_cancel_effectiveness_book_lower_bound': Durations()}
            for label in ('join', 'inside', 'behind', 'unknown')}
        self.censored = Counter()
        self.censored_intervals = {
            'request_to_activation_lower_bound': Durations(),
            'public_flow_to_hedge_result_lower_bound': Durations(),
            'exit_request_to_flat_lower_bound': Durations()}

    def _end_quote(self, at, complete):
        q = self.quote
        if q is None:
            self.censored['terminal_quote_event_without_request'] += 1
            return
        if q['activated'] is not None:
            class_stats = self.by_competitiveness[q['class']]
            modeled_stop = min(at, q['cancel_due']) if q['cancel_due'] is not None else at
            modeled_start = q['due']
            if modeled_stop >= modeled_start:
                name = ('modeled_quote_residence' if complete else
                        'censored_modeled_quote_residence_lower_bound')
                class_stats[name].add(modeled_start, modeled_stop)
            observed_name = ('activation_to_cancel_effectiveness_book' if complete else
                             'censored_activation_to_cancel_effectiveness_book_lower_bound')
            class_stats[observed_name].add(q['activated'], at)
        elif not complete:
            self.censored['requested_without_observed_activation'] += 1
            self.censored_intervals['request_to_activation_lower_bound'].add(
                q['requested'], at)
        if not complete:
            self.censored['quote_interval_censored'] += 1
        self.quote = None

    def _end_flows(self, at, reason):
        for queue in (self.unscheduled_flows, self.scheduled_flows):
            while queue:
                start, _ = queue.popleft()
                self.censored[f'flow_without_hedge_result:{reason}'] += 1
                self.censored_intervals['public_flow_to_hedge_result_lower_bound'].add(start, at)

    def consume(self, row):
        at = row['ns']
        if isinstance(at, bool) or not isinstance(at, int):
            raise ValueError('audit ns must be integer')
        if at < self.cutoff or at > self.end:
            return
        event = row['event']
        if event == 'quote_requested':
            if self.quote is not None:
                self.censored['overlapping_quote_requests'] += 1
                self._end_quote(at, False)
            label = row.get('competitiveness', 'unknown')
            if label not in self.by_competitiveness:
                label = 'unknown'
            self.quote = {'requested': at, 'due': int(row['due_ns']),
                          'class': label, 'activated': None, 'cancel_due': None}
        elif event == 'activated':
            if self.quote is None:
                self.censored['activation_without_request'] += 1
            else:
                self.quote['activated'] = at
                self.intervals['decision_to_activation'].add(self.quote['requested'], at)
        elif event == 'cancel_requested':
            if self.quote is not None:
                self.quote['cancel_due'] = int(row['due_ns'])
        elif event == 'cancel_effective':
            self._end_quote(at, True)
        elif event == 'post_only_reject':
            if self.quote is None:
                self.censored['post_only_reject_without_request'] += 1
            else:
                self.intervals['decision_to_post_only_reject'].add(
                    self.quote['requested'], at)
                self.quote = None
        elif event == 'maker_increment':
            if len(self.unscheduled_flows) + len(self.scheduled_flows) >= 64:
                raise ValueError('more pending maker increments than frozen branch cap')
            self.unscheduled_flows.append((at, Decimal(row['qty'])))
        elif event == 'hedge_scheduled':
            quantity = Decimal(row['qty'])
            if not self.unscheduled_flows:
                self.censored['hedge_schedule_without_maker_increment'] += 1
            else:
                started, maker_quantity = self.unscheduled_flows.pop()
                if maker_quantity == quantity and started == at:
                    self.scheduled_flows.append((started, quantity))
                else:
                    self.censored['hedge_schedule_flow_pairing_ambiguous'] += 1
                    self.censored['flow_without_hedge_result:ambiguous_schedule'] += 1
                    self.censored_intervals['public_flow_to_hedge_result_lower_bound'].add(
                        started, at)
        elif event == 'hedge_result':
            requested = Decimal(row['requested'])
            if not self.scheduled_flows:
                self.censored['hedge_result_without_schedule'] += 1
            else:
                started, quantity = self.scheduled_flows.popleft()
                if quantity == requested:
                    self.intervals['public_flow_to_hedge_result'].add(started, at)
                else:
                    self.censored['hedge_quantity_pairing_ambiguous'] += 1
        elif event == 'hedge_timeout':
            if not self.scheduled_flows:
                self.censored['hedge_timeout_without_schedule'] += 1
            else:
                started, quantity = self.scheduled_flows.popleft()
                if quantity != Decimal(row['qty']):
                    self.censored['hedge_timeout_quantity_pairing_ambiguous'] += 1
                self.censored['flow_without_hedge_result:hedge_timeout'] += 1
                self.censored_intervals['public_flow_to_hedge_result_lower_bound'].add(
                    started, at)
        elif event == 'exit_requested':
            if self.exit_requested is not None:
                self.censored['multiple_exit_requests_before_flat'] += 1
            else:
                self.exit_requested = at
        elif event == 'episode_flat':
            if self.exit_requested is not None:
                self.intervals['modeled_exit_request_to_flat'].add(self.exit_requested, at)
                self.exit_requested = None
            self._end_flows(at, 'flat_without_result')
            if self.quote is not None:
                self.censored['flat_without_cancel_observation'] += 1
                self._end_quote(at, False)
        elif event == 'unknown':
            if self.quote is not None:
                self._end_quote(at, False)
            self._end_flows(at, 'unknown')
            if self.exit_requested is not None:
                self.censored['exit_request_without_flat:unknown'] += 1
                self.censored_intervals['exit_request_to_flat_lower_bound'].add(
                    self.exit_requested, at)
                self.exit_requested = None

    def finish(self):
        if self.quote is not None:
            self._end_quote(self.end, False)
            self.censored['quote_open_at_replay_end'] += 1
        self._end_flows(self.end, 'replay_end')
        if self.exit_requested is not None:
            self.censored['exit_request_without_flat:replay_end'] += 1
            self.censored_intervals['exit_request_to_flat_lower_bound'].add(
                self.exit_requested, self.end)
            self.exit_requested = None
        return {'intervals': {k: v.as_dict() for k, v in self.intervals.items()},
                'quote_residence_by_competitiveness': {
                    k: {name: stat.as_dict() for name, stat in values.items()}
                    for k, values in self.by_competitiveness.items()},
                'censored_counts': dict(self.censored),
                'censored_intervals': {k: v.as_dict() for k, v in self.censored_intervals.items()},
                'duration_interpretation': {
                    'decision_to_activation': 'request receipt to public activation book receipt',
                    'public_flow_to_hedge_result': 'public RH seller-flow receipt to first eligible HL paper hedge result receipt; FIFO matched by quantity',
                    'modeled_exit_request_to_flat': 'modeled exit request timestamp to observed paper flat timestamp',
                    'modeled_quote_residence': 'activation due to modeled cancel due or cancel observation, only for observed activation',
                    'activation_to_cancel_effectiveness_book': 'activation book receipt to a later eligible book on which the model marks cancellation effective; no private order acknowledgement or continuous queue state observed',
                    'censored': 'lower bounds stop at unknown observation or replay end; no event duration is imputed after that point'}}


def audit_rows(path, expected_hash, expected_count):
    path = Path(path)
    if path.stat().st_size > MAX_AUDIT_BYTES:
        raise ValueError('audit gzip exceeds 96 MB bound')
    if sha256(path) != expected_hash:
        raise ValueError('audit gzip SHA-256 differs from replay analysis')
    decoded = records = 0
    with gzip.open(path, 'rb') as stream:
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            decoded += len(line)
            records += 1
            if (len(line) > MAX_LINE_BYTES or not line.endswith(b'\n') or
                    decoded > MAX_DECODED_BYTES or records > MAX_AUDIT_RECORDS):
                raise ValueError('audit decoded line, byte, or record bound exceeded')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('audit row must be an object')
            yield row
    if records != expected_count:
        raise ValueError('audit record count differs from replay analysis')


def economics(row):
    known = [e for e in row['episodes'] if not e.get('funding_unknown')]
    def total(field):
        return sum((Decimal(e[field]) for e in known), Decimal(0))
    cash, reserve, capital = (total(field) for field in
                              ('cash_known', 'reserve_cost', 'capital_cost'))
    contribution = cash - reserve - capital
    if contribution != Decimal(row['metrics']['closed_net_parity_usd']):
        raise ValueError('closed episode economics disagree with frozen analysis')
    return {'known_closed_episodes': len(known),
            'known_closed_filled_episodes': row['metrics']['known_closed_filled_episodes'],
            'funding_unknown_closed_episodes': row['metrics']['funding_unknown_episodes'],
            'closed_cash_after_fees_before_reserve_capital_parity_usd': str(cash),
            'closed_reserve_cost_usd': str(reserve),
            'closed_capital_cost_usd': str(capital),
            'closed_contribution_after_all_three_parity_usd': str(contribution),
            'complete_branch_net_parity_usd': row['complete_net'],
            'complete_branch_result_known': row['complete_net'] is not None,
            'open_rh_base': row['rh_position'], 'open_hl_base': row['hl_position'],
            'unknown_reason': row['unknown_reason']}


def render(result):
    lines = ['# RH maker lifecycle diagnostics', '',
             f"Replay status: **{result['replay_status']}**; source: `{result['event_source']}`.",
             '', 'Public-flow counterfactuals, not private fills. USDG and USDC dollar',
             'figures assume parity; conversion and transfer costs are omitted. The',
             'closed-cash column includes price P&L and modeled explicit fees, before reserve',
             'and capital costs. Unknown funding and open inventory are excluded from',
             'closed contribution. Each row is an independent branch; never sum rows.',
             '', '## Primary panel: Standard, $1,000, adaptive', '',
             'BTC, ETH, NVDA and XAG are reported separately. Model readiness',
             'and calibration coverage are in `lifecycle.json`; an unready rule',
             'cannot be judged from its holdout abstentions.', '']
    header = '| Tier | Asset | Budget | Policy | Ready | Known filled closes | Cash after fees | Reserve | Capital | Closed contribution | Total result |'
    rule = '|---|---|---:|---|---|---:|---:|---:|---:|---:|---|'
    def economic_rows(branches):
        out = [header, rule]
        for b in branches:
            e = b['economics']
            def money(key):
                return f"{Decimal(e[key]):+.4f}"
            total = 'unknown' if e['complete_branch_net_parity_usd'] is None else f"{Decimal(e['complete_branch_net_parity_usd']):+.4f}"
            ready = b['calibration'].get('ready')
            readiness = 'yes' if ready is True else 'no' if ready is False else 'unknown'
            out.append(f"| {b['tier']} | {b['asset']} | {b['budget_usd']} | {b['policy']} | "
                       f"{readiness} | {e['known_closed_filled_episodes']} | {money('closed_cash_after_fees_before_reserve_capital_parity_usd')} | "
                       f"{money('closed_reserve_cost_usd')} | {money('closed_capital_cost_usd')} | "
                       f"{money('closed_contribution_after_all_three_parity_usd')} | {total} |")
        return out
    lines += economic_rows([b for b in result['branches'] if b['primary_panel']])
    lines += ['', '## Controls and declared sensitivities', '',
              'Fixed-best and persistence share the same public events as adaptive;',
              '$100/$250/$500 sizes and Premium are independent sensitivities.', '']
    lines += economic_rows([b for b in result['branches'] if not b['primary_panel']])
    lines += ['', '## Timing and hazard', '',
              'The original replay already reports decision, activation, cancellation,',
              'hedge and no-flow counts by five-minute block. The JSON here preserves',
              'those counts and adds bounded duration histograms by branch.', '',
              '| Tier | Asset | Budget | Policy | Quote requests / activations / cancels / post-only rejects | Modeled residence by quote class, mean s (n) | Flow→hedge mean s / p90 bucket ≤s (n) | Exit→flat mean s / p90 bucket ≤s (n) | Censored quote / flow / exit |',
              '|---|---|---:|---|---:|---|---|---|---:|']
    def interval_text(values):
        if not values['count']:
            return '—'
        bound = values['p90_bucket_upper_seconds']
        upper = '∞' if bound is None else f'{bound:g}'
        return f"{values['mean_seconds']:.2f} / ≤{upper} ({values['count']})"
    for b in result['branches']:
        h, t = b['hazard_counts'], b['timing']
        c = t['censored_counts']
        quote_censored = c.get('quote_interval_censored', 0)
        flow_censored = sum(v for k, v in c.items() if k.startswith('flow_without_hedge_result:'))
        exit_censored = sum(v for k, v in c.items() if k.startswith('exit_request_without_flat:'))
        classes = ', '.join(f"{label} {values['modeled_quote_residence']['mean_seconds']:.2f} "
                            f"({values['modeled_quote_residence']['count']})"
                            for label, values in t['quote_residence_by_competitiveness'].items()
                            if values['modeled_quote_residence']['count']) or '—'
        lines.append(f"| {b['tier']} | {b['asset']} | {b['budget_usd']} | {b['policy']} | "
                     f"{h['quote_requested']} / {h['activated']} / {h['cancel_effective']} / {h['post_only_reject']} | "
                     f"{classes} | "
                     f"{interval_text(t['intervals']['public_flow_to_hedge_result'])} | "
                     f"{interval_text(t['intervals']['modeled_exit_request_to_flat'])} | "
                     f"{quote_censored} / {flow_censored} / {exit_censored} |")
    lines += ['', 'Duration p50/p90 fields in lifecycle.json are **histogram upper',
              'bounds**, not exact percentiles. Modeled quote residence is conditional',
              'on an observed activation; queue residence ends at a public cancel',
              'observation. Unknown or unfinished intervals are reported as lower',
              'bounds, separately from completed intervals. Cancel effectiveness is',
              'modeled on an eligible public book, not confirmed by a private order',
              'acknowledgement. A quote resting, public',
              'seller flow, or a paper hedge does **not** measure a continuously',
              'executable profitable opportunity window. No private fill probability',
              'or live-order latency is inferred.', '']
    return '\n'.join(lines)


def summarize(replay_dir, out):
    replay_dir, out = Path(replay_dir), Path(out)
    if out.exists():
        raise ValueError('output directory must be new')
    analysis_path, audit_path = replay_dir / 'analysis.json', replay_dir / 'audit.jsonl.gz'
    if analysis_path.stat().st_size > MAX_ANALYSIS_BYTES:
        raise ValueError('analysis JSON exceeds 32 MB bound')
    analysis = json.loads(analysis_path.read_bytes())
    if analysis.get('schema') != 'rh-maker-replay-v1':
        raise ValueError('unsupported replay analysis schema')
    if not 0 <= analysis['audit_records'] <= MAX_AUDIT_RECORDS:
        raise ValueError('replay audit record count exceeds bound')
    cutoff, end = int(analysis['cutoff_ns']), int(analysis['ended_ns'])
    if not 0 < cutoff <= end or end - cutoff > 1200 * NS:
        raise ValueError('invalid holdout interval')
    rows = analysis['branches']
    if not isinstance(rows, list) or len(rows) > 96:
        raise ValueError('branch count exceeds frozen 96-branch design')
    timelines = {identity(b): BranchTimeline(cutoff, end) for b in rows}
    if len(timelines) != len(rows):
        raise ValueError('duplicate branch identity')
    for row in audit_rows(audit_path, analysis['audit_sha256'], analysis['audit_records']):
        key = identity(row)
        if key not in timelines:
            raise ValueError('audit row has unknown branch')
        timelines[key].consume(row)
    branches = []
    for row in sorted(rows, key=lambda r: (r['tier'] != 'standard', int(r['budget_usd']) != 1000,
                                           r['asset'], int(r['budget_usd']), r['policy'])):
        key = identity(row)
        counts = row['counts']
        model = analysis.get('models', {}).get(key[0], {})
        fit = model.get('fit') or {}
        calibration = (fit.get('routes') or {}).get(f'{key[1]}|{key[2]}') or {}
        branches.append({'tier': key[0], 'asset': key[1], 'budget_usd': key[2],
                         'policy': key[3], 'primary_size': key[2] == '1000',
                         'primary_panel': key[0] == 'standard' and key[2] == '1000' and key[3] == 'adaptive',
                         'calibration': {name: calibration.get(name) for name in
                                         ('ready', 'flow_ready', 'close_ready', 'flow_admitted',
                                          'flow_resolved', 'flow_coverage', 'flow_span_seconds',
                                          'close_admitted', 'close_resolved', 'close_coverage',
                                          'close_span_seconds')},
                         'economics': economics(row),
                         'hazard_counts': {name: counts.get(name, 0) for name in
                                           ('decision_opportunity', 'quote_requested', 'activated',
                                            'cancel_requested', 'cancel_effective', 'post_only_reject', 'maker_increment',
                                            'hedge_result', 'exit_requested', 'episode_flat', 'unknown')},
                         'existing_five_minute_lifecycle': row.get('lifecycle_by_five_minute_block', {}),
                         'timing': timelines[key].finish()})
    result = {'schema': 'rh-maker-lifecycle-summary-v1',
              'replay_status': analysis['status'], 'event_source': analysis.get('event_source'),
              'source_analysis_sha256': sha256(analysis_path),
              'source_audit_sha256': analysis['audit_sha256'],
              'cutoff_ns': cutoff, 'ended_ns': end, 'branch_count': len(branches),
              'branches': branches,
              'limitations': ['Public-flow paper outcomes are not private fills.',
                              'USDG/USDC combined dollars assume parity and omit conversion costs.',
                              'Quote residence and public flow do not establish continuous executable profit.',
                              'Unknown funding, inventory and censored timing remain unknown.',
                              'Correlated scenario branches must not be summed.']}
    body = json.dumps(result, allow_nan=False, separators=(',', ':'), sort_keys=True).encode() + b'\n'
    report = render(result).encode()
    if len(body) > MAX_OUTPUT_BYTES or len(report) > MAX_OUTPUT_BYTES:
        raise ValueError('lifecycle output exceeds 4 MB bound')
    out.mkdir(parents=True)
    (out / 'lifecycle.json').write_bytes(body)
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True,
                        help='Directory containing a completed replay analysis.json and audit.jsonl.gz')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = summarize(args.replay, args.out)
    print(json.dumps({'out': str(args.out), 'replay_status': result['replay_status'],
                      'branches': result['branch_count']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
