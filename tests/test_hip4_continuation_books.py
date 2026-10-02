"""Offline synthetics for the HIP-4 continuation book gate. No exchange access."""
import contextlib
from decimal import Decimal
import gzip
import http.client
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import zlib

from scripts import hip4_continuation_books as b

FROZEN = b.pm.strict_json((b.ROOT / b.FROZEN_META).read_bytes())
COHORT = b.frozen_cohort(FROZEN)
PLAN = b.requests(COHORT)
RAW_META = gzip.decompress((b.ROOT / 'reports/hip4-outcome-v1/metadata-v1/response.json.gz').read_bytes())


def level(px, sz='5', n=1):
    return {'px': px, 'sz': sz, 'n': n}


def book(coin, bid, ask, t=10_000, sz='5'):
    return {'coin': coin, 'time': t, 'levels': [[level(bid, sz)] if bid else [], [level(ask, sz)] if ask else []]}


def fair_book(item, t=10_000):
    """Bids sum below 1 and asks above 1 for every question (a certified snapshot)."""
    k = len(COHORT[item['question']]['members']) if item['question'] else 2
    bid, ask = Decimal(int(100 / k) - 2) / 100, Decimal(int(100 / k) + 3) / 100
    if item['side'] == 1:
        bid, ask = 1 - ask, 1 - bid
    return book(item['coin'], str(bid), str(ask), t)


def records(changes=None, stop=None, meta_post=None, times=None, received=None, mono_gap=None):
    out = []
    for item in PLAN:
        if stop is not None and item['index'] >= stop:
            break
        if item['kind'] == 'meta':
            body = meta_post if item['phase'] == 'post' and meta_post is not None else RAW_META
        else:
            payload = fair_book(item, t=(times or {}).get(item['outcome'], 10_000))
            payload = (changes or {}).get((item['outcome'], item['side']), payload)
            body = json.dumps(payload).encode()
        sent = item['index'] * 10_000_000 + ((mono_gap or {}).get(item.get('outcome'), 0))
        out.append({'index': item['index'], 'kind': item['kind'], 'coin': item['coin'],
                    'request': item['payload'].decode(), 'http_status': 200, 'code': None,
                    'received_ms': (received or {}).get(item.get('outcome'), 10_100),
                    'sent_mono_ns': sent, 'received_mono_ns': sent + 5_000_000, 'body': body})
    return out


class PlanTests(unittest.TestCase):
    def test_dry_main_performs_no_http(self):
        out = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                contextlib.redirect_stdout(out):
            self.assertEqual(b.main([]), 0)
        dry = json.loads(out.getvalue())
        self.assertEqual((dry['status'], dry['planned_requests'], dry['planned_weight']), ('dry_no_http', 91, 218))

    def test_cohort_order_and_binary_baseline(self):
        self.assertEqual((len(COHORT), sum(len(c['members']) for c in COHORT.values())), (18, 86))
        coins = [p['coin'] for p in PLAN]
        self.assertEqual((coins[0], coins[-1], coins[1], coins[2], coins[-2]), (None, None, '#14720', '#14721', '#75440'))
        self.assertEqual(coins[coins.index('#75510') + 1], '#75511')
        raw = json.loads(RAW_META)
        spec = next(o for o in raw['outcomes'] if o['outcome'] == 7544)
        self.assertEqual(b.encoded(spec), b.encoded(b.BINARY_SPEC))

    def test_frozen_cohort_refuses_changed_projection(self):
        changed = json.loads(json.dumps(FROZEN))
        changed['questions'] = changed['questions'][:-1]
        with self.assertRaises(b.Refusal):
            b.frozen_cohort(changed)


class BookTests(unittest.TestCase):
    def test_parse_valid_book_and_units(self):
        parsed = b.parse_book({'coin': '#10', 'time': 5, 'levels': [
            [level('0.45', '10'), level('0.44', '2.5')], [level('0.47', '3')]]}, '#10')
        self.assertEqual((parsed['bid'], parsed['ask']), ((Decimal('0.45'), Decimal('10')), (Decimal('0.47'), Decimal('3'))))
        self.assertEqual((parsed['digits'], parsed['fractional_size']), ({'px': 2, 'sz': 1}, True))

    def test_parse_rejects_bad_books(self):
        good = {'coin': '#10', 'time': 5, 'levels': [[level('0.45')], [level('0.47')]]}
        bad = [dict(good, coin='#11'), dict(good, time=-1), dict(good, levels=[[]]),
               dict(good, levels=[[level('0.48')], [level('0.47')]]),
               dict(good, levels=[[level('0.40'), level('0.45')], []]),
               dict(good, levels=[[level('1.2')], []]), dict(good, levels=[[level('0.4', '0')], []]),
               dict(good, levels=[[level('4e-1')], []]), dict(good, levels=[[level('0.4', n=0)], []]),
               dict(good, levels=[[level('0.' + '1' * 31)], []]),
               dict(good, levels=[[level(f'0.{99 - i:02d}') for i in range(21)], []])]
        for obj in bad:
            with self.subTest(obj=obj), self.assertRaises(ValueError):
                b.parse_book(obj, '#10')


def brute(lo, hi, fallback_zero):
    """Exhaustive tenths grid; agnostic states L,M1,M2,H,F0,F1 with B=M2+H+F1."""
    for l in range(lo['L'], min(hi['L'], 10) + 1):
        for hh in range(lo['H'], min(hi['H'], 10 - l) + 1):
            for m1 in range(10 - l - hh + 1):
                for m2 in range(10 - l - hh - m1 + 1):
                    if not lo['M'] <= m1 + m2 <= hi['M']:
                        continue
                    for f0 in range(10 - l - hh - m1 - m2 + 1):
                        f1 = 10 - l - hh - m1 - m2 - f0
                        if fallback_zero and (f0 or f1):
                            continue
                        if lo['F'] <= f0 + f1 <= hi['F'] and lo['B'] <= m2 + hh + f1 <= hi['B']:
                            return True
    return False


def tops(spec):
    return {k: {'bid': (Decimal(bd), 1) if bd is not None else None,
                'ask': (Decimal(ak), 1) if ak is not None else None} for k, (bd, ak) in spec.items()}


class DominanceTests(unittest.TestCase):
    def test_closed_forms_match_exhaustive_search(self):
        rng = random.Random(11)
        seen = {True: 0, False: 0}
        for _ in range(400):
            spec, lo, hi = {}, {}, {}
            for key in 'LMHFB':
                bid = rng.randint(0, 9) if rng.random() < 0.75 else None
                ask = rng.randint(bid if bid is not None else 1, 10) if rng.random() < 0.75 else None
                spec[key] = (None if bid is None else str(Decimal(bid) / 10), None if ask is None else str(Decimal(ask) / 10))
                lo[key], hi[key] = bid or 0, 10 if ask is None else ask
            for fz in (False, True):
                got = b.dominance(tops(spec), fallback_zero=fz)['feasible']
                self.assertEqual(got, brute(lo, hi, fz), (spec, fz))
                seen[got] += 1
        self.assertGreater(min(seen.values()), 100)

    def test_exact_arithmetic_and_fallback_premise(self):
        tiny = '0.20000000000000000000000000001'
        near = tops({'L': ('0.25', '0.4'), 'F': ('0.25', '0.4'), 'M': (tiny, '0.4'), 'H': ('0.3', '0.4'), 'B': (None, None)})
        self.assertFalse(b.dominance(near)['feasible'])
        conflict = b.dominance(tops({'L': ('0.2', '0.3'), 'M': ('0.3', '0.4'), 'H': ('0.2', '0.3'),
                                     'F': ('0.1', '0.2'), 'B': ('0.3', '0.5')}), fallback_zero=True)
        self.assertEqual((conflict['feasible'], conflict['premise_conflict_fallback_bid']), (False, True))
        rel = b.dominance(tops({'L': ('0.3', '0.32'), 'M': ('0.33', '0.35'), 'H': ('0.3', '0.32'),
                                'F': (None, '0.01'), 'B': ('0.27', '0.28')}))
        self.assertEqual((rel['feasible'], rel['relations']['B_ask_lt_H_bid']), (False, True))

    def test_certify_is_exact_where_default_context_rounds(self):
        near = {1: {'yes_bid': ('0.50000000000000000000000000001', '1'), 'yes_ask': ('0.6', '1')},
                2: {'yes_bid': ('0.5', '1'), 'yes_ask': ('0.6', '1')}}
        self.assertEqual(b.h.certificate(near)['status'], 'certified_no_static_cycle')  # the rounding defect
        self.assertEqual(b.certify(near)['status'], 'candidate_forward')


class AnalysisTests(unittest.TestCase):
    def test_certified_snapshot_parks(self):
        r = b.stringify(b.analyze(records(), COHORT))
        self.assertEqual((r['status'], r['usable_questions'], r['candidates']), ('park_static_conversion_at_snapshot', 18, []))
        self.assertEqual(r['mirror_probes'], {'1472': 'consistent', '7551': 'consistent'})
        self.assertEqual((r['dominance_btc']['usable'], r['dominance_btc']['binary_meta_pre']), (True, 'unchanged'))
        self.assertEqual(r['native_units_observed']['books_parsed'], 89)

    def test_question_statuses(self):
        qmembers = COHORT[357]['members']
        cheap = {(m, 0): book(f'#{10 * m}', '0.20', '0.22') for m in qmembers}
        r = b.analyze(records(changes=cheap), COHORT)
        self.assertEqual((r['status'], r['candidates'], r['questions']['357']['status']),
                         ('candidates_for_separate_review', [357], 'candidate_inverse'))
        meta = json.loads(RAW_META)
        next(q for q in meta['questions'] if q['question'] == 358)['namedOutcomes'].append(99999)
        r = b.analyze(records(meta_post=json.dumps(meta).encode()), COHORT)
        self.assertEqual((r['questions']['358']['status'], r['questions']['358']['meta_post']), ('metadata_changed', 'changed'))
        cases = {'timing_unusable': dict(times={qmembers[0]: 10_000 - b.SPREAD_MS - 1}),
                 'stale_or_future_book': dict(received={qmembers[0]: 10_000 + b.MAX_AGE_MS + 1}),
                 'local_window_exceeded': dict(mono_gap={qmembers[-1]: (b.LOCAL_WINDOW_MS + 1) * 1_000_000})}
        for status, kwargs in cases.items():
            with self.subTest(status=status):
                self.assertEqual(b.analyze(records(**kwargs), COHORT)['questions']['357']['status'], status)
        future = b.analyze(records(received={qmembers[0]: 10_000 - b.MAX_FUTURE_MS - 1}), COHORT)
        self.assertEqual(future['questions']['357']['status'], 'stale_or_future_book')
        mismatch = {(1472, 1): book('#14721', '0.10', '0.90')}
        r = b.analyze(records(changes=mismatch), COHORT)
        self.assertEqual((r['status'], r['mirror_probes']['1472']), ('inconclusive_merged_book_premise_falsified', 'mismatch_same_time'))
        late = {**cheap, (qmembers[0], 0): book(f'#{10 * qmembers[0]}', '0.20', '0.22', t=10_000 - b.SPREAD_MS - 1)}
        r = b.analyze(records(changes=late), COHORT)
        self.assertEqual((r['candidates'], r['gated_certificate_failures']), ([], [357]))
        self.assertEqual(r['group_totals']['match_result'], {'certified_no_static_cycle': 10, 'timing_unusable': 1})
        self.assertEqual(sum(sum(g.values()) for g in r['group_totals'].values()), 18)

    def test_mirror_compares_every_level_exactly(self):
        yes = b.parse_book({'coin': '#10', 'time': 1, 'levels': [[level('0.4', '2', 1), level('0.3', '1', 2)],
                                                                 [level('0.50000000000000000000000000001')]]}, '#10')
        no_exact = {'coin': '#11', 'time': 1, 'levels': [[level('0.49999999999999999999999999999')],
                                                         [level('0.6', '2', 1), level('0.7', '1', 2)]]}
        self.assertEqual(b.mirror(yes, b.parse_book(no_exact, '#11')), 'consistent')
        rounded = json.loads(json.dumps(no_exact))
        rounded['levels'][0][0]['px'] = '0.5'
        self.assertEqual(b.mirror(yes, b.parse_book(rounded, '#11')), 'mismatch_same_time')
        deeper = json.loads(json.dumps(no_exact))
        deeper['levels'][1][1]['sz'] = '9'
        self.assertEqual(b.mirror(yes, b.parse_book(deeper, '#11')), 'mismatch_same_time')
        later = dict(json.loads(json.dumps(deeper)), time=2)
        self.assertEqual(b.mirror(yes, b.parse_book(later, '#11')), 'mismatch_different_time')

    def test_binary_bracket_blocks_dominance(self):
        meta = json.loads(RAW_META)
        variants = {'changed': lambda m: next(o for o in m['outcomes'] if o['outcome'] == 7544).update(description='x'),
                    'missing': lambda m: m.update(outcomes=[o for o in m['outcomes'] if o['outcome'] != 7544]),
                    'duplicate': lambda m: m['outcomes'].append(dict(b.BINARY_SPEC))}
        for status, mutate in variants.items():
            with self.subTest(status=status):
                m = json.loads(json.dumps(meta))
                mutate(m)
                r = b.analyze(records(meta_post=json.dumps(m).encode()), COHORT)
                self.assertEqual(r['dominance_btc']['binary_meta_post'], status)
                self.assertIn('binary_metadata', r['dominance_btc']['blockers'])
                self.assertFalse(r['dominance_btc']['usable'])


class Response:
    def __init__(self, body, status=200, length=True, incomplete=False, will_close=False):
        self.stream, self.status, self.incomplete = io.BytesIO(body), status, incomplete
        self.will_close = will_close
        self.headers = {'Content-Type': 'application/json', 'Content-Encoding': 'identity'}
        if length:
            self.headers['Content-Length'] = str(len(body))

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        if self.incomplete:
            raise http.client.IncompleteRead(self.stream.read(), 10)
        return self.stream.read(size)


class Connection:
    def __init__(self, responses):
        self.responses, self.sent, self.opened = list(responses), [], 0

    def __call__(self, host, timeout, context):
        self.opened += 1
        return self

    def request(self, method, target, body, headers):
        self.sent.append((method, target, body))

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        pass


def receipt():
    return {'requests_attempted': 0, 'connections_opened': 0, 'stop': None}


class FetchTests(unittest.TestCase):
    def fetch(self, responses, deadline=float('inf'), spacing=0):
        fake = Connection(responses)
        bundle, got, rec = b.Bundle(), [], receipt()
        with patch('http.client.HTTPSConnection', fake), patch.object(b, 'SPACING_SECONDS', spacing):
            b.fetch_all(PLAN, bundle, got, rec, deadline=deadline)
        return fake, got, rec, bundle.finish()

    def test_stop_at_first_failure_and_bundle_framing(self):
        ok = [Response(r['body']) for r in records(stop=3)]
        fake, got, rec, packed = self.fetch(ok + [Response(b'{"err":1}', status=429), Response(b'{}')])
        self.assertEqual((fake.opened, len(fake.sent), rec['requests_attempted'], rec['connections_opened']), (1, 4, 4, 1))
        self.assertEqual((rec['stop'], got[-1]['code']), ('http_status_not_200', 'http_status_not_200'))
        parsed = b.parse_bundle(packed)
        self.assertEqual([p['body'] for p in parsed], [g['body'] for g in got])
        self.assertTrue(all(p['received_mono_ns'] >= p['sent_mono_ns'] for p in parsed))
        with self.assertRaises(b.Refusal):
            b.validate_records(parsed, PLAN)

    def test_protocol_close_retires_connection_and_counts_reopen(self):
        bodies = [r['body'] for r in records(stop=3)]
        fake, got, rec, packed = self.fetch([Response(bodies[0], will_close=True), Response(bodies[1]),
                                             Response(bodies[2]), Response(b'{}', status=500)])
        self.assertEqual((fake.opened, rec['connections_opened'], rec['requests_attempted']), (2, 2, 4))
        good = b.parse_bundle(packed)[:3]
        b.validate_records(good, PLAN[:3])  # three successful records in plan order pass
        bad_len = [dict(good[0], declared_length='1')] + good[1:]
        bad_clock = [good[0], dict(good[1], sent_mono_ns=good[0]['received_mono_ns'] - 1)] + good[2:]
        for records_, code in ((bad_len, 'record_length_invalid'), (bad_clock, 'record_clock_invalid')):
            with self.subTest(code=code), self.assertRaises(b.Refusal) as caught:
                b.validate_records(records_, PLAN[:3])
            self.assertEqual(str(caught.exception), code)

    def test_local_window_is_exact_in_nanoseconds(self):
        top = {'time': 1, 'fresh': True, 'sent_mono_ns': 0}
        at_cap = b.timing([top, dict(top, received_mono_ns=b.LOCAL_WINDOW_MS * 1_000_000)][1:] + [dict(top, received_mono_ns=0)])
        over = b.timing([dict(top, received_mono_ns=b.LOCAL_WINDOW_MS * 1_000_000 + 1), dict(top, received_mono_ns=0)])
        self.assertIsNone(b.gate(at_cap))
        self.assertEqual((b.gate(over), over['local_window_ms_ceiling']), ('local_window_exceeded', b.LOCAL_WINDOW_MS + 1))

    def test_over_cap_incomplete_read_and_deadline(self):
        _, got, rec, packed = self.fetch([Response(b'{"a":1}', length=False),
                                          Response(b'x' * (b.BOOK_CAP + 50), length=False)])
        self.assertEqual((rec['stop'], got[1]['over_cap'], len(got[1]['body'])), ('body_over_cap', True, b.BOOK_CAP))
        self.assertEqual(len(b.parse_bundle(packed)[1]['body']), b.BOOK_CAP)
        _, got, rec, _ = self.fetch([Response(b'{"partial', incomplete=True, length=False)])
        self.assertEqual((rec['stop'], got[0]['body']), ('incomplete_read', b'{"partial'))
        import time
        _, got, rec, _ = self.fetch([Response(b'{}')] * 3, deadline=time.monotonic() + 0.05, spacing=0.2)
        self.assertEqual((rec['stop'], len(got)), ('deadline_before_request', 1))

    def test_bundle_parse_refusals(self):
        _, _, _, packed = self.fetch([Response(r['body']) for r in records(stop=2)] + [Response(b'{}', status=500)])
        for bad in (packed + gzip.compress(b'x', mtime=0), packed[:-8], b'not gzip'):
            with self.subTest(size=len(bad)), self.assertRaises(b.Refusal):
                b.parse_bundle(bad)
        data = zlib.decompress(packed, 31).replace(b'"code":null', b'"code":null,"extra":1', 1)
        with self.assertRaises(b.Refusal):
            b.parse_bundle(gzip.compress(data, mtime=0))


class VerifyTests(unittest.TestCase):
    def test_verify_accepts_only_exact_frozen_plan(self):
        draft = json.loads((b.ROOT / 'reports/hip4-research-continuation/books-v1-draft-plan.json').read_text())
        pins = [{'path': p, 'bytes': len((b.ROOT / p).read_bytes()),
                 'sha256': b.digest((b.ROOT / p).read_bytes())} for p in b.PINNED]
        frozen = dict(draft, status='frozen_book_snapshot', source_pins=pins)
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'
            def check(value, expected=None):
                data = b.encoded(value)
                plan.write_bytes(data)
                with patch.object(b, 'PLAN', plan):
                    if expected is None:
                        return b.verify(b.digest(data))
                    with self.assertRaises(b.Refusal) as caught:
                        b.verify(b.digest(data))
                    self.assertEqual(str(caught.exception), expected)
            self.assertEqual(len(check(frozen)[1]), 18)
            check(draft, 'plan_not_frozen')
            check(dict(frozen, request_plan=dict(frozen['request_plan'], retry=True)), 'request_plan_changed')
            check(dict(frozen, analysis_plan=dict(frozen['analysis_plan'], min_usable_questions=1)), 'analysis_plan_changed')
            check(dict(frozen, source_pins=pins[:3]), 'missing_source_pins')
            check(dict(frozen, source_pins=[dict(pins[0], sha256='0' * 64)] + pins[1:]), 'source_pin_mismatch')
            check(dict(frozen, previous_sha256='0' * 64), 'previous_plan_sha_mismatch')


class RunTests(unittest.TestCase):
    def supervise(self, responses, exitcode=0, final_pins=True, tamper=None, start_fails=False):
        class Process:
            def __init__(self, out):
                self.out, self.exitcode = out, None

            def start(self):
                if start_fails:
                    raise OSError('fork failed')
                b.worker('a' * 64, self.out)
                self.exitcode = exitcode
                if tamper:
                    tamper(self.out)

            def join(self, _):
                pass

            def is_alive(self):
                return False

        calls = iter([(None, COHORT)] * 4 + [(None, COHORT) if final_pins else b.Refusal('source_pin_mismatch')])
        def verify(_):
            value = next(calls, (None, COHORT))
            if isinstance(value, Exception):
                raise value
            return value
        with tempfile.TemporaryDirectory() as tmp, patch.object(b, 'verify', side_effect=verify), \
                patch.object(b, 'SPACING_SECONDS', 0), patch.object(b, 'now_ms', return_value=10_100), \
                patch('http.client.HTTPSConnection', Connection(responses)):
            out = Path(tmp)
            record = b.supervise(Process(out), float('inf'), out, 'a' * 64)
            files = {p.name for p in out.iterdir()}
            terminal = json.loads((out / 'terminal.json').read_bytes()) if 'terminal.json' in files else None
        return record, files, terminal

    def ok(self):
        return [Response(r['body']) for r in records()]

    def test_full_offline_run_reproduces_projection(self):
        record, files, terminal = self.supervise(self.ok())
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((record['conclusion_status'], record['requests_attempted'], terminal['connections_opened']),
                         ('park_static_conversion_at_snapshot', 91, 1))
        self.assertIn('projection.json', files)

    def test_stop_is_failure_without_projection(self):
        responses = self.ok()
        responses[40] = Response(b'{"rate":"limited"}', status=429)
        record, files, terminal = self.supervise(responses)
        self.assertEqual((terminal['code'], terminal['stop'], terminal['requests_attempted']),
                         ('http_status_not_200', 'http_status_not_200', 41))
        self.assertNotIn('projection.json', files)
        self.assertIn('responses.bundle.gz', files)
        self.assertEqual((record['conclusion_eligible'], record['requests_attempted']), (False, 41))

    def test_gate_failures_are_inconclusive(self):
        def repack(out):
            data = zlib.decompress((out / 'responses.bundle.gz').read_bytes(), 31)
            (out / 'responses.bundle.gz').unlink()
            (out / 'responses.bundle.gz').write_bytes(gzip.compress(data + b'', mtime=1))
        def projection(out):
            value = json.loads((out / 'projection.json').read_bytes())
            value['usable_questions'] = 17
            (out / 'projection.json').unlink()
            (out / 'projection.json').write_bytes(b.encoded(value))
        cases = [('worker_completed_exit_zero', {'exitcode': 1}),
                 ('final_plan_and_source_pins', {'final_pins': False}),
                 ('bundle_matches_terminal', {'tamper': repack}),
                 ('projection_reproduced', {'tamper': projection})]
        for check, kwargs in cases:
            with self.subTest(check=check):
                record, _, _ = self.supervise(self.ok(), **kwargs)
                self.assertFalse(record['checks'][check])
                self.assertEqual((record['conclusion_eligible'], record['conclusion_status']), (False, 'inconclusive'))
        record, files, _ = self.supervise(self.ok(), start_fails=True)
        self.assertEqual((record['status'], record['requests_attempted'], record['conclusion_eligible']),
                         ('start_failed', 'unknown_0_to_91', False))
        self.assertEqual(files, {'supervisor.json'})


if __name__ == '__main__':
    unittest.main()
