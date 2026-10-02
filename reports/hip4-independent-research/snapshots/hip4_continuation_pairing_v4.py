#!/usr/bin/env python3
"""HIP-4 continuation pairing v1: offline funded replay of the revision-4 pairing policy on one fixed
live-v1 bundle (prospective Q357).

Default is dry: no raw read, no write, no network. A run needs the exact sha256 of a plan sealed under
the owned independent-research path and of a local input seal that pins one admitted live-v1 bundle
(--admit with the primary plan sha256, after the declared close and a terminal supervisor). The bundle is
replayed through an isolated decorated copy
of the pinned live-v1 causal kernel. The run is refused unless the copy's undecorated output equals the
unchanged kernel's on the same records. Funded forward-first (FF) and named-only inverse-first (IF)
episodes are then simulated under an explicit whole-token floor. Every evaluation is a displayed
conditional evaluation: there is no fill, executability, USD or profit claim, and zero fees are optimistic.
Spec: reports/hip4-research-continuation/pairing-spec-v1.md (revision 4)
Design: reports/hip4-research-continuation/pairing-design.txt
"""
from __future__ import annotations

import argparse
import bisect
import collections
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_live as lv  # pinned causal kernel: read-only use, no global mutation

b, h, pm = lv.b, lv.h, lv.pm
Refusal = pm.Refusal
digest, encoded, bounded_read, note = pm.digest, pm.encoded, pm.bounded_read, lv.note
ZERO, ONE, MS = b.ZERO, b.ONE, lv.MS

INDEPENDENT = 'reports/hip4-independent-research'
PLAN_RELS = {'primary': INDEPENDENT + '/pairing-plan-primary-v4.json',
             'sensitivity': INDEPENDENT + '/pairing-plan-sensitivity-v4.json'}  # sealed locally, owned path
PLANS = {role: ROOT / rel for role, rel in PLAN_RELS.items()}
PENDING = ROOT / INDEPENDENT  # every run stages in an owned sibling directory on the same filesystem
SEAL = ROOT / INDEPENDENT / 'q357-input-seal-v1.json'
LIVE_OUT = 'reports/hip4-research-continuation/live-v1'
LIVE_FILES = ('claim.json', 'terminal.json', 'supervisor.json', 'projection.json')
SCHEMA, SEAL_SCHEMA = 'hip4-pairing-v1', 'hip4-pairing-input-seal-v1'
SOURCE = 'scripts/hip4_continuation_pairing.py'
TEST = 'tests/test_hip4_continuation_pairing.py'
PINNED = (SOURCE, TEST, lv.SOURCE, lv.TEST, b.SOURCE, h.SOURCE, h.HELPER)
CHAIN = ('reports/hip4-research-continuation/pairing-spec-v1.md', 'reports/hip4-research-continuation/pairing-v1.md',
         'reports/hip4-research-continuation/pairing-design.txt',
         'reports/experiment-storage/hip4-pairing-preparation-allocation-v1.json',
         'reports/experiment-storage/independent-research-ownership-v1.json')
RAM_BYTES, CPU_S, WALL_S = 4294967296, 600, 900  # hard child limits: address space, CPU seconds, wall seconds
KILL_JOIN_S, PLAN_CAP, SEAL_CAP = 30, 65536, 8192
SUPERVISOR_MISSING_S = lv.SUPERVISOR_GRACE_S + 3600  # after the declared close, a missing supervisor is unavailable
LIVE_PLAN = 'reports/experiment-storage/hip4-continuation-live-v1.json'
LIVE_PLAN_SHA = '982619f2837589e06146e9608fbf859db4fa3661d3f31fd1e7c1a66d36ee74c9'
QUESTION = 357
OUTS = {'primary': 'reports/hip4-research-continuation/pairing-v1-run',
        'sensitivity': INDEPENDENT + '/pairing-sensitivity-run'}
QUAL_NS, DELTA_NS = lv.MIN_DURATION_MS * MS, 500 * MS
# records: a framed record is at least 184 bytes, so lv.RAW_LIMIT admits at most 364,722; the cap never binds first
MAX_RECORDS, MAX_EPISODES, MAX_ATTEMPTS, MAX_STEPS = 370000, 256, 32, 20000000
# Per-role shares of the ONE shared grant (derived_episode_trace 786432 B, projection 131072 B); retained, staged and
# failed outputs of a role all count against its share. Trace caps stay within the strict JSON decoder's body cap.
CATEGORY_BYTES = {'trace': 786432, 'projection': 131072}
ROLE_LIMITS = {'primary': {'trace': 524288, 'projection': 65536, 'receipts': 8192},
               'sensitivity': {'trace': 262144, 'projection': 65536, 'receipts': 8192}}
assert all(sum(r[k] for r in ROLE_LIMITS.values()) <= CATEGORY_BYTES[k] for k in CATEGORY_BYTES)
assert all(r['trace'] <= pm.BODY_CAP and r['projection'] <= pm.BODY_CAP for r in ROLE_LIMITS.values())
ROUTES = ('FF', 'IF')
CLASSES = ('not_admitted_size', 'entry_censored', 'entry_invalidated', 'entry_after_close', 'entry_unfilled',
           'entry_closed', 'closed', 'censored_open', 'invalidated_open', 'open_at_window_end', 'work_cap')
OPEN_CLASSES = {'censored': 'censored_open', 'invalidated': 'invalidated_open', 'window_end': 'open_at_window_end'}
ENTRY_CLASSES = {'censored': 'entry_censored', 'invalidated': 'entry_invalidated', 'window_end': 'entry_after_close'}
FEE_KEYS = ('f', 'c_split', 'c_neg', 'c_merge')
SCHEDULES = ({'f': '0', 'c_split': '0', 'c_neg': '0', 'c_merge': '0'},)  # primary: zero fees, optimistic
SENSITIVITIES = ({'f': '0.001', 'c_split': '0', 'c_neg': '0', 'c_merge': '0'},
                 {'f': '0.005', 'c_split': '0', 'c_neg': '0', 'c_merge': '0'},
                 {'f': '0', 'c_split': '0.0005', 'c_neg': '0.0005', 'c_merge': '0.0005'})  # arbitrary points, not estimates
ROLE_SCHEDULES = {'primary': SCHEDULES, 'sensitivity': SENSITIVITIES}
ANALYSIS_PLAN = {
    'kernel': 'isolated decorated copy of the pinned live-v1 replay; its undecorated output must equal the '
              'unchanged kernel on the same records or the run is refused; added outputs: per-mark usable view, '
              'accepted source time and receipt time per coin',
    'gates': 'maximal half-open intervals of a continuously true predicate (key, support, economic test), '
             'evaluated at frames, liveness expiries and the episode\'s own state changes; qualification at '
             'start + 1000 ms strictly before the end; one evaluation per interval at qualification + 500 ms '
             'on the causal state only; frames at an instant precede evaluation; e = min(censoring stop, '
             'invalidation, window close) blocks any evaluation at or after it',
    'entry': 'one global episode per maximal qualifying entry interval for each route and fee schedule; '
             'episode state changes restart only that episode\'s closure gates; an all-miss attempt with no '
             'state change cannot retry until its predicate is false then true',
    'units': 'conditional one-token granularity: displayed sizes floored to whole tokens for m and fills; '
             'admission needs integer m >= 1; quote-token cash only',
    'fees': 'one schedule per replay with 0 <= f <= 1 and conversion fees >= 0; schedules enter every gate; '
            'zero fees optimistic; no component repricing',
    'capital': 'negative chronological minimum of each episode\'s cash prefix, unlimited prefunding convention; '
               'per episode only, never a portfolio sum',
    'classes': list(CLASSES),
    'caps': {'records': MAX_RECORDS, 'episodes_per_route_schedule': MAX_EPISODES,
             'attempts_per_episode': MAX_ATTEMPTS, 'scan_steps': MAX_STEPS, 'ram_bytes': RAM_BYTES,
             'cpu_seconds': CPU_S, 'wall_seconds': WALL_S, 'kill_join_seconds': KILL_JOIN_S,
             'role_output_bytes': ROLE_LIMITS, 'category_bytes': CATEGORY_BYTES},
    'retention': 'at most MAX_EPISODES episode objects per route and schedule; later decisions are counted as '
                 'unbuilt work_cap without allocation; each episode is reconciled and tallied as it ends; the trace '
                 'keeps an exact encoded prefix within its role share; failed runs keep their bounded staged '
                 'outputs renamed not-admitted-* beside an unavailable receipt',
    'rates': 'exact only for a complete scan without unbuilt overflow; unbuilt overflow has unknown size admission, '
             'so its rate pairs are conservative bounds that may be undefined; an incomplete scan makes every '
             'full-window rate unavailable and labels any prefix rates prefix_only, never a full-window result',
    'admission': 'only after the declared Q357 close and a terminal supervisor; the pairing plan chain is '
                 'authenticated before the first capture read; the live-v1 checks run in a child under the same '
                 'hard limits; the seal is written once, admitted or unavailable',
    'claims': 'displayed conditional evaluation of causally reachable states; no fill, executability, USD, '
              'collateral identity or profit claim; work caps are unknown, never negative',
}


# ---- decorated kernel copy -------------------------------------------------------------------------------

def decorated_replay(records, lay, win, against=None):
    """The pinned lv.replay loop, statement for statement, plus one snap per mark: (usable view, accepted
    (source time, receipt) per viewed coin, acked). Snap objects are reused while unchanged. With `against`
    (the kernel's output), every mark is compared as it is produced and only (live, bad) is kept."""
    anchor = next((r for r in records if (r['kind'], r['label']) == ('event', 'ws_open')), records[0])
    off = anchor['wall_ms'] * MS - anchor['mono_ns']
    s = {'acks': collections.Counter(), 'anomalies': collections.Counter(), 'gates': collections.Counter(),
         'probe': collections.Counter(), 'accepted': collections.Counter(), 'echoes': {}, 'meta': [], 'marks': [],
         'pongs': 0, 'r_meta': None, 'r_false': None, 'stop': None, 'anchor': anchor['index'], 'off': off,
         'open': lv.ms(win['open']) * MS - off, 'close': lv.ms(win['close']) * MS - off}
    state, sus, last, streak, probe_sus, probe_gate, last_in = {}, set(), {}, 0, False, False, None
    members, acc, snaps, prev = set(lay['coins']), {}, [], (None, None, None)
    for r in records:
        t = r['mono_ns']
        if (r['kind'], r['label']) == ('event', 'stop'):
            s['stop'] = r
        if r['kind'] != 'in':
            continue
        if r['label'] in ('text', 'binary'):
            last_in = t
        channel = data = None
        if r['label'] != 'text':
            note(s['anomalies'], f"frame_{r['label']}")
            sus |= members
        else:
            try:
                obj = pm.strict_json(r['body'])
                channel, data = obj['channel'], obj.get('data')
            except Exception:
                note(s['anomalies'], 'invalid_json')
                sus |= members
            else:
                if not isinstance(channel, str) or not channel:
                    note(s['anomalies'], 'channel_invalid')
                    sus |= members
                    channel = None
        if channel == 'subscriptionResponse':
            sub = data.get('subscription') if isinstance(data, dict) else None
            match = [i for i, x in enumerate(lay['subs']) if isinstance(sub, dict) and data.get('method') == 'subscribe'
                     and all(sub.get(k) == v for k, v in x.items())
                     and all(k in x or k in ('nSigFigs', 'mantissa', 'fast') for k in sub)]
            if len(match) == 1:
                s['acks'][match[0]] += 1
                extra = {k: sub[k] for k in sorted(sub) if k not in lay['subs'][match[0]]}
                if extra:
                    s['echoes'][match[0]] = encoded(extra).decode().strip()[:200]
            else:
                note(s['anomalies'], 'unexpected_ack')
        elif channel == 'bbo':
            try:
                coin, tm, bid, ask = lv.parse_bbo(data, lay['coins'])
            except (ValueError, Refusal) as exc:
                note(s['anomalies'], str(exc))
                coin = data.get('coin') if isinstance(data, dict) else None
                if coin in lay['coins']:
                    sus.add(coin)
                elif not isinstance(coin, str):
                    sus |= members
            else:
                verdict = lv.gate(last, ('bbo', coin), tm, (bid, ask), t + off)
                if verdict is None:
                    state[coin] = (tm, bid, ask)
                    acc[coin] = (tm, t)  # decoration: accepted source time and receipt
                    sus.discard(coin)
                    s['accepted'][coin] += 1
                else:
                    s['gates'][f'bbo_{verdict}'] += 1
                    if verdict != 'repeat':
                        sus.add(coin)
        elif channel == 'l2Book':
            try:
                book = b.parse_book(data, lay['probe'])
            except (ValueError, Refusal):
                note(s['anomalies'], 'l2book_invalid')
                probe_gate = True
            else:
                top = (book['bids'][0] if book['bids'] else None, book['asks'][0] if book['asks'] else None)
                verdict, cur = lv.gate(last, ('l2Book', lay['probe']), book['time'], top, t + off), state.get(lay['probe'])
                cls = None
                if verdict is not None:
                    s['gates'][f'l2Book_{verdict}'] += 1
                    probe_gate = probe_gate or verdict != 'repeat'
                else:
                    probe_gate = False
                    cls = ('unknown' if cur is None or lay['probe'] in sus else 'superseded' if cur[0] > book['time']
                           else 'match' if cur[1:] == top else 'mismatch')
                    s['probe'][cls] += 1
                if cls == 'match':
                    streak, probe_sus = 0, False
                elif cls == 'mismatch':
                    s['probe']['suspensions'] += not probe_sus
                    streak, probe_sus = streak + 1, True
                    if streak >= 2 and s['r_false'] is None:
                        s['r_false'] = t
        elif channel == 'outcomeMetaUpdates':
            labels = lv.meta_relevance(data, lay)
            if labels is None:
                note(s['anomalies'], 'meta_update_unparsed')
            s['meta'] += [{'index': r['index'], 'event': label} for label in labels or []]
            if (labels is None or labels) and s['r_meta'] is None:
                s['r_meta'] = t
        elif channel == 'pong':
            s['pongs'] += 1
        elif channel == 'error':
            note(s['anomalies'], 'channel_error')
            sus |= members
        elif channel is not None:
            note(s['anomalies'], 'channel_unexpected')
            sus |= members
        acked = all(s['acks'][i] == 1 for i in range(len(lay['subs'])))
        view = {c: v[1:] for c, v in state.items()
                if c not in sus and not ((probe_sus or probe_gate) and c == lay['probe'])}
        cash = lv.route_cash(view, lay) if acked else None
        mark = {'live': t if last_in is None else last_in + lv.CARRY_MS * MS,
                'bad': s['r_meta'] is not None or s['r_false'] is not None, 'forward': None, 'inverse_full': None}
        if cash is not None:
            fwd = cash['forward']
            sold = tuple(c for c in sorted(lay['coins']) if c not in fwd['residual'])
            mark['forward'] = ('forward_residual' if fwd['residual'] else 'forward_closed', sold), fwd
            if cash['inverse_full'] is not None:
                mark['inverse_full'] = ('inverse_full', ()), cash['inverse_full']
        if against is None:
            s['marks'].append((t, mark))
        else:
            k = len(s['marks'])
            if k >= len(against['marks']) or against['marks'][k] != (t, mark):
                raise Refusal('kernel_mismatch')
            s['marks'].append((t, {'live': mark['live'], 'bad': mark['bad']}))
        snap = (view, {c: acc[c] for c in view}, acked)
        prev = prev if snap == prev else snap  # share unchanged snapshots
        snaps.append(prev)
    s['snaps'] = snaps
    return s


def undecorated(s):
    return {k: v for k, v in s.items() if k != 'snaps'}


def scalars(s):
    return {k: v for k, v in s.items() if k not in ('marks', 'snaps')}


def kernel_checked(records, lay, win):
    """Decorated replay, refused unless every mark and every other output equals the unchanged pinned kernel
    on the same records; the kernel output is then released."""
    kernel = lv.replay(records, lay, win)
    dec = decorated_replay(records, lay, win, against=kernel)
    if scalars(dec) != scalars(kernel) or len(dec['marks']) != len(kernel['marks']):
        raise Refusal('kernel_mismatch')
    return dec


# ---- causal segments -------------------------------------------------------------------------------------

def segments(dec, stop_ns):
    """Contiguous half-open [a, z) pieces inside [open, min(close, stop)): the usable view (empty unless
    acked, live and uninvalidated) and accepted times in force. Liveness expiry splits a piece without a frame."""
    end, marks, out = min(dec['close'], stop_ns), dec['marks'], []
    for k, ((t, mark), snap) in enumerate(zip(marks, dec['snaps'])):
        nxt = marks[k + 1][0] if k + 1 < len(marks) else stop_ns
        for a, z, live in ((t, min(nxt, mark['live']), True), (max(t, mark['live']), nxt, False)):
            a, z = max(a, dec['open']), min(z, end)
            if a < z:
                usable = live and snap[2] and not mark['bad']
                out.append((a, z, snap[0] if usable else {}, snap[1]))
    return out


def event_bound(dec, stop_reason):
    """(instant, rank, name) of e = min(censoring stop, invalidation, window close); rank breaks equal times."""
    inval = [x for x in (dec['r_meta'], dec['r_false']) if x is not None]
    events = [(dec['close'], 2, 'window_end')]
    events += [(dec['stop']['mono_ns'], 0, 'censored')] if stop_reason != 'window_closed' else []
    events += [(min(inval), 1, 'invalidated')] if inval else []
    return min(events)


class Budget:
    def __init__(self, steps):
        self.left = steps

    def spend(self, n=1):
        self.left -= n
        if self.left < 0:
            raise _Exhausted()


class _Exhausted(Exception):
    pass


def named(lay):
    return [f'#{10 * m}' for m in lay['named']]


def fees(schedule):
    phi = {k: b.decimal_text(schedule[k]) for k in FEE_KEYS}
    if not (ZERO <= phi['f'] <= ONE and all(phi[k] >= ZERO for k in FEE_KEYS[1:])):
        raise Refusal('fee_domain')
    return phi


def ff_key(view, lay, phi):
    if any(c not in view for c in named(lay)):
        return None
    sold = tuple(c for c in sorted(lay['coins']) if c in view and view[c][0] is not None)
    with b.exact():
        g = sum((view[c][0][0] for c in sold), ZERO) * (ONE - phi['f']) - (ONE + phi['c_split'] + phi['c_neg'])
    return sold if sold and g > ZERO else None


def if_key(view, lay, phi):
    if any(c not in view or view[c][1] is None for c in named(lay)):
        return None
    with b.exact():
        g = ONE - phi['c_split'] - phi['c_merge'] - sum((view[c][1][0] for c in named(lay)), ZERO)
    return ('IF',) if g > ZERO else None


def entry_decisions(segs, key_fn, budget):
    """Global entry intervals, yielded lazily: one qualification per maximal interval with a constant key."""
    key0, start, done = None, None, False
    for a, z, view, _ in segs:
        budget.spend()
        key = key_fn(view)
        if key is None or key != key0:
            key0, start, done = key, (a if key is not None else None), False
        if key is not None and not done and a <= start + QUAL_NS < z:
            done = True
            yield start + QUAL_NS, key


class Book:
    """K(x) lookups over the segment list."""

    def __init__(self, segs, off, open_ns):
        self.segs, self.starts, self.off, self.open = segs, [s[0] for s in segs], off, open_ns

    def at(self, x):
        k = bisect.bisect_right(self.starts, x) - 1
        if k < 0 or x >= self.segs[k][1]:
            return {}, {}
        return self.segs[k][2], self.segs[k][3]

    def ages(self, x, coins, seen):
        """Per leg [source age ms, receipt age ms] of the accepted touch in force at x."""
        return {c: [(x + self.off) // MS - seen[c][0], (x - seen[c][1]) // MS] for c in coins if c in seen}


def whole(size):
    return int(size)  # Decimal sizes are positive; int() floors toward zero


def fill(leg, n, limit, side, better):
    """Fill up to n whole tokens on side (0 bid, 1 ask) at the touch if it is no worse than limit."""
    if leg is None or leg[side] is None:
        return 0, None, 'not_usable'
    px, sz, _ = leg[side]
    if not better(px, limit):
        return 0, px, 'limit'
    q = min(n, whole(sz))
    return (q, px, None) if q > 0 else (0, px, 'size')


# ---- episodes ----------------------------------------------------------------------------------------------

class Episode:
    def __init__(self, route, lay, phi, q, key, book):
        self.route, self.lay, self.phi, self.book = route, lay, phi, book
        self.members, self.named = sorted(lay['coins']), named(lay)
        self.q, self.key, self.actions, self.cash, self.low = q, key, [], ZERO, ZERO
        self.attempts, self.misses, self.partials, self.negated = 0, 0, 0, False
        self.zero = collections.Counter()
        self.hold = dict.fromkeys(self.members + ['NO_F'], 0)
        view, seen = book.at(q)
        legs = list(key) if route == 'FF' else self.named
        sides = [view[c][0] if route == 'FF' else view[c][1] for c in legs]
        self.limits = {c: px for c, (px, _, _) in zip(legs, sides)}
        self.m = min(whole(sz) for _, sz, _ in sides)
        self.decision_ages = book.ages(q, legs, seen)

    def act(self, x, kind, cash, **detail):
        with b.exact():
            self.cash += cash
        self.low = min(self.low, self.cash)
        self.actions.append(dict(detail, t_ns=x - self.book.open, act=kind, cash=cash))

    def trade(self, x, kind, want, limits, side, better):
        view, seen = self.book.at(x)
        qty, px, whys = {}, {}, {}
        for c, n in want.items():
            got, price, why = fill(view.get(c), n, limits[c], side, better)
            if why:
                self.zero[why] += 1
                whys[c] = why
            if got:
                qty[c], px[c] = got, price
        if not qty:  # a recorded miss: no cash, no holdings change
            self.act(x, f'miss_{kind}', ZERO, want=dict(want), why=whys, ages=self.book.ages(x, list(want), seen))
        else:
            with b.exact():
                value = sum((qty[c] * px[c] for c in qty), ZERO)
                cash = value * (ONE - self.phi['f']) if kind == 'sell' else -value
            sign = -1 if kind == 'sell' else 1
            for c in qty:
                self.hold[c] += sign * qty[c]
            self.act(x, kind, cash, qty=qty, px=px, why=whys, ages=self.book.ages(x, list(want), seen))
        return qty

    def convert(self, x, kind, n):
        if n <= 0:
            return  # zero-amount conversions are skipped at no cost
        p = self.phi
        with b.exact():
            cash = {'make': -n * (ONE + p['c_split'] + p['c_neg']), 'merge': n * (ONE - p['c_merge']),
                    'split': -n * (ONE + p['c_split']), 'negate': -n * p['c_neg']}[kind]
        fb = self.lay['fallback_coin']
        delta = {'make': {c: n for c in self.members}, 'merge': {c: -n for c in self.members},
                 'split': {fb: n, 'NO_F': n}, 'negate': dict({c: n for c in self.named}, NO_F=-n)}[kind]
        for c, d in delta.items():
            self.hold[c] += d
        self.act(x, kind, cash, n=n)

    def T(self):
        return max(self.hold[c] for c in self.members)

    def flat(self):
        return all(v == 0 for v in self.hold.values())

    # FF ------------------------------------------------------------------------------------------------
    def entry(self, x):
        self.x_entry = x
        if self.route == 'FF':
            self.convert(x, 'make', self.m)
            self.trade(x, 'sell', {c: self.m for c in self.key}, self.limits, 0, lambda px, lim: px >= lim)
            self.convert(x, 'merge', min(self.hold[c] for c in self.members))
            return any(a['act'] == 'sell' for a in self.actions)
        bought = self.trade(x, 'buy', {c: self.m for c in self.named}, self.limits, 1, lambda px, lim: px <= lim)
        mm = min(bought.get(c, 0) for c in self.named)
        self.convert(x, 'split', mm)
        self.convert(x, 'merge', mm)
        return bool(bought)

    def owed(self):
        """FF: legs to buy back (T - h); IF: named legs to sell after any pending negation."""
        if self.route == 'FF':
            t = self.T()
            return {c: t - self.hold[c] for c in self.members if t - self.hold[c] > 0}
        n = self.hold['NO_F']
        return {c: self.hold[c] + n for c in self.named if self.hold[c] + n > 0}

    def gate(self, view):
        owed, p = self.owed(), self.phi
        if self.route == 'FF':
            if any(c not in view or view[c][1] is None for c in owed):
                return False
            with b.exact():
                return self.T() * (ONE - p['c_merge']) - sum((n * view[c][1][0] for c, n in owed.items()), ZERO) >= ZERO
        if any(c not in view or view[c][0] is None for c in owed):
            return False
        with b.exact():
            proceeds = sum((n * view[c][0][0] for c, n in owed.items()), ZERO) * (ONE - p['f'])
            return proceeds - self.hold['NO_F'] * p['c_neg'] + self.cash >= ZERO  # B - R = -cash so far

    def attempt(self, x, limits):
        before = (dict(self.hold), len(self.actions))
        self.attempts += 1
        if self.route == 'FF':
            owed = self.owed()
            self.trade(x, 'buy', owed, limits, 1, lambda px, lim: px <= lim)
            self.convert(x, 'merge', min(self.hold[c] for c in self.members))
        else:
            self.convert(x, 'negate', self.hold['NO_F'])  # a state change even if every sale misses
            self.trade(x, 'sell', self.owed(), limits, 0, lambda px, lim: px >= lim)
        changed = self.hold != before[0]
        self.misses += not changed
        self.partials += changed and not self.flat()
        return changed

    def closed(self):
        return self.flat()


def run_episode(ep, book, segs, x_entry, e, budget):
    """Entry at x_entry, then closure gates restarted only by this episode's own state changes."""
    if not ep.entry(x_entry):
        return 'entry_unfilled'
    if ep.closed():
        return 'entry_closed'
    k = max(0, bisect.bisect_right(book.starts, x_entry) - 1)
    t, start, done, pending, limits = x_entry, None, False, None, None
    while k < len(segs):
        budget.spend()
        a, z, view, _ = segs[k]
        a = max(a, t)
        if pending is not None and pending < z:
            if pending >= e[0]:
                break
            t = pending
            changed = ep.attempt(pending, limits)
            pending = None
            if ep.closed():
                return 'closed'
            if ep.attempts >= MAX_ATTEMPTS:
                return 'work_cap'
            if changed:
                start, done = None, False
            continue
        if view and ep.gate(view):
            if start is None:
                start, done = a, False
            q = start + QUAL_NS
            if not done and a <= q < z:
                done, pending = True, q + DELTA_NS
                gv = book.at(q)[0]
                limits = {c: gv[c][1 if ep.route == 'FF' else 0][0] for c in ep.owed()}
                t = q
                continue
        else:
            start, done = None, False
        t, k = z, k + 1
    return OPEN_CLASSES[e[2]]


class Tally:
    """Streaming per-route summary: every decision is counted, only bounded state is kept."""

    def __init__(self):
        self.count, self.zero = collections.Counter(), collections.Counter()
        self.vs, self.sum_v, self.v_min, self.v_max, self.v_pos = 0, ZERO, None, None, 0
        self.capital, self.attempts, self.misses, self.partials, self.src, self.recv = ZERO, 0, 0, 0, None, None
        self.unbuilt = 0

    def add(self, cls, ep=None):
        self.count[cls] += 1
        if ep is None:  # an unbuilt overflow decision: its size admission and entry class are unknown
            self.unbuilt += 1
            return
        self.attempts, self.misses, self.partials = self.attempts + ep.attempts, self.misses + ep.misses, \
            self.partials + ep.partials
        self.zero.update(ep.zero)
        self.capital = max(self.capital, -ep.low)
        for a in ep.actions:
            for src, recv in a.get('ages', {}).values():
                self.src = src if self.src is None else max(self.src, src)
                self.recv = recv if self.recv is None else max(self.recv, recv)
        if cls not in ('work_cap', 'not_admitted_size'):
            with b.exact():
                self.sum_v += ep.cash
            self.vs += 1
            self.v_min = ep.cash if self.v_min is None else min(self.v_min, ep.cash)
            self.v_max = ep.cash if self.v_max is None else max(self.v_max, ep.cash)
            self.v_pos += ep.cash > ZERO

    def summary(self, complete):
        c = self.count
        filled = sum(c[k] for k in ('entry_closed', 'closed', 'censored_open', 'invalidated_open', 'open_at_window_end'))
        closed, unknown = c['entry_closed'] + c['closed'], c['work_cap']
        admitted = sum(c.values()) - c['not_admitted_size'] - c['entry_censored']
        rates = {'decision_to_fill': [rate(filled, admitted), rate(filled + unknown, admitted)],
                 'closure_within_window': [rate(closed, filled + unknown),
                                           rate(closed + c['censored_open'] + c['invalidated_open'] + unknown,
                                                filled + unknown)],
                 'complete_case_conditional': rate(closed, closed + c['open_at_window_end'])}
        # unbuilt overflow counts as admitted and unknown: the pairs still bound the truth but may be undefined
        status = 'exact' if not self.unbuilt else 'conservative_bounds_possibly_undefined'
        out = {
            'decisions': sum(c.values()) if complete else None, 'decisions_seen': sum(c.values()),
            'decisions_complete': complete, 'classes': {k: c[k] for k in CLASSES}, 'filled': filled,
            'work_cap_unbuilt': self.unbuilt, 'work_cap_built': c['work_cap'] - self.unbuilt,
            'rates_status': status if complete else 'unavailable_incomplete_scan', **dict.fromkeys(rates)}
        if complete:
            out.update(rates)
        else:
            out['prefix_only'] = dict(rates, label='prefix of the window only; never a full-window result',
                                      rates_status=status)
        return dict(out, **{
            'episode_sum_v_overlapping': self.sum_v, 'v_count': self.vs, 'v_min': self.v_min, 'v_max': self.v_max,
            'v_positive': self.v_pos, 'capital_max_per_episode': self.capital, 'attempts': self.attempts,
            'all_miss': self.misses, 'partial': self.partials, 'zero_fills': dict(sorted(self.zero.items())),
            'max_source_age_ms': self.src, 'max_receipt_age_ms': self.recv})


class TraceBuffer:
    """Exact encoded-prefix trace: the wrapper is sized with 16-digit counters; the first record that does not
    fit ends retention, and the final encoding is checked against the cap."""
    SCHEMA_NAME = 'hip4-pairing-trace-v1'

    def __init__(self, cap):
        self.cap, self.kept, self.total, self.open = cap, [], 0, True
        self.size = len(encoded({'episodes': [], 'episodes_kept': 10 ** 15, 'episodes_total': 10 ** 15,
                                 'schema': self.SCHEMA_NAME}))

    def offer(self, rec):
        self.total += 1
        n = len(encoded(rec)) - 1 + (1 if self.kept else 0)
        if self.open and self.size + n <= self.cap:
            self.kept.append(rec)
            self.size += n
        else:
            self.open = False

    def result(self):
        out = {'episodes': self.kept, 'episodes_kept': len(self.kept), 'episodes_total': self.total,
               'schema': self.SCHEMA_NAME}
        if len(encoded(out)) > self.cap:
            raise Refusal('trace_size_accounting')
        return out


def simulate(dec, lay, stop_reason, schedule, budget, trace):
    """All decisions for one fee schedule, both routes. Episodes beyond MAX_EPISODES are counted, never built;
    each built episode is reconciled independently, tallied and offered to the bounded trace as it ends."""
    phi = fees(schedule)
    segs = segments(dec, dec['stop']['mono_ns'])
    book, e = Book(segs, dec['off'], dec['open']), event_bound(dec, stop_reason)
    out = {}
    for route, key_fn in (('FF', lambda v: ff_key(v, lay, phi)), ('IF', lambda v: if_key(v, lay, phi))):
        tally, built, complete = Tally(), 0, True
        try:
            for q, key in entry_decisions(segs, key_fn, budget):
                if built >= MAX_EPISODES or budget.left <= 0:
                    tally.add('work_cap')
                    continue
                built += 1
                ep, x = Episode(route, lay, phi, q, key, book), q + DELTA_NS
                if ep.m < 1:
                    ep.cls = 'not_admitted_size'
                elif x >= e[0]:
                    ep.cls = ENTRY_CLASSES[e[2]]
                else:
                    try:
                        ep.cls = run_episode(ep, book, segs, x, e, budget)
                    except _Exhausted:
                        ep.cls = 'work_cap'
                rec = b.stringify(episode_record(ep))
                check = reconcile(rec, lay, schedule)  # independent recomputation from the action trace
                shape = None if ep.cls == 'work_cap' else ep.cls not in OPEN_CLASSES.values()
                if check['v'] != ep.cash or check['capital'] != -ep.low or check['flat'] != ep.flat() \
                        or shape not in (None, check['flat']):
                    raise Refusal('reconcile_mismatch')
                tally.add(ep.cls, ep)
                trace.offer(dict(rec, schedule=schedule))
        except _Exhausted:
            complete = False
        out[route] = tally.summary(complete)
    return out


# ---- independent reconciliation ---------------------------------------------------------------------------

def reconcile(record, lay, schedule):
    """Recompute cash, holdings, prefix minimum and flatness from the action trace alone."""
    phi, fb = fees(schedule), lay['fallback_coin']
    members, nm = sorted(lay['coins']), named(lay)
    hold, cash, low = dict.fromkeys(members + ['NO_F'], 0), ZERO, ZERO
    with b.exact():
        for a in record['actions']:
            kind = a['act']
            if kind.startswith('miss_'):
                continue
            if kind in ('sell', 'buy'):
                value = sum((Decimal(str(n)) * b.decimal_text(a['px'][c]) for c, n in a['qty'].items()), ZERO)
                cash += value * (ONE - phi['f']) if kind == 'sell' else -value
                for c, n in a['qty'].items():
                    hold[c] += -n if kind == 'sell' else n
            else:
                n = a['n']
                cash += {'make': -n * (ONE + phi['c_split'] + phi['c_neg']), 'merge': n * (ONE - phi['c_merge']),
                         'split': -n * (ONE + phi['c_split']), 'negate': -n * phi['c_neg']}[kind]
                for c in (members if kind in ('make', 'merge') else []):
                    hold[c] += n if kind == 'make' else -n
                if kind == 'split':
                    hold[fb] += n
                    hold['NO_F'] += n
                if kind == 'negate':
                    hold['NO_F'] -= n
                    for c in nm:
                        hold[c] += n
            if min(hold.values()) < 0:
                raise Refusal('reconcile_negative_holding')
            low = min(low, cash)
    return {'v': cash, 'capital': -low, 'hold': hold, 'flat': all(v == 0 for v in hold.values())}


# ---- projection and trace ------------------------------------------------------------------------------------

def rate(num, den):
    """An exact [numerator, denominator] pair; None (unavailable) for a zero denominator; never rounded."""
    return None if den == 0 else [num, den]


def episode_record(ep):
    rec = {'route': ep.route, 'decision_ns': ep.q - ep.book.open, 'key': list(ep.key), 'm': ep.m, 'class': ep.cls,
           'limits': ep.limits, 'decision_ages': ep.decision_ages, 'actions': ep.actions, 'v': ep.cash, 'capital': -ep.low, 'hold': ep.hold,
           'attempts': ep.attempts, 'all_miss': ep.misses, 'partial': ep.partials, 'zero_fills': dict(ep.zero)}
    if ep.cls in OPEN_CLASSES.values():
        f = ep.phi['f']
        with b.exact():
            w = ep.T() if ep.route == 'FF' else max(ep.hold[c] + ep.hold['NO_F'] for c in ep.named)
            rec['envelope'] = [ep.cash, ep.cash + w * (ONE - f)]  # formal, only under A1-A3
    return rec


def analyze(records, cohort, stop_reason, schedules=SCHEDULES, steps=MAX_STEPS, limits=None):
    limits = limits or ROLE_LIMITS['primary']
    if len(records) > MAX_RECORDS:
        raise Refusal('records_over_cap')
    lay, win = lv.layout(cohort, QUESTION), lv.window(QUESTION)
    dec = kernel_checked(records, lay, win)
    budget, results, trace = Budget(steps), [], TraceBuffer(limits['trace'])
    for schedule in schedules:
        sim = simulate(dec, lay, stop_reason, schedule, budget, trace)
        results += [{'schedule': schedule, 'route': route, **sim[route]} for route in ROUTES]
    e = event_bound(dec, stop_reason)
    projection = b.stringify({
        'schema': 'hip4-pairing-projection-v1', 'question': QUESTION, 'stop': stop_reason,
        'kernel_match': True, 'event_bound': [e[0] - dec['open'], e[2]],
        'window_ns': dec['close'] - dec['open'], 'steps_used': steps - max(budget.left, 0),
        'step_cap_exhausted': budget.left < 0, 'results': results,
        'claim': 'displayed conditional evaluation on causally reachable supported states; quote-token units; '
                 'zero fees optimistic; episode sums overlap and are never portfolio cash; work caps are unknown'})
    if len(encoded(projection)) > limits['projection']:
        raise Refusal('projection_over_cap')
    return projection, trace.result()


# ---- plan, seal, admission, run and dry entry point -----------------------------------------------------------

REQUIRED_CHECKS = ('admission_after_close', 'supervisor_terminal', 'supervisor_finished_eligible',
                   'claim_plan_and_question', 'live_plan_and_sources', 'admission_stage_complete',
                   'conclusion_worker_completed_exit_zero', 'conclusion_terminal_without_failure',
                   'conclusion_bundle_matches_terminal', 'conclusion_records_match_plan',
                   'conclusion_projection_reproduced', 'conclusion_no_pending_publication',
                   'conclusion_final_plan_and_source_pins')
SUPERVISOR_TERMINAL = ('start_failed', 'process_deadline', 'worker_finished', 'worker_failed_without_valid_terminal')
EXIT_CAUSES = {3: 'refused', 4: 'memory_limit', -24: 'cpu_limit', -9: 'killed'}
OUTPUT_FILES = {'projection.json': 'projection', 'trace.json': 'trace'}


def utc_now():
    return lv.now_utc()


def pin_ok(pin, cap=lv.BUNDLE_CAP):
    """A relative repository path whose bytes and sha256 match exactly."""
    rel = pin.get('path') if isinstance(pin, dict) else None
    if not isinstance(rel, str) or rel.startswith('/') or '..' in Path(rel).parts:
        return False
    path = ROOT / rel
    try:
        data = bounded_read(path, cap)
    except (OSError, Refusal):
        return False
    return path.resolve() == ROOT.resolve() / rel and len(data) == pin.get('bytes') and digest(data) == pin.get('sha256')


def verify_plan(role, plan_sha256):
    """The sealed role plan, with every declared source, chain and live-plan pin authenticated."""
    if role not in PLANS:
        raise Refusal('role_unknown')
    try:
        raw = bounded_read(PLANS[role], PLAN_CAP)
    except (OSError, Refusal):
        raise Refusal('plan_unreadable') from None
    if digest(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != SCHEMA or p.get('status') != 'sealed_prospective' \
            or p.get('role') != role:
        raise Refusal('plan_not_sealed')
    if encoded(p.get('analysis_plan')) != encoded(ANALYSIS_PLAN) \
            or encoded(p.get('schedules')) != encoded(list(ROLE_SCHEDULES[role])) \
            or encoded(p.get('output_limits_bytes')) != encoded(ROLE_LIMITS[role]) or p.get('output_dir') != OUTS[role]:
        raise Refusal('plan_changed')
    pins, chain = p.get('source_pins'), p.get('chain_pins')
    if not isinstance(pins, list) or sorted(str(x.get('path')) for x in pins if isinstance(x, dict)) != sorted(PINNED) \
            or not isinstance(chain, list) or sorted(str(x.get('path')) for x in chain if isinstance(x, dict)) != sorted(CHAIN):
        raise Refusal('missing_pins')
    live = p.get('live_plan')
    if not all(pin_ok(x) for x in pins + chain + [live]) or live.get('sha256') != LIVE_PLAN_SHA:
        raise Refusal('pin_mismatch')
    if role != 'primary':  # every non-primary role names the exact primary plan, authenticated in full
        ref = p.get('primary_plan')
        if not isinstance(ref, dict) or ref.get('path') != PLAN_RELS['primary'] or not isinstance(ref.get('sha256'), str):
            raise Refusal('primary_plan_unbound')
        verify_plan('primary', ref['sha256'])
    try:
        frozen = bounded_read(ROOT / b.FROZEN_META, h.PROJECTION_CAP)
    except (OSError, Refusal):
        raise Refusal('frozen_metadata_changed') from None
    if digest(frozen) != b.FROZEN_META_SHA:
        raise Refusal('frozen_metadata_changed')
    return p, b.frozen_cohort(pm.strict_json(frozen))


def primary_sha(role, plan, plan_sha256):
    return plan_sha256 if role == 'primary' else plan['primary_plan']['sha256']


def verify_seal(seal_sha256, primary_plan_sha256):
    """The once-only input seal: exact schema, question, live plan and primary pairing plan, the four live receipts
    in order, the capture bundle path, and an explicit True for exactly the required admission checks; all bound
    before any capture pin is read."""
    try:
        raw = bounded_read(SEAL, SEAL_CAP)
    except (OSError, Refusal):
        raise Refusal('seal_unreadable') from None
    if digest(raw) != seal_sha256:
        raise Refusal('seal_sha_mismatch')
    seal = pm.strict_json(raw)
    seal = seal if isinstance(seal, dict) else {}
    pins, checks, bundle = seal.get('pins'), seal.get('checks'), seal.get('input')
    paths = [x.get('path') if isinstance(x, dict) else None for x in pins] if isinstance(pins, list) else None
    if not (seal.get('schema') == SEAL_SCHEMA and seal.get('question') == QUESTION
            and seal.get('live_plan_sha256') == LIVE_PLAN_SHA and seal.get('plan_sha256') == primary_plan_sha256
            and seal.get('status') == 'admitted'
            and paths == [f'{LIVE_OUT}/{name}' for name in LIVE_FILES]
            and isinstance(bundle, dict) and bundle.get('path') == f'{LIVE_OUT}/capture.bundle.gz'
            and isinstance(checks, dict) and set(checks) == set(REQUIRED_CHECKS)
            and all(v is True for v in checks.values())):
        raise Refusal('input_not_admitted')
    if not all(pin_ok(x) for x in pins + [bundle]):
        raise Refusal('seal_pin_mismatch')
    return seal


def verify(role, plan_sha256, seal_sha256):
    plan, cohort = verify_plan(role, plan_sha256)
    return plan, verify_seal(seal_sha256, primary_sha(role, plan, plan_sha256)), cohort


def pin_of(rel, cap=lv.BUNDLE_CAP):
    path = ROOT / rel
    try:
        data = bounded_read(path, cap)
    except (OSError, Refusal):
        return None
    return {'path': rel, 'bytes': len(data), 'sha256': digest(data)}


def fork_process(target, args):
    child = multiprocessing.get_context('fork').Process(target=target, args=args)
    child.start()
    return child


def bounded_child(target, args):
    """Start a forked child, join it within WALL_S, then kill and re-join it within KILL_JOIN_S. Returns None on a
    clean exit, otherwise an explicit cause."""
    try:
        child = fork_process(target, args)
    except Exception:
        return 'start_failed'
    child.join(WALL_S)
    if child.is_alive():
        child.kill()
        child.join(KILL_JOIN_S)
        return 'wall_limit' if not child.is_alive() else 'wall_limit_kill_unconfirmed'
    return None if child.exitcode == 0 else EXIT_CAUSES.get(child.exitcode, f'exit_{child.exitcode}')


def limit_self():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (RAM_BYTES, RAM_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_S, CPU_S + 5))


def _admission_child(conn, finished):
    """Live-v1 plan and source pins, then the conclusion rechecks (bundle decompression, records, reproduced
    projection), under the same hard limits as the replay."""
    code = 5
    try:
        limit_self()
        try:
            lv.verify(LIVE_PLAN_SHA)
        except Exception:  # no capture decompression or replay against unverified live sources
            conn.send({'live_plan_and_sources': False, 'recheck': {}})
            code = 0
            return
        recheck = lv.conclusion_checks(ROOT / LIVE_OUT, LIVE_PLAN_SHA, finished)[0]
        conn.send({'live_plan_and_sources': True, 'recheck': {str(k): v is True for k, v in recheck.items()}})
        code = 0
    except MemoryError:
        code = 4
    finally:
        os._exit(code)


def _gather(out, checks):
    def read(name):
        try:
            value = pm.strict_json(bounded_read(out / name, 2048))
        except (OSError, Refusal, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    supervisor, claim = read('supervisor.json'), read('claim.json')
    finished = supervisor.get('status') == 'worker_finished' and supervisor.get('worker_exitcode') == 0
    checks['supervisor_terminal'] = supervisor.get('status') in SUPERVISOR_TERMINAL
    checks['supervisor_finished_eligible'] = finished and supervisor.get('conclusion_eligible') is True
    checks['claim_plan_and_question'] = claim.get('plan_sha256') == LIVE_PLAN_SHA and claim.get('target_question') == QUESTION
    recv, send = multiprocessing.get_context('fork').Pipe(duplex=False)
    try:
        cause = bounded_child(_admission_child, (send, finished))
        report = recv.recv() if cause is None and recv.poll(1) else None
    finally:
        recv.close()
        send.close()
    if cause is None and not isinstance(report, dict):
        cause = 'admission_stage_without_report'
    if cause is None:
        checks['live_plan_and_sources'] = report.get('live_plan_and_sources') is True
        checks.update({f'conclusion_{k}': v is True for k, v in report.get('recheck', {}).items()})
    checks['admission_stage_complete'] = cause is None
    return cause


def admit(plan_sha256):
    """Local admission of the closed Q357 capture (integrity only; no quote or result informs any rule). Refuses
    without writing unless the primary pairing plan chain authenticates first, the declared close has passed and
    the supervisor is terminal. Otherwise it writes the input seal once: admitted with exact pins, or unavailable
    with its cause and every available pin."""
    verify_plan('primary', plan_sha256)  # before the first capture read
    now, close = utc_now(), lv.window(QUESTION)['close']
    if now < close:
        raise Refusal('admission_before_close')
    if SEAL.exists():
        raise Refusal('seal_exists')
    out = ROOT / LIVE_OUT
    if not (out / 'supervisor.json').exists() and (now - close).total_seconds() < SUPERVISOR_MISSING_S:
        raise Refusal('supervisor_not_terminal')
    checks = dict.fromkeys(REQUIRED_CHECKS, False)
    checks['admission_after_close'] = True
    try:
        cause = _gather(out, checks)
    except Exception as exc:  # keep what is available behind an explicit unavailable receipt
        cause = f'admission_error_{type(exc).__name__}'[:80]
    pins = [pin_of(f'{LIVE_OUT}/{name}', 65536) for name in LIVE_FILES]
    bundle = pin_of(f'{LIVE_OUT}/capture.bundle.gz')
    admitted = cause is None and all(v is True for v in checks.values()) and all(pins) and bundle is not None
    seal = {'schema': SEAL_SCHEMA, 'question': QUESTION, 'live_plan_sha256': LIVE_PLAN_SHA, 'plan_sha256': plan_sha256,
            'checks': checks, 'cause': cause, 'pins': [x for x in pins if x], 'input': bundle,
            'status': 'admitted' if admitted else 'unavailable', 'sealed_utc': pm.utc()}
    data = encoded(seal)
    if len(data) > SEAL_CAP:
        raise Refusal('seal_over_cap')
    SEAL.parent.mkdir(parents=True, exist_ok=True)
    h.write_once(SEAL, data)
    return seal


def _child(input_pin, cohort, schedules, limits, pending):
    """Bounded analysis in a forked child: hard address-space and CPU limits, the actual input bytes checked against
    the seal, and complete serialization and size admission of both outputs before either is written."""
    code = 5
    try:
        limit_self()
        packed = bounded_read(ROOT / input_pin['path'], lv.BUNDLE_CAP)
        if len(packed) != input_pin['bytes'] or digest(packed) != input_pin['sha256']:
            raise Refusal('input_changed')
        records = lv.parse_bundle(packed)
        stop = lv.validate_records(records, lv.layout(cohort, QUESTION))
        projection, trace = analyze(records, cohort, stop, schedules, limits=limits)
        projection.update(bundle_sha256=digest(packed), records=len(records))
        blobs = [('projection.json', encoded(projection), limits['projection']),
                 ('trace.json', encoded(trace), limits['trace'])]
        if any(len(data) > cap for _, data, cap in blobs):
            raise Refusal('output_over_cap')
        for name, data, _ in blobs:
            h.write_once(pending / name, data)
        code = 0
    except Refusal as exc:
        code = 3
        h.write_once(pending / 'refusal.json', encoded({'code': str(exc)[:200]}))
    except MemoryError:
        code = 4
    except Exception as exc:
        h.write_once(pending / 'refusal.json', encoded({'code': 'exception', 'type': type(exc).__name__[:100]}))
    finally:
        os._exit(code)


def staged_usage(pending):
    """Bytes per category of everything staged (outputs, their temporaries and receipts), each inode once."""
    usage, seen = {'projection': 0, 'trace': 0, 'receipts': 0}, set()
    for path in pending.iterdir():
        st = path.stat()
        if st.st_ino not in seen:
            seen.add(st.st_ino)
            usage[OUTPUT_FILES.get(path.name.removesuffix('.pending'), 'receipts')] += st.st_size
    return usage


def retain_not_admitted(pending):
    """A failed run keeps its own staged outputs, renamed not-admitted-*; nothing is deleted."""
    kept = []
    for path in sorted(pending.iterdir()):
        if path.name == 'refusal.json':
            continue
        target = path.with_name('not-admitted-' + path.name)
        os.rename(path, target)
        try:
            sha = digest(bounded_read(target, pm.BODY_CAP))
        except (OSError, Refusal):
            sha = None
        kept.append({'name': target.name, 'bytes': target.stat().st_size, 'sha256': sha})
    return kept


def kill_unconfirmed(role, plan_sha256, seal_sha256, out, pending):
    """The child may still be alive: nothing in its staging directory is read, renamed or published. A separate
    bounded parent receipt records the unavailable run beside it."""
    receipt = {'schema': 'hip4-pairing-run-failure-v1', 'role': role, 'plan_sha256': plan_sha256,
               'seal_sha256': seal_sha256, 'status': 'unavailable', 'cause': 'wall_limit_kill_unconfirmed',
               'staging_left_untouched': pending.name, 'output_dir_unpublished': out.name, 'recorded_utc': pm.utc()}
    h.write_once(pending.with_name(out.name + '.failure.json'), encoded(receipt))
    return receipt


def run(role, plan_sha256, seal_sha256):
    """Verify, analyze in a limited child, re-verify the whole chain and admit both outputs, then publish the
    directory atomically. Any failure publishes an explicit unavailable receipt beside the retained, labelled
    staged outputs."""
    plan, seal, cohort = verify(role, plan_sha256, seal_sha256)
    limits = ROLE_LIMITS[role]
    out = ROOT / plan['output_dir']
    pending = PENDING / (out.name + '.pending')
    if out.exists() or pending.exists():
        raise Refusal('output_exists')
    if not out.parent.is_dir():
        raise Refusal('output_parent_missing')
    pending.mkdir()
    cause = bounded_child(_child, (seal['input'], cohort, ROLE_SCHEDULES[role], limits, pending))
    if cause == 'wall_limit_kill_unconfirmed':
        return kill_unconfirmed(role, plan_sha256, seal_sha256, out, pending)
    if cause is None:
        try:
            for name, category in OUTPUT_FILES.items():
                pm.strict_json(bounded_read(pending / name, limits[category]))
        except (OSError, Refusal, ValueError):
            cause = 'output_admission_failed'
    if cause is None:
        try:
            verify(role, plan_sha256, seal_sha256)  # plan, sources, chain, seal and input unchanged after the child
        except (OSError, Refusal):
            cause = 'pins_changed_after_run'
    usage = staged_usage(pending)
    if cause is None and any(usage[k] > limits[k] for k in OUTPUT_FILES.values()):
        cause = 'output_share_exceeded'
    record = {'schema': 'hip4-pairing-run-v1', 'role': role, 'plan_sha256': plan_sha256, 'seal_sha256': seal_sha256,
              'status': 'complete' if cause is None else 'unavailable', 'cause': cause,
              'limits': {'ram_bytes': RAM_BYTES, 'cpu_seconds': CPU_S, 'wall_seconds': WALL_S},
              'output_limits_bytes': limits, 'staged_bytes': usage,
              'within_role_shares': all(usage[k] <= limits[k] for k in OUTPUT_FILES.values())}
    if cause is not None:
        try:
            record['refusal'] = pm.strict_json(bounded_read(pending / 'refusal.json', 4096))
        except (OSError, Refusal, ValueError):
            record['refusal'] = None
        try:
            record['retained_not_admitted'] = retain_not_admitted(pending)
        except OSError:
            record['retained_not_admitted'] = 'labelling_failed_staged_files_left_in_place'
    data = encoded(record)
    if len(data) + usage['receipts'] > limits['receipts']:
        raise Refusal('receipt_share_exceeded')  # staged evidence stays in place for review
    h.write_once(pending / 'run.json', data)
    try:
        os.rename(pending, out)  # atomic publication of a complete or explicitly unavailable directory
    except OSError:
        raise Refusal('publication_failed') from None  # the staged directory and its receipt remain
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', choices=sorted(PLANS))
    parser.add_argument('--admit', action='store_true', help='needs the sealed primary plan sha256')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--seal-sha256')
    args = parser.parse_args(argv)
    if args.admit:
        print(encoded(admit(args.plan_sha256)).decode(), end='')
        return 0
    if args.run:
        print(encoded(run(args.run, args.plan_sha256, args.seal_sha256)).decode(), end='')
        return 0
    print(encoded({'status': 'dry', 'raw_reads': 0, 'writes': 0, 'network_calls': 0, 'question': QUESTION,
                   'roles': {r: list(ROLE_SCHEDULES[r]) for r in sorted(PLANS)}, 'caps': ANALYSIS_PLAN['caps']}).decode(),
          end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
