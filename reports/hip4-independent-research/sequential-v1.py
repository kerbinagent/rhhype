#!/usr/bin/env python3
"""HIP-4 pairing, secondary sequential single-account analysis (predeclared; never pooled with the primary).

The primary pairing replay builds one episode per qualifying entry interval. Episodes overlap and reuse the same
displayed size, so their sums are never one account's cash. This analysis runs the same causal entry decisions,
in time order, as one account per route at zero fees:
- a decision is taken only when the account is flat at its decision instant;
- decisions arriving while an episode is still open are counted as skipped_busy;
- after a work cap, or after the episode cap, the account's state is unknown, so later decisions are skipped_unknown
  and the account path is a labelled prefix.
Episodes never interact, so every taken episode is exactly the engine's own episode (pinned
scripts/hip4_continuation_pairing.py). The account cash is their chronological sum, and account capital is the
negative minimum of the cumulative cash path. Every figure is a displayed conditional evaluation: there is no
fill, executability, USD or profit claim.

Default is dry. --run needs the sha256 of sequential-plan-v4.json and of the admitted input seal. --self-test runs
the synthetic checks.
"""
import argparse
import collections
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_pairing as pr  # noqa: E402

lv, b, h, pm = pr.lv, pr.b, pr.h, pr.pm
HERE = Path(__file__).resolve().parent
SELF = 'reports/hip4-independent-research/sequential-v1.py'
PLAN = HERE / 'sequential-plan-v4.json'
OUT = 'reports/hip4-independent-research/sequential-v1-run'
SCHEMA, SCHEDULE = 'hip4-pairing-sequential-v1', pr.SCHEDULES[0]
LIMITS = {'projection': 16384, 'receipts': 8192}  # secondary shares of the amendment below; every staged copy counts
AMENDMENT = {'path': 'reports/experiment-storage/hip4-secondary-output-category-amendment-v1.json', 'bytes': 2203,
             'sha256': '3ca851e7a1c5377eef4d84adc197e083431c68c0b7c3ade5353e1bca5cc3f293'}
PRIMARY_PLAN_SHA = 'dd34883d64725a95561f4ce144b1058384326fed88b75aafa37cc979f21c73b7'
ANALYSIS = {
    'policy': 'one account per route at zero fees; the primary entry decisions in time order; a decision is taken '
              'only when the account is flat at its decision instant; taken episodes are the engine episodes',
    'busy': 'an episode keeps the account busy until its closing attempt (closed), its entry instant '
            '(entry_closed, entry_unfilled) or the event bound (open classes); not_admitted_size and entry classes '
            'at or after the event bound leave it flat',
    'unknown': 'a work cap, the episode cap or an exhausted step budget makes the account state unknown; later '
               'decisions are skipped_unknown and the account figures are a labelled prefix',
    'account': 'exact chronological cash sum of taken episodes; capital is the negative minimum of the cumulative '
               'path; an open final episode adds the formal envelope [cash, cash + W(1 - f)] under A1-A3',
    'claims': 'secondary and predeclared; never pooled with the primary or sensitivity results; displayed '
              'conditional evaluation only',
}


def account(dec, lay, stop_reason, schedule, budget):
    phi = pr.fees(schedule)
    segs = pr.segments(dec, dec['stop']['mono_ns'])
    book, e = pr.Book(segs, dec['off'], dec['open']), pr.event_bound(dec, stop_reason)
    out = {}
    for route, key_fn in (('FF', lambda v: pr.ff_key(v, lay, phi)), ('IF', lambda v: pr.if_key(v, lay, phi))):
        counts, cash, low, built, busy, unknown, complete = collections.Counter(), pr.ZERO, pr.ZERO, 0, None, None, True
        final, envelope, taken = 'flat', None, []
        try:
            for q, key in pr.entry_decisions(segs, key_fn, budget):
                if unknown:
                    counts['skipped_unknown'] += 1
                    continue
                if busy is not None and busy > q:
                    counts['skipped_busy'] += 1
                    continue
                if built >= pr.MAX_EPISODES:
                    counts['skipped_unknown'] += 1
                    unknown = 'episode_cap'
                    continue
                built += 1
                ep, x = pr.Episode(route, lay, phi, q, key, book), q + pr.DELTA_NS
                if ep.m < 1:
                    cls = 'not_admitted_size'
                elif x >= e[0]:
                    cls = pr.ENTRY_CLASSES[e[2]]
                else:
                    try:
                        cls = pr.run_episode(ep, book, segs, x, e, budget)
                    except pr._Exhausted:
                        cls = 'work_cap'
                counts[cls] += 1
                with b.exact():
                    for a in ep.actions:
                        cash += a['cash']
                        low = min(low, cash)
                taken.append({'decision_ns': q - dec['open'], 'class': cls, 'v': ep.cash})
                if cls == 'closed':
                    busy = max(a['t_ns'] for a in ep.actions) + dec['open']
                elif cls in ('entry_closed', 'entry_unfilled'):
                    busy = x
                elif cls in pr.OPEN_CLASSES.values():
                    busy, final = e[0], cls
                    w = ep.T() if route == 'FF' else max(ep.hold[c] + ep.hold['NO_F'] for c in ep.named)
                    with b.exact():
                        envelope = [cash, cash + w * (pr.ONE - phi['f'])]
                elif cls == 'work_cap':
                    unknown, final = 'work_cap', 'unknown'
        except pr._Exhausted:
            complete = False
        status = 'unavailable_incomplete_scan' if not complete else f'prefix_until_{unknown}' if unknown else 'complete'
        out[route] = {'status': status, 'decisions_seen': sum(counts.values()), 'counts': dict(sorted(counts.items())),
                      'taken': taken[:64], 'taken_total': len(taken), 'account_cash': cash, 'account_capital': -low,
                      'final': final if complete else 'unknown', 'envelope': envelope}
    return out


def analyze(records, cohort, stop_reason, steps=pr.MAX_STEPS):
    if len(records) > pr.MAX_RECORDS:
        raise pr.Refusal('records_over_cap')
    lay, win = lv.layout(cohort, pr.QUESTION), lv.window(pr.QUESTION)
    dec = pr.kernel_checked(records, lay, win)
    budget = pr.Budget(steps)
    projection = b.stringify({'schema': SCHEMA + '-projection', 'question': pr.QUESTION, 'stop': stop_reason,
                              'schedule': SCHEDULE, 'routes': account(dec, lay, stop_reason, SCHEDULE, budget),
                              'step_cap_exhausted': budget.left < 0, 'claims': ANALYSIS['claims']})
    if len(pm.encoded(projection)) > LIMITS['projection']:
        raise pr.Refusal('projection_over_cap')
    return projection


def pinned():
    return (SELF, *pr.PINNED)


def verify(plan_sha256, seal_sha256):
    try:
        raw = pr.bounded_read(PLAN, pr.PLAN_CAP)
    except (OSError, pr.Refusal):
        raise pr.Refusal('plan_unreadable') from None
    if pr.digest(raw) != plan_sha256:
        raise pr.Refusal('plan_sha_mismatch')
    p = pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != SCHEMA or p.get('status') != 'sealed_prospective' \
            or pm.encoded(p.get('analysis')) != pm.encoded(ANALYSIS) or p.get('schedule') != SCHEDULE \
            or p.get('output_dir') != OUT or p.get('output_limits_bytes') != LIMITS \
            or p.get('primary_plan_sha256') != PRIMARY_PLAN_SHA or p.get('category_amendment') != AMENDMENT:
        raise pr.Refusal('plan_not_sealed')
    if not pr.pin_ok(AMENDMENT, pr.PLAN_CAP):
        raise pr.Refusal('amendment_mismatch')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or sorted(str(x.get('path')) for x in pins if isinstance(x, dict)) != sorted(pinned()) \
            or not all(pr.pin_ok(x) for x in pins):
        raise pr.Refusal('pin_mismatch')
    _, cohort = pr.verify_plan('primary', PRIMARY_PLAN_SHA)  # the whole pairing chain
    return p, pr.verify_seal(seal_sha256, PRIMARY_PLAN_SHA), cohort


def _child(input_pin, cohort, pending):
    code = 5
    try:
        pr.limit_self()
        packed = pr.bounded_read(ROOT / input_pin['path'], lv.BUNDLE_CAP)
        if len(packed) != input_pin['bytes'] or pr.digest(packed) != input_pin['sha256']:
            raise pr.Refusal('input_changed')
        records = lv.parse_bundle(packed)
        projection = analyze(records, cohort, lv.validate_records(records, lv.layout(cohort, pr.QUESTION)))
        projection.update(bundle_sha256=pr.digest(packed), records=len(records))
        data = pm.encoded(projection)
        if len(data) > LIMITS['projection']:
            raise pr.Refusal('output_over_cap')
        h.write_once(pending / 'projection.json', data)
        code = 0
    except pr.Refusal as exc:
        code = 3
        h.write_once(pending / 'refusal.json', pm.encoded({'code': str(exc)[:200]}))
    except MemoryError:
        code = 4
    except Exception as exc:
        h.write_once(pending / 'refusal.json', pm.encoded({'code': 'exception', 'type': type(exc).__name__[:100]}))
    finally:
        os._exit(code)


def run(plan_sha256, seal_sha256):
    _, seal, cohort = verify(plan_sha256, seal_sha256)
    out = ROOT / OUT
    pending = out.with_name(out.name + '.pending')
    if out.exists() or pending.exists():
        raise pr.Refusal('output_exists')
    pending.mkdir()
    cause = pr.bounded_child(_child, (seal['input'], cohort, pending))
    if cause == 'wall_limit_kill_unconfirmed':
        return pr.kill_unconfirmed('sequential', plan_sha256, seal_sha256, out, pending)
    if cause is None:
        try:
            pm.strict_json(pr.bounded_read(pending / 'projection.json', LIMITS['projection']))
        except (OSError, pr.Refusal, ValueError):
            cause = 'output_admission_failed'
    if cause is None:
        try:
            verify(plan_sha256, seal_sha256)
        except (OSError, pr.Refusal):
            cause = 'pins_changed_after_run'
    usage = pr.staged_usage(pending)
    if cause is None and usage['projection'] > LIMITS['projection']:
        cause = 'output_share_exceeded'
    record = {'schema': SCHEMA + '-run', 'plan_sha256': plan_sha256, 'seal_sha256': seal_sha256,
              'status': 'complete' if cause is None else 'unavailable', 'cause': cause,
              'limits': {'ram_bytes': pr.RAM_BYTES, 'cpu_seconds': pr.CPU_S, 'wall_seconds': pr.WALL_S},
              'output_limits_bytes': LIMITS, 'staged_bytes': usage}
    if cause is not None:
        try:
            record['refusal'] = pm.strict_json(pr.bounded_read(pending / 'refusal.json', 4096))
        except (OSError, pr.Refusal, ValueError):
            record['refusal'] = None
        try:
            record['retained_not_admitted'] = pr.retain_not_admitted(pending)
        except OSError:
            record['retained_not_admitted'] = 'labelling_failed_staged_files_left_in_place'
    record['within_shares'] = usage['projection'] <= LIMITS['projection'] and \
        usage['receipts'] + len(pm.encoded(dict(record, within_shares=True))) <= LIMITS['receipts']
    data = pm.encoded(record)
    if len(data) + usage['receipts'] > LIMITS['receipts']:
        raise pr.Refusal('receipt_share_exceeded')  # staged evidence stays in place for review
    h.write_once(pending / 'run.json', data)
    try:
        os.rename(pending, out)
    except OSError:
        raise pr.Refusal('publication_failed') from None
    return record


def self_test():
    """Synthetic checks with the pairing test builders (no raw data, no files)."""
    from tests import test_hip4_continuation_pairing as tp
    def both(frames, **kw):
        recs = tp.records(frames, **kw)
        stop = lv.validate_records(recs, tp.LAY)
        _, trace = pr.analyze(recs, tp.COHORT, stop)
        return analyze(recs, tp.COHORT, stop)['routes'], trace
    checks = {}
    # the multi-entry fixture: overlapping forward decisions at 16000, 18000 and 41000 ms
    routes, trace = both(tp.stream(*tp.MULTI))
    ff, eps = routes['FF'], [e for e in trace['episodes'] if e['route'] == 'FF']
    checks['first_decision_taken'] = ff['taken'][0]['decision_ns'] == eps[0]['decision_ns']
    checks['busy_skips_counted'] = ff['counts'].get('skipped_busy', 0) == len(eps) - ff['taken_total']
    checks['taken_equal_engine'] = all(any(t['decision_ns'] == e['decision_ns'] and t['v'] == e['v'] and t['class'] == e['class']
                                           for e in eps) for t in ff['taken'])
    # a closed episode frees the account: entry, closure at 21600 ms, then a later entry is taken
    later = [tp.bbo(tp.B2, 40000, '0.47', '0.48')]  # named bids 1.01 again
    routes, trace = both(tp.stream(*tp.ENTRY, *tp.CLOSING, *later))
    ff, eps = routes['FF'], [e for e in trace['episodes'] if e['route'] == 'FF']
    checks['sequential_after_close'] = ff['taken_total'] == len(eps) >= 2 and ff['counts'].get('skipped_busy', 0) == 0
    total = sum(pr.b.decimal_text(e['v']) for e in eps)
    checks['account_cash_is_sum'] = pr.b.decimal_text(ff['account_cash']) == total
    # a work cap makes the remainder unknown, never zero
    with __import__('unittest.mock').mock.patch.object(pr, 'MAX_ATTEMPTS', 1):
        thin = tp.bbo(tp.D, 21300, '0.25', '0.26', asz='3')
        routes, _ = both(tp.stream(*tp.ENTRY, *tp.CLOSING, thin, *later))
    checks['work_cap_unknown'] = routes['FF']['status'] == 'prefix_until_work_cap' and routes['FF']['final'] == 'unknown'
    # incomplete scans are unavailable
    recs = tp.records(tp.stream(*tp.ENTRY))
    proj = analyze(recs, tp.COHORT, lv.validate_records(recs, tp.LAY), steps=5)
    checks['incomplete_unavailable'] = proj['routes']['FF']['status'] == 'unavailable_incomplete_scan'
    # publication: complete once, then a forced CPU limit publishes an explicit unavailable receipt
    import tempfile
    from unittest import mock
    recs = tp.records(tp.stream(*tp.ENTRY, *tp.CLOSING))
    data = b''.join(lv.gzip_member(b''.join(lv.encoded({k: r[k] for k in lv.HEADER_KEYS}) + r['body'] + b'\n'
                                             for r in recs)) for _ in [0])
    for name, patches, want in (('run_complete', [], ('complete', ['projection.json', 'run.json'])),
                                ('run_cpu_limit', [mock.patch.object(pr, 'CPU_S', 1),
                                                   mock.patch.object(sys.modules[__name__], 'analyze',
                                                                     side_effect=lambda *a, **k: [0 for _ in iter(int, 1)])],
                                 ('unavailable', ['run.json']))):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'capture.bundle.gz'
            bundle.write_bytes(data)
            seal = {'input': {'path': str(bundle), 'bytes': len(data), 'sha256': pr.digest(data)}}
            with mock.patch.object(sys.modules[__name__], 'verify', return_value=({}, seal, tp.COHORT)), \
                    mock.patch.object(sys.modules[__name__], 'OUT', str(Path(tmp) / 'run')):
                for item in patches:
                    item.start()
                try:
                    record = run('a' * 64, 'b' * 64)
                finally:
                    for item in patches:
                        item.stop()
            checks[name] = (record['status'], sorted(x.name for x in (Path(tmp) / 'run').iterdir())) == want
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--seal-sha256')
    args = parser.parse_args(argv)
    if args.self_test:
        checks = self_test()
        print(pm.encoded(checks).decode(), end='')
        return 0 if all(checks.values()) else 1
    if args.run:
        print(pm.encoded(run(args.plan_sha256, args.seal_sha256)).decode(), end='')
        return 0
    print(pm.encoded({'status': 'dry', 'raw_reads': 0, 'writes': 0, 'network_calls': 0, 'analysis': ANALYSIS,
                      'limits': LIMITS}).decode(), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
