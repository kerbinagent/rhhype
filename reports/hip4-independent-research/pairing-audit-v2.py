#!/usr/bin/env python3
"""Coverage extension of the pairing audit. The v1 harness and its written result stay unchanged.

The v1 random streams never reached entry_censored, entry_unfilled or work_cap. This harness reuses v1's
generator, 100 ms-grid reference and episode comparison on targeted variants of fixed seeds:
- censor: a censoring stop placed 100 to 500 ms after the stream's first reference decision, inside its entry delay;
- unfilled: 200 ms after the first forward-first (FF) and inverse-first (IF) reference decisions, every leg's touch
  moves one cent past its limit, so the entry misses;
- capped: the unmodified stream with the attempt cap lowered to 2 for both engine and reference.
The variants are built from the reference's own decisions on synthetic data; no engine output chooses them.
The audit passes only with zero mismatches and every targeted class present. It reads no raw data, makes no
network call and creates no temp files. With --write it writes one bounded result file, once.
"""
import argparse
import collections
import contextlib
from decimal import Decimal
import importlib.util
from pathlib import Path
import random
import sys
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pairing_audit_v1', HERE / 'pairing-audit-v1.py')
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)
pr, tp = v1.pr, v1.tp
SEEDS = range(120)
TARGETS = ('entry_censored', 'entry_unfilled', 'work_cap')
OUT = HERE / 'pairing-audit-v2-result.json'
ZERO_FEES = pr.SCHEDULES[0]


def rebuild(frames, g, stop_at=None):
    """Recompute the ground truth after a variant: optional earlier censoring stop, injected frames already added."""
    g = dict(g)
    if stop_at is not None:
        g.update(censored=True, stop_at=stop_at)
    g['meta'] = g['meta'] if g['meta'] is not None and g['meta'] <= g['stop_at'] else None
    g['end'] = min(g['length'], g['stop_at'])
    g['ins'] = sorted(at - tp.O for at, _ in frames if at - tp.O <= g['stop_at'])
    g['truth_at'] = {c: [r[0] for r in rows] for c, rows in g['truth'].items()}
    g['views'] = [v1.view_at(g, t) for t in range(0, g['end'], v1.GRID)]
    return g


def first_decisions(g):
    ref = v1.reference(g, ZERO_FEES)
    return {route: [(ep.q, ep) for ep, _ in rows] for route, rows in ref.items()}


def censor(seed, frames, g):
    found = sorted(q for rows in first_decisions(g).values() for q, _ in rows)
    if not found:
        return None
    stop = found[0] + 100 * random.Random(seed).randint(1, 5)
    if stop >= g['length']:
        return None
    return frames, rebuild(frames, g, stop)


def unfilled(seed, frames, g):
    found = first_decisions(g)
    truth = {c: list(rows) for c, rows in g['truth'].items()}
    taken = {(c, r[0]) for c, rows in truth.items() for r in rows}
    extra = []
    for route, rows in found.items():
        if not rows:
            continue
        q, ep = rows[0]
        at = q + 200
        for c, limit in ep.limits.items():
            if (c, at) in taken or not q + 500 < g['end']:
                continue
            if route == 'FF':
                bid = Decimal(limit.numerator) / Decimal(limit.denominator) - Decimal('0.01')
                ask = bid + Decimal('0.01')
            else:
                ask = Decimal(limit.numerator) / Decimal(limit.denominator) + Decimal('0.01')
                bid = ask - Decimal('0.02')
            if bid < Decimal('0.001') or ask > 1:
                continue
            row = (at, str(bid), '10', str(ask), '10')
            truth[c].append(row)
            taken.add((c, at))
            extra.append(tp.bbo(c, at, row[1], row[3], age=v1.AGE))
    if not extra:
        return None
    for c in truth:
        truth[c].sort()
    frames = sorted(frames + extra, key=lambda f: f[0])
    return frames, rebuild(frames, dict(g, truth=truth))


def run_variant(seed, built, patches=()):
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(v1, 'generate', return_value=built))
        for name, value in patches:
            stack.enter_context(mock.patch.object(pr, name, value))
        problems, compared, classes, _ = v1.audit(seed)
    return problems, compared, classes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    problems, compared, classes, variants = [], 0, collections.Counter(), collections.Counter()
    for seed in SEEDS:
        frames, g = v1.generate(seed)
        for name, built, patches in (('censor', censor(seed, frames, g), ()),
                                     ('unfilled', unfilled(seed, frames, g), ()),
                                     ('capped', (frames, g), (('MAX_ATTEMPTS', 2),))):
            if built is None:
                continue
            variants[name] += 1
            p, n, c = run_variant(seed, built, patches)
            problems += [dict(x, variant=name) for x in p]
            compared += n
            classes.update(c)
    present = all(classes[k] for k in TARGETS)
    result = {'schema': 'hip4-pairing-audit-v2', 'seeds': [SEEDS.start, SEEDS.stop], 'variants': dict(sorted(variants.items())),
              'schedules': len(v1.SCHEDULES), 'episodes_compared': compared,
              'class_coverage': {k: classes[k] for k in pr.CLASSES}, 'targets_present': present,
              'mismatches': len(problems), 'first_mismatches': problems[:12],
              'result': 'pass' if not problems and present else 'fail',
              'engine_pins': {rel: pr.digest((pr.ROOT / rel).read_bytes()) for rel in (pr.SOURCE, pr.TEST)},
              'harness_sha256': {'v1': pr.digest((HERE / 'pairing-audit-v1.py').read_bytes()),
                                 'v2': pr.digest(Path(__file__).read_bytes())}}
    data = pr.encoded(result)
    if args.write:
        pr.h.write_once(OUT, data)
    print(data.decode(), end='')
    return 0 if result['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
