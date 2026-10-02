#!/usr/bin/env python3
"""HIP-4 continuation expiry v1: near-expiry BTC books and settlement semantics.

Default is dry and performs no HTTP. A run needs the exact sha256 of a root-frozen plan and
a launch inside 05:00-05:38 UTC on 3 October 2026. It follows a fixed schedule with no
retry: an outcomeMeta bracket around three five-book L2 snapshots of binary 7544 and
question 371, then settledOutcome reads near 06:01 and 06:10 (plus one unsettled control)
and a final outcomeMeta. Each record is persisted as its own gzip member before the next
request, under an exact cap with a fail-closed admission bound. Any stop is a failure and
keeps the retained prefix. Analysis reuses the reviewed book-gate parser, timing gates,
exact certificate and dominance models; settlement responses must bind to the requested id
and the exact frozen spec. Design: reports/hip4-research-continuation/expiry-v1-design.md
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_books as b  # reviewed parser, gates, certificate, fetch

h, pm = b.h, b.pm
Refusal = pm.Refusal
digest, encoded, utc, bounded_read = pm.digest, pm.encoded, pm.utc, pm.bounded_read

PLAN = ROOT / 'reports/experiment-storage/hip4-continuation-expiry-v1.json'
SCHEMA = 'hip4-continuation-expiry-v1'
SOURCE = 'scripts/hip4_continuation_expiry.py'
TEST = 'tests/test_hip4_continuation_expiry.py'
PINNED = (SOURCE, TEST, b.SOURCE, h.SOURCE, h.HELPER)
OUT = 'reports/hip4-research-continuation/expiry-v1'
UTC = dt.timezone.utc
DAY = dt.date(2026, 10, 3)
LAUNCH = ('05:00:00', '05:38:00')
END = '06:12:30'
EXPIRY = '06:00:00'
LATE_TOLERANCE_SECONDS = 5
BUNDLE_CAP, PROJECTION_CAP, CONTROL_CAP = 49152, 24576, 12288
FIVE = (7550, 7551, 7552, 7553, 7544)
SETTLED = (7544, 7550, 7551, 7552, 7553, 1473)
CONTROL = 1473
CONTROL_QUESTION = 198  # long-dated witness: must be present and unchanged before any absence is classified
ROLES = {'F': 7550, 'L': 7551, 'M': 7552, 'H': 7553, 'B': 7544}
PRICE_REQUIRED = ('B', 'L', 'M', 'H')  # P8: each must carry details "price:X"; F may omit it
THRESHOLDS = (Decimal('84251'), Decimal('87690'))
TARGET = Decimal('85971')
SPEC_KEYS = ('description', 'name', 'outcome', 'quoteToken', 'sideSpecs')
SCHEDULE = (('05:40:00', 'meta_pre', ('meta',)), ('05:40:05', 'S1', FIVE), ('05:50:00', 'S2', FIVE),
            ('05:57:00', 'S3', FIVE), ('05:57:10', 'meta_mid', ('meta',)),
            ('06:01:00', 'settled_0601', SETTLED), ('06:10:00', 'settled_0610', SETTLED + ('meta',)))
REQUEST_PLAN = {
    'method': 'POST', 'url': 'https://api.hyperliquid.xyz/info', 'day_utc': DAY.isoformat(),
    'launch_window_utc': list(LAUNCH), 'end_utc': END, 'late_tolerance_seconds': LATE_TOLERANCE_SECONDS,
    'schedule': [[at, name, list(items)] for at, name, items in SCHEDULE],
    'request_count': 30, 'documented_weight': 330,
    'connection': 'one keep-alive connection per scheduled group via the reused book-gate fetch, which '
                  'retires a connection after any protocol-indicated close and counts every open; never a retry',
    'caps': {'meta_body': b.META_CAP, 'other_body': b.BOOK_CAP, 'bundle_gzip_exact': BUNDLE_CAP},
    'bundle': 'one gzip member per record, written and fsynced to a pending file before the next request '
              'and hard-linked to the final name at the end (a killed worker leaves the pending prefix); '
              'a request is sent only if a worst-case empty record still fits; a record that does not fit '
              'keeps a bounded body prefix whose stored (level 0) member fits (bounded, not proven maximal), '
              'is flagged truncated, and stops the run as a failure',
    'retry': False, 'redirects': False, 'environment_proxies': False, 'any_stop_is_failure': True,
}
ANALYSIS_PLAN = {
    'roles': ROLES, 'thresholds': [str(x) for x in THRESHOLDS], 'target': str(TARGET),
    'binary_spec': b.BINARY_SPEC, 'question': 371, 'control': CONTROL,
    'snapshot_gates': 'book-gate freshness, local window and server spread; Q371 and 7544 brackets '
                      'unchanged at meta_pre and meta_mid',
    'models': b.DOMINANCE['models'], 'arithmetic': b.ANALYSIS_PLAN['arithmetic'],
    'settlement_binding': 'a settledOutcome object counts only if spec.outcome is the requested id, the spec '
                          'equals the frozen canonical spec exactly, and settleFraction is a decimal in [0, 1]',
    'price_detail_premise': 'B, L, M and H must each carry details "price:X" and all X must agree; F may omit '
                            'details or carry an empty string, but a present F price must parse and agree; a missing, '
                            'unparsable or conflicting price is a premise failure, never agreement',
    'p6': 'consistent_at_observed_price if every role matches its expected 0/1 at the one observed X; '
          'falsified_at_observed_price on any mismatch; unavailable on any premise failure; a match does not '
          'identify the mapping at unobserved prices',
    'settlement_observation': 'observation bounds only: each read keeps its send and receive times and shape, and a valid '
               'bound object proves the record existed by that read\'s receipt; no protocol settlement lower bound '
               'is derived, because a null response is not proof of an unsettled state',
    'removal': 'classified only from a final outcomeMeta that parses with outcomes and questions lists, '
               'integer ids and no duplicates, and in which the long-dated control question 198 matches its '
               'frozen structure (book-gate meta check) with control outcome 1473 listed; otherwise unavailable',
    'ex_post': 'one unit at the touch, zero fee, valued only when every role in the route has a valid bound '
               'settlement; otherwise the route lists its premise failures and carries no value',
}
OUTPUT_LIMITS = {'bundle_gzip': BUNDLE_CAP, 'projection': PROJECTION_CAP,
                 'claim_terminal_and_supervisor_receipts': CONTROL_CAP}
HEADER_KEYS = tuple(sorted(b.HEADER_KEYS + ('group', 'scheduled_ms', 'truncated_from')))


def at(clock):
    hh, mm, ss = (int(x) for x in clock.split(':'))
    return dt.datetime(DAY.year, DAY.month, DAY.day, hh, mm, ss, tzinfo=UTC)


def at_ms(clock):
    return int(at(clock).timestamp() * 1000)


def now_utc():
    return dt.datetime.now(UTC)


def sleep(seconds):
    time.sleep(seconds)


def plan_items():
    items, index = [], 0
    for clock, group, members in SCHEDULE:
        for member in members:
            if member == 'meta':
                item = {'kind': 'meta', 'coin': None, 'body': {'type': 'outcomeMeta'}}
            elif group.startswith('S'):
                item = {'kind': 'book', 'outcome': member, 'side': 0, 'coin': f'#{10 * member}',
                        'body': {'type': 'l2Book', 'coin': f'#{10 * member}', 'nSigFigs': None}}
            else:
                item = {'kind': 'settled', 'outcome': member, 'coin': None,
                        'body': {'type': 'settledOutcome', 'outcome': member}}
            item.update(index=index, group=group, at=clock, scheduled_ms=at_ms(clock),
                        payload=json.dumps(item['body'], separators=(',', ':')).encode('ascii'))
            items.append(item)
            index += 1
    return items


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
    if not isinstance(p, dict) or p.get('schema') != SCHEMA or p.get('status') != 'frozen_expiry_schedule':
        raise Refusal('plan_not_frozen')
    for key, expected in (('request_plan', REQUEST_PLAN), ('analysis_plan', ANALYSIS_PLAN),
                          ('output_limits_bytes', OUTPUT_LIMITS)):
        if encoded(p.get(key)) != encoded(expected):
            raise Refusal(f'{key}_changed')
    if p.get('output_dir') != OUT or (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_plan_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != len(PINNED) or sorted(
            pin.get('path') for pin in pins if isinstance(pin, dict)) != sorted(PINNED):
        raise Refusal('missing_source_pins')
    for pin in pins:
        data = bounded_read(ROOT / pin['path'], 262144)
        if (ROOT / pin['path']).resolve() != ROOT.resolve() / pin['path'] or type(pin.get('bytes')) is not int \
                or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if p.get('previous') != b.PREVIOUS or digest(bounded_read(ROOT / b.PREVIOUS, 65536)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    return p, b.frozen_cohort(frozen_projection())


def frozen_projection():
    frozen = bounded_read(ROOT / b.FROZEN_META, h.PROJECTION_CAP)
    if digest(frozen) != b.FROZEN_META_SHA:
        raise Refusal('frozen_metadata_changed')
    return pm.strict_json(frozen)


def frozen_specs(projection):
    """Canonical settledOutcome specs from the pinned projection; 7544 from the frozen baseline."""
    specs = {b.BINARY_SPEC['outcome']: b.BINARY_SPEC}
    for q in projection['questions']:
        for s in q['member_specs']:
            if s['outcome'] in SETTLED:
                specs[s['outcome']] = {'description': s['description'], 'name': s['name'], 'outcome': s['outcome'],
                                       'quoteToken': s['quoteToken'], 'sideSpecs': [{'name': n} for n in s['sideNames']]}
    if sorted(specs) != sorted(SETTLED):
        raise Refusal('frozen_spec_missing')
    return specs


def stored_member(data):
    stream = zlib.compressobj(0, zlib.DEFLATED, 31)  # size is monotone in len(data)
    return stream.compress(data) + stream.flush(zlib.Z_FINISH)


def best_member(data):
    stream = zlib.compressobj(9, zlib.DEFLATED, 31)  # deterministic: no name, mtime 0
    return stream.compress(data) + stream.flush(zlib.Z_FINISH)


def framed(header, body, full_bytes):
    return encoded(dict(header, body_bytes=len(body), body_sha256=digest(body),
                        truncated_from=None if len(body) == full_bytes else full_bytes)) + body + b'\n'


WORST_HEADER = {k: None for k in HEADER_KEYS if k not in ('body_bytes', 'body_sha256', 'truncated_from')}
WORST_HEADER.update(index=10 ** 6, kind='settled', coin='#' + '9' * 12, group='settled_0610',
                    request='x' * 96, scheduled_ms=2 ** 63,
                    sent_utc='9999-12-31T23:59:59.999999+00:00', received_utc='9999-12-31T23:59:59.999999+00:00',
                    sent_ms=2 ** 63, received_ms=2 ** 63, sent_mono_ns=2 ** 63, received_mono_ns=2 ** 63,
                    http_status=None, code='x' * 64, declared_length='9' * 24, over_cap=False)
EMPTY_BOUND = len(stored_member(framed(WORST_HEADER, b'', 2 ** 63)))  # longest form of every field


class Members:
    """Progressive pending file of one gzip member per record under an exact cap."""

    def __init__(self, path, cap=None):
        self.path, self.cap = path, BUNDLE_CAP if cap is None else cap
        self.pending = path.with_name(path.name + '.pending')
        self.stream = self.pending.open('xb')
        self.size, self.count, self.truncated = 0, 0, False

    def admits(self):
        return not self.truncated and self.size + EMPTY_BOUND <= self.cap

    def add(self, header, body):
        chunk = best_member(framed(header, body, len(body)))
        if self.size + len(chunk) > self.cap:
            room, keep = self.cap - self.size, len(body)
            while True:  # stored size(n) - size(n-k) >= k, so cutting the excess always fits
                chunk = stored_member(framed(header, body[:keep], len(body)))
                excess = self.size + len(chunk) - self.cap
                if excess <= 0 or keep == 0:
                    break
                keep = max(0, keep - excess)
            if len(chunk) > room:
                raise Refusal('bundle_cap_exhausted')  # the admission bound makes this unreachable
            self.truncated = True
        self.stream.write(chunk)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.size += len(chunk)
        self.count += 1

    def finish(self):
        self.stream.close()
        os.link(self.pending, self.path)  # same inode, refuses overwrite
        self.pending.unlink()
        return bounded_read(self.path, self.cap)


def parse_members(packed):
    records, rest = [], packed
    while rest:
        inflater = zlib.decompressobj(31)
        try:
            data = inflater.decompress(rest, b.RAW_LIMIT + 1)
        except zlib.error:
            raise Refusal('bundle_not_gzip') from None
        if not inflater.eof or inflater.unconsumed_tail or len(records) >= 30:
            raise Refusal('bundle_incomplete_or_extra')
        rest = inflater.unused_data
        end = data.find(b'\n')
        header = pm.strict_json(data[:end + 1]) if end >= 0 else None
        if not isinstance(header, dict) or tuple(sorted(header)) != HEADER_KEYS or not h.uint(header['body_bytes']):
            raise Refusal('bundle_header')
        body = data[end + 1:end + 1 + header['body_bytes']]
        if len(data) != end + 2 + header['body_bytes'] or data[-1:] != b'\n' or digest(body) != header['body_sha256']:
            raise Refusal('bundle_body_mismatch')
        records.append(dict(header, body=body))
    return records


def validate(records, items):
    """Plan identity, success, integer monotone clocks and the recorded schedule of every record."""
    if len(records) != len(items):
        raise Refusal('record_count_mismatch')
    starts = {}
    for item in items:
        starts.setdefault(item['group'], item['scheduled_ms'])
    following = dict(zip(list(starts), list(starts.values())[1:] + [at_ms(END)]))
    previous, seen = 0, set()
    for record, item in zip(records, items):
        if (record['index'], record['kind'], record['coin'], record['request'], record['group'],
                record['scheduled_ms']) != (item['index'], item['kind'], item['coin'],
                                            item['payload'].decode('ascii'), item['group'], item['scheduled_ms']):
            raise Refusal('record_plan_mismatch')
        if record['http_status'] != 200 or record['code'] is not None or record['over_cap'] is not False \
                or record['truncated_from'] is not None:
            raise Refusal('record_not_successful')
        clocks = [record[k] for k in ('sent_ms', 'received_ms', 'sent_mono_ns', 'received_mono_ns')]
        if not all(h.uint(c) for c in clocks) or record['sent_mono_ns'] > record['received_mono_ns'] \
                or record['sent_mono_ns'] < previous or record['sent_ms'] > record['received_ms']:
            raise Refusal('record_clock_invalid')
        previous = record['received_mono_ns']
        late = record['sent_ms'] - item['scheduled_ms']
        first = item['group'] not in seen
        seen.add(item['group'])
        if late < 0 or (first and late > LATE_TOLERANCE_SECONDS * 1000) \
                or record['received_ms'] > following[item['group']]:
            raise Refusal('record_schedule_invalid')
        cap = b.META_CAP if item['kind'] == 'meta' else b.BOOK_CAP
        if len(record['body']) > cap or (record['declared_length'] is not None
                                         and record['declared_length'] != str(len(record['body']))):
            raise Refusal('record_length_invalid')


def settled(record, oid, spec):
    """Parse one settledOutcome response bound to the requested id and the frozen spec."""
    if record is None:
        return {'shape': 'unavailable', 'issues': ['not_recorded']}
    try:
        obj = pm.strict_json(record['body'])
    except Refusal:
        return {'shape': 'invalid', 'issues': ['invalid_json']}
    if obj is None:
        return {'shape': 'null', 'issues': []}
    if not isinstance(obj, dict) or not isinstance(obj.get('spec'), dict):
        return {'shape': 'other', 'issues': ['not_an_object_with_spec']}
    issues = []
    if obj['spec'].get('outcome') != oid:
        issues.append('spec_outcome_not_requested_id')
    if encoded(obj['spec']) != encoded(spec):
        issues.append('spec_not_frozen_canonical')
    fraction = None
    try:
        fraction = b.decimal_text(obj.get('settleFraction'))
        if fraction > b.ONE:
            fraction, issues = None, issues + ['fraction_out_of_range']
    except ValueError:
        issues.append('fraction_invalid')
    details = obj.get('details')
    found = re.fullmatch(r'price:([0-9]{1,20}(\.[0-9]{1,30})?)', details) if isinstance(details, str) else None
    return {'shape': 'object', 'issues': issues, 'fraction': fraction,
            'price': Decimal(found.group(1)) if found else None,
            'details': 'absent' if details is None else 'empty' if details == '' else 'price' if found else 'unparsed'}


def valid(s):
    return s['shape'] == 'object' and not s['issues'] and s['fraction'] is not None


def expected(role, x):
    low, high = THRESHOLDS
    return {'L': x < low, 'M': low <= x < high, 'H': x >= high, 'F': False, 'B': x >= TARGET}[role]


def p6_check(final):
    """Per-role comparisons at the one observed price; a match is consistency, not identification."""
    roles, failures = {}, []
    for role, oid in ROLES.items():
        s = final[oid]
        roles[role] = {'shape': s['shape'], 'issues': s['issues'], 'fraction': s.get('fraction'),
                       'price': s.get('price'), 'details': s.get('details')}
        if s.get('details') == 'unparsed':
            failures.append(f'{role}_price_detail_unparsed')  # present but malformed is never omission
        if not valid(s):
            failures.append(f'{role}_settlement_invalid_or_absent')
        elif s['fraction'] not in (b.ZERO, b.ONE):
            failures.append(f'{role}_fraction_not_0_or_1')
        if role in PRICE_REQUIRED and s.get('price') is None:
            failures.append(f'{role}_price_detail_missing')
    prices = sorted({s['price'] for s in roles.values() if s['price'] is not None})
    if len(prices) > 1:
        failures.append('settlement_prices_disagree')
    if failures or not prices:
        return {'status': 'unavailable', 'premise_failures': failures or ['no_price'], 'observed_prices': prices,
                'roles': roles}
    x = prices[0]
    for role, item in roles.items():
        item.update(expected_at_price=b.ONE if expected(role, x) else b.ZERO)
        item['match'] = item['fraction'] == item['expected_at_price']
    status = 'consistent_at_observed_price' if all(r['match'] for r in roles.values()) else 'falsified_at_observed_price'
    return {'status': status, 'premise_failures': [], 'observed_prices': prices, 'roles': roles,
            'scope': 'one realized price; buckets not containing it are not identified'}


def observation(r1, r2, s1, s2):
    """Observed read intervals and shapes. A valid bound object proves the record existed by that read's
    receipt; no protocol settlement lower bound is derived, because null is not proof of an unsettled state."""
    expiry = at_ms(EXPIRY)
    reads = [{'read': name, 'shape': s['shape'], 'valid_object': valid(s),
              'sent_ms': None if r is None else r['sent_ms'], 'received_ms': None if r is None else r['received_ms']}
             for name, r, s in (('read1', r1, s1), ('read2', r2, s2))]
    first = next((x for x in reads if x['valid_object'] and x['received_ms'] is not None), None)
    out = {'reads': reads, 'protocol_settlement_lower_bound': 'unavailable',
           'valid_object_observed_by_ms': None if first is None else first['received_ms'],
           'valid_object_observed_by_minus_expiry_ms': None if first is None else first['received_ms'] - expiry}
    if reads[0]['valid_object'] and reads[1]['shape'] == 'null':
        out['anomaly'] = 'null_after_valid_object'
    return out


def listing(record):
    """Strict outcomes/questions id sets of one outcomeMeta body, or None."""
    if record is None or record.get('code') or record.get('http_status') != 200:
        return None
    try:
        obj = pm.strict_json(record['body'])
    except Refusal:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get('outcomes'), list) \
            or not isinstance(obj.get('questions'), list):
        return None
    ids = [o.get('outcome') if isinstance(o, dict) else None for o in obj['outcomes']]
    qids = [q.get('question') if isinstance(q, dict) else None for q in obj['questions']]
    if not all(h.uint(i) for i in ids + qids) or len(set(ids)) != len(ids) or len(set(qids)) != len(qids):
        return None
    return set(ids), set(qids)


ROUTES = {'B_ask_lt_H_bid': ('B', 'H'), 'B_bid_plus_L_bid_gt_1': ('B', 'L'),
          'B_bid_gt_M_H_F_asks': ('B', 'M', 'H', 'F'), 'semantic_B_bid_gt_M_H_asks': ('B', 'M', 'H')}


def ex_post(tops, final):
    """Conditional zero-fee one-unit values for true relations; invalid settlements carry no value."""
    bid = {k: t['bid'][0] if t['bid'] else None for k, t in tops.items()}
    ask = {k: t['ask'][0] if t['ask'] else None for k, t in tops.items()}
    with b.exact():
        true = {'B_ask_lt_H_bid': None not in (ask['B'], bid['H']) and ask['B'] < bid['H'],
                'B_bid_plus_L_bid_gt_1': None not in (bid['B'], bid['L']) and bid['B'] + bid['L'] > 1,
                'B_bid_gt_M_H_F_asks': None not in (bid['B'], ask['M'], ask['H'], ask['F'])
                                       and bid['B'] > ask['M'] + ask['H'] + ask['F'],
                'semantic_B_bid_gt_M_H_asks': None not in (bid['B'], ask['M'], ask['H'])
                                              and bid['B'] > ask['M'] + ask['H']}
        out = {}
        for name, roles in ROUTES.items():
            if not true[name]:
                continue
            bad = [r for r in roles if not valid(final[ROLES[r]])]
            if bad:
                out[name] = {'value': None, 'premise_failures': [f'{r}_settlement_invalid_or_absent' for r in bad]}
                continue
            s = {r: final[ROLES[r]]['fraction'] for r in roles}
            value = {'B_ask_lt_H_bid': lambda: -ask['B'] - 1 + bid['H'] + s['B'] + (1 - s['H']),
                     'B_bid_plus_L_bid_gt_1': lambda: -2 + bid['B'] + bid['L'] + (1 - s['B']) + (1 - s['L']),
                     'B_bid_gt_M_H_F_asks': lambda: -1 + bid['B'] - ask['M'] - ask['H'] - ask['F']
                                                    + (1 - s['B']) + s['M'] + s['H'] + s['F'],
                     'semantic_B_bid_gt_M_H_asks': lambda: -1 + bid['B'] - ask['M'] - ask['H']
                                                           + (1 - s['B']) + s['M'] + s['H']}[name]()
            out[name] = {'value': value, 'premise_failures': []}
    return out


def analyze(records, cohort, specs):
    by_group = {}
    for r in records:
        by_group.setdefault(r['group'], []).append(r)
    metas = {g: b.meta_check(by_group.get(g, [None])[0], cohort) for g in ('meta_pre', 'meta_mid')}
    bracket = all(m[0][371] == 'unchanged' and m[1] == 'unchanged' for m in metas.values())
    reads = {name: {r['outcome_id']: r for r in by_group.get(name, []) if r['kind'] == 'settled'}
             for name in ('settled_0601', 'settled_0610')}
    parsed = {name: {oid: settled(group.get(oid), oid, specs[oid]) for oid in SETTLED}
              for name, group in reads.items()}
    final = parsed['settled_0610']
    snapshots = {}
    for name in ('S1', 'S2', 'S3'):
        group = {r['outcome_id']: r for r in by_group.get(name, [])}
        books = {role: b.tops_of(group.get(oid)) for role, oid in ROLES.items()}
        if any(err for _, err in books.values()):
            snapshots[name] = {'usable': False, 'blockers': sorted({e for _, e in books.values() if e})}
            continue
        tops = {role: t for role, (t, _) in books.items()}
        clock = b.timing(list(tops.values()))
        blockers = [x for x in ('metadata_bracket' if not bracket else None, b.gate(clock)) if x]
        cert = b.certify({ROLES[r]: {'yes_bid': tops[r]['bid'], 'yes_ask': tops[r]['ask']} for r in 'FLMH'})
        snapshots[name] = dict(clock, usable=not blockers, blockers=blockers, q371_certificate=cert['status'],
                               agnostic_six_state=b.dominance(tops),
                               fallback_zero_semantic=b.dominance(tops, fallback_zero=True),
                               time_to_expiry_ms=at_ms(EXPIRY) - max(t['time'] for t in tops.values()),
                               tops={r: {'bid': t['bid'], 'ask': t['ask']} for r, t in tops.items()})
        if not blockers:
            snapshots[name]['ex_post_zero_fee_one_unit'] = ex_post(tops, final)
    lat = {str(oid): observation(reads['settled_0601'].get(oid), reads['settled_0610'].get(oid),
                             parsed['settled_0601'][oid], final[oid]) for oid in SETTLED}
    post = by_group.get('settled_0610', [])
    final_meta = post[-1] if post and post[-1]['kind'] == 'meta' else None
    found = listing(final_meta)
    witness = b.meta_check(final_meta, cohort)[0][CONTROL_QUESTION]
    if found is None or witness != 'unchanged' or CONTROL not in found[0]:
        removal = {'status': 'unavailable', 'strict_listing': found is not None,
                   'control_question_198': witness, 'control_1473_listed': bool(found and CONTROL in found[0])}
    else:
        ids, qids = found
        removal = {str(o): 'listed' if o in ids else 'absent' for o in SETTLED}
        removal['question_371'] = 'listed' if 371 in qids else 'absent'
    usable = [n for n, s in snapshots.items() if s['usable']]
    infeasible = [n for n in usable if not snapshots[n]['agnostic_six_state']['feasible']]
    h2 = 'inconclusive' if not usable else 'candidate' if infeasible else 'no_violation'
    return b.stringify({
        'schema': 'hip4-continuation-expiry-projection-v1', 'h2': h2, 'usable_snapshots': usable,
        'infeasible_snapshots': infeasible, 'bracket_unchanged': bracket,
        'meta': {g: {'q371': m[0].get(371), 'binary': m[1]} for g, m in metas.items()},
        'snapshots': snapshots, 'p6_index_map': p6_check(final), 'settlement_observation': lat,
        'settlement_reads': {name: {str(o): {'shape': s['shape'], 'issues': s['issues']} for o, s in group.items()}
                             for name, group in parsed.items()},
        'control_1473_shapes': {name: group[CONTROL]['shape'] for name, group in parsed.items()},
        'removal_after_settlement': removal,
        'claim': 'conditional zero-fee valuation checks on recorded L2 quote vectors near one expiry and '
                 'observed settlement responses; no fills, fees, takerability, quote identity or profit'})


def build_projection(records, cohort, specs, plan_sha256, packed):
    projection = analyze(records, cohort, specs)
    projection.update(plan_sha256=plan_sha256, bundle_sha256=digest(packed), records=len(records))
    return projection


class GroupBundle:
    """Adapter so the reviewed fetch loop writes group-tagged members into the shared bundle."""

    def __init__(self, members, item_by_index, group):
        self.members, self.items, self.group = members, item_by_index, group

    def room_for(self, _cap):
        return self.members.admits()

    def add(self, header, body):
        self.members.add(dict(header, group=self.group, scheduled_ms=self.items[header['index']]['scheduled_ms']),
                         body)


def with_ids(records, items):
    by_index = {i['index']: i for i in items}
    return [dict(r, outcome_id=by_index.get(r['index'], {}).get('outcome')) for r in records]


def wait_until(moment):
    while True:
        remaining = (moment - now_utc()).total_seconds()
        if remaining <= 0:
            return -remaining
        sleep(remaining)


def worker(plan_sha256, out):
    receipt = {'schema': 'hip4-continuation-expiry-terminal-v1', 'started_utc': utc(), 'plan_sha256': plan_sha256,
               'status': 'inconclusive', 'code': None, 'stop': None, 'requests_planned': 30,
               'requests_attempted': 0, 'connections_opened': 0, 'records_retained': 0, 'bundle_bytes': 0,
               'bundle_sha256': None, 'projection_published': False}
    members = None
    try:
        _, cohort = verify(plan_sha256)
        specs = frozen_specs(frozen_projection())
        items = plan_items()
        by_index = {i['index']: i for i in items}
        members = Members(out / 'responses.members.gz')
        try:
            for clock, group, _ in SCHEDULE:
                if wait_until(at(clock)) > LATE_TOLERANCE_SECONDS:
                    receipt['stop'] = 'schedule_missed'
                    break
                group_items = [i for i in items if i['group'] == group]
                b.fetch_all(group_items, GroupBundle(members, by_index, group), [], receipt,
                            deadline=time.monotonic() + 60)
                if members.truncated:
                    receipt['stop'] = 'bundle_cap_truncated'  # the root cause, even if admission then refused
                if receipt['stop']:
                    break
        finally:
            packed = members.finish()
            receipt.update(bundle_bytes=len(packed), bundle_sha256=digest(packed), records_retained=members.count)
        if receipt['stop']:
            raise Refusal(receipt['stop'])
        verify(plan_sha256)
        parsed = with_ids(parse_members(packed), items)
        validate(parsed, items)
        projection = build_projection(parsed, cohort, specs, plan_sha256, packed)
        verify(plan_sha256)
        b.publish(out / 'projection.json', projection, PROJECTION_CAP)
        receipt.update(projection_published=True, status=projection['h2'])
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
        publish(out / 'terminal.json', receipt, 4096)


def publish(path, value, cap):
    data = encoded(value)
    used = sum(p.stat().st_size for p in path.parent.glob('*.json') if p.name != 'projection.json')
    if len(data) > cap or used + 2 * len(data) > CONTROL_CAP:
        raise Refusal('control_byte_cap')
    h.write_once(path, data)


def conclusion_checks(out, plan_sha256, finished):
    def read(path, cap):
        try:
            return pm.strict_json(bounded_read(path, cap))
        except Exception:
            return None
    terminal, projection = read(out / 'terminal.json', 4096), read(out / 'projection.json', PROJECTION_CAP)
    valid_terminal = (isinstance(terminal, dict) and terminal.get('schema') == 'hip4-continuation-expiry-terminal-v1'
                      and terminal.get('plan_sha256') == plan_sha256)
    checks = {'worker_completed_exit_zero': finished,
              'terminal_without_failure': valid_terminal and terminal.get('code') is None
                                          and terminal.get('stop') is None
                                          and terminal.get('projection_published') is True
                                          and terminal.get('requests_attempted') == 30,
              'bundle_matches_terminal': False, 'records_match_plan': False, 'projection_reproduced': False,
              'no_pending_publication': not any(out.glob('*.pending'))}
    try:
        _, cohort = verify(plan_sha256)
        specs = frozen_specs(frozen_projection())
        checks['final_plan_and_source_pins'] = True
    except Exception:
        cohort, specs, checks['final_plan_and_source_pins'] = None, None, False
    try:
        packed = bounded_read(out / 'responses.members.gz', BUNDLE_CAP)
        checks['bundle_matches_terminal'] = (valid_terminal and len(packed) == terminal.get('bundle_bytes')
                                             and digest(packed) == terminal.get('bundle_sha256'))
        if cohort is not None:
            items = plan_items()
            parsed = with_ids(parse_members(packed), items)
            validate(parsed, items)
            checks['records_match_plan'] = True
            checks['projection_reproduced'] = (isinstance(projection, dict) and valid_terminal and encoded(
                build_projection(parsed, cohort, specs, plan_sha256, packed)) == encoded(projection))
    except Exception:
        pass
    attempts = terminal.get('requests_attempted') if valid_terminal else 'unknown_0_to_30'
    return checks, attempts, terminal if valid_terminal else None


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
            process.join(5)
    finished = started and not timed_out and process.exitcode == 0
    checks, attempts, terminal = conclusion_checks(out, plan_sha256, finished)
    eligible = all(checks.values())
    record = {'schema': 'hip4-continuation-expiry-supervisor-v1', 'plan_sha256': plan_sha256, 'ended_utc': utc(),
              'status': 'start_failed' if not started else 'process_deadline' if timed_out
              else 'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode if started else None, 'requests_attempted': attempts,
              'pending_prefix_retained': any(out.glob('*.pending')),
              'checks': checks, 'conclusion_eligible': eligible,
              'conclusion_status': terminal['status'] if eligible else 'inconclusive'}
    publish(out / 'supervisor.json', record, 2048)
    return record


def run(plan_sha256):
    start = now_utc()
    if not at(LAUNCH[0]) <= start < at(LAUNCH[1]):
        raise Refusal('outside_launch_window')
    verify(plan_sha256)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out / 'claim.json', {'schema': 'hip4-continuation-expiry-claim-v1', 'started_utc': utc(),
                                 'plan_sha256': plan_sha256, 'request_count_max': 30,
                                 'source_sha256': digest(bounded_read(ROOT / SOURCE, 131072)),
                                 'purpose': 'near_expiry_l2_books_and_settlement_responses'}, 2048)
    deadline = time.monotonic() + (at(END) - now_utc()).total_seconds()
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        items = plan_items()
        print(encoded({'status': 'dry_no_http', 'request_count': 0, 'planned_requests': len(items),
                       'planned_weight': sum(2 if i['kind'] == 'book' else 20 for i in items),
                       'empty_record_bound_bytes': EMPTY_BOUND,
                       'launch_window_utc': [f'{DAY}T{LAUNCH[0]}Z', f'{DAY}T{LAUNCH[1]}Z']}).decode(), end='')
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
