"""Offline synthetics for the HIP-4 near-expiry schedule. No exchange access."""
import contextlib
import datetime as dt
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from scripts import hip4_continuation_expiry as e

b = e.b
FROZEN = b.pm.strict_json((b.ROOT / b.FROZEN_META).read_bytes())
COHORT = b.frozen_cohort(FROZEN)
SPECS = e.frozen_specs(FROZEN)
ITEMS = e.plan_items()
RAW_META = gzip.decompress((b.ROOT / 'reports/hip4-outcome-v1/metadata-v1/response.json.gz').read_bytes())
FAIR = {7550: ('0.001', '0.01'), 7551: ('0.20', '0.25'), 7552: ('0.50', '0.55'), 7553: ('0.20', '0.25'),
        7544: ('0.40', '0.45')}
X = '86000'  # inside the middle bucket and above the binary target
FRACTIONS = {7551: '0.0', 7552: '1.0', 7553: '0.0', 7550: '0.0', 7544: '1.0'}


def book(oid, bid, ask, t):
    lv = lambda px: [{'px': px, 'sz': '5', 'n': 1}] if px else []  # noqa: E731
    return {'coin': f'#{10 * oid}', 'time': t, 'levels': [lv(bid), lv(ask)]}


def settled_body(oid, settled=True, spec=None, fraction=None, details=True):
    if not settled or oid == 1473:
        return b'null'
    body = {'spec': spec or SPECS[oid], 'settleFraction': fraction or FRACTIONS[oid]}
    if details is True:
        body['details'] = f'price:{X}'
    elif details is not False:
        body['details'] = details  # an explicit, possibly malformed, details value
    return json.dumps(body).encode()


def removed_meta():
    meta = json.loads(RAW_META)
    meta['outcomes'] = [o for o in meta['outcomes'] if o['outcome'] not in e.FIVE]
    meta['questions'] = [q for q in meta['questions'] if q['question'] != 371]
    return json.dumps(meta).encode()


def bodies(books=None, mid=None, settled_0601=True, final_meta=None, settle=None):
    out = []
    for item in ITEMS:
        if item['kind'] == 'meta':
            body = ((final_meta if final_meta is not None else removed_meta()) if item['group'] == 'settled_0610'
                    else mid if item['group'] == 'meta_mid' and mid else RAW_META)
        elif item['kind'] == 'book':
            bid, ask = (books or {}).get((item['group'], item['outcome']), FAIR[item['outcome']])
            body = json.dumps(book(item['outcome'], bid, ask, item['scheduled_ms'] - 100)).encode()
        else:
            final = item['group'] == 'settled_0610'
            kwargs = (settle or {}).get(item['outcome'], {}) if final else {}
            body = settled_body(item['outcome'], settled_0601 or final, **kwargs)
        out.append(body)
    return out


def records(**kwargs):
    out, position = [], {}
    for item, body in zip(ITEMS, bodies(**kwargs)):
        k = position[item['group']] = position.get(item['group'], -1) + 1
        sent = item['scheduled_ms'] + 100 * k
        out.append({'index': item['index'], 'kind': item['kind'], 'coin': item['coin'], 'group': item['group'],
                    'request': item['payload'].decode(), 'outcome_id': item.get('outcome'), 'http_status': 200,
                    'code': None, 'sent_ms': sent, 'received_ms': sent + 50, 'scheduled_ms': item['scheduled_ms'],
                    'sent_mono_ns': item['index'] * 1_000_000, 'received_mono_ns': item['index'] * 1_000_000 + 500_000,
                    'over_cap': False, 'truncated_from': None, 'declared_length': None, 'body': body})
    return out


def analyze(**kwargs):
    return e.analyze(records(**kwargs), COHORT, SPECS)


class PlanTests(unittest.TestCase):
    def test_dry_main_and_schedule(self):
        out = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                contextlib.redirect_stdout(out):
            self.assertEqual(e.main([]), 0)
        dry = json.loads(out.getvalue())
        self.assertEqual((dry['planned_requests'], dry['planned_weight'], dry['request_count']), (30, 330, 0))
        self.assertEqual([i['group'] for i in ITEMS].count('S2'), 5)
        self.assertEqual(ITEMS[-1]['payload'], b'{"type":"outcomeMeta"}')
        self.assertEqual(e.ROLES['B'], b.BINARY_SPEC['outcome'])
        self.assertEqual(SPECS[7544], b.BINARY_SPEC)
        raw = {o['outcome']: o for o in json.loads(RAW_META)['outcomes']}
        for oid in (7550, 7551, 7552, 7553):  # canonical spec equals the raw frozen entry
            self.assertEqual(b.encoded(SPECS[oid]), b.encoded(raw[oid]))


class SettlementTests(unittest.TestCase):
    def test_consistent_at_observed_price_retains_prices_and_bounds(self):
        r = analyze()
        p6 = r['p6_index_map']
        self.assertEqual((p6['status'], p6['observed_prices']), ('consistent_at_observed_price', [X]))
        self.assertEqual({k: v['match'] for k, v in p6['roles'].items()}, dict.fromkeys('FLMHB', True))
        self.assertIn('not identified', p6['scope'])
        read1 = records()[ITEMS.index(next(i for i in ITEMS if i['group'] == 'settled_0601'))]
        obs = r['settlement_observation']['7544']
        self.assertEqual((obs['valid_object_observed_by_ms'], obs['protocol_settlement_lower_bound']),
                         (read1['received_ms'], 'unavailable'))
        self.assertEqual(obs['valid_object_observed_by_minus_expiry_ms'], read1['received_ms'] - e.at_ms(e.EXPIRY))
        control = r['settlement_observation']['1473']
        self.assertEqual(([x['shape'] for x in control['reads']], control['valid_object_observed_by_ms']),
                         (['null', 'null'], None))
        self.assertEqual(r['control_1473_shapes'], {'settled_0601': 'null', 'settled_0610': 'null'})
        self.assertEqual((r['removal_after_settlement']['7544'], r['removal_after_settlement']['1473'],
                          r['removal_after_settlement']['question_371']), ('absent', 'listed', 'absent'))

    def test_root_repro_wrong_specs_missing_details_empty_meta(self):
        wrong = {oid: {'spec': dict(SPECS[oid], outcome=999999, description='wrong market')} for oid in e.FIVE}
        p6 = analyze(settle=wrong)['p6_index_map']
        self.assertEqual(p6['status'], 'unavailable')
        self.assertEqual(sorted(f for f in p6['premise_failures'] if 'invalid' in f),
                         sorted(f'{r}_settlement_invalid_or_absent' for r in 'FLMHB'))
        self.assertIn('spec_outcome_not_requested_id', p6['roles']['B']['issues'])
        bare = {oid: {'details': False} for oid in (7551, 7552, 7553, 7544)}
        p6 = analyze(settle=bare)['p6_index_map']
        self.assertEqual((p6['status'], sorted(p6['premise_failures'])),
                         ('unavailable', sorted(f'{r}_price_detail_missing' for r in 'BLMH')))
        dup = json.loads(RAW_META)
        dup['outcomes'].append(dup['outcomes'][0])
        no_control = json.loads(removed_meta())
        no_control['outcomes'] = [o for o in no_control['outcomes'] if o['outcome'] != e.CONTROL]
        wrong_control = json.loads(removed_meta())
        next(o for o in wrong_control['outcomes'] if o['outcome'] == e.CONTROL)['description'] = 'participant:Other'
        no_question = json.loads(removed_meta())
        no_question['questions'] = [q for q in no_question['questions'] if q['question'] != e.CONTROL_QUESTION]
        for name, body in (('empty_object', b'{}'), ('empty_arrays', b'{"outcomes":[],"questions":[]}'),
                           ('duplicate_ids', json.dumps(dup).encode()),
                           ('control_outcome_missing', json.dumps(no_control).encode()),
                           ('control_spec_wrong', json.dumps(wrong_control).encode()),
                           ('control_question_missing', json.dumps(no_question).encode())):
            with self.subTest(name):
                removal = analyze(final_meta=body)['removal_after_settlement']
                self.assertEqual(removal['status'], 'unavailable')
                self.assertNotIn('7544', removal)
        p6 = analyze(settle={7552: {'fraction': '1.5'}})['p6_index_map']
        self.assertEqual((p6['status'], p6['roles']['M']['issues']), ('unavailable', ['fraction_out_of_range']))
        for omitted in (False, ''):  # F may omit details or carry the documented empty form
            p6 = analyze(settle={7550: {'details': omitted}})['p6_index_map']
            self.assertEqual(p6['status'], 'consistent_at_observed_price')
        for malformed in ('price:-1', 'price:abc', 'pricex', 'price:86000 ', 86000):
            with self.subTest(malformed=malformed):
                p6 = analyze(settle={7550: {'details': malformed}})['p6_index_map']
                self.assertEqual((p6['status'], p6['premise_failures']), ('unavailable', ['F_price_detail_unparsed']))
        p6 = analyze(settle={7550: {'details': 'price:85000'}})['p6_index_map']
        self.assertEqual((p6['status'], p6['premise_failures']), ('unavailable', ['settlement_prices_disagree']))

    def test_falsified_and_latency_between_reads(self):
        p6 = analyze(settle={7551: {'fraction': '1.0'}, 7552: {'fraction': '0.0'}})['p6_index_map']
        self.assertEqual((p6['status'], p6['roles']['L']['match'], p6['roles']['M']['match']),
                         ('falsified_at_observed_price', False, False))
        recs = records(settled_0601=False)
        r = e.analyze(recs, COHORT, SPECS)
        first = next(x for x in recs if x['group'] == 'settled_0601' and x['outcome_id'] == 7544)
        second = next(x for x in recs if x['group'] == 'settled_0610' and x['outcome_id'] == 7544)
        obs = r['settlement_observation']['7544']
        self.assertEqual([(x['shape'], x['sent_ms'], x['received_ms']) for x in obs['reads']],
                         [('null', first['sent_ms'], first['received_ms']),
                          ('object', second['sent_ms'], second['received_ms'])])
        self.assertEqual(obs['valid_object_observed_by_ms'], second['received_ms'])
        self.assertNotIn('after_ms', obs)  # a null read never yields a settlement lower bound
        self.assertEqual(obs['protocol_settlement_lower_bound'], 'unavailable')


class AnalysisTests(unittest.TestCase):
    def test_consistent_expiry_books(self):
        r = analyze()
        self.assertEqual((r['h2'], r['usable_snapshots']), ('no_violation', ['S1', 'S2', 'S3']))
        self.assertEqual(r['snapshots']['S1']['ex_post_zero_fee_one_unit'], {})

    def test_violation_values_need_valid_settlements(self):
        books = {('S2', 7544): ('0.15', '0.20'), ('S2', 7553): ('0.30', '0.35')}
        r = analyze(books=books)
        self.assertEqual((r['h2'], r['infeasible_snapshots']), ('candidate', ['S2']))
        route = r['snapshots']['S2']['ex_post_zero_fee_one_unit']['B_ask_lt_H_bid']
        self.assertEqual((Decimal(route['value']), route['premise_failures']), (Decimal('1.10'), []))
        bad = analyze(books=books, settle={7544: {'fraction': '2'}})
        route = bad['snapshots']['S2']['ex_post_zero_fee_one_unit']['B_ask_lt_H_bid']
        self.assertEqual((route['value'], route['premise_failures']), (None, ['B_settlement_invalid_or_absent']))

    def test_bracket_blocks(self):
        mid = json.loads(RAW_META)
        next(o for o in mid['outcomes'] if o['outcome'] == 7544)['description'] = 'changed'
        r = analyze(mid=json.dumps(mid).encode())
        self.assertEqual((r['h2'], r['bracket_unchanged'], r['meta']['meta_mid']['binary']), ('inconclusive', False, 'changed'))
        self.assertIn('metadata_bracket', r['snapshots']['S1']['blockers'])


class ValidateTests(unittest.TestCase):
    def test_schedule_and_clock_fields(self):
        e.validate(records(), ITEMS)
        def broken(index, **change):
            recs = records()
            recs[index] = dict(recs[index], **change)
            return recs
        first_s2 = next(i['index'] for i in ITEMS if i['group'] == 'S2')
        cases = {'record_schedule_invalid': [broken(first_s2, sent_ms=ITEMS[first_s2]['scheduled_ms'] - 1),
                                             broken(first_s2, sent_ms=ITEMS[first_s2]['scheduled_ms'] + 5001,
                                                    received_ms=ITEMS[first_s2]['scheduled_ms'] + 5002),
                                             broken(0, received_ms=ITEMS[1]['scheduled_ms'] + 1)],
                 'record_clock_invalid': [broken(3, sent_mono_ns=1), broken(3, sent_ms=-1),
                                          broken(3, received_ms=records()[3]['sent_ms'] - 1)],
                 'record_plan_mismatch': [broken(3, scheduled_ms=0), broken(3, group='S1x')],
                 'record_not_successful': [broken(3, truncated_from=9)],
                 'record_length_invalid': [broken(3, declared_length='1')]}
        for code, items in cases.items():
            for recs in items:
                with self.subTest(code=code), self.assertRaises(e.Refusal) as caught:
                    e.validate(recs, ITEMS)
                self.assertEqual(str(caught.exception), code)


class MembersTests(unittest.TestCase):
    def header(self, index, **kw):
        base = {k: None for k in e.HEADER_KEYS if k not in ('body_bytes', 'body_sha256', 'truncated_from')}
        return dict(base, index=index, group='g', **kw)

    def test_progressive_prefix_truncation_and_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'm.gz'
            members = e.Members(path, cap=3000)
            members.add(self.header(0), b'{"small":1}')
            prefix = members.pending.read_bytes()  # persisted before any later request or finish
            self.assertEqual(e.parse_members(prefix)[0]['body'], b'{"small":1}')
            self.assertTrue(members.admits())
            noise = random.Random(5).randbytes(5000)
            members.add(self.header(1), noise)
            self.assertTrue(members.truncated)
            self.assertFalse(members.admits())
            packed = members.finish()
            self.assertFalse(members.pending.exists())
            self.assertLessEqual(len(packed), 3000)
            parsed = e.parse_members(packed)
            self.assertEqual(parsed[1]['truncated_from'], len(noise))
            self.assertEqual(parsed[1]['body'], noise[:len(parsed[1]['body'])])
            self.assertGreater(len(parsed[1]['body']), 3000 - 1000)  # stored prefix uses the room
            for bad in (packed + b'x', packed[:-3], b'junk'):
                with self.subTest(n=len(bad)), self.assertRaises(e.Refusal):
                    e.parse_members(bad)
            tight = e.Members(Path(tmp) / 't.gz', cap=e.EMPTY_BOUND - 1)
            self.assertFalse(tight.admits())
            tight.stream.close()

    def test_empty_bound_covers_a_real_failure_record(self):
        header = self.header(29, kind='settled', coin=None, request=ITEMS[-2]['payload'].decode(),
                             sent_utc=b.utc(), received_utc=b.utc(), sent_ms=2 ** 62, received_ms=2 ** 62,
                             sent_mono_ns=2 ** 62, received_mono_ns=2 ** 62, http_status=None,
                             code='declared_length_invalid_or_over_cap', declared_length='9' * 24, over_cap=True,
                             scheduled_ms=e.at_ms('06:10:00'))
        header['group'] = 'settled_0610'
        self.assertLessEqual(len(e.stored_member(e.framed(header, b'', b.META_CAP))), e.EMPTY_BOUND)


class Response:
    def __init__(self, body):
        self.stream, self.status = io.BytesIO(body), 200
        self.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        return self.stream.read(size)


class Connection:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, host, timeout, context):
        return self

    def request(self, method, target, body, headers):
        pass

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        pass


class RunTests(unittest.TestCase):
    def supervise(self, start=dt.datetime(2026, 10, 3, 5, 30, tzinfo=e.UTC)):
        clock = {'now': start}
        def sleep(seconds):
            clock['now'] += dt.timedelta(seconds=seconds)
        class Process:
            def __init__(self, out):
                self.out, self.exitcode = out, None
            def start(self):
                e.worker('a' * 64, self.out)
                self.exitcode = 0
            def join(self, _):
                pass
            def is_alive(self):
                return False
        responses = [Response(body) for body in bodies()]
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, 'verify', return_value=(None, COHORT)), \
                patch.object(e, 'now_utc', side_effect=lambda: clock['now']), patch.object(e, 'sleep', side_effect=sleep), \
                patch.object(b, 'now_ms', side_effect=lambda: int(clock['now'].timestamp() * 1000)), \
                patch.object(b, 'SPACING_SECONDS', 0), patch('http.client.HTTPSConnection', Connection(responses)):
            out = Path(tmp)
            record = e.supervise(Process(out), float('inf'), out, 'a' * 64)
            terminal = json.loads((out / 'terminal.json').read_bytes())
            files = {p.name for p in out.iterdir()}
        return record, terminal, files

    def test_full_offline_schedule_is_reproduced(self):
        record, terminal, files = self.supervise()
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((record['conclusion_status'], terminal['requests_attempted'], terminal['connections_opened'],
                          terminal['records_retained']), ('no_violation', 30, 7, 30))
        self.assertLessEqual(terminal['bundle_bytes'], e.BUNDLE_CAP)
        self.assertIn('projection.json', files)
        self.assertNotIn('responses.members.gz.pending', files)

    def test_cap_stops_are_failures_with_retained_prefix(self):
        for cap, code in ((14000, 'bundle_cap_truncated'), (20000, 'bundle_cap_or_deadline_before_request')):
            with self.subTest(cap=cap), patch.object(e, 'BUNDLE_CAP', cap):
                record, terminal, files = self.supervise()
                self.assertEqual(terminal['code'], code)  # truncation, or fail-closed admission before sending
                self.assertLessEqual(terminal['bundle_bytes'], cap)
                self.assertLess(terminal['records_retained'], 30)
                self.assertNotIn('projection.json', files)
                self.assertFalse(record['conclusion_eligible'])

    def test_missed_schedule_and_launch_window(self):
        record, terminal, files = self.supervise(start=dt.datetime(2026, 10, 3, 5, 45, tzinfo=e.UTC))
        self.assertEqual((terminal['code'], terminal['requests_attempted']), ('schedule_missed', 0))
        self.assertNotIn('projection.json', files)
        self.assertFalse(record['conclusion_eligible'])
        with patch.object(e, 'now_utc', return_value=dt.datetime(2026, 10, 3, 5, 39, tzinfo=e.UTC)):
            with self.assertRaises(e.Refusal) as caught:
                e.run('a' * 64)
        self.assertEqual(str(caught.exception), 'outside_launch_window')


class VerifyTests(unittest.TestCase):
    def test_verify_accepts_only_exact_frozen_plan(self):
        draft = json.loads((b.ROOT / 'reports/hip4-research-continuation/expiry-v1-draft-plan.json').read_text())
        pins = [{'path': p, 'bytes': len((b.ROOT / p).read_bytes()),
                 'sha256': b.digest((b.ROOT / p).read_bytes())} for p in e.PINNED]
        frozen = dict(draft, status='frozen_expiry_schedule', source_pins=pins)
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'
            def check(value, expected=None):
                data = b.encoded(value)
                plan.write_bytes(data)
                with patch.object(e, 'PLAN', plan):
                    if expected is None:
                        return e.verify(b.digest(data))
                    with self.assertRaises(e.Refusal) as caught:
                        e.verify(b.digest(data))
                    self.assertEqual(str(caught.exception), expected)
            self.assertEqual(len(check(frozen)[1]), 18)
            check(draft, 'plan_not_frozen')
            check(dict(frozen, request_plan=dict(frozen['request_plan'], retry=True)), 'request_plan_changed')
            check(dict(frozen, analysis_plan=dict(frozen['analysis_plan'], p6='verified')), 'analysis_plan_changed')
            check(dict(frozen, source_pins=pins[:4]), 'missing_source_pins')
            check(dict(frozen, source_pins=[dict(pins[0], sha256='0' * 64)] + pins[1:]), 'source_pin_mismatch')


if __name__ == '__main__':
    unittest.main()
