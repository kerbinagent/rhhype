#!/usr/bin/env python3
"""Independent audit of the HIP-4 pairing engine (queue item 2), fixed before any Q357 data is read.

A reference simulator on a 100 ms grid, written from spec revision 4, is compared episode by episode with the
engine on seeded random synthetic streams. It does not use the engine's segments, snapshots, gates, fills or
episode code. Every instant in these streams lies on the grid (frames, 1,000 ms qualification, 500 ms
evaluation, 35,000 ms liveness), so grid stepping is exact. The usable view comes from the generator's own
ground truth: fresh bbo frames only (source age 300 ms), acknowledgements complete, liveness from the last
inbound frame, and invalidation from a questionSettled update. A locked or crossed member frame (bid >= ask)
suspends that coin until its next valid frame, as the frozen kernel's parse rule does.

Harness revisions (dry runs only, nothing written; no engine code changed in response to either):
- revision 1: the first dry run treated locked frames as valid, and every mismatch traced to that omission;
- revision 2: the reference aged a suspended coin's rejected frame, while the engine (correctly) reports ages
  only for accepted touches in force.

Seeds and schedules are fixed, and the audit passes only with zero mismatches. It reads no raw data, makes no
network call and creates no temp files. With --write it writes one bounded result file, once.
"""
import argparse
import bisect
import collections
import datetime as dt
from decimal import Decimal
from fractions import Fraction as Fr
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_pairing as pr  # noqa: E402
from tests import test_hip4_continuation_pairing as tp  # noqa: E402  (record builders only)

lv = pr.lv
SEEDS = range(300)
AUDIT_ONLY = {'f': '0.003', 'c_split': '0.001', 'c_neg': '0.002', 'c_merge': '0.0005'}  # exercises every fee term
SCHEDULES = pr.SCHEDULES + pr.SENSITIVITIES + (AUDIT_ONLY,)
GRID, QUAL, DELTA, CARRY, AGE = 100, 1000, 500, 35000, 300  # ms
OUT = ROOT / 'reports/hip4-independent-research/pairing-audit-v1-result.json'
F, A, D, B2 = tp.F, tp.A, tp.D, tp.B2
COINS, NAMED = sorted(tp.LAY['coins']), [A, D, B2]
SIZES = ('0.4', '1', '1.7', '3', '10', '25.9', '100')
OPEN = {'censored': 'censored_open', 'invalidated': 'invalidated_open', 'window_end': 'open_at_window_end'}
ENTRY = {'censored': 'entry_censored', 'invalidated': 'entry_invalidated', 'window_end': 'entry_after_close'}


# ---- seeded synthetic streams with ground truth --------------------------------------------------------------

def thousandths(k):
    return str(Decimal(k) / 1000)


def generate(seed):
    rng = random_for(seed)
    length = rng.choice((60000, 90000))
    fb = ('0.01', '0.03') if rng.random() < 0.2 else (None, None)
    truth = {F: [(-50000, fb[0], '10', fb[1], '10')], A: [(-50000, '0.30', '10', '0.31', '10')],
             D: [(-50000, '0.25', '10', '0.26', '10')], B2: [(-50000, '0.44', '10', '0.45', '10')]}
    frames, used = [], set()
    base = {A: 300, D: 250, B2: 450}
    for _ in range(rng.randint(8, 50)):
        c, at = rng.choice([A, D, B2] * 4 + [F]), rng.randrange(0, length, GRID)
        if (c, at) in used:
            continue
        used.add((c, at))
        if c == F:
            bid, ask = rng.choice((None, '0.01', '0.02')), rng.choice((None, '0.03', '0.05'))
        else:
            k = base[c] + rng.randint(-25, 25)
            bid, ask = thousandths(k), thousandths(k + rng.choice((0, 5, 10, 10, 20)))
            bid = None if rng.random() < 0.06 else bid
            ask = None if rng.random() < 0.06 else ask
        bsz, asz = rng.choice(SIZES), rng.choice(SIZES)
        frames.append(tp.bbo(c, at, bid, ask, bsz, asz, age=AGE))
        truth[c].append((at, bid, bsz, ask, asz))  # a locked or crossed pair is kept and marks the coin suspended
    beats, t = [], -30000
    while t < length:
        beats.append(t)
        t += rng.choice((10000, 20000, 30000, 30000, 45000))
    frames += [(tp.O + t, {'channel': 'pong'}) for t in beats]
    meta = rng.randrange(0, length, GRID) if rng.random() < 0.2 else None
    if meta is not None:
        frames.append(tp.meta(meta, {'questionSettled': pr.QUESTION}))
    censored = rng.random() < 0.35
    stop_at = rng.randrange(5000, length, GRID) if censored else length
    meta = meta if meta is not None and meta <= stop_at else None
    lead = tp.lead(fb)
    frames = sorted(lead + frames, key=lambda f: f[0])
    end = min(length, stop_at)
    ins = sorted(at - tp.O for at, _ in frames if at - tp.O <= stop_at)
    for c in truth:
        truth[c].sort()
    g = {'length': length, 'censored': censored, 'stop_at': stop_at, 'meta': meta, 'end': end, 'ins': ins,
         'truth': truth, 'truth_at': {c: [r[0] for r in rows] for c, rows in truth.items()}}
    g['views'] = [view_at(g, t) for t in range(0, end, GRID)]
    return frames, g


def random_for(seed):
    import random
    return random.Random(seed)


def view_at(g, t):
    """Usable view from ground truth: acked, live (last inbound frame + 35 s), uninvalidated, before the end."""
    if not 0 <= t < g['end'] or (g['meta'] is not None and t >= g['meta']):
        return {}
    k = bisect.bisect_right(g['ins'], t)
    if k == 0 or t >= g['ins'][k - 1] + CARRY:
        return {}
    view = {}
    for c in COINS:
        i = bisect.bisect_right(g['truth_at'][c], t) - 1
        if i >= 0:
            at, bid, bsz, ask, asz = g['truth'][c][i]
            if suspended(g['truth'][c][i]):
                continue  # until the coin's next valid frame
            view[c] = ((Fr(bid), Fr(bsz)) if bid else None, (Fr(ask), Fr(asz)) if ask else None, at)
    return view


def suspended(row):
    return bool(row[1] and row[3] and Fr(row[1]) >= Fr(row[3]))


def ages(g, t, coins):
    """Per accepted leg [source age, receipt age]; a suspended coin has no accepted touch in force."""
    rows = {c: g['truth'][c][bisect.bisect_right(g['truth_at'][c], t) - 1] for c in coins}
    return {c: [t - r[0] + AGE, t - r[0]] for c, r in rows.items() if not suspended(r)}


def event_bound(g):
    events = [(g['length'], 2, 'window_end')]
    events += [(g['stop_at'], 0, 'censored')] if g['censored'] else []
    events += [(g['meta'], 1, 'invalidated')] if g['meta'] is not None else []
    return min(events)


# ---- reference policy (spec revision 4) -----------------------------------------------------------------------

def ff_key(v, phi):
    if any(c not in v for c in NAMED):
        return None
    sold = tuple(c for c in COINS if c in v and v[c][0] is not None)
    if sold and sum(v[c][0][0] for c in sold) * (1 - phi['f']) > 1 + phi['c_split'] + phi['c_neg']:
        return sold
    return None


def if_key(v, phi):
    if any(c not in v or v[c][1] is None for c in NAMED):
        return None
    return ('IF',) if 1 - phi['c_split'] - phi['c_merge'] - sum(v[c][1][0] for c in NAMED) > 0 else None


def decisions(g, key_fn):
    out, key0, start, done = [], None, None, False
    for i, v in enumerate(g['views']):
        t, key = i * GRID, key_fn(v)
        if key != key0:
            key0, start, done = key, (t if key is not None else None), False
        if key is not None and not done and t == start + QUAL:
            done = True
            out.append((t, key))
    return out


class Ref:
    def __init__(self, route, q, key, phi, g):
        self.route, self.q, self.key, self.phi, self.g = route, q, key, phi, g
        v = g['views'][q // GRID]
        legs, side = (list(key), 0) if route == 'FF' else (NAMED, 1)
        self.limits = {c: v[c][side][0] for c in legs}
        self.m = min(int(v[c][side][1]) for c in legs)
        self.decision_ages = ages(g, q, legs)
        self.hold = dict.fromkeys(COINS + ['NO_F'], 0)
        self.cash = self.low = Fr(0)
        self.log, self.zero = [], collections.Counter()
        self.attempts = self.misses = self.partials = 0

    def post(self, t, act, cash, detail):
        self.cash += cash
        self.low = min(self.low, self.cash)
        self.log.append(dict(detail, act=act, t=t, cash=cash))

    def convert(self, t, kind, n):
        if n <= 0:
            return
        p, h = self.phi, self.hold
        if kind == 'make':
            cash = -n * (1 + p['c_split'] + p['c_neg'])
            for c in COINS:
                h[c] += n
        elif kind == 'merge':
            cash = n * (1 - p['c_merge'])
            for c in COINS:
                h[c] -= n
        elif kind == 'split':
            cash = -n * (1 + p['c_split'])
            h[F] += n
            h['NO_F'] += n
        else:
            cash = -n * p['c_neg']
            h['NO_F'] -= n
            for c in NAMED:
                h[c] += n
        self.post(t, kind, cash, {'n': n})

    def trade(self, t, kind, want, limits):
        v, side = self.g['views'][t // GRID], 0 if kind == 'sell' else 1
        qty, px = {}, {}
        for c, n in want.items():
            level = v[c][side] if c in v else None
            if level is None:
                self.zero['not_usable'] += 1
            elif (level[0] < limits[c]) if kind == 'sell' else (level[0] > limits[c]):
                self.zero['limit'] += 1
            elif min(n, int(level[1])) <= 0:
                self.zero['size'] += 1
            else:
                qty[c], px[c] = min(n, int(level[1])), level[0]
        detail = {'ages': ages(self.g, t, list(want))}
        if not qty:
            self.post(t, 'miss_' + kind, Fr(0), detail)
            return qty
        value = sum(qty[c] * px[c] for c in qty)
        for c in qty:
            self.hold[c] += -qty[c] if kind == 'sell' else qty[c]
        self.post(t, kind, value * (1 - self.phi['f']) if kind == 'sell' else -value, dict(detail, qty=qty))
        return qty

    def flat(self):
        return not any(self.hold.values())

    def owed(self):
        if self.route == 'FF':
            top = max(self.hold[c] for c in COINS)
            return {c: top - self.hold[c] for c in COINS if top > self.hold[c]}
        return {c: self.hold[c] + self.hold['NO_F'] for c in NAMED if self.hold[c] + self.hold['NO_F'] > 0}

    def gate(self, v):
        owed, p = self.owed(), self.phi
        if self.route == 'FF':
            if any(c not in v or v[c][1] is None for c in owed):
                return False
            return max(self.hold[c] for c in COINS) * (1 - p['c_merge']) - sum(n * v[c][1][0] for c, n in owed.items()) >= 0
        if any(c not in v or v[c][0] is None for c in owed):
            return False
        return sum(n * v[c][0][0] for c, n in owed.items()) * (1 - p['f']) - self.hold['NO_F'] * p['c_neg'] + self.cash >= 0

    def enter(self, x):
        if self.route == 'FF':
            self.convert(x, 'make', self.m)
            sold = self.trade(x, 'sell', {c: self.m for c in self.key}, self.limits)
            self.convert(x, 'merge', min(self.hold[c] for c in COINS))
            return bool(sold)
        bought = self.trade(x, 'buy', {c: self.m for c in NAMED}, self.limits)
        both = min(bought.get(c, 0) for c in NAMED)
        self.convert(x, 'split', both)
        self.convert(x, 'merge', both)
        return bool(bought)

    def attempt(self, t, limits):
        before = dict(self.hold)
        self.attempts += 1
        if self.route == 'FF':
            self.trade(t, 'buy', self.owed(), limits)
            self.convert(t, 'merge', min(self.hold[c] for c in COINS))
        else:
            self.convert(t, 'negate', self.hold['NO_F'])
            self.trade(t, 'sell', self.owed(), limits)
        changed = self.hold != before
        self.misses += not changed
        self.partials += changed and not self.flat()
        return changed

    def run(self, x, e):
        if not self.enter(x):
            return 'entry_unfilled'
        if self.flat():
            return 'entry_closed'
        start, done, pending, limits, t = None, False, None, None, x
        while t < self.g['end']:
            if pending is not None and t == pending:
                if t >= e[0]:
                    break
                changed, pending = self.attempt(t, limits), None
                if self.flat():
                    return 'closed'
                if self.attempts >= pr.MAX_ATTEMPTS:
                    return 'work_cap'
                if changed:
                    start, done = None, False
            v = self.g['views'][t // GRID]
            if v and self.gate(v):
                if start is None:
                    start, done = t, False
                if not done and t == start + QUAL:
                    side = 1 if self.route == 'FF' else 0
                    done, pending, limits = True, t + DELTA, {c: v[c][side][0] for c in self.owed()}
            else:
                start, done = None, False
            t += GRID
        return OPEN[e[2]]


def reference(g, schedule):
    phi, e, out = {k: Fr(v) for k, v in schedule.items()}, event_bound(g), {}
    for route, key_fn in (('FF', ff_key), ('IF', if_key)):
        rows = []
        for q, key in decisions(g, lambda v: key_fn(v, phi)):
            ep, x = Ref(route, q, key, phi, g), q + DELTA
            cls = 'not_admitted_size' if ep.m < 1 else ENTRY[e[2]] if x >= e[0] else ep.run(x, e)
            rows.append((ep, cls))
        out[route] = rows
    return out


# ---- comparison -------------------------------------------------------------------------------------------------

def ms(ns):
    return int(ns) // pr.MS


def fr(text):
    return Fr(str(text))


def expected(ep, cls):
    rec = {'decision_ms': ep.q, 'key': list(ep.key), 'm': ep.m, 'class': cls, 'v': ep.cash, 'capital': -ep.low,
           'hold': dict(ep.hold), 'attempts': ep.attempts, 'all_miss': ep.misses, 'partial': ep.partials,
           'zero_fills': dict(ep.zero), 'decision_ages': ep.decision_ages,
           'actions': [(a['act'], a['t'], a['cash'], a.get('n'), a.get('qty'), a.get('ages')) for a in ep.log]}
    if cls in OPEN.values():
        w = max(ep.hold[c] for c in COINS) if ep.route == 'FF' else max(ep.hold[c] + ep.hold['NO_F'] for c in NAMED)
        rec['envelope'] = [ep.cash, ep.cash + w * (1 - ep.phi['f'])]
    return rec


def observed(rec):
    out = {'decision_ms': ms(rec['decision_ns']), 'key': rec['key'], 'm': rec['m'], 'class': rec['class'],
           'v': fr(rec['v']), 'capital': fr(rec['capital']), 'hold': {c: int(n) for c, n in rec['hold'].items()},
           'attempts': rec['attempts'], 'all_miss': rec['all_miss'], 'partial': rec['partial'],
           'zero_fills': {k: int(n) for k, n in rec['zero_fills'].items()}, 'decision_ages': rec['decision_ages'],
           'actions': [(a['act'], ms(a['t_ns']), fr(a['cash']), a.get('n'),
                        {c: int(n) for c, n in a['qty'].items()} if 'qty' in a else None, a.get('ages'))
                       for a in rec['actions']]}
    if 'envelope' in rec:
        out['envelope'] = [fr(x) for x in rec['envelope']]
    return out


def audit(seed):
    frames, g = generate(seed)
    recs = tp.records(frames, 'ws_closed' if g['censored'] else 'window_closed', tp.O + g['stop_at'])
    win = dict(tp.WIN, close=tp.WIN['open'] + dt.timedelta(milliseconds=g['length']))
    with mock.patch.object(lv, 'window', return_value=win):
        projection, trace = pr.analyze(recs, tp.COHORT, lv.validate_records(recs, tp.LAY), SCHEDULES)
    problems, compared, classes = [], 0, collections.Counter()
    if trace['episodes_kept'] != trace['episodes_total']:
        problems.append({'seed': seed, 'field': 'trace_truncated'})
    for s, schedule in enumerate(SCHEDULES):
        ref = reference(g, schedule)
        for route in pr.ROUTES:
            got = [observed(r) for r in trace['episodes'] if r['route'] == route and r['schedule'] == schedule]
            want = [expected(ep, cls) for ep, cls in ref[route]]
            summary = next(r for r in projection['results'] if r['route'] == route and r['schedule'] == schedule)
            counts = collections.Counter(w['class'] for w in want)
            if summary['classes'] != {k: counts[k] for k in pr.CLASSES}:
                problems.append({'seed': seed, 'schedule': s, 'route': route, 'field': 'class_counts',
                                 'engine': summary['classes'], 'reference': dict(counts)})
            if len(got) != len(want):
                problems.append({'seed': seed, 'schedule': s, 'route': route, 'field': 'episode_count',
                                 'engine': [x['decision_ms'] for x in got], 'reference': [x['decision_ms'] for x in want]})
                continue
            for i, (x, y) in enumerate(zip(got, want)):
                compared += 1
                classes[y['class']] += 1
                for field in y:
                    if x.get(field) != y[field]:
                        e, r = x.get(field), y[field]
                        if field == 'actions' and isinstance(e, list):
                            k = next((j for j, (u, w) in enumerate(zip(e, r)) if u != w), min(len(e), len(r)))
                            e, r, field = e[k:k + 1], r[k:k + 1], f'actions[{k}]'
                        problems.append({'seed': seed, 'schedule': s, 'route': route, 'episode': i, 'field': field,
                                         'engine': str(e)[:400], 'reference': str(r)[:400]})
    return problems, compared, classes, g


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    problems, compared, classes, kinds = [], 0, collections.Counter(), collections.Counter()
    for seed in SEEDS:
        p, n, c, g = audit(seed)
        problems += p
        compared += n
        classes.update(c)
        kinds.update(['censored' if g['censored'] else 'window_closed', 'invalidated' if g['meta'] is not None else 'valid'])
    result = {'schema': 'hip4-pairing-audit-v1', 'seeds': [SEEDS.start, SEEDS.stop], 'schedules': list(SCHEDULES),
              'streams': len(SEEDS), 'stream_kinds': dict(sorted(kinds.items())), 'episodes_compared': compared,
              'class_coverage': {k: classes[k] for k in pr.CLASSES}, 'mismatches': len(problems),
              'first_mismatches': problems[:12], 'result': 'pass' if not problems and compared else 'fail',
              'engine_pins': {rel: pr.digest((ROOT / rel).read_bytes()) for rel in (pr.SOURCE, pr.TEST)},
              'audit_source_sha256': pr.digest(Path(__file__).read_bytes())}
    data = pr.encoded(result)
    if args.write:
        pr.h.write_once(OUT, data)
    print(data.decode(), end='')
    return 0 if result['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
