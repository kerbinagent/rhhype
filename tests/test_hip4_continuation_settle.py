"""Offline synthetics for the HIP-4 recurring settlement window. No network access."""
import asyncio
import contextlib
import datetime as dt
from decimal import Decimal
import enum
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import hip4_continuation_settle as st

b, lv = st.b, st.lv
DRAFT = json.loads((b.ROOT / 'reports/hip4-research-continuation/settle-v1-draft-plan.json').read_text())
EXPIRY, ITEMS = st.instruments(DRAFT)
WIN = st.window(EXPIRY)
EXP_MS = int(EXPIRY.timestamp() * 1000)
RAW_META = gzip.decompress((b.ROOT / DRAFT['snapshot']['path']).read_bytes())
SPECS = {i['outcome']: i['spec'] for i in ITEMS}
FRACTIONS = {7544: '1.0', 7545: '0.0', 7546: '1.0', 7549: '0.0', 7550: '0.0', 7551: '0.0', 7552: '1.0', 7553: '0.0'}
IDS = [i['outcome'] for i in ITEMS]


def settled_body(oid, fraction=None):
    return json.dumps({'spec': SPECS[oid], 'settleFraction': fraction or FRACTIONS[oid], 'details': 'price:86000'}).encode()


def book_body(oid, bid=None, ask=None):
    side = lambda px: [{'px': px, 'sz': '9', 'n': 1}] if px else []  # noqa: E731
    return json.dumps({'coin': f'#{10 * oid}', 'time': EXP_MS + 30000, 'levels': [side(bid), side(ask)]}).encode()


def bbo(oid, t, bid, ask):
    lvl = lambda px: {'px': px, 'sz': '9', 'n': 1} if px else None  # noqa: E731
    return {'channel': 'bbo', 'data': {'coin': f'#{10 * oid}', 'time': t, 'bbo': [lvl(bid), lvl(ask)]}}


def acks():
    return [{'channel': 'subscriptionResponse', 'data': {'method': 'subscribe', 'subscription': json.loads(p)['subscription']}}
            for p in st.payloads(ITEMS)[1]]


def settled_event(*ids):
    return {'channel': 'outcomeMetaUpdates', 'data': [{'outcomeSettled': i} for i in ids]}


class ResolveTests(unittest.TestCase):
    def test_dry_main_and_instrument_resolution(self):
        out = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                patch.dict(sys.modules, {'aiohttp': None}), contextlib.redirect_stdout(out):
            self.assertEqual(st.main([]), 0)
        dry = json.loads(out.getvalue())
        self.assertEqual((dry['network_calls'], dry['instruments'], dry['max_rest_weight']), (0, IDS, 372))
        self.assertEqual((WIN['open'].isoformat(), WIN['close'].isoformat()),
                         ('2026-10-03T05:58:00+00:00', '2026-10-03T06:08:00+00:00'))
        raw = {o['outcome']: o for o in json.loads(RAW_META)['outcomes']}
        self.assertTrue(all(b.encoded(SPECS[o]) == b.encoded(raw[o]) for o in IDS))
        bad = {'wrong_expiry': dict(DRAFT, expiry_utc='2026-10-04T06:00:00+00:00'),
               'question_member_as_binary': dict(DRAFT, instruments=[{'outcome': 1473, 'kind': 'binary'}]),
               'standalone_as_bucket': dict(DRAFT, instruments=[{'outcome': 7544, 'kind': 'bucket', 'question': 371}]),
               'unsorted': dict(DRAFT, instruments=DRAFT['instruments'][::-1]),
               'snapshot_sha': dict(DRAFT, snapshot=dict(DRAFT['snapshot'], gz_sha256='0' * 64))}
        codes = {'wrong_expiry': 'instrument_not_this_expiry', 'question_member_as_binary': 'instrument_spec_invalid',
                 'standalone_as_bucket': 'instrument_not_this_expiry', 'unsorted': 'instrument_list_invalid',
                 'snapshot_sha': 'snapshot_sha_mismatch'}
        for name, plan in bad.items():
            with self.subTest(name), self.assertRaises(st.Refusal) as caught:
                st.instruments(plan)
            self.assertEqual(str(caught.exception), codes[name])


class ClassifyTests(unittest.TestCase):
    def rec(self, body, code=None, status=200):
        return {'code': code, 'http_status': status, 'body': body}

    def test_post_record_classes(self):
        cases = [(book_body(7544, None, '0.99'), '1.0', 'winner_gap_displayed'),
                 (book_body(7544, '0.98', None), '1.0', 'no_winner_gap_display'),   # bid on the winner is harmless
                 (book_body(7545, '0.02', None), '0.0', 'winner_gap_displayed'),
                 (book_body(7545, None, '0.03'), '0.0', 'no_winner_gap_display'),   # ask on the loser is harmless
                 (book_body(7544), '1.0', 'no_winner_gap_display'), (b'null', '1.0', 'no_book_after_record'),
                 (b'{"error":1}', '1.0', 'unavailable')]
        for body, fraction, expected in cases:
            oid = 7545 if b'75450' in body else 7544
            with self.subTest(expected=expected, body=body[:40]):
                self.assertEqual(st.post_record(self.rec(body), Decimal(fraction), f'#{10 * oid}')[0], expected)
        self.assertEqual(st.post_record(self.rec(b'', code='transport_failure'), Decimal(1), '#75440')[0], 'unavailable')
        self.assertEqual(st.post_record(None, Decimal(1), '#75440')[0], 'not_attempted')
        status, detail = st.post_record(self.rec(book_body(7544, None, '0.99')), Decimal(1), '#75440')
        self.assertEqual((detail['displayed_gap_per_unit'], detail['units'], detail['route']), (Decimal('0.01'), Decimal(9), 'winner_yes_ask_below_1'))

    def test_ex_post_runs_after_expiry_only(self):
        level = lambda px: (Decimal(px), Decimal(9), 1)  # noqa: E731
        events = [(EXP_MS - 5000, 1, '#75440', None, level('0.90')),            # carried into the expiry
                  (EXP_MS + 800, 2, '#75440', None, level('1')),                 # 800 ms run: below the gate
                  (EXP_MS + 3000, 3, '#75440', None, level('0.95')),
                  (EXP_MS + 9000, 4, '#75440', None, None)]
        runs = st.ex_post_runs(events, Decimal(1), EXP_MS, EXP_MS + 20000)
        self.assertEqual([(r['start_ms'] - EXP_MS, r['duration_ms'], r['max_cash']) for r in runs],
                         [(3000, 6000, Decimal('0.05'))])
        self.assertEqual(st.ex_post_runs(events, Decimal(0), EXP_MS, EXP_MS + 20000), [])


class MsgType(enum.Enum):
    TEXT, BINARY, CLOSE, CLOSING, CLOSED, ERROR = range(1, 7)


class Msg:
    def __init__(self, kind, data, extra=None):
        self.type, self.data, self.extra = kind, data, extra


class FakeAiohttp:
    def __init__(self, script, clock, settled=None, books=None):
        self.script, self.clock, self.sent, self.posts = list(script), clock, [], []
        self.settled, self.books, self.WSMsgType = settled or {}, books or {}, MsgType

    def ClientSession(self, trust_env, auto_decompress):  # noqa: N802
        assert trust_env is False and auto_decompress is False
        fake = self
        class Content:
            def __init__(self, body):
                self.stream = io.BytesIO(body)
            async def read(self, n):
                return self.stream.read(n)
        class Response:
            def __init__(self, body):
                self.status, self.content = 200, Content(body)
                self.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
        class Socket:
            async def send_str(self, text):
                fake.sent.append(text)
            async def receive(self, timeout=None):
                await asyncio.sleep(0)
                if fake.script:
                    fake.clock['now'] += dt.timedelta(seconds=1)
                    return Msg(MsgType.TEXT, json.dumps(fake.script.pop(0)))
                fake.clock['now'] = WIN['close']
                raise asyncio.TimeoutError
            async def close(self):
                pass
        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def ws_connect(self, url, **kw):
                return Socket()
            def post(self, url, data, headers, allow_redirects):
                assert url == st.URL and allow_redirects is False and headers['Accept-Encoding'] == 'identity'
                body = json.loads(data)
                fake.posts.append(body)
                if body['type'] == 'settledOutcome':
                    queue = fake.settled.get(body['outcome'], [settled_body(body['outcome'])])
                    return Response(queue.pop(0) if len(queue) > 1 else queue[0])
                books = fake.books.get(body['coin'], b'null')
                if isinstance(books, list):
                    books = books.pop(0) if len(books) > 1 else books[0]
                return Response(books)
        return Session()


class Connection:
    def __init__(self, bodies):
        self.bodies = list(bodies)

    def __call__(self, host, timeout, context):
        return self

    def request(self, method, target, body, headers):
        pass

    def close(self):
        pass

    def getresponse(self):
        body = self.bodies.pop(0)
        class Response:
            status = 200
            def __init__(self):
                self.stream = io.BytesIO(body)
                self.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
            def getheader(self, name, default=None):
                return self.headers.get(name, default)
            def read1(self, size):
                return self.stream.read(size)
        return Response()


class RunTests(unittest.TestCase):
    def run_worker(self, frames, settled=None, books=None):
        clock = {'now': WIN['meta_pre_at'] - dt.timedelta(minutes=3)}
        fake = FakeAiohttp(frames, clock, settled, books)
        class Process:
            def __init__(self, out):
                self.out, self.exitcode = out, None
            def start(self):
                st.worker('a' * 64, self.out)
                self.exitcode = 0
            def join(self, _):
                pass
            def is_alive(self):
                return False
        def sleep(seconds):
            clock['now'] += dt.timedelta(seconds=max(0, seconds))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(st, 'verify', return_value=(DRAFT, EXPIRY, ITEMS)), \
                patch.object(st, 'now_utc', side_effect=lambda: clock['now']), patch.object(st, 'sleep', sleep), \
                patch.object(st, 'REST_SPACING_S', 0), patch.dict(sys.modules, {'aiohttp': fake}), \
                patch('http.client.HTTPSConnection', Connection([RAW_META])):
            out = Path(tmp)
            record = st.supervise(Process(out), float('inf'), out, 'a' * 64)
            terminal = json.loads((out / 'terminal.json').read_bytes())
            projection = json.loads((out / 'projection.json').read_bytes())
        return record, terminal, projection, fake

    def test_event_driven_follow_ups_park_when_books_vanish(self):
        frames = acks() + [bbo(7544, EXP_MS - 1000, '0.70', '0.72'), bbo(7544, EXP_MS + 4000, '0.97', '0.98'),
                           settled_event(*IDS[:4]), settled_event(*IDS[4:]), {'channel': 'pong'}]
        record, terminal, projection, fake = self.run_worker(frames)
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((terminal['stop'], projection['status'], terminal['rest_attempted']),
                         ('window_closed', 'park_no_post_record_winner_gap_display', 1 + 2 * len(IDS)))
        btc = projection['instruments']['7544']
        self.assertEqual((btc['post_record'], btc['record']['path'], btc['post_expiry_bbo_changes']),
                         ('no_book_after_record', 'follow_up', 1))
        self.assertEqual(btc['pre_record_gap'], 'unavailable_no_timestamped_mark_pair')
        self.assertEqual(btc['ex_post_runs'][0]['route'], 'winner_yes_ask_below_1')   # reported, never decisive
        kinds = [p['type'] for p in fake.posts]
        self.assertEqual(kinds, ['settledOutcome', 'l2Book'] * len(IDS))

    def test_question_settled_triggers_its_members(self):
        frames = acks() + [settled_event(*IDS[:4]), {'channel': 'outcomeMetaUpdates', 'data': {'questionSettled': 371}}]
        record, terminal, projection, _ = self.run_worker(frames)
        self.assertEqual(projection['status'], 'park_no_post_record_winner_gap_display')
        self.assertEqual({v['record']['path'] for v in projection['instruments'].values()}, {'follow_up'})

    def test_post_record_quote_is_candidate(self):
        frames = acks() + [settled_event(*IDS)]
        record, terminal, projection, _ = self.run_worker(frames, books={'#75440': book_body(7544, None, '0.99')})
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((projection['status'], projection['displayed_gap_instruments']),
                         ('candidate_post_record_display_conditional', ['7544']))

    def test_silence_and_lagging_records_are_inconclusive(self):
        record, terminal, projection, fake = self.run_worker(acks())  # no events: sweep only
        self.assertEqual(projection['status'], 'inconclusive')
        self.assertIn('post_record_check_incomplete_late_or_sweep', projection['reasons'])
        self.assertEqual(projection['instruments']['7544']['record']['path'], 'sweep')
        lag = {7544: [b'null', settled_body(7544)]}  # follow-up sees null; the sweep's second pair binds
        books = {'#75440': book_body(7544, None, '0.99')}
        record, terminal, projection, fake = self.run_worker(acks() + [settled_event(*IDS)], settled=lag, books=books)
        btc = projection['instruments']['7544']
        self.assertEqual([r['shape'] for r in btc['settled_reads']], ['null', 'object'])
        self.assertEqual((btc['record']['path'], btc['post_record']), ('sweep', 'winner_gap_displayed'))
        self.assertEqual([p['type'] for p in fake.posts if p.get('outcome') == 7544 or p.get('coin') == '#75440'],
                         ['settledOutcome', 'l2Book', 'settledOutcome', 'l2Book'])

    def test_book_before_record_is_never_used(self):
        lag = {7544: [b'null', settled_body(7544)]}  # the first book precedes any bound record
        books = {'#75440': [book_body(7544, None, '0.99'), b'null']}
        record, terminal, projection, _ = self.run_worker(acks() + [settled_event(*IDS)], settled=lag, books=books)
        btc = projection['instruments']['7544']
        self.assertEqual((btc['post_record'], btc['record']['path']), ('no_book_after_record', 'sweep'))
        self.assertGreater(btc['book_delay_ns'], 0)
        self.assertNotEqual(projection['status'], 'candidate_post_record_display_conditional')


class ValidateTests(unittest.TestCase):
    def base(self):
        out, clock = [], [0]
        def add(kind, label, body=b'{}', **kw):
            clock[0] += 1000
            header = {k: None for k in lv.HEADER_KEYS}
            header.update(kw, index=len(out), kind=kind, label=label, body_bytes=len(body), wall_ms=clock[0], mono_ns=clock[0])
            if kind == 'rest':
                header.update(sent_ms=clock[0] - 1, sent_mono_ns=clock[0] - 1, http_status=200)
            out.append(dict(header, body=body))
        return out, add

    def test_orders(self):
        recs, add = self.base()
        add('rest', 'meta_pre', RAW_META)
        add('event', 'ws_open')
        for p in st.payloads(ITEMS)[1]:
            add('out', 'subscribe', p)
        add('rest', 'settled:7544', settled_body(7544))
        add('rest', 'book:7544', b'null')
        add('event', 'stop', b.encoded({'reason': 'window_closed'}))
        add('rest', 'settled:7545', settled_body(7545))
        add('rest', 'book:7545', b'null')
        self.assertEqual(st.validate_records(recs, ITEMS), 'window_closed')
        broken = {'book_first': recs[:12] + [recs[13], recs[12]],
                  'unplanned_label': recs[:12] + [dict(recs[12], label='settled:1473')],
                  'ws_after_stop': recs + [dict(recs[11], kind='in', label='text')]}
        for name, items in broken.items():
            items = [dict(r, index=i) for i, r in enumerate(items)]
            with self.subTest(name), self.assertRaises(st.Refusal):
                st.validate_records(items, ITEMS)
        recs, add = self.base()
        add('rest', 'meta_pre', RAW_META)
        add('event', 'ws_open_failed')
        add('event', 'stop', b.encoded({'reason': 'ws_connect_failed'}))
        add('rest', 'settled:7544', settled_body(7544))
        add('rest', 'book:7544', b'null')
        self.assertEqual(st.validate_records(recs, ITEMS), 'ws_connect_failed')


class ReserveTests(unittest.TestCase):
    def test_reserve_covers_pending_frame_all_pairs_and_stop(self):
        import random
        noise = random.Random(3)
        with tempfile.TemporaryDirectory() as tmp:
            cap = st.Capture(Path(tmp) / 'c.gz', cap=st.BUNDLE_CAP)
            while not cap.reserve_reached():
                cap.add('in', 'text', noise.randbytes(lv.FLUSH_BYTES - 1), wall_ms=1, mono_ns=1)
            cap.add('in', 'text', noise.randbytes(lv.MAX_FRAME), wall_ms=1, mono_ns=1)
            cap.add('event', 'stop', b.encoded({'reason': 'cap_reserve_reached'}), wall_ms=1, mono_ns=1)
            for _ in range(2 * len(ITEMS)):  # every queued and sweep pair at its body cap
                for kind in ('settled', 'book'):
                    cap.add('rest', f'{kind}:7544', noise.randbytes(st.REST_BODY_CAP), wall_ms=1, mono_ns=1,
                            sent_ms=1, sent_mono_ns=1, http_status=200, code='x' * 40, declared_length='9' * 24,
                            over_cap=True)
            self.assertLessEqual(len(cap.finish()), st.BUNDLE_CAP)


class VerifyTests(unittest.TestCase):
    def test_verify_accepts_only_exact_frozen_plan(self):
        pins = [{'path': p, 'bytes': len((b.ROOT / p).read_bytes()),
                 'sha256': b.digest((b.ROOT / p).read_bytes())} for p in st.PINNED]
        frozen = dict(DRAFT, status='frozen_settle_window', source_pins=pins)
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'
            def check(value, expected=None):
                data = b.encoded(value)
                plan.write_bytes(data)
                with patch.object(st, 'PLAN', plan):
                    if expected is None:
                        return st.verify(b.digest(data))
                    with self.assertRaises(st.Refusal) as caught:
                        st.verify(b.digest(data))
                    self.assertEqual(str(caught.exception), expected)
            self.assertEqual([i['outcome'] for i in check(frozen)[2]], IDS)
            check(DRAFT, 'plan_not_frozen')
            check(dict(frozen, analysis_plan=dict(frozen['analysis_plan'], pre_record_gap='known')), 'analysis_plan_changed')
            check(dict(frozen, source_pins=pins[:3]), 'missing_source_pins')
            check(dict(frozen, source_pins=[dict(pins[0], sha256='0' * 64)] + pins[1:]), 'source_pin_mismatch')


if __name__ == '__main__':
    unittest.main()
