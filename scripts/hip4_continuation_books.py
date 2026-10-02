#!/usr/bin/env python3
"""HIP-4 continuation gate v1: one bracketed YES-side book snapshot of the 18 frozen questions.

Default is dry and performs no HTTP. A run needs the exact sha256 of a root-frozen plan.
It makes one sequential pass with no retry: outcomeMeta, one l2Book per member plus fixed
premise probes, then outcomeMeta again. Any stop is a failure: the retained prefix and
terminal are kept, and no projection is accepted. The analysis is a conditional zero-fee
certificate per question plus an agnostic and a semantic settlement-dominance check for the
recurring BTC pair, all computed in an exact decimal context. It makes no fill, fee,
precision, identity or profit claim. Design: reports/hip4-research-continuation/books-v1-design.md
"""
from __future__ import annotations

import argparse
import contextlib
import decimal
from decimal import Decimal
import http.client
import json
import multiprocessing
from pathlib import Path
import re
import ssl
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import hip4_outcome_metadata_v1 as h  # frozen parser, certificate and helpers

pm = h.pm
Refusal = pm.Refusal
digest, encoded, utc, bounded_read = pm.digest, pm.encoded, pm.utc, pm.bounded_read

PLAN = ROOT / 'reports/experiment-storage/hip4-continuation-books-v1.json'
SCHEMA = 'hip4-continuation-books-v1'
SOURCE = 'scripts/hip4_continuation_books.py'
TEST = 'tests/test_hip4_continuation_books.py'
PINNED = (SOURCE, TEST, h.SOURCE, h.HELPER)
PREVIOUS = 'reports/experiment-storage/hip4-research-continuation-allocation-v1.json'
FROZEN_META = 'reports/hip4-outcome-v1/metadata-v1/metadata.json'
FROZEN_META_SHA = '66913ed2f88aca6f05c4f32f81b438d0abd8228e660c9b97a8165e4cf6bf8788'
OUT = 'reports/hip4-research-continuation/books-v1'
HOST, TARGET = 'api.hyperliquid.xyz', '/info'
META_CAP, BOOK_CAP = 196608, 8192
BUNDLE_CAP, RAW_LIMIT = 393216, 2097152
PROJECTION_CAP, CONTROL_CAP = 49152, 16384
REQUEST_SECONDS, PROCESS_SECONDS, SPACING_SECONDS = 10, 150, 0.05
SPREAD_MS, LOCAL_WINDOW_MS, MAX_AGE_MS, MAX_FUTURE_MS = 2000, 2000, 5000, 250
MIN_USABLE = 12
MIRRORS = (1472, 7551)
BINARY_SPEC = {'outcome': 7544, 'name': 'Recurring',
               'description': 'class:priceBinary|underlying:BTC|expiry:20261003-0600|targetPrice:85971|period:1d',
               'sideSpecs': [{'name': 'Yes'}, {'name': 'No'}], 'quoteToken': 'USDC'}
DOMINANCE = {'binary': 7544, 'question': 371, 'binary_spec': BINARY_SPEC,
             'index_map': {'L': 7551, 'M': 7552, 'H': 7553, 'F': 7550},
             'models': {'agnostic_six_state': 'states L,M1,M2,H,F0,F1 with B=M2+H+F1: conversions plus '
                                              'the contract-spec common mark; nothing assumed about B in '
                                              'the fallback state',
                        'fallback_zero_semantic': 'adds the semantic premise F=0, intersected with the F '
                                                  'quotes (a positive F bid is a premise conflict)'},
             'premises': {'P8': 'contract-spec common interpolated mark and expiry for 7544 and question 371',
                          'P9': 'common quote collateral for 7544 and question 371: both labelled USDC; '
                                'identity unresolved beyond the label; no USD claim'},
             'scope': 'conditional valuation feasibility only; infeasibility authorizes no naked short; '
                      'construction, collateral and settlement gates remain future work'}
QUESTION_IDS = (198, 199, 200, 250, 289, 331, 357, 358, 359, 361, 362, 363, 366, 367,
                368, 369, 370, 371)
GROUPS = {'tournament_winner': [198, 199, 200, 250], 'policy_rate': [289, 331],
          'match_result': [357, 358, 359, 361, 362, 363, 366, 367, 368, 369, 370],
          'recurring_btc_bucket': [371]}  # reporting clusters fixed from the frozen labels
ZERO, ONE = Decimal(0), Decimal(1)
REQUEST_PLAN = {
    'method': 'POST', 'url': 'https://api.hyperliquid.xyz/info',
    'connection': 'sequential requests on one keep-alive connection; after any protocol-indicated '
                  'close (response.will_close or Connection: close) the connection is retired and a '
                  'new one is opened only for the next distinct planned request; never a retry; '
                  'every open, including any implicit reconnect, is counted in connections_opened',
    'order': 'outcomeMeta; per question ascending, members ascending YES l2Book, mirror NO '
             'probe right after its YES book, binary 7544 YES after question 371; outcomeMeta',
    'request_count': 91, 'documented_weight': 218, 'meta_body_cap': META_CAP,
    'book_body_cap': BOOK_CAP, 'bundle_gzip_cap': BUNDLE_CAP,
    'request_deadline_seconds': REQUEST_SECONDS, 'process_deadline_seconds': PROCESS_SECONDS,
    'min_spacing_seconds': SPACING_SECONDS, 'retry': False, 'redirects': False,
    'environment_proxies': False, 'fallbacks': [], 'any_stop_is_failure': True,
}
ANALYSIS_PLAN = {'question_ids': list(QUESTION_IDS), 'groups': GROUPS, 'mirrors': list(MIRRORS),
                 'mirror_scope': 'every returned level on both sides: price complement, size and count',
                 'dominance': DOMINANCE,
                 'max_server_book_spread_ms': SPREAD_MS, 'max_local_request_window_ms': LOCAL_WINDOW_MS,
                 'max_book_age_ms': MAX_AGE_MS, 'max_book_future_ms': MAX_FUTURE_MS,
                 'min_usable_questions': MIN_USABLE,
                 'arithmetic': 'exact decimal context (prec 120, Inexact and Rounded trapped); '
                               'px/sz at most 20 integer and 30 fractional digits'}
OUTPUT_LIMITS = {'bundle_gzip': BUNDLE_CAP, 'projection': PROJECTION_CAP,
                 'claim_terminal_and_supervisor_receipts': CONTROL_CAP}
SIG_KEYS = ('question', 'name', 'description', 'fallbackOutcome', 'namedOutcomes',
            'settledNamedOutcomes', 'member_specs', 'issues', 'structural_candidate')
HEADER_KEYS = ('index', 'kind', 'coin', 'request', 'sent_utc', 'sent_ms', 'sent_mono_ns',
               'received_utc', 'received_ms', 'received_mono_ns', 'http_status', 'code',
               'declared_length', 'over_cap', 'body_bytes', 'body_sha256')


@contextlib.contextmanager
def exact():
    """Decimal context in which any rounding raises; inputs are digit-bounded at parse."""
    with decimal.localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin = 120, 999999, -999999
        ctx.traps[decimal.Inexact] = ctx.traps[decimal.Rounded] = True
        yield


def certify(book):
    """The frozen v1 certificate evaluated exactly (default Decimal precision can round)."""
    with exact():
        return h.certificate(book)


def signature(q):
    """Canonical structure of one projected question; any difference invalidates it."""
    return digest(encoded({k: q.get(k) for k in SIG_KEYS}))


def frozen_cohort(projection):
    """Members per question from the frozen projection; labels are not consulted."""
    questions = {q['question']: q for q in projection.get('questions', [])}
    if sorted(questions) != sorted(QUESTION_IDS) or not all(
            questions[i].get('structural_candidate') is True for i in QUESTION_IDS):
        raise Refusal('frozen_cohort_mismatch')
    cohort = {}
    for qid in QUESTION_IDS:
        q = questions[qid]
        cohort[qid] = {'fallback': q['fallbackOutcome'],
                       'members': sorted(q['namedOutcomes'] + [q['fallbackOutcome']]),
                       'signature': signature(q)}
    members = {m for c in cohort.values() for m in c['members']}
    if len(members) != 86 or not set(MIRRORS) <= members:
        raise Refusal('frozen_cohort_mismatch')
    if sorted(DOMINANCE['index_map'].values()) != cohort[DOMINANCE['question']]['members']:
        raise Refusal('dominance_map_mismatch')
    return cohort


def requests(cohort):
    meta = {'kind': 'meta', 'body': {'type': 'outcomeMeta'}}
    plan = [dict(meta, phase='pre')]
    for qid in QUESTION_IDS:
        for member in cohort[qid]['members']:
            plan.append({'kind': 'book', 'outcome': member, 'side': 0, 'question': qid})
            if member in MIRRORS:
                plan.append({'kind': 'book', 'outcome': member, 'side': 1, 'question': qid})
        if qid == DOMINANCE['question']:
            plan.append({'kind': 'book', 'outcome': DOMINANCE['binary'], 'side': 0, 'question': None})
    plan.append(dict(meta, phase='post'))
    for index, item in enumerate(plan):
        item['index'] = index
        item['coin'] = None
        if item['kind'] == 'book':
            item['coin'] = f"#{10 * item['outcome'] + item['side']}"
            item['body'] = {'type': 'l2Book', 'coin': item['coin'], 'nSigFigs': None}
        item['payload'] = json.dumps(item['body'], separators=(',', ':')).encode('ascii')
    return plan


def verify(plan_sha256):
    if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
        raise Refusal('expected_plan_sha_required')
    try:
        raw = bounded_read(PLAN, 65536)
    except OSError:
        raise Refusal('plan_unreadable') from None
    if digest(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != SCHEMA:
        raise Refusal('plan_schema')
    if p.get('status') != 'frozen_book_snapshot':
        raise Refusal('plan_not_frozen')
    for key, expected in (('request_plan', REQUEST_PLAN), ('analysis_plan', ANALYSIS_PLAN),
                          ('output_limits_bytes', OUTPUT_LIMITS)):
        if encoded(p.get(key)) != encoded(expected):
            raise Refusal(f'{key}_changed')
    if p.get('output_dir') != OUT or (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_plan_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 4 or sorted(
            pin.get('path') for pin in pins if isinstance(pin, dict)) != sorted(PINNED):
        raise Refusal('missing_source_pins')
    for pin in pins:
        path = ROOT / pin['path']
        if path.resolve() != ROOT.resolve() / pin['path']:
            raise Refusal('symlinked_source_pin')
        data = bounded_read(path, 262144)
        if type(pin.get('bytes')) is not int or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if p.get('previous') != PREVIOUS or digest(bounded_read(ROOT / PREVIOUS, 65536)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    frozen = bounded_read(ROOT / FROZEN_META, h.PROJECTION_CAP)
    if digest(frozen) != FROZEN_META_SHA:
        raise Refusal('frozen_metadata_changed')
    return p, frozen_cohort(pm.strict_json(frozen))


def decimal_text(text):
    if not isinstance(text, str) or not re.fullmatch(r'[0-9]{1,20}(\.[0-9]{1,30})?', text):
        raise ValueError('decimal_invalid_or_unbounded')
    return Decimal(text)


def parse_book(obj, coin):
    """Validate one l2Book body; return tops, time and digit counts, or raise ValueError."""
    if not isinstance(obj, dict) or obj.get('coin') != coin:
        raise ValueError('coin_mismatch')
    if not h.uint(obj.get('time')):
        raise ValueError('time_invalid')
    levels = obj.get('levels')
    if not isinstance(levels, list) or len(levels) != 2:
        raise ValueError('levels_invalid')
    sides, digits = [], {'px': 0, 'sz': 0}
    for index, side in enumerate(levels):
        if not isinstance(side, list) or len(side) > 20:
            raise ValueError('levels_invalid')
        parsed = []
        for level in side:
            if not isinstance(level, dict) or not h.uint(level.get('n')) or level['n'] < 1:
                raise ValueError('level_invalid')
            px, sz = decimal_text(level.get('px')), decimal_text(level.get('sz'))
            if not ZERO <= px <= ONE or sz <= ZERO:
                raise ValueError('level_out_of_range')
            for key in ('px', 'sz'):
                digits[key] = max(digits[key], len(level[key].partition('.')[2].rstrip('0')))
            parsed.append((px, sz, level['n']))
        prices = [p for p, _, _ in parsed]
        if prices != sorted(prices, reverse=index == 0) or len(set(prices)) != len(prices):
            raise ValueError('level_order_invalid')
        sides.append(parsed)
    bid = sides[0][0][:2] if sides[0] else None
    ask = sides[1][0][:2] if sides[1] else None
    if bid and ask and bid[0] >= ask[0]:
        raise ValueError('crossed_book')
    fractional = any(sz != sz.to_integral_value() for side in sides for _, sz, _ in side)
    return {'time': obj['time'], 'bid': bid, 'ask': ask, 'bids': sides[0], 'asks': sides[1],
            'digits': digits, 'fractional_size': fractional, 'levels': [len(sides[0]), len(sides[1])]}


def interval(top):
    return (top['bid'][0] if top['bid'] else ZERO, top['ask'][0] if top['ask'] else ONE)


def dominance(tops, fallback_zero=False):
    """Exact valuation feasibility for L, M, H, F (question 371) and binary B (target in M).

    Agnostic model: states L, M1, M2, H, F0, F1 with B = M2 + H + F1, so H <= B <= 1 - L.
    Feasible iff every interval is consistent, aL <= min(bL, 1-aB), aH <= min(bH, bB) and
    aL+aM+aH+aF <= 1 <= min(bL,1-aB) + bM + min(bH,bB) + bF (B is not in the sum). The
    fallback_zero model adds the
    semantic premise F = 0, intersected with the F quotes (a positive F bid is a premise
    conflict), and B = M2 + H: max(aM+aH, aB, 1-bL) <= min(bM+min(bH,bB), 1-aL).
    """
    with exact():
        lo, hi = {}, {}
        for key in ('L', 'M', 'H', 'F', 'B'):
            lo[key], hi[key] = interval(tops[key])
        conflicts = [k for k in lo if lo[k] > hi[k]]
        u_l, u_h = min(hi['L'], ONE - lo['B']), min(hi['H'], hi['B'])
        if not fallback_zero:
            feasible = (not conflicts and lo['L'] <= u_l and lo['H'] <= u_h and
                        lo['L'] + lo['M'] + lo['H'] + lo['F'] <= ONE <= u_l + hi['M'] + u_h + hi['F'])
            relations = {'B_ask_lt_H_bid': hi['B'] < lo['H'],
                         'B_bid_plus_L_bid_gt_1': lo['B'] + lo['L'] > ONE,
                         'B_bid_gt_M_H_F_asks': lo['B'] > hi['M'] + hi['H'] + hi['F']}
            return {'feasible': feasible, 'conflicts': conflicts, 'relations': relations}
        premise_conflict = lo['F'] > ZERO
        lower = max(lo['M'] + lo['H'], lo['B'], ONE - hi['L'])
        upper = min(hi['M'] + u_h, ONE - lo['L'])
        feasible = (not conflicts and not premise_conflict and lo['H'] <= u_h and lower <= upper)
        relations = {'B_ask_lt_H_bid': hi['B'] < lo['H'],
                     'B_bid_gt_M_H_asks': lo['B'] > hi['M'] + hi['H'],
                     'B_bid_plus_L_bid_gt_1': lo['B'] + lo['L'] > ONE}
        return {'feasible': feasible, 'conflicts': conflicts, 'premise_conflict_fallback_bid': premise_conflict,
                'lower': str(lower), 'upper': str(upper), 'relations': relations}


def meta_check(record, cohort):
    """Per-question and binary-spec comparison of one outcomeMeta read with the frozen state."""
    unavailable = ({qid: 'unavailable' for qid in QUESTION_IDS}, 'unavailable')
    if record is None or record.get('code') or record.get('http_status') != 200:
        return unavailable
    try:
        obj = pm.strict_json(record['body'])
        projection = h.analyze(obj)
    except Exception:
        return unavailable
    found = {}
    for q in projection.get('questions', []):
        found.setdefault(q['question'], []).append(q)
    questions = {qid: 'missing' if qid not in found else
                 'unchanged' if len(found[qid]) == 1 and signature(found[qid][0]) == cohort[qid]['signature']
                 else 'changed' for qid in QUESTION_IDS}
    entries = [o for o in obj.get('outcomes', []) if isinstance(o, dict) and o.get('outcome') == BINARY_SPEC['outcome']]
    binary = ('missing' if not entries else 'duplicate' if len(entries) > 1 else
              'unchanged' if encoded(entries[0]) == encoded(BINARY_SPEC) else 'changed')
    return questions, binary


def tops_of(record):
    if record is None:
        return None, 'not_attempted'
    if record.get('code') or record.get('http_status') != 200:
        return None, 'request_failed'
    try:
        tops = parse_book(pm.strict_json(record['body']), record['coin'])
    except (ValueError, Refusal):
        return None, 'book_invalid'
    age = record['received_ms'] - tops['time']
    tops.update(age_ms=age, fresh=-MAX_FUTURE_MS <= age <= MAX_AGE_MS,
                sent_mono_ns=record['sent_mono_ns'], received_mono_ns=record['received_mono_ns'])
    return tops, None


def mirror(yes, no):
    if yes is None or no is None:
        return 'unavailable'
    with exact():  # complements are exact; every displayed level, size and count must mirror
        flip = lambda side: [(ONE - px, sz, n) for px, sz, n in side]  # noqa: E731
        same = flip(yes['asks']) == no['bids'] and flip(yes['bids']) == no['asks']
    if same:
        return 'consistent'
    return 'mismatch_same_time' if yes['time'] == no['time'] else 'mismatch_different_time'


def timing(tops):
    """Server-time spread and exact local send-to-receive window (ns) for a set of book tops."""
    times = [t['time'] for t in tops]
    window = max(t['received_mono_ns'] for t in tops) - min(t['sent_mono_ns'] for t in tops)
    return {'server_spread_ms': max(times) - min(times), 'local_window_ns': window,
            'local_window_ms_ceiling': -(-window // 1000000), 'all_fresh': all(t['fresh'] for t in tops)}


def gate(clock):
    if not clock['all_fresh']:
        return 'stale_or_future_book'
    if clock['local_window_ns'] > LOCAL_WINDOW_MS * 1000000:
        return 'local_window_exceeded'
    if clock['server_spread_ms'] > SPREAD_MS:
        return 'timing_unusable'
    return None


def analyze(records, cohort):
    """Pure analysis of a complete validated pass; every question stays in the denominator."""
    plan = requests(cohort)
    by_index = {r['index']: r for r in records}
    pre, binary_pre = meta_check(by_index.get(0), cohort)
    post, binary_post = meta_check(by_index.get(len(plan) - 1), cohort)
    books = {}
    for item in plan:
        if item['kind'] == 'book':
            books[(item['outcome'], item['side'])] = tops_of(by_index.get(item['index']))
    probes = {str(m): mirror(books[(m, 0)][0], books[(m, 1)][0]) for m in MIRRORS}
    p4_falsified = 'mismatch_same_time' in probes.values()
    parsed = [t for t, _ in books.values() if t]
    units = {'books_parsed': len(parsed),
             'max_px_digits': max((t['digits']['px'] for t in parsed), default=None),
             'max_sz_digits': max((t['digits']['sz'] for t in parsed), default=None),
             'fractional_size_observed': any(t['fractional_size'] for t in parsed)}
    results, usable, candidates, gated = {}, 0, [], []
    for qid in QUESTION_IDS:
        c = cohort[qid]
        row = {'members': len(c['members']), 'meta_pre': pre[qid], 'meta_post': post[qid]}
        member_tops = {m: books[(m, 0)] for m in c['members']}
        failures = sorted({err for _, err in member_tops.values() if err})
        fb = member_tops[c['fallback']][0]
        row['fallback_levels'] = fb['levels'] if fb else None
        if failures:
            row['status'] = 'not_attempted' if failures == ['not_attempted'] else 'book_unavailable'
            row['failures'] = failures
        else:
            clock = timing([t for t, _ in member_tops.values()])
            cert = certify({m: {'yes_bid': t['bid'], 'yes_ask': t['ask']} for m, (t, _) in member_tops.items()})
            row.update(clock, certificate=cert['status'], sum_bid=cert['sum_ell'], sum_ask=cert['sum_u'],
                       route=cert['route'])
            if {pre[qid], post[qid]} & {'changed', 'missing'}:
                row['status'] = 'metadata_changed'
            elif pre[qid] != 'unchanged' or post[qid] != 'unchanged':
                row['status'] = 'metadata_unverified'
            elif gate(clock):
                row['status'] = gate(clock)
            elif p4_falsified:
                row['status'] = 'premise_failed'
            if 'status' in row:
                if cert['status'] != 'certified_no_static_cycle':
                    gated.append(qid)  # certificate failure retained even though a gate blocks it
            else:
                row['status'] = cert['status']
                usable += 1
                if cert['status'] != 'certified_no_static_cycle':
                    candidates.append(qid)
        results[str(qid)] = row
    dom_keys = dict(DOMINANCE['index_map'], B=DOMINANCE['binary'])
    dom_tops = {k: books[(v, 0)][0] for k, v in dom_keys.items()}
    if all(dom_tops.values()):
        clock = timing(list(dom_tops.values()))
        blockers = [b for b in (
            'question_metadata' if (pre[DOMINANCE['question']], post[DOMINANCE['question']]) != ('unchanged',) * 2 else None,
            'binary_metadata' if (binary_pre, binary_post) != ('unchanged',) * 2 else None,
            gate(clock), 'merged_book_premise' if p4_falsified else None) if b]
        dom = dict(clock, binary_meta_pre=binary_pre, binary_meta_post=binary_post, blockers=blockers,
                   usable=not blockers, agnostic_six_state=dominance(dom_tops),
                   fallback_zero_semantic=dominance(dom_tops, fallback_zero=True),
                   premise_p6_index_map='assumed', hold_to_settlement=True)
    else:
        dom = {'usable': False, 'blockers': ['books_unavailable'],
               'binary_meta_pre': binary_pre, 'binary_meta_post': binary_post}
    if p4_falsified:
        status = 'inconclusive_merged_book_premise_falsified'
    elif usable < MIN_USABLE:
        status = 'inconclusive_insufficient_usable_questions'
    elif candidates:
        status = 'candidates_for_separate_review'
    else:
        status = 'park_static_conversion_at_snapshot'
    groups = {name: dict(sorted(h.tally(results[str(q)]['status'] for q in ids).items()))
              for name, ids in GROUPS.items()}
    return {'schema': 'hip4-continuation-books-projection-v1', 'status': status,
            'denominator': len(QUESTION_IDS), 'usable_questions': usable, 'candidates': candidates,
            'gated_certificate_failures': gated, 'group_totals': groups,
            'questions': results, 'mirror_probes': probes, 'native_units_observed': units,
            'dominance_btc': dom,
            'claim': 'conditional zero-fee certificate on one frozen vector of recorded quotes, read '
                     'as one executable state; freshness and window gates do not prove simultaneity '
                     'or absence of routes during the interval; displayed levels are not proof of '
                     'takerability; no fills, fees, precision, quote identity, active state or profit'}


def stringify(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: stringify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [stringify(v) for v in value]
    return value


def build_projection(records, cohort, plan_sha256, packed):
    projection = stringify(analyze(records, cohort))
    projection.update(plan_sha256=plan_sha256, bundle_sha256=digest(packed), records=len(records))
    return projection


class Bundle:
    """Deterministic gzip of framed records; refuses a request that could breach the cap."""

    def __init__(self):
        self.stream = zlib.compressobj(9, zlib.DEFLATED, 31)
        self.parts, self.size = [], 0

    def room_for(self, body_cap):
        worst = body_cap + 2048 + 5 * (body_cap // 16384 + 2)
        return self.size + worst + 64 <= BUNDLE_CAP

    def add(self, header, body):
        data = encoded(dict(header, body_bytes=len(body), body_sha256=digest(body))) + body + b'\n'
        chunk = self.stream.compress(data) + self.stream.flush(zlib.Z_SYNC_FLUSH)
        self.parts.append(chunk)
        self.size += len(chunk)

    def finish(self):
        self.parts.append(self.stream.flush(zlib.Z_FINISH))
        return b''.join(self.parts)


def parse_bundle(packed):
    """Bounded strict parse of the framed bundle; header hashes must match bodies."""
    inflater = zlib.decompressobj(31)
    try:
        data = inflater.decompress(packed, RAW_LIMIT + 1)
    except zlib.error:
        raise Refusal('bundle_not_gzip') from None
    if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data or len(data) > RAW_LIMIT:
        raise Refusal('bundle_incomplete_or_trailing')
    records, pos = [], 0
    while pos < len(data):
        end = data.find(b'\n', pos)
        if end < 0 or len(records) >= 91:
            raise Refusal('bundle_framing')
        header = pm.strict_json(data[pos:end + 1])
        if not isinstance(header, dict) or sorted(header) != sorted(HEADER_KEYS):
            raise Refusal('bundle_header_keys')
        size = header['body_bytes']
        if not h.uint(size):
            raise Refusal('bundle_framing')
        body = data[end + 1:end + 1 + size]
        if len(body) != size or data[end + 1 + size:end + 2 + size] != b'\n' or digest(body) != header['body_sha256']:
            raise Refusal('bundle_body_mismatch')
        records.append(dict(header, body=body))
        pos = end + 2 + size
    return records


def validate_records(records, plan):
    """Exactly one successful record per planned request, in plan order, with sane clocks."""
    if len(records) != len(plan):
        raise Refusal('record_count_mismatch')
    previous = None
    for record, item in zip(records, plan):
        if (record['index'], record['kind'], record['coin'], record['request']) != (
                item['index'], item['kind'], item['coin'], item['payload'].decode('ascii')):
            raise Refusal('record_plan_mismatch')
        if record['http_status'] != 200 or record['code'] is not None or record['over_cap'] is not False:
            raise Refusal('record_not_successful')
        clocks = [record[k] for k in ('sent_ms', 'received_ms', 'sent_mono_ns', 'received_mono_ns')]
        if not all(h.uint(c) for c in clocks) or record['sent_mono_ns'] > record['received_mono_ns'] or (
                previous is not None and record['sent_mono_ns'] < previous):
            raise Refusal('record_clock_invalid')
        previous = record['received_mono_ns']
        cap = META_CAP if item['kind'] == 'meta' else BOOK_CAP
        declared = record['declared_length']
        if len(record['body']) > cap or (declared is not None and declared != str(len(record['body']))):
            raise Refusal('record_length_invalid')


def now_ms():
    return time.time_ns() // 1000000


def fetch_all(plan, bundle, records, receipt, deadline):
    """Sequential keep-alive pass; the first failure stops the pass (no retry)."""
    connection, last = None, 0.0
    try:
        for item in plan:
            cap = META_CAP if item['kind'] == 'meta' else BOOK_CAP
            if not bundle.room_for(cap) or time.monotonic() > deadline:
                receipt['stop'] = 'bundle_cap_or_deadline_before_request'
                return
            time.sleep(max(0.0, last + SPACING_SECONDS - time.monotonic()))
            if time.monotonic() > deadline:
                receipt['stop'] = 'deadline_before_request'
                return
            last = time.monotonic()
            record = {'index': item['index'], 'kind': item['kind'], 'coin': item['coin'],
                      'request': item['payload'].decode('ascii'), 'sent_utc': utc(), 'sent_ms': now_ms(),
                      'sent_mono_ns': time.monotonic_ns(), 'http_status': None, 'code': None,
                      'declared_length': None, 'over_cap': False}
            body = bytearray()
            try:
                with pm.hard_deadline(REQUEST_SECONDS, 'request_deadline'):
                    if connection is None:
                        connection = http.client.HTTPSConnection(
                            HOST, timeout=REQUEST_SECONDS, context=ssl.create_default_context())
                        receipt['connections_opened'] += 1
                    elif getattr(connection, 'sock', True) is None:
                        receipt['connections_opened'] += 1  # http.client would reconnect implicitly
                    receipt['requests_attempted'] += 1
                    connection.request('POST', TARGET, body=item['payload'], headers={
                        'Content-Type': 'application/json', 'Accept': 'application/json',
                        'Accept-Encoding': 'identity', 'User-Agent': 'rhhype-public-metadata/1.0'})
                    response = connection.getresponse()
                    record['http_status'] = response.status
                    length = response.getheader('Content-Length')
                    if length is not None:
                        record['declared_length'] = length[:24]
                        if not re.fullmatch(r'[0-9]{1,9}', length) or int(length) > cap:
                            raise Refusal('declared_length_invalid_or_over_cap')
                    try:
                        while True:  # http.client decodes chunked bodies and keeps the socket reusable
                            chunk = response.read1(min(16384, cap + 1 - len(body)))
                            if not chunk:
                                break
                            body.extend(chunk)
                            if len(body) > cap:
                                del body[cap:]  # never retain beyond the cap; evidence is the flag
                                record['over_cap'] = True
                                raise Refusal('body_over_cap')
                    except http.client.IncompleteRead as exc:
                        body.extend(exc.partial[:cap - len(body)])
                        raise Refusal('incomplete_read') from None
                    if length is not None and len(body) != int(length):
                        raise Refusal('incomplete_body')
                    if (response.getheader('Content-Encoding') or 'identity').lower() != 'identity':
                        raise Refusal('unsupported_content_encoding')
                    media = (response.getheader('Content-Type') or '').split(';', 1)[0].strip().lower()
                    if response.status != 200:
                        raise Refusal('http_status_not_200')
                    if media != 'application/json':
                        raise Refusal('unsupported_content_type')
                    if getattr(response, 'will_close', False) or \
                            (response.getheader('Connection') or '').lower() == 'close':
                        connection.close()  # retire; only the next distinct planned request reopens
                        connection = None
            except Refusal as exc:
                record['code'] = str(exc)
            except Exception:
                record['code'] = 'transport_failure'
            record.update(received_utc=utc(), received_ms=now_ms(), received_mono_ns=time.monotonic_ns())
            bundle.add(record, bytes(body))
            records.append(dict(record, body=bytes(body)))
            if record['code']:
                receipt['stop'] = record['code']
                return
    finally:
        if connection is not None:
            connection.close()


def publish(path, value, cap, controls=False):
    data = encoded(value)
    if len(data) > cap:
        raise Refusal('publication_byte_cap')
    if controls:
        used = sum(p.stat().st_size for p in path.parent.glob('*.json') if p.name != 'projection.json')
        if used + 2 * len(data) > CONTROL_CAP:
            raise Refusal('control_total_byte_cap')
    h.write_once(path, data)


def worker(plan_sha256, out):
    receipt = {'schema': 'hip4-continuation-books-terminal-v1', 'started_utc': utc(),
               'plan_sha256': plan_sha256, 'status': 'inconclusive', 'code': None, 'stop': None,
               'requests_planned': 91, 'requests_attempted': 0, 'connections_opened': 0,
               'bundle_bytes': 0, 'bundle_sha256': None, 'projection_published': False}
    records, bundle = [], Bundle()
    deadline = time.monotonic() + PROCESS_SECONDS - 15
    try:
        _, cohort = verify(plan_sha256)
        plan = requests(cohort)
        try:
            fetch_all(plan, bundle, records, receipt, deadline)
        finally:
            packed = bundle.finish()
            if len(packed) > BUNDLE_CAP:
                raise Refusal('bundle_gzip_cap_breached')
            h.write_once(out / 'responses.bundle.gz', packed)
            receipt.update(bundle_bytes=len(packed), bundle_sha256=digest(packed))
        if receipt['stop']:
            raise Refusal(receipt['stop'])  # retained prefix and terminal only; no projection
        verify(plan_sha256)
        parsed = parse_bundle(packed)  # analyze the retained bytes, not process memory
        validate_records(parsed, plan)
        projection = build_projection(parsed, cohort, plan_sha256, packed)
        verify(plan_sha256)
        publish(out / 'projection.json', projection, PROJECTION_CAP)
        receipt.update(projection_published=True, status=projection['status'])
    except Refusal as exc:
        receipt['code'] = str(exc)
    except Exception:
        receipt['code'] = 'internal_failure'
    finally:
        receipt['ended_utc'] = utc()
        try:
            verify(plan_sha256)
        except Exception:
            receipt.update(code='post_run_pin_check_failed', status='inconclusive')
        publish(out / 'terminal.json', receipt, 4096, controls=True)


def conclusion_checks(out, plan_sha256, finished):
    """Every gate, including an independent re-analysis of the retained bundle."""
    def read(path, cap):
        try:
            return pm.strict_json(bounded_read(path, cap))
        except Exception:
            return None
    terminal = read(out / 'terminal.json', 4096)
    projection = read(out / 'projection.json', PROJECTION_CAP)
    valid = (isinstance(terminal, dict) and terminal.get('schema') == 'hip4-continuation-books-terminal-v1'
             and terminal.get('plan_sha256') == plan_sha256)
    checks = {'worker_completed_exit_zero': finished,
              'terminal_without_failure': valid and terminal.get('code') is None and terminal.get('stop') is None
                                          and terminal.get('projection_published') is True
                                          and terminal.get('requests_attempted') == 91,
              'bundle_matches_terminal': False, 'records_match_plan': False,
              'projection_reproduced': False,
              'no_pending_publication': not any(out.glob('*.pending'))}
    try:
        _, cohort = verify(plan_sha256)
        checks['final_plan_and_source_pins'] = True
    except Exception:
        cohort = None
        checks['final_plan_and_source_pins'] = False
    try:
        packed = bounded_read(out / 'responses.bundle.gz', BUNDLE_CAP)
        checks['bundle_matches_terminal'] = (valid and len(packed) == terminal.get('bundle_bytes')
                                             and digest(packed) == terminal.get('bundle_sha256'))
        if cohort is not None:
            parsed = parse_bundle(packed)
            validate_records(parsed, requests(cohort))
            checks['records_match_plan'] = True
            recomputed = build_projection(parsed, cohort, plan_sha256, packed)
            checks['projection_reproduced'] = (isinstance(projection, dict)
                                               and encoded(recomputed) == encoded(projection)
                                               and valid and projection.get('status') == terminal.get('status'))
    except Exception:
        pass
    attempts = terminal.get('requests_attempted') if valid else 'unknown_0_to_91'
    return checks, attempts, terminal if valid else None


def supervise(process, deadline, out, plan_sha256):
    try:
        process.start()
        started = True
    except Exception:
        started = False
    timed_out = False
    if started:
        process.join(max(0, deadline - time.monotonic() - 0.5))
        timed_out = process.is_alive()
        if timed_out:
            process.kill()
            process.join(max(0, deadline - time.monotonic()))
    finished = started and not timed_out and process.exitcode == 0
    checks, attempts, terminal = conclusion_checks(out, plan_sha256, finished)
    eligible = all(checks.values())
    record = {'schema': 'hip4-continuation-books-supervisor-v1', 'plan_sha256': plan_sha256,
              'ended_utc': utc(), 'status': 'start_failed' if not started else 'process_deadline' if timed_out
              else 'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode if started else None, 'requests_attempted': attempts,
              'checks': checks, 'conclusion_eligible': eligible,
              'conclusion_status': terminal['status'] if eligible else 'inconclusive'}
    publish(out / 'supervisor.json', record, 2048, controls=True)
    return record


def run(plan_sha256):
    deadline = time.monotonic() + PROCESS_SECONDS
    with pm.hard_deadline(PROCESS_SECONDS, 'process_deadline_before_claim'):
        verify(plan_sha256)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out / 'claim.json', {
        'schema': 'hip4-continuation-books-claim-v1', 'started_utc': utc(),
        'plan_sha256': plan_sha256, 'source_sha256': digest(bounded_read(ROOT / SOURCE, 131072)),
        'request_count_max': 91, 'purpose': 'public_book_snapshot_certificate_only'},
        2048, controls=True)
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        frozen = pm.strict_json(bounded_read(ROOT / FROZEN_META, h.PROJECTION_CAP))
        plan = requests(frozen_cohort(frozen))
        print(encoded({'status': 'dry_no_http', 'request_count': 0, 'planned_requests': len(plan),
                       'planned_weight': sum(20 if p['kind'] == 'meta' else 2 for p in plan),
                       'first': plan[1]['payload'].decode(), 'last_book': plan[-2]['payload'].decode()}).decode(),
              end='')
        return 0
    try:
        result = run(args.plan_sha256)
    except Refusal as exc:
        result = {'status': 'refused_no_retry', 'code': str(exc)}
    except FileExistsError:
        result = {'status': 'refused_no_retry', 'code': 'existing_output'}
    except Exception:
        result = {'status': 'failed_no_retry', 'code': 'internal_failure'}
    print(encoded(result).decode(), end='')
    return 0 if result.get('conclusion_eligible') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
