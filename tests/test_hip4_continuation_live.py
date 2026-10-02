"""Offline synthetics for the HIP-4 live touch-stream window. No network access."""
import asyncio
import contextlib
import datetime as dt
from decimal import Decimal
import enum
import gzip
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import hip4_continuation_live as e

b = e.b
FROZEN = b.pm.strict_json((b.ROOT / b.FROZEN_META).read_bytes())
COHORT = b.frozen_cohort(FROZEN)
RAW_META = gzip.decompress((b.ROOT / 'reports/hip4-outcome-v1/metadata-v1/response.json.gz').read_bytes())
Q = 359
LAY = e.layout(COHORT, Q)
WIN = e.window(Q)
OPEN, HINT, CLOSE = e.ms(WIN['open']), e.ms(WIN['hint']), e.ms(WIN['close'])
F, A, D, B2 = LAY['fallback_coin'], *[f'#{10 * m}' for m in LAY['named']]
D_ = Decimal


def lv(px, sz='10', n=1):
    return None if px is None else {'px': px, 'sz': sz, 'n': n}


def bbo(coin, t, bid, ask, sz='10'):
    return {'channel': 'bbo', 'data': {'coin': coin, 'time': t, 'bbo': [lv(bid, sz), lv(ask, sz)]}}


def book(t, bid, ask, sz='10'):
    side = lambda px: [lv(px, sz)] if px else []  # noqa: E731
    return {'channel': 'l2Book', 'data': {'coin': LAY['probe'], 'time': t, 'levels': [side(bid), side(ask)]}}


def ack(sub, **extra):
    return {'channel': 'subscriptionResponse', 'data': {'method': 'subscribe', 'subscription': dict(sub, **extra)}}


def quiet_stream(extra=(), probes=120, end=CLOSE):
    """Acks, initial touches summing below one, a probe every 60 s and a final probe at close."""
    frames = [ack(s, **({'nSigFigs': None, 'mantissa': None, 'fast': False} if s['type'] == 'l2Book' else {}))
              for s in LAY['subs']]
    frames += [bbo(F, OPEN - 5000, None, None), bbo(A, OPEN - 5000, '0.30', '0.31'),
               bbo(D, OPEN - 5000, '0.25', '0.26'), bbo(B2, OPEN - 5000, '0.44', '0.45')]
    frames += list(extra)
    frames += [book(OPEN + 60000 * k, '0.30', '0.31') for k in range(probes)]
    frames += [book(end, '0.30', '0.31'), {'channel': 'pong'}]
    return frames


def records_from(frames, stop='window_closed', meta_post=RAW_META, meta_pre=RAW_META, subs=None):
    out, clock = [], [1000]
    def add(kind, label, body, **kw):
        clock[0] += 1000
        header = {k: None for k in e.HEADER_KEYS}
        header.update(kw, index=len(out), kind=kind, label=label, body_bytes=len(body),
                       wall_ms=clock[0], mono_ns=clock[0])
        if kind == 'rest':
            header.update(sent_ms=clock[0] - 1, sent_mono_ns=clock[0] - 1, http_status=200, over_cap=False)
        out.append(dict(header, body=body))
    add('rest', 'meta_pre', meta_pre)
    add('event', 'ws_open', b'{}')
    for p in (LAY['payloads'] if subs is None else subs):
        add('out', 'subscribe', p)
    for f in frames:
        add('in', 'text', json.dumps(f).encode())
    add('event', 'stop', e.encoded({'reason': stop}))
    add('rest', 'meta_post', meta_post)
    return out


class LayoutTests(unittest.TestCase):
    def test_targets_match_frozen_schedule_hints_and_dry_main(self):
        raw = json.loads(RAW_META)
        for q in raw['questions']:
            fields = dict(kv.split(':', 1) for kv in q['description'].split('|')) if '|' in q['description'] else {}
            if 'scheduledStart' in fields and q['question'] in b.GROUPS['match_result']:
                stamp = fields['scheduledStart']
                self.assertEqual(e.TARGETS[q['question']], f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:]}')
        self.assertEqual(sorted(e.TARGETS), b.GROUPS['match_result'])
        out = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                patch.dict(sys.modules, {'aiohttp': None}), contextlib.redirect_stdout(out):
            self.assertEqual(e.main([]), 0)
        dry = json.loads(out.getvalue())
        self.assertEqual((dry['network_calls'], dry['target_question'], len(dry['subscriptions'])), (0, 363, 6))
        self.assertEqual(LAY['probe'], '#65280')
        self.assertEqual((WIN['open'].isoformat(), WIN['close'].isoformat()),
                         ('2026-10-03T15:50:00+00:00', '2026-10-03T18:05:00+00:00'))


class RouteTests(unittest.TestCase):
    def state(self, fb=(None, None), a=('0.3', '0.31'), d=('0.3', '0.31'), c=('0.4', '0.41')):
        level = lambda px: (D_(px), D_('7'), 1) if px else None  # noqa: E731
        return {coin: (level(bid), level(ask)) for coin, (bid, ask) in ((F, fb), (A, a), (D, d), (B2, c))}

    def test_forward_basis_residual_and_exactness(self):
        cash = e.route_cash(self.state(a=('0.3333333333333333333333333333334', '0.4'),
                                       d=('0.3333333333333333333333333333333', '0.4'),
                                       c=('0.3333333333333333333333333333334', '0.4')), LAY)
        self.assertEqual(cash['forward']['cash'], D_('1E-31'))  # 28-digit default precision would round
        self.assertEqual((cash['forward']['basis'], cash['forward']['residual']), (1, [F]))
        self.assertIsNone(cash['inverse_full'])
        with_fb = e.route_cash(self.state(fb=('0.01', '0.02'), a=('0.2', '0.3'), d=('0.2', '0.3'), c=('0.2', '0.3')), LAY)
        self.assertEqual((with_fb['forward']['residual'], with_fb['inverse_full']['cash']), ([], D_('0.08')))
        self.assertEqual(with_fb['inverse_full']['basis'], D_('0.92'))
        missing = e.route_cash(self.state(a=(None, '0.5')), LAY)
        self.assertEqual(missing['forward']['residual'], sorted([F, A]))
        self.assertIsNone(e.route_cash({F: (None, None), A: (None, None)}, LAY))


class TimelineTests(unittest.TestCase):
    def run_frames(self, events, end=OPEN + 10000):
        s = e.scan(records_from(events), LAY)
        return e.excursions(e.timeline(s['bbo'], LAY), LAY, OPEN, end)

    def test_equal_times_apply_together_and_duration_gate(self):
        base = [bbo(A, OPEN, '0.30', '0.31'), bbo(D, OPEN, '0.30', '0.31'), bbo(B2, OPEN, '0.39', '0.41')]
        swap = [bbo(A, OPEN + 100, '0.55', '0.56'), bbo(D, OPEN + 100, '0.05', '0.06')]  # same block; A first would read 1.24
        runs, cov = self.run_frames(base + swap)
        self.assertEqual(runs['forward'], [])
        self.assertEqual((cov['covered_ms'], cov['first_all_named_known_ms']), (10000, OPEN))
        spike = [bbo(B2, OPEN + 2000, '0.41', '0.42'), bbo(B2, OPEN + 2999, '0.39', '0.41'),
                 bbo(B2, OPEN + 5000, '0.42', '0.43')]
        runs, cov = self.run_frames(base + spike)
        self.assertEqual([(r['start_ms'] - OPEN, r['duration_ms'], r['right_censored']) for r in runs['forward']],
                         [(2000, 999, False), (5000, 5000, True)])
        self.assertEqual((runs['forward'][1]['max_cash'], runs['forward'][1]['units_at_max']), (D_('0.02'), D_('10')))
        self.assertEqual(cov['max_forward_cash'], D_('0.02'))

    def test_state_before_open_is_carried_and_unknown_named_breaks_coverage(self):
        early = [bbo(A, OPEN - 50, '0.30', '0.31'), bbo(D, OPEN - 50, '0.30', '0.31')]
        runs, cov = self.run_frames(early + [bbo(B2, OPEN + 4000, '0.39', '0.41')])
        self.assertEqual((cov['covered_ms'], cov['first_all_named_known_ms']), (6000, OPEN + 4000))


class FalsifierTests(unittest.TestCase):
    def test_single_mismatch_tolerated_two_consecutive_falsify(self):
        events = [(OPEN, 1, A, (D_('0.3'), D_('1'), 1), (D_('0.31'), D_('1'), 1))]
        top = lambda px: (D_(px), D_('1'), 1)  # noqa: E731
        ok = [(OPEN - 1, 0, top('0.3'), top('0.31')), (OPEN + 5, 2, top('0.3'), top('0.31')),
              (OPEN + 9, 3, top('0.2'), top('0.31')), (OPEN + 12, 4, top('0.3'), top('0.31'))]
        result = e.falsifier(ok, events, A)
        self.assertEqual((result['unknown'], result['match'], result['mismatch'], result['status']),
                         (1, 2, 1, 'not_falsified'))
        bad = ok[:2] + [(OPEN + 9, 3, top('0.2'), top('0.31')), (OPEN + 14, 4, top('0.2'), top('0.31'))]
        self.assertEqual(e.falsifier(bad, events, A)['status'], 'falsified')


class ScanTests(unittest.TestCase):
    def test_acks_meta_updates_and_anomalies(self):
        frames = quiet_stream(extra=[
            {'channel': 'outcomeMetaUpdates', 'data': {'outcomeCreated': {'outcome': 9999}}},
            {'channel': 'outcomeMetaUpdates', 'data': [{'outcomeSettled': 7544}, {'questionSettled': Q}]},
            {'channel': 'outcomeMetaUpdates', 'data': {'mystery': 1}},
            bbo(A, OPEN - 6000, '0.30', '0.31'),            # time regression
            bbo(D, OPEN, '0.40', '0.30'),                   # crossed
            {'channel': 'error', 'data': 'x'}])
        s = e.scan(records_from(frames), LAY)
        self.assertEqual([m['event'] for m in s['meta']], ['question_settled'])
        self.assertEqual(s['anomalies']['meta_update_unparsed'], 1)
        self.assertEqual(s['anomalies']['bbo_time_regression'], 1)
        self.assertEqual(s['anomalies']['bbo_invalid_bbo_crossed'], 1)
        self.assertEqual(s['anomalies']['channel_error'], 1)
        self.assertEqual(set(s['acks'].values()), {1})
        self.assertIn('nSigFigs', s['echoes'][4])
        bad_ack = e.scan(records_from([ack(LAY['subs'][0], extra=1)]), LAY)
        self.assertEqual(bad_ack['anomalies']['unexpected_ack'], 1)


class BundleTests(unittest.TestCase):
    def test_roundtrip_reserve_math_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = e.Capture(Path(tmp) / 'c.gz')
            noise = random.Random(7)
            while not cap.reserve_reached():  # incompressible frames up to the reserve
                cap.add('in', 'text', noise.randbytes(e.FLUSH_BYTES - 1), wall_ms=1, mono_ns=1)
            cap.add('in', 'text', noise.randbytes(e.MAX_FRAME), wall_ms=1, mono_ns=1)  # worst frame
            cap.add('event', 'stop', e.encoded({'reason': 'cap_reserve_reached'}), wall_ms=1, mono_ns=1)
            cap.add('rest', 'meta_post', noise.randbytes(b.META_CAP), wall_ms=1, mono_ns=1)
            packed = cap.finish()
            self.assertLessEqual(len(packed), e.BUNDLE_CAP)
            parsed = e.parse_bundle(packed)
            self.assertEqual([r['index'] for r in parsed], list(range(len(parsed))))
            self.assertEqual(parsed[-1]['body_bytes'], b.META_CAP)
            for bad in (packed + b'x', packed[:-3], b'junk'):
                with self.subTest(n=len(bad)), self.assertRaises(e.Refusal):
                    e.parse_bundle(bad)
            small = e.Capture(Path(tmp) / 'd.gz', cap=64)
            with self.assertRaises(e.Refusal):
                small.add('in', 'text', noise.randbytes(e.FLUSH_BYTES), wall_ms=1, mono_ns=1)

    def test_validate_orders(self):
        self.assertEqual(e.validate_records(records_from(quiet_stream()), LAY), 'window_closed')
        recs = records_from([])
        self.assertEqual(e.validate_records(recs, LAY), 'window_closed')
        stop = dict(recs[-2], index=1, body=e.encoded({'reason': 'meta_pre_failed'}))
        stop['body_bytes'] = len(stop['body'])
        self.assertEqual(e.validate_records([dict(recs[0], code='transport_failure'), stop], LAY), 'meta_pre_failed')
        with self.assertRaises(e.Refusal):
            e.validate_records([recs[0], stop], LAY)  # a successful pre-read cannot stop as failed
        partial = records_from([], stop='transport_failure', subs=LAY['payloads'][:2])
        self.assertEqual(e.validate_records(partial, LAY), 'transport_failure')
        for broken in (records_from([], subs=LAY['payloads'][:2]),           # missing subscriptions
                       records_from([], subs=LAY['payloads'][::-1]),          # order changed
                       records_from([])[:-1],                                 # meta_post missing
                       records_from([], stop='unheard')):
            with self.subTest(), self.assertRaises(e.Refusal):
                e.validate_records(broken, LAY)


class MsgType(enum.Enum):
    TEXT, BINARY, CLOSE, CLOSING, CLOSED, ERROR = range(1, 7)


class Msg:
    def __init__(self, kind, data, extra=None):
        self.type, self.data, self.extra = kind, data, extra


class FakeAiohttp:
    def __init__(self, script, clock, connect_fails=False, tail='timeout'):
        self.script, self.clock, self.sent, self.connect_fails, self.tail = list(script), clock, [], connect_fails, tail
        self.WSMsgType = MsgType

    def ClientSession(self, trust_env):  # noqa: N802
        assert trust_env is False
        fake = self
        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def ws_connect(self, url, **kw):
                assert url == e.WS_URL and kw['compress'] == 0 and kw['max_msg_size'] == e.MAX_FRAME
                if fake.connect_fails:
                    raise OSError('refused')
                return Socket()
        class Socket:
            async def send_str(self, text):
                fake.sent.append(text)
            async def receive(self, timeout=None):
                if fake.script:
                    fake.clock['now'] += dt.timedelta(seconds=1)
                    return Msg(MsgType.TEXT, json.dumps(fake.script.pop(0)))
                if fake.tail == 'close':
                    return Msg(MsgType.CLOSE, 1006, 'gone')
                fake.clock['now'] = WIN['close']
                raise asyncio.TimeoutError
            async def close(self):
                pass
        return Session()


class Response:
    def __init__(self, body):
        self.stream, self.status = io.BytesIO(body), 200
        self.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        return self.stream.read(size)


class Connection:
    def __init__(self, bodies):
        self.bodies = list(bodies)

    def __call__(self, host, timeout, context):
        return self

    def request(self, method, target, body, headers):
        assert body == e.META_PAYLOAD

    def getresponse(self):
        body = self.bodies.pop(0)
        if body is None:
            raise OSError('reset')
        return Response(body)

    def close(self):
        pass


class RunTests(unittest.TestCase):
    def run_worker(self, frames, connect_fails=False, tail='timeout', cap=e.BUNDLE_CAP, metas=(RAW_META, RAW_META)):
        clock = {'now': WIN['meta_pre_at'] - dt.timedelta(minutes=5)}
        fake = FakeAiohttp(frames, clock, connect_fails, tail)
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
        def sleep(seconds):
            clock['now'] += dt.timedelta(seconds=max(0, seconds))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(e, 'verify', return_value=({'target_question': Q}, COHORT)), \
                patch.object(e, 'now_utc', side_effect=lambda: clock['now']), patch.object(e, 'sleep', sleep), \
                patch.object(e, 'BUNDLE_CAP', cap), patch.dict(sys.modules, {'aiohttp': fake}), \
                patch('http.client.HTTPSConnection', Connection(metas)):
            out = Path(tmp)
            record = e.supervise(Process(out), float('inf'), out, 'a' * 64)
            terminal = json.loads((out / 'terminal.json').read_bytes())
            projection = json.loads((out / 'projection.json').read_bytes()) if (out / 'projection.json').exists() else None
        return record, terminal, projection, fake

    def test_quiet_window_parks_and_is_reproduced(self):
        record, terminal, projection, fake = self.run_worker(quiet_stream())
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((terminal['stop'], projection['status'], projection['reasons']),
                         ('window_closed', 'park_no_qualifying_excursion_in_window', []))
        self.assertEqual(fake.sent[:6], [p.decode() for p in LAY['payloads']])
        self.assertEqual(projection['routes']['forward']['max_cash'], None)
        self.assertEqual(projection['coverage']['max_forward_cash'], '-0.01')
        self.assertEqual(projection['falsifier']['status'], 'not_falsified')

    def test_forward_excursion_is_candidate(self):
        spike = [bbo(B2, HINT + 1000, '0.46', '0.47'), bbo(B2, HINT + 3500, '0.44', '0.45')]
        record, terminal, projection, _ = self.run_worker(quiet_stream(extra=spike))
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual(projection['status'], 'candidate_recorded_vector')
        run = projection['routes']['forward']['qualifying_runs'][0]
        self.assertEqual((run['max_cash'], run['basis_per_unit'], run['residual'], run['duration_ms']),
                         ('0.01', '1', [F], 2500))

    def test_censored_stops_cannot_park(self):
        record, terminal, projection, _ = self.run_worker(quiet_stream()[:20], tail='close')
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((terminal['stop'], projection['status']), ('ws_closed', 'inconclusive'))
        self.assertIn('censored_ws_closed', projection['reasons'])
        record, terminal, projection, _ = self.run_worker([], connect_fails=True)
        self.assertEqual((terminal['stop'], projection['status'], record['conclusion_eligible']),
                         ('ws_connect_failed', 'inconclusive', True))
        pad = random.Random(1)
        noisy = quiet_stream(extra=[{'channel': 'pad', 'data': pad.randbytes(15000).hex()} for _ in range(40)])
        record, terminal, projection, _ = self.run_worker(noisy, cap=e.RESERVE + 200000)
        self.assertEqual((terminal['stop'], projection['status']), ('cap_reserve_reached', 'inconclusive'))
        self.assertLessEqual(terminal['bundle_bytes'], e.RESERVE + 200000)

    def test_meta_pre_failure_and_launch_window(self):
        record, terminal, projection, _ = self.run_worker(quiet_stream(), metas=(b'not json', RAW_META))
        self.assertEqual(terminal['stop'], 'window_closed')
        self.assertIn('meta_pre_not_unchanged', projection['reasons'])
        with patch.object(e, 'verify', return_value=({'target_question': Q}, COHORT)), \
                patch.object(e, 'now_utc', return_value=WIN['launch_until'] + dt.timedelta(seconds=1)):
            with self.assertRaises(e.Refusal) as caught:
                e.run('a' * 64)
        self.assertEqual(str(caught.exception), 'outside_launch_window')
        record, terminal, projection, fake = self.run_worker(quiet_stream(), metas=(None,))
        self.assertEqual((terminal['stop'], projection['status'], fake.sent), ('meta_pre_failed', 'inconclusive', []))
        self.assertTrue(record['conclusion_eligible'], record)


class VerifyTests(unittest.TestCase):
    def test_verify_accepts_only_exact_frozen_plan(self):
        draft = json.loads((b.ROOT / 'reports/hip4-research-continuation/live-v1-draft-plan.json').read_text())
        pins = [{'path': p, 'bytes': len((b.ROOT / p).read_bytes()),
                 'sha256': b.digest((b.ROOT / p).read_bytes())} for p in e.PINNED]
        frozen = dict(draft, status='frozen_live_window', source_pins=pins)
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
            self.assertEqual(check(frozen)[0]['target_question'], 363)
            self.assertEqual(check(dict(frozen, target_question=359))[0]['target_question'], 359)
            check(draft, 'plan_not_frozen')
            check(dict(frozen, target_question=371), 'target_not_allowed')
            check(dict(frozen, request_plan=dict(frozen['request_plan'], stops=[])), 'request_plan_changed')
            check(dict(frozen, source_pins=pins[:4]), 'missing_source_pins')
            check(dict(frozen, source_pins=[dict(pins[0], sha256='0' * 64)] + pins[1:]), 'source_pin_mismatch')


if __name__ == '__main__':
    unittest.main()
