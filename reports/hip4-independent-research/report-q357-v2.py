#!/usr/bin/env python3
"""Predeclared Q357 results report, v2. It succeeds v1, which is kept unchanged. Written 2 October 2026, about
19:10 UTC, before any capture data was read.

This script renders the sealed runs into one markdown report plus a binding receipt, applying each plan's own
predeclared criteria mechanically. It adds no new statistic, threshold or claim. All figures are displayed
conditional evaluations: there is no fill, executability, USD or profit claim.

Changes from v1 (root reviews, 19:07 UTC):
- An incomplete scan (decisions null) is unavailable first, as the sealed plan's unavailable criterion says. A
  positive close inside such a prefix is only described, never called a pass of the planned gate.
- Before anything is rendered, the renderer authenticates:
  - each role's plan, by sha256, with its source and chain pins;
  - the input seal, structurally, by the same rules as verify_seal.
- It does not read or hash the capture body. The bundle identity is taken as declared in the seal and
  cross-checked against each projection.
- Each run receipt must name the same plan and seal sha256. The run receipts carry no output hashes, so the
  receipt written here records the exact bytes and sha256 of every bound file at render time; no historic hash
  authentication is implied.
- Every read is bounded before allocation by its sealed share. Each parsed document has a JSON node cap, and the
  report has a row cap. Report and receipt share the 16,384-byte rendered-readout category of the pinned
  amendment. Publication is atomic and once only.

Verdicts are decided per route and fee schedule.
- Primary and sensitivity:
  - unavailable: decisions null (incomplete scan);
  - success: a closed or entry_closed episode with v > 0 is present in the retained trace;
  - failure: no episode is work-capped, and either no episode at all has v > 0, or the trace is complete and none
    is closed with v > 0;
  - otherwise undetermined, never a negative.
- Sequential:
  - success: the route status is complete, account cash > 0 and the final state is flat;
  - failure: the route status is complete and either cash <= 0 or the final state is open;
  - otherwise unavailable.
A missing or unavailable run is reported as unavailable, with its cause. Nothing is pooled.

Usage: report-q357-v2.py --plan-sha256 READOUT_PLAN_SHA [--write]
"""
import argparse
from decimal import Decimal
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_pairing as pr  # noqa: E402

spec = importlib.util.spec_from_file_location('sequential_v1', HERE / 'sequential-v1.py')
seq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seq)
SELF = 'reports/hip4-independent-research/report-q357-v2.py'
READOUT_PLAN = HERE / 'readout-plan-v1.json'
AMENDMENT = {'path': 'reports/experiment-storage/hip4-readout-category-amendment-v1.json', 'bytes': 1957,
             'sha256': 'a0c4578569ab1f669edb63a3221d6ef4e5114d31bd38f906a799ea9874dbe021'}
PLAN_SHAS = {'primary': 'dd34883d64725a95561f4ce144b1058384326fed88b75aafa37cc979f21c73b7',
             'sensitivity': 'f87c6a953a8dd7f63a6f835b32a833ed0a741c1a430161c5046011b74e2f47df',
             'sequential': '892a70ba5330c269618fb17a649384f17faa7074c6217d4afac888060249dfb8'}
RUNS = {'primary': ROOT / pr.OUTS['primary'], 'sensitivity': ROOT / pr.OUTS['sensitivity'], 'sequential': ROOT / seq.OUT}
CAPS = {'primary': pr.ROLE_LIMITS['primary'], 'sensitivity': pr.ROLE_LIMITS['sensitivity'], 'sequential': seq.LIMITS}
SEAL, OUT, RECEIPT = pr.SEAL, HERE / 'q357-report-v2.md', HERE / 'q357-report-v2-receipt.json'
NODE_CAP, CATEGORY_CAP, ROW_CAP = 400000, 16384, 16
CLOSING = ('closed', 'entry_closed')


def rel(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT.resolve())) if path.is_relative_to(ROOT.resolve()) else str(path)


def nodes(value):
    stack, count = [value], 0
    while stack:
        item = stack.pop()
        count += 1
        if count > NODE_CAP:
            raise pr.Refusal('node_cap')
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return value


class Binder:
    """Bounded reads (before allocation) of planned controls and derived outputs only, each recorded exactly."""

    def __init__(self):
        self.files = {}

    def read(self, path, cap):
        try:
            raw = pr.bounded_read(path, cap)
        except FileNotFoundError:
            return None
        self.files[rel(path)] = {'bytes': len(raw), 'sha256': pr.digest(raw)}
        return nodes(pr.pm.strict_json(raw))


def verify_readout_plan(plan_sha256):
    raw = pr.bounded_read(READOUT_PLAN, pr.PLAN_CAP)
    if pr.digest(raw) != plan_sha256:
        raise pr.Refusal('readout_plan_sha_mismatch')
    p = pr.pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('status') != 'sealed_prospective' or p.get('category_amendment') != AMENDMENT \
            or p.get('role_plans') != PLAN_SHAS or p.get('caps') != {'category_bytes': CATEGORY_CAP, 'nodes': NODE_CAP,
                                                                     'rows': ROW_CAP} \
            or not isinstance(p.get('source_pins'), list) or {x.get('path') for x in p['source_pins']} != {SELF, *seq.pinned()}:
        raise pr.Refusal('readout_plan_not_sealed')
    if not all(pr.pin_ok(x) for x in p['source_pins'] + [AMENDMENT]):
        raise pr.Refusal('readout_pin_mismatch')
    return p


def seal_ok(seal, primary_sha):
    """verify_seal's structural rules (exact schema, question, live plan, primary plan, four receipts, bundle path,
    exactly the required checks all True), without reading or hashing any capture file."""
    pins, checks, bundle = seal.get('pins'), seal.get('checks'), seal.get('input')
    paths = [x.get('path') if isinstance(x, dict) else None for x in pins] if isinstance(pins, list) else None
    return (seal.get('schema') == pr.SEAL_SCHEMA and seal.get('question') == pr.QUESTION
            and seal.get('live_plan_sha256') == pr.LIVE_PLAN_SHA and seal.get('plan_sha256') == primary_sha
            and seal.get('status') == 'admitted' and paths == [f'{pr.LIVE_OUT}/{n}' for n in pr.LIVE_FILES]
            and isinstance(bundle, dict) and bundle.get('path') == f'{pr.LIVE_OUT}/capture.bundle.gz'
            and isinstance(checks, dict) and set(checks) == set(pr.REQUIRED_CHECKS)
            and all(v is True for v in checks.values()))


def verify_role_plan(role):
    if role != 'sequential':
        plan, _ = pr.verify_plan(role, PLAN_SHAS[role])  # plan, sources, chain, live plan; no capture read
        return pr.primary_sha(role, plan, PLAN_SHAS[role])
    raw = pr.bounded_read(seq.PLAN, pr.PLAN_CAP)
    p = pr.pm.strict_json(raw)
    if pr.digest(raw) != PLAN_SHAS[role] or p.get('status') != 'sealed_prospective' \
            or p.get('primary_plan_sha256') != PLAN_SHAS['primary'] or p.get('category_amendment') != seq.AMENDMENT \
            or not all(pr.pin_ok(x) for x in p.get('source_pins', []) + [seq.AMENDMENT]):
        raise pr.Refusal('sequential_plan_not_verified')
    pr.verify_plan('primary', PLAN_SHAS['primary'])
    return PLAN_SHAS['primary']


def verdict(r, episodes, trace_complete):
    positive = any(e['class'] in CLOSING and Decimal(e['v']) > 0 for e in episodes)
    if r.get('decisions') is None:
        return 'unavailable (incomplete scan)' + ('; the retained prefix contains a positive close (descriptive only)'
                                                  if positive else '')
    if positive:
        return 'success: candidate_conditional'
    if r['classes']['work_cap']:
        return 'undetermined (work caps)'
    if r['v_positive'] == 0 or trace_complete:
        return 'failure (this window and policy only)'
    return 'undetermined (trace prefix)'


def rate(pair):
    return 'n/a' if pair is None else f'{pair[0]}/{pair[1]}'


def section(role, binder, seal, seal_sha):
    run, caps, lines = RUNS[role], CAPS[role], [f'## {role.capitalize()}', '']
    try:
        primary_sha = verify_role_plan(role)
    except (pr.Refusal, OSError) as exc:
        return lines + [f'Unavailable: plan verification refused ({exc}).', '']
    if not seal_ok(seal, primary_sha):
        return lines + ['Unavailable: the input seal does not bind this plan chain.', '']
    receipt = binder.read(run / 'run.json', caps['receipts'])
    if receipt is None:
        failure = binder.read(run.with_name(run.name + '.failure.json'), caps['receipts'])
        return lines + [f'Unavailable: no published run ({"cause " + failure["cause"] if failure else "not run"}).', '']
    if receipt.get('plan_sha256') != PLAN_SHAS[role] or receipt.get('seal_sha256') != seal_sha:
        return lines + ['Unavailable: the run receipt does not name the sealed plan and seal.', '']
    lines += [f'Run status **{receipt["status"]}**, cause `{receipt["cause"]}`, within shares '
              f'{receipt.get("within_role_shares", receipt.get("within_shares"))}.', '']
    if receipt['status'] != 'complete':
        return lines + [f'Unavailable; refusal `{receipt.get("refusal")}`; retained not-admitted outputs: '
                        f'{receipt.get("retained_not_admitted")}.', '']
    projection = binder.read(run / 'projection.json', caps['projection'])
    if projection is None or projection.get('bundle_sha256') != seal['input']['sha256']:
        return lines + ['Unavailable: the projection does not name the sealed bundle.', '']
    if role == 'sequential':
        lines += ['| Route | Status | Decisions seen | Counts | Account cash | Capital | Final | Envelope | Verdict |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for route, r in list(projection['routes'].items())[:ROW_CAP]:
            if r['status'] != 'complete':
                v = 'unavailable'
            elif Decimal(r['account_cash']) > 0 and r['final'] == 'flat':
                v = 'success: candidate_conditional'
            else:
                v = 'failure (this window only)'
            lines.append(f'| {route} | {r["status"]} | {r["decisions_seen"]} | {r["counts"]} | {r["account_cash"]} | '
                         f'{r["account_capital"]} | {r["final"]} | {r["envelope"]} | {v} |')
        return lines + ['', 'Secondary; never pooled with the primary or sensitivity results.', '']
    trace = binder.read(run / 'trace.json', caps['trace'])
    if trace is None:
        return lines + ['Unavailable: the trace is missing.', '']
    complete = trace['episodes_kept'] == trace['episodes_total']
    lines += [f'Records {projection.get("records")}, stop `{projection["stop"]}`, event bound '
              f'{projection["event_bound"]}, steps used {projection["steps_used"]}, step cap exhausted '
              f'{projection["step_cap_exhausted"]}. Trace kept {trace["episodes_kept"]} of {trace["episodes_total"]} '
              'episodes.', '',
              '| Schedule (f, split, negate, merge) | Route | Decisions | Classes (non-zero) | Rates status | '
              'Decision to fill | Closure in window | Complete case | v count / min / max / > 0 | Max capital | '
              'Max ages ms (source, receipt) | Verdict |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in projection['results'][:ROW_CAP]:
        s = r['schedule']
        eps = [e for e in trace['episodes'] if e['route'] == r['route'] and e['schedule'] == s]
        pairs = [('n/a' if r.get(k) is None else f'[{rate(r[k][0])}, {rate(r[k][1])}]')
                 for k in ('decision_to_fill', 'closure_within_window')] + [rate(r.get('complete_case_conditional'))]
        classes = {k: v for k, v in r['classes'].items() if v}
        lines.append(f'| {s["f"]}, {s["c_split"]}, {s["c_neg"]}, {s["c_merge"]} | {r["route"]} | {r["decisions"]} | '
                     f'{classes} | {r["rates_status"]} | ' + ' | '.join(pairs) +
                     f' | {r["v_count"]} / {r["v_min"]} / {r["v_max"]} / {r["v_positive"]} | '
                     f'{r["capital_max_per_episode"]} | ({r["max_source_age_ms"]}, {r["max_receipt_age_ms"]}) | '
                     f'{verdict(r, eps, complete)} |')
    return lines + ['', 'Episode sums overlap and are never portfolio cash. Zero fees are optimistic. Each fee schedule '
                    'is a separate replay; nothing is pooled.', '']


def render(plan_sha256):
    verify_readout_plan(plan_sha256)
    binder = Binder()
    lines = ['# HIP-4 Q357 funded pairing: results (predeclared report v2)', '',
             'Rendered mechanically from the sealed runs by report-q357-v2.py. The format and criteria were fixed before '
             'any capture data was read. Displayed conditional evaluation only: there is no fill, executability, USD or '
             'profit claim. File hashes in the receipt were recorded at render time; the run receipts carry no output '
             'hashes, so no historic hash authentication is implied. The capture body was not read.', '']
    seal = binder.read(SEAL, pr.SEAL_CAP)
    seal_sha = binder.files.get(rel(SEAL), {}).get('sha256')
    if seal is None or seal.get('status') != 'admitted':
        status = 'missing' if seal is None else seal['status']
        failed = [] if seal is None else sorted(k for k, v in seal['checks'].items() if v is not True)
        lines += [f'**Input seal {status}**' + (f' (cause `{seal.get("cause")}`, failed checks {failed})' if seal else '')
                  + '. Every result is unavailable; nothing is converted to a negative.', '']
    else:
        lines += [f'Input seal admitted ({seal["sealed_utc"]}), sha256/16 `{seal_sha[:16]}`. Declared bundle '
                  f'{seal["input"]["bytes"]} B, sha256/16 `{seal["input"]["sha256"][:16]}`.', '']
        for role in ('primary', 'sensitivity', 'sequential'):
            lines += section(role, binder, seal, seal_sha)
    text = '\n'.join(lines).encode()
    receipt = {'schema': 'hip4-q357-readout-receipt-v1', 'readout_plan_sha256': plan_sha256,
               'report': {'path': rel(OUT), 'bytes': len(text), 'sha256': pr.digest(text)},
               'bound_files_at_render_time': binder.files, 'category_amendment': AMENDMENT,
               'note': 'hashes recorded at render time; no historic hash authentication of run outputs is implied; '
                       'the capture body was not read', 'rendered_utc': pr.pm.utc()}
    data = pr.encoded(receipt)
    if len(text) + len(data) > CATEGORY_CAP:
        raise pr.Refusal('readout_over_category')
    return text, data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    text, receipt = render(args.plan_sha256)
    if args.write:
        pr.h.write_once(OUT, text)  # atomic link, refuses overwrite
        pr.h.write_once(RECEIPT, receipt)
    print(text.decode())
    return 0


if __name__ == '__main__':
    sys.exit(main())
