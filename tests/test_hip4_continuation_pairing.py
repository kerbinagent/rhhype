"""Offline synthetics for the HIP-4 funded pairing replay. No network, no raw data, small temp files only."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import hip4_continuation_live as lv
from scripts import hip4_continuation_pairing as pr

b = lv.b
COHORT = b.frozen_cohort(b.pm.strict_json((b.ROOT / b.FROZEN_META).read_bytes()))
RAW_META = gzip.decompress((b.ROOT / 'reports/hip4-outcome-v1/metadata-v1/response.json.gz').read_bytes())
LAY = lv.layout(COHORT, pr.QUESTION)
WIN = lv.window(pr.QUESTION)
O, CLOSE = lv.ms(WIN['open']), lv.ms(WIN['close'])
BASE = O - 600000
F, A, D, B2 = LAY['fallback_coin'], *[f'#{10 * m}' for m in LAY['named']]
L2_ECHO = {'nSigFigs': None, 'mantissa': None, 'fast': False}
S = pr.MS


def lvl(px, sz='10'):
    return None if px is None else {'px': px, 'sz': sz, 'n': 1}


def bbo(coin, at, bid, ask, bsz='10', asz='10', age=300):
    return O + at, {'channel': 'bbo', 'data': {'coin': coin, 'time': O + at - age, 'bbo': [lvl(bid, bsz), lvl(ask, asz)]}}


def meta(at, update):
    return O + at, {'channel': 'outcomeMetaUpdates', 'data': [update]}


def lead(fb=(None, None), fbsz='10'):
    frames = [(O - 59000, {'channel': 'subscriptionResponse', 'data': {'method': 'subscribe', 'subscription': dict(
        s, **(L2_ECHO if s['type'] == 'l2Book' else {}))}}) for s in LAY['subs']]
    return frames + [bbo(F, -50000, *fb, bsz=fbsz), bbo(A, -50000, '0.30', '0.31'), bbo(D, -50000, '0.25', '0.26'),
                     bbo(B2, -50000, '0.44', '0.45')]


def stream(*extra, fb=(None, None), fbsz='10', beats=(-30000, CLOSE - O)):
    pongs = [(O + t, {'channel': 'pong'}) for t in range(beats[0], beats[1], 30000)]
    return sorted(lead(fb, fbsz) + pongs + list(extra), key=lambda f: f[0])


def records(frames, stop='window_closed', stop_at=CLOSE):
    out = []
    def add(kind, label, body, at):
        header = dict.fromkeys(lv.HEADER_KEYS)
        header.update(index=len(out), kind=kind, label=label, body_bytes=len(body), wall_ms=at, mono_ns=(at - BASE) * S)
        if kind == 'rest':
            header.update(sent_ms=at, sent_mono_ns=(at - BASE) * S, http_status=200, over_cap=False)
        out.append(dict(header, body=body))
    add('rest', 'meta_pre', RAW_META, O - 61000)
    add('event', 'ws_open', b'{}', O - 60000)
    for p in LAY['payloads']:
        add('out', 'subscribe', p, O - 60000)
    for at, f in frames:
        if at <= stop_at:  # a frame at the stop instant precedes the stop record
            add('in', *(f if isinstance(f, tuple) else ('text', json.dumps(f).encode())), at)
    add('event', 'stop', lv.encoded({'reason': stop}), stop_at)
    add('rest', 'meta_post', RAW_META, stop_at + 1)
    return out


def project(frames, stop='window_closed', stop_at=CLOSE, schedules=pr.SCHEDULES, steps=pr.MAX_STEPS):
    recs = records(frames, stop, O + stop_at if stop_at != CLOSE else CLOSE)
    projection, trace = pr.analyze(recs, COHORT, lv.validate_records(recs, LAY), schedules, steps)
    for res in projection['results']:  # exact class partition of every complete decision set
        if res['decisions'] is not None:
            assert sum(res['classes'].values()) == res['decisions'], res
    return projection, trace


def eps(trace, route):
    return [e for e in trace['episodes'] if e['route'] == route]


def summary(projection, route, n=0):
    return [r for r in projection['results'] if r['route'] == route][n]


def ms_(ns):
    return int(ns) // S


ENTRY = [bbo(B2, 10000, '0.46', '0.47')]                                   # named bids 1.01 -> FF at 11000
CLOSING = [bbo(A, 20000, '0.29', '0.30'), bbo(B2, 20100, '0.43', '0.44')]   # asks 1.00 -> gate from 20100


class KernelTests(unittest.TestCase):
    def test_decorated_copy_matches_unchanged_kernel_and_never_mutates_it(self):
        noisy = stream(*ENTRY, *CLOSING, (O + 5000, {'channel': 'l2Book', 'data': {'coin': A, 'time': O + 4700,
                                                    'levels': [[lvl('0.29')], [lvl('0.31')]]}}),
                       (O + 6000, ('text', b'{')), (O + 7000, {'channel': 'mystery'}), bbo(D, 8000, '0.25', '0.26', age=2500),
                       meta(40000, {'questionUpdated': {}}))
        recs = records(noisy)
        before = {k: id(v) for k, v in vars(lv).items()}
        full, kernel = pr.decorated_replay(recs, LAY, WIN), lv.replay(recs, LAY, WIN)
        self.assertEqual(pr.undecorated(full), kernel)                      # statement-for-statement copy
        dec = pr.kernel_checked(recs, LAY, WIN)                              # streaming per-mark comparison
        self.assertEqual((pr.scalars(dec), len(dec['snaps'])), (pr.scalars(kernel), len(kernel['marks'])))
        self.assertEqual({k: id(v) for k, v in vars(lv).items()}, before)
        broken = dict(dec, pongs=dec['pongs'] + 1)
        with patch.object(pr, 'decorated_replay', return_value=broken), self.assertRaises(pr.Refusal) as caught:
            pr.kernel_checked(recs, LAY, WIN)
        self.assertEqual(str(caught.exception), 'kernel_mismatch')


class ForwardTests(unittest.TestCase):
    def test_funded_close_and_false_999ms_gate(self):
        projection, trace = project(stream(*ENTRY, *CLOSING))
        ep, = eps(trace, 'FF')
        self.assertEqual((ms_(ep['decision_ns']), ep['m'], ep['class'], ep['v'], ep['capital']), (11000, 10, 'closed', '0.10', '10'))
        self.assertEqual([(a['act'], ms_(a['t_ns'])) for a in ep['actions']],
                         [('make', 11500), ('sell', 11500), ('buy', 21600), ('merge', 21600)])
        false_gate = [bbo(A, 21099, '0.29', '0.31')]                     # gate true 20100..21099 only
        _, trace = project(stream(*ENTRY, *CLOSING, *false_gate, bbo(A, 30000, '0.29', '0.30')))
        ep, = eps(trace, 'FF')
        self.assertEqual(([ms_(a['t_ns']) for a in ep['actions'] if a['act'] == 'buy'], ep['attempts']), ([31500], 1))

    def test_partial_fill_restarts_only_its_own_gate(self):
        thin = bbo(D, 21300, '0.25', '0.26', asz='3')
        projection, trace = project(stream(*ENTRY, *CLOSING, thin))
        ep, = eps(trace, 'FF')
        buys = [(ms_(a['t_ns']), a['qty']) for a in ep['actions'] if a['act'] == 'buy']
        self.assertEqual(buys, [(21600, {A: 10, D: 3, B2: 10}), (23100, {D: 3}), (24600, {D: 3}), (26100, {D: 1})])
        self.assertEqual((ep['class'], ep['v'], ep['partial'], ep['attempts']), ('closed', '0.10', 3, 4))
        self.assertEqual(summary(projection, 'FF')['decisions'], 1)  # the entry interval is not restarted

    def test_all_miss_suppressed_until_false_then_true(self):
        drop = [bbo(A, 20000, '0.27', '0.28'), bbo(D, 20000, '0.24', '0.25'), bbo(B2, 20000, '0.42', '0.43')]
        rise = [bbo(A, 21200, '0.275', '0.285'), bbo(D, 21200, '0.245', '0.255'), bbo(B2, 21200, '0.425', '0.435')]
        back = [bbo(A, 25000, '0.27', '0.28'), bbo(D, 25000, '0.24', '0.25'), bbo(B2, 25000, '0.42', '0.43')]
        off, on = bbo(B2, 30000, '0.42', '0.50'), bbo(B2, 31000, '0.42', '0.43')
        projection, trace = project(stream(*ENTRY, *drop, *rise, *back, off, on))
        ff, = eps(trace, 'FF')
        self.assertEqual([(a['act'], ms_(a['t_ns'])) for a in ff['actions'][2:]],
                         [('miss_buy', 21500), ('buy', 32500), ('merge', 32500)])
        self.assertEqual((ff['class'], ff['v'], ff['all_miss']), ('closed', '0.50', 1))
        self.assertEqual([e['class'] for e in eps(trace, 'IF')], ['entry_unfilled', 'open_at_window_end'])

    def test_same_time_cuts_and_missing_support(self):
        settled = {'questionSettled': pr.QUESTION}
        for frames, stop, stop_at, expect in (
                ([meta(11000, settled)], 'window_closed', CLOSE, []),                 # cut at q: no decision
                ([meta(11001, settled)], 'window_closed', CLOSE, ['entry_invalidated']),
                ([], 'ws_closed', 11500, ['entry_censored']),                         # stop at the evaluation
                ([meta(11200, settled)], 'ws_closed', 11200, ['entry_censored'])):    # equal times: censored first
            _, trace = project(stream(*ENTRY, *frames), stop, stop_at)
            self.assertEqual([e['class'] for e in eps(trace, 'FF')], expect)
        _, trace = project(stream(*ENTRY, bbo(B2, 11400, '0.46', '0.47', age=3000)), 'ws_closed', 12000)
        ep, = eps(trace, 'FF')
        self.assertEqual((ep['class'], ep['v'], ep['zero_fills'], ep['hold'][B2], ep['envelope']),
                         ('censored_open', '-4.50', {'not_usable': 1}, 10, ['-4.50', '5.50']))

    def test_quiet_coin_ages_and_all_member_entries(self):
        _, trace = project(stream(bbo(B2, 3600000, '0.46', '0.47')))
        ep, = eps(trace, 'FF')
        self.assertEqual(ep['decision_ages'][D], [3651300, 3651000])       # carried by pongs, never re-aged
        _, trace = project(stream(fb=('0.02', '0.03'), fbsz='4'))
        ep, = eps(trace, 'FF')
        self.assertEqual((ep['key'], ep['m'], ep['class'], ep['v']), (sorted([F, A, D, B2]), 4, 'entry_closed', '0.04'))
        _, trace = project(stream(bbo(F, 1200, '0.02', '0.03', bsz='2'), fb=('0.02', '0.03'), fbsz='4'))
        ep, = eps(trace, 'FF')
        self.assertEqual((ep['class'], ep['v'], ep['hold'][F], ep['envelope']), ('open_at_window_end', '0.00', 2, ['0.00', '2.00']))

    def test_fee_schedule_changes_decisions_and_capital_exceeds_m(self):
        fee = {'f': '0.01', 'c_split': '0', 'c_neg': '0', 'c_merge': '0'}
        projection, _ = project(stream(*ENTRY), schedules=(pr.SCHEDULES[0], fee))
        self.assertEqual([summary(projection, 'FF', n)['decisions'] for n in (0, 1)], [1, 0])
        stale = [bbo(D, 11400, '0.25', '0.26', age=3000), bbo(B2, 11400, '0.46', '0.47', age=3000)]
        _, trace = project(stream(*ENTRY, *stale))
        ep, = eps(trace, 'FF')
        self.assertEqual((ep['class'], ep['v'], ep['capital']), ('closed', '-0.10', '10.10'))
        with self.assertRaises(pr.Refusal):
            pr.fees({'f': '1.5', 'c_split': '0', 'c_neg': '0', 'c_merge': '0'})

    def test_caps_are_unknown_not_negative(self):
        thin = bbo(D, 21300, '0.25', '0.26', asz='3')
        with patch.object(pr, 'MAX_ATTEMPTS', 2):
            projection, trace = project(stream(*ENTRY, *CLOSING, thin))
        self.assertEqual((eps(trace, 'FF')[0]['class'], summary(projection, 'FF')['closure_within_window']),
                         ('work_cap', [[0, 1], [1, 1]]))
        self.assertEqual(summary(projection, 'FF')['rates_status'], 'exact')
        projection, trace = project(stream(*ENTRY, *CLOSING), steps=12)
        ff = summary(projection, 'FF')
        self.assertEqual((ff['decisions'], ff['decisions_seen'], projection['step_cap_exhausted']), (None, 1, True))
        self.assertEqual((ff['rates_status'], ff['decision_to_fill'], ff['closure_within_window'],
                          ff['complete_case_conditional']), ('unavailable_incomplete_scan', None, None, None))
        self.assertEqual((ff['prefix_only']['label'][:6], ff['prefix_only']['decision_to_fill']),
                         ('prefix', [[1, 1], [1, 1]]))


MULTI = [*ENTRY, bbo(B2, 10800, '0.44', '0.45'),                            # 800 ms run: no decision
         bbo(B2, 15000, '0.46', '0.47'), bbo(F, 17000, '0.01', '0.02'),       # sold set changes at 17000
         bbo(B2, 19000, '0.44', '0.45'), bbo(B2, 40000, '0.47', '0.48')]


class BoundsTests(unittest.TestCase):
    def test_zero_fee_entries_equal_kernel_forward_runs(self):
        frames = stream(*MULTI)
        s = lv.replay(records(frames), LAY, WIN)
        runs = lv.runs_of(lv.pieces(s['marks'], s['stop']['mono_ns'], s['open'], s['close']), s['open'], s['close'])
        want = sorted(r['start_ns'] + 1000 * S for r in runs if r['disposition'] != 'inverse_full' and r['qualified'])
        _, trace = project(frames)
        self.assertEqual(sorted(int(e['decision_ns']) for e in eps(trace, 'FF')), want)
        self.assertEqual([w // S for w in want], [16000, 18000, 41000])

    def test_episode_and_trace_caps_and_determinism(self):
        frames = stream(*MULTI)
        with patch.object(pr, 'MAX_EPISODES', 1), patch.object(pr, 'Episode', wraps=pr.Episode) as built:
            projection, trace = project(frames)
        ff = summary(projection, 'FF')
        self.assertEqual((len(eps(trace, 'FF')), ff['classes']['work_cap'], ff['decisions']), (1, 2, 3))
        self.assertEqual((ff['work_cap_unbuilt'], ff['work_cap_built'], ff['rates_status']),
                         (2, 0, 'conservative_bounds_possibly_undefined'))  # unknown size admission
        self.assertEqual(built.call_count, 1)  # overflow decisions are counted, never allocated
        with patch.dict(pr.ROLE_LIMITS['primary'], {'trace': 1000}):
            _, small = project(frames)
        self.assertLess(small['episodes_kept'], small['episodes_total'])
        self.assertEqual(lv.encoded(project(frames)), lv.encoded(project(frames)))


class InverseTests(unittest.TestCase):
    def test_first_negation_miss_is_a_state_change_then_closes(self):
        dip = bbo(B2, 10000, '0.41', '0.42')                                 # named asks 0.99 -> IF at 11000
        up = bbo(B2, 20000, '0.45', '0.46')                                  # proceeds 10.00 >= 9.90
        sag = [bbo(A, 21200, '0.295', '0.31'), bbo(D, 21200, '0.245', '0.26'), bbo(B2, 21200, '0.445', '0.46')]
        back = [bbo(A, 25000, '0.30', '0.31'), bbo(D, 25000, '0.25', '0.26'), bbo(B2, 25000, '0.45', '0.46')]
        _, trace = project(stream(dip, up, *sag, *back))
        ep, = eps(trace, 'IF')
        self.assertEqual([(a['act'], ms_(a['t_ns'])) for a in ep['actions']],
                         [('buy', 11500), ('split', 11500), ('merge', 11500), ('negate', 21500), ('miss_sell', 21500),
                          ('sell', 26500)])
        self.assertEqual((ep['class'], ep['v'], ep['all_miss'], ep['partial']), ('closed', '0.10', 0, 1))

    def test_zero_merge_skips_conversions(self):
        dip, dear = bbo(B2, 10000, '0.41', '0.42'), bbo(D, 11300, '0.25', '0.27')
        _, trace = project(stream(dip, dear, bbo(B2, 20000, '0.45', '0.46')))
        ep, = eps(trace, 'IF')
        self.assertEqual([a['act'] for a in ep['actions']], ['buy', 'sell'])
        self.assertEqual((ep['class'], ep['v'], ep['zero_fills']), ('closed', '0.20', {'limit': 1}))


class TraceAndRunTests(unittest.TestCase):
    def test_reconcile_detects_tampering(self):
        _, trace = project(stream(*ENTRY, *CLOSING))
        ep = eps(trace, 'FF')[0]
        self.assertEqual(str(pr.reconcile(ep, LAY, pr.SCHEDULES[0])['v']), ep['v'])
        bad = json.loads(json.dumps(ep))
        bad['actions'][1]['px'][A] = '0.31'
        self.assertNotEqual(str(pr.reconcile(bad, LAY, pr.SCHEDULES[0])['v']), ep['v'])

    def run_role(self, tmp, analyze=None, role='primary', sha=None, verify=None, extra=(), **limits):
        recs = records(stream(*ENTRY, *CLOSING))
        data = b''.join(lv.gzip_member(b''.join(lv.encoded({k: r[k] for k in lv.HEADER_KEYS}) + r['body'] + b'\n'
                                                 for r in recs[i:i + 50])) for i in range(0, len(recs), 50))
        bundle = Path(tmp) / 'capture.bundle.gz'
        bundle.write_bytes(data)
        out = Path(tmp) / 'run'
        plan = {'output_dir': str(out)}
        seal = {'input': {'path': str(bundle), 'bytes': len(data), 'sha256': sha or lv.digest(data)}}
        checked = patch.object(pr, 'verify', side_effect=verify((plan, seal, COHORT))) if verify else \
            patch.object(pr, 'verify', return_value=(plan, seal, COHORT))
        patches = [checked, patch.object(pr, 'PENDING', Path(tmp)), *extra]
        patches += [patch.object(pr, k, v) for k, v in limits.items()]
        patches += [patch.object(pr, 'analyze', side_effect=analyze)] if analyze else []
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            record = pr.run(role, 'a' * 64, 'b' * 64)
        return record, out, (plan, seal, COHORT)

    def test_run_publishes_atomically_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp)
            self.assertEqual((record['status'], sorted(p.name for p in out.iterdir())),
                             ('complete', ['projection.json', 'run.json', 'trace.json']))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['capture.bundle.gz', 'run'])
            projection = json.loads((out / 'projection.json').read_bytes())
            self.assertEqual(summary(projection, 'FF')['classes']['closed'], 1)
            with self.assertRaises(pr.Refusal):
                self.run_role(tmp)
        printed = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                patch.dict(sys.modules, {'aiohttp': None}), contextlib.redirect_stdout(printed):
            self.assertEqual(pr.main([]), 0)
        self.assertEqual(json.loads(printed.getvalue())['writes'], 0)

    def test_hard_limits_publish_unavailable(self):
        def spin(*_, **__):
            while True:
                pass
        def nap(*_, **__):
            import time
            time.sleep(30)
        def hog(*_, **__):
            return bytearray(1 << 31)
        vm = int(Path('/proc/self/statm').read_text().split()[0]) * 4096
        for kw, cause in (({'analyze': spin, 'CPU_S': 1, 'WALL_S': 60}, 'cpu_limit'),
                          ({'analyze': nap, 'WALL_S': 1}, 'wall_limit'),
                          ({'analyze': hog, 'RAM_BYTES': vm + (1 << 28)}, 'memory_limit')):
            with self.subTest(cause=cause), tempfile.TemporaryDirectory() as tmp:
                record, out, _ = self.run_role(tmp, **kw)
                self.assertEqual((record['status'], record['cause'], sorted(p.name for p in out.iterdir())),
                                 ('unavailable', cause, ['run.json']))

    def test_role_shares_fit_and_a_large_trace_round_trips(self):
        for k, total in pr.CATEGORY_BYTES.items():
            self.assertLessEqual(sum(r[k] for r in pr.ROLE_LIMITS.values()), total)
        self.assertLessEqual(max(r['trace'] for r in pr.ROLE_LIMITS.values()), b.pm.BODY_CAP)
        def big(*_, **__):  # a valid trace above the sensitivity share and within the primary share and decoder
            return {'schema': 'p'}, {'episodes': ['x' * 1000] * 20, 'episodes_kept': 20, 'episodes_total': 20}
        scaled = [patch.dict(pr.ROLE_LIMITS['primary'], {'trace': 24576}),
                  patch.dict(pr.ROLE_LIMITS['sensitivity'], {'trace': 12288}), patch.object(b.pm, 'BODY_CAP', 24576)]
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, analyze=big, extra=scaled)
            self.assertEqual((record['status'], record['staged_bytes']['trace'] > 12288, record['within_role_shares']),
                             ('complete', True, True))
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, analyze=big, role='sensitivity', extra=scaled)
            self.assertEqual((record['status'], record['cause'], record['refusal'], sorted(p.name for p in out.iterdir())),
                             ('unavailable', 'refused', {'code': 'output_over_cap'}, ['refusal.json', 'run.json']))

    def test_child_checks_input_bytes_and_run_reverifies_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, sha='0' * 64)
            self.assertEqual((record['cause'], record['refusal']), ('refused', {'code': 'input_changed'}))
        calls = []
        def flaky(ok):
            def check(*_):
                calls.append(1)
                if len(calls) > 1:
                    raise pr.Refusal('pin_mismatch')  # a pinned file changed while the child ran
                return ok
            return check
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, verify=flaky)
            self.assertEqual((record['status'], record['cause'], len(calls)), ('unavailable', 'pins_changed_after_run', 2))
            kept = {k['name'] for k in record['retained_not_admitted']}
            self.assertEqual(kept, {'not-admitted-projection.json', 'not-admitted-trace.json'})
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(kept | {'run.json'}))

    def test_failures_keep_labelled_partial_outputs_and_start_failure_is_explicit(self):
        real = pr.h.write_once
        def broken(path, data):
            if Path(path).name == 'trace.json':
                raise OSError('disk')
            return real(path, data)
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, extra=[patch.object(pr.h, 'write_once', side_effect=broken)])
            self.assertEqual((record['cause'], record['refusal']), ('exit_5', {'code': 'exception', 'type': 'OSError'}))
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(names, ['not-admitted-projection.json', 'refusal.json', 'run.json'])
            kept, = record['retained_not_admitted']
            self.assertEqual((kept['bytes'], kept['sha256']),
                             (len((out / kept['name']).read_bytes()), lv.digest((out / kept['name']).read_bytes())))
        with tempfile.TemporaryDirectory() as tmp:
            record, out, _ = self.run_role(tmp, extra=[patch.object(pr, 'fork_process', side_effect=OSError('fork'))])
            self.assertEqual((record['cause'], sorted(p.name for p in out.iterdir())), ('start_failed', ['run.json']))

    def test_unconfirmed_kill_leaves_staging_untouched(self):
        class Stuck:
            exitcode = None
            def join(self, *_):
                pass
            def is_alive(self):
                return True
            def kill(self):
                pass
        with patch.object(pr, 'fork_process', return_value=Stuck()), patch.object(pr, 'WALL_S', 0), \
                patch.object(pr, 'KILL_JOIN_S', 0):
            self.assertEqual(pr.bounded_child(None, ()), 'wall_limit_kill_unconfirmed')
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / 'run.pending'
            record, out, _ = self.run_role(tmp, extra=[patch.object(pr, 'bounded_child', side_effect=lambda *_: (
                (staged / 'trace.json.pending').write_bytes(b'partial'), 'wall_limit_kill_unconfirmed')[1])])
            self.assertEqual((record['status'], record['cause'], out.exists()), ('unavailable', 'wall_limit_kill_unconfirmed', False))
            self.assertEqual(sorted(p.name for p in staged.iterdir()), ['trace.json.pending'])  # untouched
            receipt = json.loads((Path(tmp) / 'run.failure.json').read_bytes())
            self.assertEqual((receipt['staging_left_untouched'], receipt['status']), ('run.pending', 'unavailable'))

    def test_verify_authenticates_the_whole_chain(self):
        def pin(rel):
            data = (b.ROOT / rel).read_bytes()
            return {'path': rel, 'bytes': len(data), 'sha256': lv.digest(data)}
        sealed = {'schema': pr.SCHEMA, 'status': 'sealed_prospective', 'role': 'primary',
                  'analysis_plan': json.loads(lv.encoded(pr.ANALYSIS_PLAN)), 'schedules': list(pr.SCHEDULES),
                  'output_limits_bytes': pr.ROLE_LIMITS['primary'], 'output_dir': pr.OUTS['primary'],
                  'source_pins': [pin(x) for x in pr.PINNED], 'chain_pins': [pin(x) for x in pr.CHAIN],
                  'live_plan': pin(pr.LIVE_PLAN), 'bounds': pr.declared('primary')['bounds'],
                  'category_shares': pr.declared('primary')['category_shares'], 'question': pr.QUESTION,
                  'predeclaration': {'costs_and_limits': pr.declared('primary')['costs_and_limits']}}
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            def check(value, code=None):
                plan_path.write_bytes(lv.encoded(value))
                with patch.dict(pr.PLANS, {'primary': plan_path}):
                    if code is None:
                        return pr.verify_plan('primary', lv.digest(plan_path.read_bytes()))
                    with self.assertRaises(pr.Refusal) as caught:
                        pr.verify_plan('primary', lv.digest(plan_path.read_bytes()))
                    self.assertEqual(str(caught.exception), code)
            self.assertEqual(check(sealed)[0]['role'], 'primary')
            check(dict(sealed, status='draft_not_frozen'), 'plan_not_sealed')
            check(dict(sealed, schedules=list(pr.SENSITIVITIES)), 'plan_changed')
            check(dict(sealed, output_limits_bytes=pr.ROLE_LIMITS['sensitivity']), 'plan_changed')
            stale = dict(sealed['bounds'], scan_steps=20000000)
            for bad in (dict(sealed, bounds=stale), dict(sealed, bounds=dict(sealed['bounds'], episodes_per_route_schedule=512)),
                        dict(sealed, bounds=dict(sealed['bounds'], measured='150,291 records: 28.7 s CPU')),
                        dict(sealed, predeclaration={'costs_and_limits': dict(sealed['predeclaration']['costs_and_limits'],
                                                                              outputs=pr.ROLE_LIMITS['sensitivity'])}),
                        dict(sealed, predeclaration={}), dict(sealed, question=358),
                        dict(sealed, category_shares={'roles': pr.ROLE_LIMITS}),
                        {k: v for k, v in sealed.items() if k != 'bounds'}):
                check(bad, 'declared_bounds_conflict')
            check(dict(sealed, chain_pins=sealed['chain_pins'][1:]), 'missing_pins')
            tampered = [dict(sealed['chain_pins'][0], sha256='0' * 64)] + sealed['chain_pins'][1:]
            check(dict(sealed, chain_pins=tampered), 'pin_mismatch')
            outside = [dict(sealed['source_pins'][0], path='/' + sealed['source_pins'][0]['path'])]
            check(dict(sealed, source_pins=outside + sealed['source_pins'][1:]), 'missing_pins')
            with patch.dict(pr.PLANS, {'primary': Path(tmp) / 'absent.json'}), self.assertRaises(pr.Refusal) as caught:
                pr.verify_plan('primary', 'a' * 64)
            self.assertEqual(str(caught.exception), 'plan_unreadable')
            primary_path, sens_path = Path(tmp) / 'primary.json', Path(tmp) / 'sens.json'
            primary_path.write_bytes(lv.encoded(sealed))
            ref = {'path': pr.PLAN_RELS['primary'], 'bytes': len(primary_path.read_bytes()),
                   'sha256': lv.digest(primary_path.read_bytes())}
            sens = dict(sealed, role='sensitivity', schedules=list(pr.SENSITIVITIES), output_dir=pr.OUTS['sensitivity'],
                        output_limits_bytes=pr.ROLE_LIMITS['sensitivity'], primary_plan=ref,
                        bounds=pr.declared('sensitivity')['bounds'],
                        predeclaration={'costs_and_limits': pr.declared('sensitivity')['costs_and_limits']})
            def bound(value, code=None):
                sens_path.write_bytes(lv.encoded(value))
                with patch.dict(pr.PLANS, {'primary': primary_path, 'sensitivity': sens_path}):
                    if code is None:
                        plan, _ = pr.verify_plan('sensitivity', lv.digest(sens_path.read_bytes()))
                        return pr.primary_sha('sensitivity', plan, 'unused')
                    with self.assertRaises(pr.Refusal) as caught:
                        pr.verify_plan('sensitivity', lv.digest(sens_path.read_bytes()))
                    self.assertEqual(str(caught.exception), code)
            self.assertEqual(bound(sens), ref['sha256'])
            bound({k: v for k, v in sens.items() if k != 'primary_plan'}, 'primary_plan_unbound')
            bound(dict(sens, primary_plan=dict(ref, path='other.json')), 'primary_plan_unbound')
            bound(dict(sens, primary_plan=dict(ref, sha256='0' * 64)), 'plan_sha_mismatch')
        self.assertFalse(pr.pin_ok({'path': '../x', 'bytes': 0, 'sha256': ''}))

    def test_verify_seal_requires_the_exact_admitted_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, live = Path(tmp), Path(tmp) / pr.LIVE_OUT
            live.mkdir(parents=True)
            for name in (*pr.LIVE_FILES, 'capture.bundle.gz'):
                (live / name).write_bytes(name.encode())
            (root / 'other.gz').write_bytes(b'books')
            def pin(rel):
                data = (root / rel).read_bytes()
                return {'path': rel, 'bytes': len(data), 'sha256': lv.digest(data)}
            good = {'schema': pr.SEAL_SCHEMA, 'question': pr.QUESTION, 'live_plan_sha256': pr.LIVE_PLAN_SHA,
                    'plan_sha256': 'c' * 64, 'status': 'admitted', 'checks': dict.fromkeys(pr.REQUIRED_CHECKS, True),
                    'pins': [pin(f'{pr.LIVE_OUT}/{n}') for n in pr.LIVE_FILES],
                    'input': pin(f'{pr.LIVE_OUT}/capture.bundle.gz')}
            seal_path = root / 'seal.json'
            def check(value, code=None):
                seal_path.write_bytes(lv.encoded(value))
                with patch.object(pr, 'ROOT', root), patch.object(pr, 'SEAL', seal_path):
                    if code is None:
                        return pr.verify_seal(lv.digest(seal_path.read_bytes()), 'c' * 64)
                    with self.assertRaises(pr.Refusal) as caught:
                        pr.verify_seal(lv.digest(seal_path.read_bytes()), 'c' * 64)
                    self.assertEqual(str(caught.exception), code)
            self.assertEqual(check(good)['status'], 'admitted')
            for bad in (dict(good, plan_sha256='d' * 64), dict(good, plan_sha256=None), dict(good, pins=[]), dict(good, pins=good['pins'][::-1]), dict(good, input=pin('other.gz')),
                        dict(good, input=None), dict(good, schema='x'), dict(good, question=358),
                        dict(good, live_plan_sha256='0' * 64), dict(good, status='unavailable'),
                        dict(good, checks=dict(good['checks'], supervisor_terminal=False)),
                        dict(good, checks=dict(good['checks'], admission_stage_complete=1)),
                        dict(good, checks={k: True for k in pr.REQUIRED_CHECKS[1:]}), dict(good, checks={})):
                check(bad, 'input_not_admitted')
            (live / 'capture.bundle.gz').write_bytes(b'changed')
            check(good, 'seal_pin_mismatch')


CONCLUSIONS = dict.fromkeys(('worker_completed_exit_zero', 'terminal_without_failure', 'bundle_matches_terminal',
                             'records_match_plan', 'projection_reproduced', 'no_pending_publication',
                             'final_plan_and_source_pins'), True)
AFTER = WIN['close'] + __import__('datetime').timedelta(seconds=1)


class AdmissionTests(unittest.TestCase):
    def admit(self, tmp, sup=None, recheck=None, now=AFTER, plan=None, extra=()):
        good_sup = {'status': 'worker_finished', 'worker_exitcode': 0, 'conclusion_eligible': True}
        claim = {'plan_sha256': pr.LIVE_PLAN_SHA, 'target_question': pr.QUESTION}
        rel = str(Path(tmp) / 'live')
        (Path(tmp) / 'live').mkdir(exist_ok=True)
        files = (('claim.json', claim), ('terminal.json', {}), ('projection.json', {}))
        files += (('supervisor.json', good_sup if sup is None else sup),) if sup != 'missing' else ()
        for name, value in files:
            (Path(tmp) / 'live' / name).write_bytes(lv.encoded(value))
        (Path(tmp) / 'live' / 'capture.bundle.gz').write_bytes(b'x')
        seal_path = Path(tmp) / 'seal' / 'seal.json'
        planned = patch.object(pr, 'verify_plan', side_effect=plan) if plan else \
            patch.object(pr, 'verify_plan', return_value=({}, COHORT))
        patches = [planned, patch.object(pr, 'LIVE_OUT', rel), patch.object(pr, 'SEAL', seal_path),
                   patch.object(pr, 'utc_now', return_value=now), patch.object(pr.lv, 'verify', return_value=None),
                   patch.object(pr.lv, 'conclusion_checks', return_value=(recheck or CONCLUSIONS, None, None)), *extra]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            return pr.admit('c' * 64), seal_path

    def test_admission_seals_once_and_preserves_unavailable(self):
        good_sup = {'status': 'worker_finished', 'worker_exitcode': 0, 'conclusion_eligible': True}
        for sup, recheck, status in ((None, None, 'admitted'),
                                     (dict(good_sup, conclusion_eligible=False), None, 'unavailable'),
                                     (None, dict(CONCLUSIONS, bundle_matches_terminal=False), 'unavailable')):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                seal, seal_path = self.admit(tmp, sup, recheck)
                self.assertEqual((seal['status'], len(seal['pins']), seal['plan_sha256'], set(seal['checks'])),
                                 (status, 4, 'c' * 64, set(pr.REQUIRED_CHECKS)))
                self.assertEqual(json.loads(seal_path.read_bytes())['status'], status)
                with self.assertRaises(pr.Refusal) as caught:
                    self.admit(tmp, sup, recheck)
                self.assertEqual(str(caught.exception), 'seal_exists')

    def test_premature_or_unauthenticated_admission_refuses_without_writing(self):
        before = WIN['close'] - __import__('datetime').timedelta(seconds=1)
        grace = WIN['close'] + __import__('datetime').timedelta(seconds=pr.SUPERVISOR_MISSING_S - 1)
        for kw, code in (({'now': before}, 'admission_before_close'), ({'sup': 'missing', 'now': grace}, 'supervisor_not_terminal'),
                         ({'plan': pr.Refusal('plan_sha_mismatch')}, 'plan_sha_mismatch')):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                reads = []
                real = pr.bounded_read
                def spy(path, cap):
                    reads.append(str(path))
                    return real(path, cap)
                with patch.object(pr, 'bounded_read', side_effect=spy), self.assertRaises(pr.Refusal) as caught:
                    self.admit(tmp, **kw)
                self.assertEqual((str(caught.exception), (Path(tmp) / 'seal').exists()), (code, False))
                self.assertFalse([r for r in reads if '/live/' in r])  # no capture read before the gates pass
        late = WIN['close'] + __import__('datetime').timedelta(seconds=pr.SUPERVISOR_MISSING_S)
        with tempfile.TemporaryDirectory() as tmp:
            seal, _ = self.admit(tmp, sup='missing', now=late)
            self.assertEqual((seal['status'], seal['checks']['supervisor_terminal'], len(seal['pins'])),
                             ('unavailable', False, 3))

    def test_admission_child_stops_when_live_verification_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'replayed'
            def replay(*_):
                marker.write_bytes(b'x')
                return CONCLUSIONS, None, None
            seal, _ = self.admit(tmp, extra=[patch.object(pr.lv, 'verify', side_effect=pr.Refusal('pin_mismatch')),
                                             patch.object(pr.lv, 'conclusion_checks', side_effect=replay)])
            self.assertFalse(marker.exists())
            self.assertEqual((seal['status'], seal['cause'], seal['checks']['live_plan_and_sources'],
                              seal['checks']['admission_stage_complete'], seal['checks']['conclusion_records_match_plan']),
                             ('unavailable', None, False, True, False))

    def test_admission_stage_is_bounded(self):
        def spin(*_):
            while True:
                pass
        def nap(*_):
            import time
            time.sleep(30)
        for extra, cause in (([patch.object(pr, 'CPU_S', 1), patch.object(pr.lv, 'conclusion_checks', side_effect=spin)],
                              'cpu_limit'),
                             ([patch.object(pr, 'WALL_S', 1), patch.object(pr.lv, 'conclusion_checks', side_effect=nap)],
                              'wall_limit'),
                             ([patch.object(pr, 'fork_process', side_effect=OSError('fork'))], 'start_failed')):
            with self.subTest(cause=cause), tempfile.TemporaryDirectory() as tmp:
                seal, seal_path = self.admit(tmp, extra=extra)
                self.assertEqual((seal['status'], seal['cause'], seal['checks']['admission_stage_complete'], len(seal['pins'])),
                                 ('unavailable', cause, False, 4))
                self.assertTrue(seal_path.exists())


if __name__ == '__main__':
    unittest.main()
