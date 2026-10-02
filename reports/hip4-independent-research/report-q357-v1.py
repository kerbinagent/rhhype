#!/usr/bin/env python3
"""Predeclared Q357 results report (written 2 October 2026, before any capture data was read).

This script renders the sealed runs into one markdown report, applying each plan's own predeclared criteria
mechanically. It adds no new statistic, threshold or claim. All figures are displayed conditional evaluations:
there is no fill, executability, USD or profit claim.

Verdicts are decided per route and fee schedule.
- Primary and sensitivity:
  - success: a closed or entry_closed episode with v > 0 is present in the retained trace;
  - failure: the scan is complete, no episode is work-capped, and either no episode at all has v > 0, or the
    trace is complete and none is closed with v > 0;
  - otherwise undetermined, never a negative.
- Sequential:
  - success: the route status is complete, account cash > 0 and the final state is flat;
  - failure: the route status is complete and either cash <= 0 or the final state is open;
  - otherwise unavailable.
A run that is missing or unavailable is reported as unavailable, with its cause. Sensitivity schedules are reported
separately and never pooled. The sequential result is secondary and never pooled.

Usage: report-q357-v1.py [--write]. Reads the input seal and the run directories; with --write it writes
q357-report-v1.md once.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = {'primary': ROOT / 'reports/hip4-research-continuation/pairing-v1-run',
        'sensitivity': HERE / 'pairing-sensitivity-run', 'sequential': HERE / 'sequential-v1-run'}
SEAL, OUT = HERE / 'q357-input-seal-v1.json', HERE / 'q357-report-v1.md'
CLOSING = ('closed', 'entry_closed')


def load(path, cap=1 << 20):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return json.loads(data) if len(data) <= cap else None


def rate(pair):
    return 'n/a' if pair is None else f'{pair[0]}/{pair[1]}'


def pair_rates(r):
    out = []
    for key in ('decision_to_fill', 'closure_within_window'):
        v = r.get(key)
        out.append('n/a' if v is None else f'[{rate(v[0])}, {rate(v[1])}]')
    out.append(rate(r.get('complete_case_conditional')))
    return out


def verdict(r, episodes, trace_complete):
    if any(e['class'] in CLOSING and Decimal(e['v']) > 0 for e in episodes):
        return 'success: candidate_conditional'
    if r.get('decisions') is None:
        return 'undetermined (incomplete scan)'
    if r['classes']['work_cap']:
        return 'undetermined (work caps)'
    if r['v_positive'] == 0 or trace_complete:
        return 'failure (this window and policy only)'
    return 'undetermined (trace prefix)'


def role_section(role):
    run, lines = RUNS[role], [f'## {role.capitalize()}', '']
    receipt = load(run / 'run.json')
    if receipt is None:
        failure = load(run.with_name(run.name + '.failure.json'))
        return lines + [f'Unavailable: no published run ({"cause " + failure["cause"] if failure else "not run"}).', '']
    lines += [f'Run status **{receipt["status"]}**, cause `{receipt["cause"]}`, within shares '
              f'{receipt.get("within_role_shares", receipt.get("within_shares"))}.', '']
    if receipt['status'] != 'complete':
        return lines + [f'Unavailable; refusal `{receipt.get("refusal")}`; retained not-admitted outputs: '
                        f'{receipt.get("retained_not_admitted")}.', '']
    projection = load(run / 'projection.json')
    if role == 'sequential':
        lines += ['| Route | Status | Decisions seen | Counts | Account cash | Capital | Final | Envelope | Verdict |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for route, r in projection['routes'].items():
            if r['status'] != 'complete':
                v = 'unavailable'
            elif Decimal(r['account_cash']) > 0 and r['final'] == 'flat':
                v = 'success: candidate_conditional'
            else:
                v = 'failure (this window only)'
            lines.append(f'| {route} | {r["status"]} | {r["decisions_seen"]} | {r["counts"]} | {r["account_cash"]} | '
                         f'{r["account_capital"]} | {r["final"]} | {r["envelope"]} | {v} |')
        return lines + ['', 'Secondary; never pooled with the primary or sensitivity results.', '']
    trace = load(run / 'trace.json')
    lines += [f'Records {projection.get("records")}, stop `{projection["stop"]}`, event bound '
              f'{projection["event_bound"]}, steps used {projection["steps_used"]}, step cap exhausted '
              f'{projection["step_cap_exhausted"]}. Trace kept {trace["episodes_kept"]} of {trace["episodes_total"]} '
              'episodes.', '',
              '| Schedule (f, split, negate, merge) | Route | Decisions | Classes (non-zero) | Rates status | '
              'Decision to fill | Closure in window | Complete case | v count / min / max / > 0 | Max capital | '
              'Max ages ms (source, receipt) | Verdict |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in projection['results']:
        s = r['schedule']
        eps = [e for e in trace['episodes'] if e['route'] == r['route'] and e['schedule'] == s]
        classes = {k: v for k, v in r['classes'].items() if v}
        lines.append(f'| {s["f"]}, {s["c_split"]}, {s["c_neg"]}, {s["c_merge"]} | {r["route"]} | {r["decisions"]} | '
                     f'{classes} | {r["rates_status"]} | ' + ' | '.join(pair_rates(r)) +
                     f' | {r["v_count"]} / {r["v_min"]} / {r["v_max"]} / {r["v_positive"]} | '
                     f'{r["capital_max_per_episode"]} | ({r["max_source_age_ms"]}, {r["max_receipt_age_ms"]}) | '
                     f'{verdict(r, eps, trace["episodes_kept"] == trace["episodes_total"])} |')
    return lines + ['', 'Episode sums overlap and are never portfolio cash. Zero fees are optimistic. Each fee schedule '
                    'is a separate replay; nothing is pooled.', '']


def render():
    seal = load(SEAL)
    lines = ['# HIP-4 Q357 funded pairing: results (predeclared report v1)', '',
             'Rendered mechanically from the sealed runs by report-q357-v1.py. The format and criteria were fixed before '
             'any capture data was read. Displayed conditional evaluation only: there is no fill, executability, USD '
             'or profit claim.', '']
    if seal is None or seal.get('status') != 'admitted':
        status = 'missing' if seal is None else seal['status']
        cause = None if seal is None else seal.get('cause')
        failed = [] if seal is None else sorted(k for k, v in seal['checks'].items() if v is not True)
        return '\n'.join(lines + [f'**Input seal {status}** (cause `{cause}`; failed checks {failed}). Every result '
                                  'is unavailable; nothing is converted to a negative.', ''])
    lines += [f'Input seal admitted ({seal["sealed_utc"]}). Bundle {seal["input"]["bytes"]} B, sha256 '
              f'`{seal["input"]["sha256"][:16]}…`, primary plan `{seal["plan_sha256"][:16]}…`.', '']
    for role in ('primary', 'sensitivity', 'sequential'):
        lines += role_section(role)
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    text = render()
    if args.write:
        with OUT.open('x') as stream:  # once only
            stream.write(text)
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
