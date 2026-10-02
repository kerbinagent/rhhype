#!/usr/bin/env python3
"""Equivalence and causality audit of the v5 implementation amendment, on synthetic data only.

v5 is a blinded, during-collection implementation amendment. It was written after the Q357 window opened at
18:35 UTC, with no capture data read. It caches each episode's closure-gate terms between state changes and holds
one exact decimal context per closure scan; the step cap is raised separately. This audit compares v5 with the
exact v4 snapshot (snapshots/hip4_continuation_pairing_v4.py, sha256 bc7e9204...).

1. Equivalence. Over the same streams and the same explicit step budget, v4 and v5 must produce byte-identical
   projections and traces. The streams are:
   - the v1 audit seeds 0-299 under all five audit schedules;
   - the v2 targeted variants for seeds 0-59;
   - one 20,000-frame stress stream.
   The budgets are unlimited and also small caps that exhaust it at different points, so work_cap,
   overflow and incomplete-scan classifications are compared too. MAX_ATTEMPTS is also lowered to 2 in both
   engines on the stress stream.
2. No lookahead. For the v1 seeds 0-99, v5 on the stream cut at a seeded time T (a censoring stop at T, later
   frames dropped) must yield exactly the same decisions before T and the same actions before T for each of them
   as the uncut stream.

The audit passes only if every comparison holds. It reads no raw data, makes no network call and creates no temp
files. With --write it writes one bounded result file, once.
"""
import argparse
import contextlib
import datetime as dt
import importlib.util
from pathlib import Path
import random
import sys
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v1 = load('pairing_audit_v1', HERE / 'pairing-audit-v1.py')
v2 = load('pairing_audit_v2', HERE / 'pairing-audit-v2.py')
new, tp, lv = v1.pr, v1.tp, v1.lv
old = load('pairing_v4_snapshot', HERE / 'snapshots' / 'hip4_continuation_pairing_v4.py')
OUT = HERE / 'pairing-equivalence-v5-result.json'
BUDGETS = (None, 40, 400, 4000)


def window(length):
    return dict(tp.WIN, close=tp.WIN['open'] + dt.timedelta(milliseconds=length))


def both(recs, length, schedules, steps, patches=()):
    outs = []
    for engine in (old, new):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(lv, 'window', return_value=window(length)))
            for name, value in patches:
                stack.enter_context(mock.patch.object(engine, name, value))
            limit = 10 ** 12 if steps is None else steps  # the same explicit budget for both engines
            projection, trace = engine.analyze(recs, tp.COHORT, lv.validate_records(recs, tp.LAY), schedules, limit)
        outs.append(new.encoded(projection) + new.encoded(trace))
    return outs[0] == outs[1]


def records_of(frames, g):
    return tp.records(frames, 'ws_closed' if g['censored'] else 'window_closed', tp.O + g['stop_at'])


def stress(n=20000, seed=7):
    rng, span = random.Random(seed), 90000
    mid, frames = {tp.A: 300, tp.D: 250, tp.B2: 450}, []
    for i in range(n):
        c = rng.choice((tp.A, tp.D, tp.B2))
        mid[c] = max(50, min(900, mid[c] + rng.choice((-1, 0, 1))))
        drift = sum(mid.values()) - 1000
        mid[c] += -1 if drift > 3 else 1 if drift < -3 else 0
        frames.append(tp.bbo(c, (i * span) // n, str(mid[c] / 1000), str((mid[c] + rng.choice((1, 2, 3))) / 1000),
                             rng.choice(('5', '10', '40')), rng.choice(('5', '10', '40'))))
    return tp.records(tp.stream(*frames, beats=(-30000, span))), span


def causal(seed):
    """Every decision and action before a seeded cut T is the same with and without the data after T."""
    frames, g = v1.generate(seed)
    cut = random.Random(1000 + seed).randrange(2000, g['stop_at'], v1.GRID)
    def run(fr, stop, stop_at):
        recs = tp.records(fr, stop, tp.O + stop_at)
        with mock.patch.object(lv, 'window', return_value=window(g['length'])):
            _, trace = new.analyze(recs, tp.COHORT, lv.validate_records(recs, tp.LAY), v1.SCHEDULES)
        keep = {}
        for e in trace['episodes']:
            if int(e['decision_ns']) // new.MS < cut:
                key = (new.encoded(e['schedule']), e['route'], e['decision_ns'])
                keep[key] = [a for a in e['actions'] if int(a['t_ns']) // new.MS < cut]
        return keep
    full = run(frames, 'ws_closed' if g['censored'] else 'window_closed', g['stop_at'])
    short = run([f for f in frames if f[0] - tp.O <= cut], 'ws_closed', cut)
    return full == short, cut


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    failures, cases = [], 0
    for seed in range(300):
        frames, g = v1.generate(seed)
        recs = records_of(frames, g)
        for steps in BUDGETS:
            cases += 1
            if not both(recs, g['length'], v1.SCHEDULES, steps):
                failures.append({'set': 'v1', 'seed': seed, 'steps': steps})
    for seed in range(60):
        frames, g = v1.generate(seed)
        for name, built in (('censor', v2.censor(seed, frames, g)), ('unfilled', v2.unfilled(seed, frames, g))):
            if built is None:
                continue
            for steps in BUDGETS:
                cases += 1
                if not both(records_of(*built), built[1]['length'], v1.SCHEDULES, steps):
                    failures.append({'set': name, 'seed': seed, 'steps': steps})
    recs, span = stress()
    for steps in (None, 100000, 1000000):
        for patches in ((), (('MAX_ATTEMPTS', 2),), (('MAX_EPISODES', 8),)):
            cases += 1
            if not both(recs, span, new.SCHEDULES + new.SENSITIVITIES, steps, patches):
                failures.append({'set': 'stress', 'steps': steps, 'patches': [list(p) for p in patches]})
    causal_fail, cuts = [], 0
    for seed in range(100):
        ok, cut = causal(seed)
        cuts += 1
        if not ok:
            causal_fail.append({'seed': seed, 'cut_ms': cut})
    result = {'schema': 'hip4-pairing-equivalence-v5', 'equivalence_cases': cases, 'equivalence_failures': failures[:12],
              'equivalence_failure_count': len(failures), 'causality_cuts': cuts, 'causality_failures': causal_fail[:12],
              'budgets': [b_ for b_ in BUDGETS], 'result': 'pass' if not failures and not causal_fail else 'fail',
              'v4_snapshot_sha256': new.digest((HERE / 'snapshots' / 'hip4_continuation_pairing_v4.py').read_bytes()),
              'v5_source_sha256': new.digest((ROOT / new.SOURCE).read_bytes()),
              'harness_sha256': new.digest(Path(__file__).read_bytes())}
    data = new.encoded(result)
    if args.write:
        new.h.write_once(OUT, data)
    print(data.decode(), end='')
    return 0 if result['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
