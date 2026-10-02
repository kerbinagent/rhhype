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
WIN_NS = (CLOSE - OPEN) * e.MS
F, A, D, B2 = LAY['fallback_coin'], *[f'#{10 * m}' for m in LAY['named']]
D_ = Decimal
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
BASE = OPEN - 600000  # wall ms mapped to mono 0 in synthetic receipts
L2_ECHO = {'nSigFigs': None, 'mantissa': None, 'fast': False}


def lv(px, sz='10', n=1):
    return None if px is None else {'px': px, 'sz': sz, 'n': n}


def bbo(coin, t, bid, ask, sz='10'):
    return {'channel': 'bbo', 'data': {'coin': coin, 'time': t, 'bbo': [lv(bid, sz), lv(ask, sz)]}}


def book(t, bid, ask, sz='10'):
    side = lambda px: [lv(px, sz)] if px else []  # noqa: E731
    return {'channel': 'l2Book', 'data': {'coin': LAY['probe'], 'time': t, 'levels': [side(bid), side(ask)]}}


def ack(sub, **extra):
    return {'channel': 'subscriptionResponse', 'data': {'method': 'subscribe', 'subscription': dict(sub, **extra)}}


def q(coin, at, bid, ask, age=300):
    """A bbo received at wall ms `at`, stamped `age` ms earlier at the source."""
    return at, bbo(coin, at - age, bid, ask)


def pb(at, bid, ask, src=None):
    return at, book(at - 300 if src is None else src, bid, ask)


def lead(acks=True):
    """Acknowledgements, then initial touches summing below one, received before the window opens."""
    frames = [(OPEN - 59000, ack(s, **(L2_ECHO if s['type'] == 'l2Book' else {}))) for s in LAY['subs']] if acks else []
    return frames + [q(F, OPEN - 50000, None, None), q(A, OPEN - 50000, '0.30', '0.31'),
                     q(D, OPEN - 50000, '0.25', '0.26'), q(B2, OPEN - 50000, '0.44', '0.45')]


def beats(start, end, probe=True):
    """A matching probe (or a pong) every 30 s: the liveness heartbeat."""
    return [pb(t, '0.30', '0.31') if probe else (t, {'channel': 'pong'}) for t in range(start, end, 30000)]


def stream_of(*parts):
    return sorted((f for part in parts for f in part), key=lambda f: f[0])


def live_stream(extra=(), probe=True):
    return stream_of(lead(), beats(OPEN - 30000, CLOSE, probe), extra)


def timed(frames, stop='window_closed', stop_at=CLOSE, metas=(RAW_META, RAW_META)):
    """Records whose wall and mono receipts agree; frames are receipt-ordered (wall ms, object)."""
    out = []
    def add(kind, label, body, at):
        header = dict.fromkeys(e.HEADER_KEYS)
        header.update(index=len(out), kind=kind, label=label, body_bytes=len(body), wall_ms=at,
                      mono_ns=(at - BASE) * e.MS)
        if kind == 'rest':
            header.update(sent_ms=at, sent_mono_ns=(at - BASE) * e.MS, http_status=200, over_cap=False)
        out.append(dict(header, body=body))
    add('rest', 'meta_pre', metas[0], OPEN - 61000)
    add('event', 'ws_open', b'{}', OPEN - 60000)
    for p in LAY['payloads']:
        add('out', 'subscribe', p, OPEN - 60000)
    for at, f in frames:
        if at < stop_at:  # a (label, raw body) pair injects a non-JSON or non-text frame
            add('in', *(f if isinstance(f, tuple) else ('text', json.dumps(f).encode())), at)
    add('event', 'stop', e.encoded({'reason': stop}), stop_at)
    add('rest', 'meta_post', metas[1], stop_at + 1)
    return out


def project(frames, stop='window_closed', stop_at=CLOSE):
    recs = timed(frames, stop, stop_at)
    return e.analyze(recs, COHORT, Q, e.validate_records(recs, LAY))


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
        for q_ in raw['questions']:
            fields = dict(kv.split(':', 1) for kv in q_['description'].split('|')) if '|' in q_['description'] else {}
            if 'scheduledStart' in fields and q_['question'] in b.GROUPS['match_result']:
                stamp = fields['scheduledStart']
                self.assertEqual(e.TARGETS[q_['question']], f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:]}')
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


class CausalTests(unittest.TestCase):
    def partitioned(self, p):
        for route, cov in p['coverage_ns'].items():
            self.assertEqual(sum(cov.values()), WIN_NS, route)
        return p

    def runs(self, p, d):
        return sorted(((r['start_ns'] // e.MS, r['duration_ns'] // e.MS, r['end_cause'], r['qualified'])
                       for r in p['dispositions'][d]['longest_runs']))

    def test_receipt_order_cannot_backdate_and_ties_do_not_qualify(self):
        late = project(live_stream([q(B2, OPEN + 5000, '0.46', '0.47', age=1500), q(B2, OPEN + 5800, '0.44', '0.45')]))
        self.assertEqual(self.runs(late, 'forward_residual'), [(5000, 800, 'frame', False)])  # source times: 2,000 ms
        for end, count in ((6000, 0), (6001, 1)):
            p = self.partitioned(project(live_stream([q(B2, OPEN + 5000, '0.46', '0.47'),
                                                      q(B2, OPEN + end, '0.44', '0.45')])))
            self.assertEqual(p['dispositions']['forward_residual']['qualifying'], count)
        run = p['dispositions']['forward_residual']['qualifying_runs'][0]
        self.assertEqual((p['status'], run['decision']['residual'], run['decision']['cash']),
                         ('candidate_supported_path', [F], D_('0.01')))

    def test_gates_repeats_and_restoration(self):
        p = self.partitioned(project(live_stream([
            q(B2, OPEN + 5000, '0.44', '0.45', age=-300),               # future: suspended
            q(B2, OPEN + 9000, '0.44', '0.45'),                         # accepted: restored after 4,000 ms
            q(D, OPEN + 12000, '0.25', '0.26', age=2500),               # stale: 2,000 ms
            q(D, OPEN + 14000, '0.25', '0.26'),
            (OPEN + 15000, bbo(D, OPEN + 13700, '0.25', '0.26')),       # identical equal-time repeat: ignored
            (OPEN + 15500, bbo(D, OPEN + 13700, '0.24', '0.26')),       # changed equal time: 1,500 ms
            q(D, OPEN + 17000, '0.25', '0.26'),
            (OPEN + 18000, bbo(D, OPEN + 16000, '0.25', '0.26')),       # regressed: 500 ms
            q(D, OPEN + 18500, '0.25', '0.26')])))
        self.assertEqual(p['gates'], {'bbo_future': 1, 'bbo_order': 2, 'bbo_repeat': 1, 'bbo_stale': 1})
        self.assertEqual(p['coverage_ns']['forward']['gap'], 8000 * e.MS)

    def test_probe_suspends_until_compared_match_then_falsifies(self):
        p = self.partitioned(project(live_stream([
            pb(OPEN + 20000, '0.29', '0.31'),                           # mismatch: probe coin suspended
            q(A, OPEN + 25000, '0.30', '0.31'),                         # a new bbo alone does not restore
            pb(OPEN + 31000, '0.30', '0.31'),                           # compared match restores
            pb(OPEN + 40000, '0.29', '0.31'),
            q(A, OPEN + 44000, '0.30', '0.31'),
            pb(OPEN + 45000, '0.29', '0.31', src=OPEN + 43000),         # superseded: streak unchanged
            pb(OPEN + 50000, '0.29', '0.31')], probe=False)))           # second compared mismatch
        self.assertEqual(p['probe'], {'match': 1, 'mismatch': 3, 'superseded': 1, 'suspensions': 2,
                                      'status': 'falsified'})
        self.assertEqual((p['window_ns']['falsified'], p['coverage_ns']['forward']['gap']), (50000 * e.MS, 21000 * e.MS))
        self.assertEqual(p['coverage_ns']['forward']['invalidated'], WIN_NS - 50000 * e.MS)
        self.assertEqual(p['status'], 'inconclusive')

    def test_traded_legs_and_sold_set_split(self):
        p = self.partitioned(project(live_stream([
            q(B2, OPEN + 10000, '0.46', '0.47'),                        # named sum 1.01, fallback residual
            q(F, OPEN + 13000, '0.005', '0.03'),                        # supported fallback sold
            q(B2, OPEN + 16000, '0.44', '0.45'),                        # sum 0.995
            q(B2, OPEN + 20000, '0.46', '0.47'),
            q(F, OPEN + 21500, '0.005', '0.03', age=3000)])))           # stale fallback: unsold residual only
        self.assertEqual(self.runs(p, 'forward_closed'), [(13000, 3000, 'frame', True), (20000, 1500, 'frame', True)])
        self.assertEqual(self.runs(p, 'forward_residual'),
                         [(10000, 3000, 'frame', True), (21500, CLOSE - OPEN - 21500, 'close', True)])
        self.assertEqual(p['dispositions']['inverse_full']['runs'], 0)

    def test_acks_meta_ties_and_liveness(self):
        acks = [(OPEN - 59000 if i else OPEN + 5000, ack(s, **(L2_ECHO if s['type'] == 'l2Book' else {})))
                for i, s in enumerate(LAY['subs'])]
        p = self.partitioned(project(stream_of(lead(acks=False), acks, beats(OPEN - 30000, CLOSE),
                                               [(OPEN + 20000, acks[1][1])])))
        cov = p['coverage_ns']['forward']
        self.assertEqual((cov['initial'], cov['supported'], p['status']), (5000 * e.MS, 15000 * e.MS, 'inconclusive'))
        self.assertIn('subscriptions_not_acked_once', p['reasons'])
        settled = {'channel': 'outcomeMetaUpdates', 'data': {'questionSettled': Q}}
        for at, count in ((11000, 0), (11500, 1)):
            p = project(live_stream([q(B2, OPEN + 10000, '0.46', '0.47'), (OPEN + at, settled)]))
            self.assertEqual(p['dispositions']['forward_residual']['qualifying'], count)
        self.assertEqual((self.runs(p, 'forward_residual')[0][2], p['status']), ('invalidated', 'candidate_supported_path'))
        quiet = stream_of(lead(), beats(OPEN - 30000, OPEN + 100001), beats(OPEN + 200000, CLOSE),
                          [q(B2, OPEN + 90000, '0.46', '0.47')])
        p = self.partitioned(project(quiet))
        self.assertEqual(self.runs(p, 'forward_residual')[0], (90000, 35000, 'liveness', True))  # last beat +35 s
        self.assertEqual(p['coverage_ns']['forward']['gap'], 75000 * e.MS)

    def test_coverage_precedence_and_enumerated_anomalies(self):
        changed = {'channel': 'outcomeMetaUpdates', 'data': [{'questionUpdated': {'question': Q}}]}
        p = self.partitioned(project(live_stream([(OPEN + 30000, changed)]), 'ws_closed', OPEN + 60000))
        self.assertEqual(p['coverage_ns']['forward'], {'censored': WIN_NS - 60000 * e.MS, 'invalidated': 30000 * e.MS,
                                                       'initial': 0, 'gap': 0, 'supported': 30000 * e.MS})
        p = self.partitioned(project(live_stream([
            (OPEN + 1000, {'channel': 'x' * 40, 'data': 1}), (OPEN + 2000, bbo(A, OPEN + 1700, '0.40', '0.30')),
            (OPEN + 3000, ack({'type': 'bbo', 'coin': '#1'})),
            (OPEN + 4000, {'channel': 'outcomeMetaUpdates', 'data': {'mystery': 1}})])))
        self.assertEqual(p['anomalies'], {'bbo_crossed': 1, 'channel_unexpected': 1, 'meta_update_unparsed': 1,
                                          'unexpected_ack': 1})
        self.assertEqual((p['window_ns']['meta_invalidated'], p['coverage_ns']['forward']['gap']),
                         (4000 * e.MS, 3000 * e.MS))  # the unexpected channel suspends every member

    def test_inverse_needs_every_ask_and_unattributable_frames_reseed(self):
        p = self.partitioned(project(live_stream([q(F, OPEN + 10000, '0.005', '0.03'), q(F, OPEN + 20000, '0.005', None)])))
        self.assertEqual(p['coverage_ns']['inverse_full'], {'censored': 0, 'invalidated': 0, 'initial': 10000 * e.MS,
                                                            'gap': WIN_NS - 20000 * e.MS, 'supported': 10000 * e.MS})
        reseed = [q(A, OPEN + 2000, '0.30', '0.31'), q(D, OPEN + 3000, '0.25', '0.26'), q(B2, OPEN + 4000, '0.44', '0.45')]
        for bad in (('text', b'{'), ('binary', b'0'), {'channel': 'error', 'data': 'x'}, {'channel': 'bbo', 'data': 7},
                    {'channel': None}, {'channel': 7}, {'channel': ''}, {'channel': 'mystery'}, {'data': 1}):
            p = self.partitioned(project(live_stream([(OPEN + 1000, bad)] + reseed)))
            self.assertEqual(p['coverage_ns']['forward']['gap'], 3000 * e.MS, bad)

    def test_meta_ids_validate(self):
        spec = lambda qid, named: {'question': qid, 'name': 'n', 'description': 'd', 'fallbackOutcome': 1,  # noqa: E731
                                   'namedOutcomes': named, 'settledNamedOutcomes': []}
        for update, relevant in (({'questionUpdated': {}}, None), ({'questionUpdated': spec(1, [2])}, False),
                                 ({'outcomeCreated': {'outcome': 1, 'name': 'x'}}, False), ({'outcomeSettled': -1}, None),
                                 ({'questionUpdated': spec(1, [LAY['named'][0]])}, True)):
            p = project(live_stream([(OPEN + 1000, {'channel': 'outcomeMetaUpdates', 'data': [update]})]))
            self.assertEqual((p['window_ns']['meta_invalidated'] is not None, 'meta_update_unparsed' in p['anomalies']),
                             (relevant is not False, relevant is None), update)
        self.assertEqual(p['meta_events'][0]['event'], 'question_updated')

    def test_gated_or_unusable_probes_suspend_probe_coin(self):
        p = self.partitioned(project(live_stream([
            pb(OPEN + 20000, '0.30', '0.31', src=OPEN + 17500),                    # stale probe
            pb(OPEN + 31000, '0.30', '0.31'),                                      # next accepted probe restores
            (OPEN + 40000, {'channel': 'l2Book', 'data': {'coin': A, 'time': 1}}),  # unusable probe
            pb(OPEN + 45000, '0.30', '0.31'),
            pb(OPEN + 46000, '0.30', '0.31', src=OPEN + 44500),                    # regressed probe
            pb(OPEN + 55000, '0.30', '0.31')], probe=False)))
        self.assertEqual((p['gates'], p['anomalies'], p['probe']),
                         ({'l2Book_order': 1, 'l2Book_stale': 1}, {'l2book_invalid': 1}, {'match': 3, 'status': 'not_falsified'}))
        self.assertEqual(p['coverage_ns']['forward']['gap'], 25000 * e.MS)

    def test_projection_worst_case_fits_cap(self):
        p = project(live_stream())
        big = D_('-' + '9' * 20 + '.' + '9' * 30)
        run = {'disposition': 'forward_residual', 'sold': [A, D, B2], 'start_ns': 10 ** 13, 'duration_ns': 10 ** 13,
               'end_cause': 'invalidated', 'qualified': True, 'max_cash_run': big,
               'decision': dict(dict.fromkeys(('cash', 'min_cash', 'units', 'min_units', 'basis_per_unit'), big),
                                residual=[F, A, D, B2])}
        for d in e.DISPOSITIONS:
            p['dispositions'][d].update(qualifying_runs=[run] * e.QUAL_CAP, longest_runs=[run] * e.LONG_CAP, max_cash=big)
        p.update(meta_events=[{'index': 10 ** 9, 'event': 'question_updated'}] * e.META_LIST_CAP,
                 anomalies=dict.fromkeys(e.ANOMALY_KEYS | {'other'}, 10 ** 9), reasons=['x' * 40] * 12,
                 gates={f'{c}_{g}': 10 ** 9 for c in ('bbo', 'l2Book') for g in ('future', 'stale', 'order', 'repeat')},
                 ack_echo_extras={x.decode(): 'x' * 200 for x in LAY['payloads']}, max_forward_cash_supported=big)
        out = dict(b.stringify(p), plan_sha256='a' * 64, bundle_sha256='a' * 64, records=10 ** 9)
        self.assertLessEqual(len(e.encoded(out)), e.PROJECTION_CAP)


class Mem(io.BytesIO):
    def fileno(self):
        return -1


class MemCapture(e.LiveCapture):
    """The same flush, reserve and raw logic over memory: the production-size proofs write no disk."""
    def __init__(self):
        self.path, self.pending, self.cap, self.stream = None, None, e.BUNDLE_CAP, Mem()
        self.size, self.count, self.buffer, self.flushed_at = 0, 0, bytearray(), 0.0


class BundleTests(unittest.TestCase):
    def test_reserve_and_raw_stop_bounds_in_memory(self):
        noise = random.Random(7)
        with patch.object(e.os, 'fsync', lambda fd: None):
            for cap, fill, full in ((MemCapture(), lambda: noise.randbytes(e.FLUSH_BYTES - 1), 'reserve_reached'),
                                    (MemCapture(), lambda: bytes(e.FLUSH_BYTES - 1), 'raw_reached')):
                while not getattr(cap, full)():  # incompressible to the reserve; compressible to the raw stop
                    cap.add('in', 'text', fill(), wall_ms=1, mono_ns=1)
                cap.add('in', 'text', noise.randbytes(e.MAX_FRAME), wall_ms=1, mono_ns=1)  # worst frame
                cap.add('event', 'stop', e.encoded({'reason': 'cap_reserve_reached'}), wall_ms=1, mono_ns=1)
                cap.add('rest', 'meta_post', noise.randbytes(b.META_CAP), wall_ms=1, mono_ns=1)
                cap.flush()
                packed = cap.stream.getvalue()
                parsed = e.parse_bundle(packed)
                self.assertTrue(len(packed) <= e.BUNDLE_CAP and cap.raw <= e.RAW_LIMIT, (len(packed), cap.raw))
                self.assertEqual([r['index'] for r in parsed[-2:]], [len(parsed) - 2, len(parsed) - 1])
                self.assertEqual(parsed[-1]['body_bytes'], b.META_CAP)
        for bad in (packed + b'x', packed[:-3], b'junk'):
            with self.subTest(n=len(bad)), self.assertRaises(e.Refusal):
                e.parse_bundle(bad)

    def test_small_disk_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = e.LiveCapture(Path(tmp) / 'c.gz')
            cap.add('in', 'text', b'{}', wall_ms=1, mono_ns=1)
            self.assertEqual((len(e.parse_bundle(cap.finish())), [p.name for p in Path(tmp).iterdir()]), (1, ['c.gz']))
            small = e.Capture(Path(tmp) / 'd.gz', cap=64)
            with self.assertRaises(e.Refusal):
                small.add('in', 'text', random.Random(7).randbytes(e.FLUSH_BYTES), wall_ms=1, mono_ns=1)
            small.stream.close()

    def test_validate_orders(self):
        self.assertEqual(e.validate_records(records_from([bbo(A, OPEN, '0.3', '0.31')]), LAY), 'window_closed')
        self.assertEqual(e.validate_records(records_from([], stop='raw_reserve_reached'), LAY), 'raw_reserve_reached')
        recs = records_from([])
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
    def __init__(self, script, clock, connect_fails=False, tail='timeout', redirect=False):
        self.script, self.clock, self.sent, self.connect_fails, self.tail = list(script), clock, [], connect_fails, tail
        self.redirect, self.WSMsgType = redirect, MsgType

    class TraceConfig:  # noqa: N801
        def __init__(self):
            self.on_request_redirect = []

    def ClientSession(self, trust_env, trace_configs):  # noqa: N802
        assert trust_env is False and len(trace_configs) == 1
        fake = self
        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def ws_connect(self, url, **kw):
                assert url == e.WS_URL and kw['compress'] == 0 and kw['max_msg_size'] == e.MAX_FRAME
                if fake.redirect:
                    for hook in trace_configs[0].on_request_redirect:
                        await hook(self, None, None)
                if fake.connect_fails:
                    raise OSError('refused')
                return Socket()
        class Socket:
            async def send_str(self, text):
                fake.sent.append(text)
            async def receive(self, timeout=None):
                while fake.script and fake.script[0][0] == 'jump':  # a wall-clock step; mono is unaffected
                    fake.clock['jump'] = fake.script.pop(0)[1]
                if fake.script:
                    at, frame = fake.script.pop(0)
                    fake.clock['ms'] = max(fake.clock['ms'], at)
                    return Msg(MsgType.TEXT, json.dumps(frame))
                if fake.tail == 'close':
                    return Msg(MsgType.CLOSE, 1006, 'gone')
                fake.clock['ms'] = CLOSE
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
    def run_worker(self, frames, connect_fails=False, tail='timeout', cap=e.BUNDLE_CAP, metas=(RAW_META, RAW_META),
                   redirect=False, raw_stop=e.RAW_STOP):
        clock = {'ms': e.ms(WIN['meta_pre_at']) - 300000}  # one fake clock drives wall, mono and now_utc
        fake = FakeAiohttp(frames, clock, connect_fails, tail, redirect)
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
            clock['ms'] += int(max(0, seconds) * 1000)
        def wall():
            return clock['ms'] + clock.get('jump', 0)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(e, 'verify', return_value=({'target_question': Q}, COHORT)), \
                patch.object(e, 'now_utc', side_effect=lambda: EPOCH + dt.timedelta(milliseconds=wall())), \
                patch.object(e, 'sleep', sleep), patch('time.time_ns', lambda: wall() * e.MS), \
                patch('time.monotonic_ns', lambda: (clock['ms'] - BASE) * e.MS), \
                patch.object(e, 'BUNDLE_CAP', cap), patch.object(e, 'RAW_STOP', raw_stop), \
                patch.dict(sys.modules, {'aiohttp': fake}), patch('http.client.HTTPSConnection', Connection(metas)):
            out = Path(tmp)
            record = e.supervise(Process(out), float('inf'), out, 'a' * 64, Q)
            terminal = json.loads((out / 'terminal.json').read_bytes())
            projection = json.loads((out / 'projection.json').read_bytes()) if (out / 'projection.json').exists() else None
            fake.records = e.parse_bundle((out / 'capture.bundle.gz').read_bytes())
        return record, terminal, projection, fake

    def test_quiet_window_has_no_qualifying_path_and_is_reproduced(self):
        record, terminal, projection, fake = self.run_worker(live_stream())
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((terminal['stop'], projection['status'], projection['reasons']),
                         ('window_closed', 'no_qualifying_supported_path', []))
        self.assertEqual(record['denominator'], {'question': Q, 'availability': 'available',
                                                 'qualifying': dict.fromkeys(e.DISPOSITIONS, 0)})
        self.assertEqual(fake.sent[:6], [p.decode() for p in LAY['payloads']])
        self.assertEqual((projection['max_forward_cash_supported'], projection['probe']['status']), ('-0.01', 'not_falsified'))
        self.assertEqual(projection['coverage_ns']['forward']['supported'], WIN_NS)
        self.assertIn('nSigFigs', projection['ack_echo_extras'][LAY['payloads'][4].decode()])

    def test_forward_excursion_is_candidate(self):
        spike = [q(B2, HINT + 1000, '0.46', '0.47'), q(B2, HINT + 3500, '0.44', '0.45')]
        record, terminal, projection, _ = self.run_worker(live_stream(spike))
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((projection['status'], record['denominator']['qualifying']['forward_residual']),
                         ('candidate_supported_path', 1))
        run = projection['dispositions']['forward_residual']['qualifying_runs'][0]
        self.assertEqual((run['max_cash_run'], run['decision']['basis_per_unit'], run['decision']['residual'],
                          run['duration_ns']), ('0.01', '1', [F], 2500 * e.MS))

    def test_wall_jump_cannot_close_the_window(self):
        frames = live_stream()
        frames.insert(100, ('jump', 8 * 3600 * 1000))
        record, terminal, projection, fake = self.run_worker(frames)
        self.assertEqual((terminal['stop'], fake.script, projection['clock']['stop_wall_drift_ms']),
                         ('window_closed', [], 8 * 3600 * 1000))
        self.assertEqual(projection['coverage_ns']['forward']['supported'], WIN_NS)

    def test_censored_failed_redirected_and_capped_runs(self):
        record, terminal, projection, _ = self.run_worker(live_stream()[:20], tail='close')
        self.assertTrue(record['conclusion_eligible'], record)
        self.assertEqual((terminal['stop'], projection['status']), ('ws_closed', 'inconclusive'))
        self.assertIn('censored_ws_closed', projection['reasons'])
        for kw, cause in (({'connect_fails': True}, b'{}'), ({'redirect': True}, e.encoded({'cause': 'redirect'}))):
            record, terminal, projection, fake = self.run_worker([], **kw)
            self.assertEqual((terminal['stop'], projection['status'], record['conclusion_eligible']),
                             ('ws_connect_failed', 'inconclusive', True))
            self.assertEqual([r['body'] for r in fake.records if r['label'] == 'ws_open_failed'], [cause])
            self.assertEqual(projection['coverage_ns']['forward']['censored'], WIN_NS)
        pad = random.Random(1)
        noisy = live_stream([(OPEN + k, {'channel': 'pad', 'data': pad.randbytes(15000).hex()}) for k in range(40)])
        record, terminal, projection, _ = self.run_worker(noisy, cap=e.RESERVE + 200000)
        self.assertEqual((terminal['stop'], projection['status']), ('cap_reserve_reached', 'inconclusive'))
        self.assertLessEqual(terminal['bundle_bytes'], e.RESERVE + 200000)
        record, terminal, projection, _ = self.run_worker(noisy, raw_stop=100000)
        self.assertEqual((terminal['stop'], record['conclusion_eligible']), ('raw_reserve_reached', True))

    def test_meta_pre_failure_launch_window_and_unavailable_denominator(self):
        record, terminal, projection, _ = self.run_worker(live_stream(), metas=(b'not json', RAW_META))
        self.assertEqual(terminal['stop'], 'window_closed')
        self.assertIn('meta_pre_not_unchanged', projection['reasons'])
        with patch.object(e, 'verify', return_value=({'target_question': Q}, COHORT)), \
                patch.object(e, 'now_utc', return_value=WIN['launch_until'] + dt.timedelta(seconds=1)):
            with self.assertRaises(e.Refusal) as caught:
                e.run('a' * 64)
        self.assertEqual(str(caught.exception), 'outside_launch_window')
        record, terminal, projection, fake = self.run_worker(live_stream(), metas=(None,))
        self.assertEqual((terminal['stop'], projection['status'], fake.sent), ('meta_pre_failed', 'inconclusive', []))
        self.assertTrue(record['conclusion_eligible'], record)
        class Broken:
            exitcode = None
            def start(self):
                raise OSError('spawn')
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, 'verify', side_effect=e.Refusal('plan_unreadable')):
            record = e.supervise(Broken(), float('inf'), Path(tmp), 'a' * 64, Q)
        self.assertEqual((record['status'], record['denominator']),
                         ('start_failed', {'question': Q, 'availability': 'unavailable',
                                           'qualifying': dict.fromkeys(e.DISPOSITIONS)}))


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
