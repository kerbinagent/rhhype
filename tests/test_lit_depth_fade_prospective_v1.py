"""Focused offline fixtures only: no real store, capture, nomination or network."""
import sys
sys.dont_write_bytecode = True
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import lit_depth_fade_prospective_v1 as w


def index(entries=(), next_number=92, expired=()):
    return dict(schema='rolling-research-index-v1', next_number=next_number, expired=list(expired),
        chunks={w.chunk_name(n): dict(number=n, role='reserved_validation', launched_ns=t,
                state=s, pins=[], seal_sha256='e' * 64) for n, t, s in entries})


def rows():
    result = w.unknown(96, 'fixture', 'a' * 64)['rows']
    for r in result:
        r.update(attempts=0, closed=0, complete=True, unknown=None, position_open=False,
                 pending_order=False, closed_cash_after_capital='0', closed_stressed_cash='0')
        if r['venue'] == 'rh_lighter':
            r.update(attempts=2, closed=2, closed_stressed_cash='0.2' if r['rule'] == 'depth_fade' else '-0.1')
    return result


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lit_depth_fade_test_')
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        for module, key, value in ((w, 'ROOT', self.root), (w.old, 'ROOT', self.root),
                (w, 'PLAN', self.root / 'plan.json'), (w, 'OUT', self.root / 'controls'),
                (w.fix, 'RESEARCH', self.root / 'ledgers'),
                (w.rolling, 'STORE', self.root / 'data/rolling/market-research-v1')):
            self.stack.enter_context(patch.object(module, key, value))
        w.fix.RESEARCH.mkdir()

    def tearDown(self):
        self.assertLessEqual(sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()), 32768)
        self.stack.close(); self.temp.cleanup()

    def frozen(self, **changes):
        p = dict(schema=w.SCHEMA, status='frozen', frozen_utc_ns=w.FREEZE_NS - 100,
                 store_identity_sha256='b' * 64, **w.fields())
        p['source_pins'] = []
        for rel in (w.SOURCE, w.TEST, w.DESIGN):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'pinned synthetic source\n')
            p['source_pins'].append(dict(path=rel, bytes=path.stat().st_size, sha256=w.fix.sha(path)))
        p.update(changes); w.PLAN.write_bytes(w.fix.encode(p))
        return p, w.fix.sha(w.PLAN)

    def outputs(self):
        w.OUT.mkdir()
        for n in w.NUMBERS: w.controls(n).mkdir()

    def test_default_dry_and_exact_freeze_pins(self):
        with patch.object(w.rolling, 'Store', side_effect=AssertionError('store')), \
                patch.object(w, 'read', side_effect=AssertionError('read')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            w.main([])
        self.assertEqual(json.loads(output.getvalue())['nominations'], 0)
        p, digest = self.frozen()
        with patch.object(w, 'source_contracts'):
            self.assertEqual(w.verify(digest, before_freeze=True, now_ns=w.FREEZE_NS - 1), p)
            with self.assertRaisesRegex(ValueError, 'launch_missed_cutoff'):
                w.verify(digest, before_freeze=True, now_ns=w.FREEZE_NS)
            with self.assertRaisesRegex(ValueError, 'plan_sha256'): w.verify('c' * 64)
            (self.root / w.SOURCE).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'pin_bytes'): w.verify(digest)
        _, digest = self.frozen(execution_parameters=dict(w.strategy.PARAMS, budget=101))
        with patch.object(w, 'source_contracts'), self.assertRaisesRegex(ValueError, 'plan_scope'):
            w.verify(digest)
        self.assertFalse(w.OUT.exists())

    def test_fixed_reservation_not_success_selection_and_deadline(self):
        self.outputs(); p, digest = self.frozen()
        store = Mock(); store.index.return_value = index(); store.locked.return_value = contextlib.nullcontext()
        with patch.object(w, 'store_identity', return_value=store), patch.object(w.time, 'time_ns', return_value=w.FREEZE_NS - 1):
            w.nominate(digest, p)
        nominated = w.read(w.OUT / 'nomination.json')
        self.assertEqual(nominated['fixed_chunk_numbers'], [96, 100])
        store.index.return_value = index([(96, w.FREEZE_NS + 1, 'sealed_failed'), (100, w.FREEZE_NS + 2, 'sealed_complete')])
        with patch.object(w, 'store_identity', return_value=store), patch.object(w, 'verify'):
            with self.assertRaisesRegex(ValueError, 'fixed_attempt_failed'):
                w.wait_selected(96, p, digest, wall=lambda: w.FREEZE_NS + 3, mono=lambda: 0)
        store.pin.assert_not_called()
        self.assertEqual(w.read(w.controls(96) / 'nomination.json')['number'], 96)
        with self.assertRaisesRegex(ValueError, 'fixed_attempt_expired'):
            w.selected_entry(index(expired=[dict(chunk_id='chunk-000096')]), 96)
        with self.assertRaisesRegex(ValueError, 'fixed_attempt_missing'):
            w.selected_entry(index(next_number=101), 96)
        with patch.object(w, 'store_identity', return_value=store):
            with self.assertRaises(TimeoutError):
                w.wait_selected(100, p, digest, wall=lambda: w.DEADLINES[100] + 1)

    def test_scope_routes_outer_loop_and_restores_every_alias(self):
        self.outputs(); p, digest = self.frozen()
        w.control(None, 'nomination.json', dict(schema=w.SCHEMA + '-nomination', plan_sha256=digest,
            fixed_chunk_numbers=list(w.NUMBERS), nominated_ns=w.FREEZE_NS - 1))
        w.control(96, 'nomination.json', dict(schema=w.SCHEMA + '-selected', plan_sha256=digest,
            chunk=w.chunk_name(96), number=96, role='reserved_validation', launched_ns=w.FREEZE_NS + 1))
        tracked = [(w.old, 'PLAN'), (w.old, 'OUT'), (w.old, 'configure'), (w.old, 'verify'),
                   (w.fix.news, 'ASSETS'), (w.fix.news.study, 'ASSETS'), (w.fix.news.study, 'NAMES'),
                   (w.fix.news.study.capture, 'SELECTED'), (w.fix, 'publish'), (w.fix, 'events'),
                   (w.fix, 'require_pins'), (w.old.cash, 'inputs'),
                   (w.old.cash, 'verify_signal'), (w.strategy, 'snapshot')]
        before = [getattr(m, k) for m, k in tracked]
        pins = dict(manifest_sha256='d' * 64, raw_sha256='e' * 64, analysis_plan_sha256=digest)
        w.control(96, 'input-pins.json', pins)
        iterator = Mock(return_value=iter([dict(type='control', received_ns=1)]))
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'BASE_SNAPSHOT', return_value=pins), \
                patch.object(w.fix.ordinary, 'iter_events', iterator):
            with self.assertRaisesRegex(RuntimeError, 'after routing'):
                with w.aliases(96, p, digest):
                    self.assertEqual(w.fix.news.ASSETS, ('LIT',))
                    self.assertEqual(w.fix.news.study.ASSETS, ('LIT',))
                    self.assertEqual(w.fix.news.study.NAMES, {'LIT': w.stem(96) + '-depth-lit'})
                    self.assertEqual(w.fix.news.study.capture.SELECTED, w.rolling.SELECTED)
                    w.fix.verify('depth')  # inherited replay reconfiguration must stay narrowed
                    self.assertEqual(w.fix.news.study.ASSETS, ('LIT',))
                    self.assertEqual(w.fix.require_pins(p, 'd' * 64), pins)
                    self.assertFalse((w.OUT / 'input-pins.json').exists())
                    self.assertEqual(list(w.fix.events(self.root / 'synthetic',
                        expected_manifest_sha256='d' * 64, max_raw_bytes=w.BOUNDS['raw_bytes']))[0]['type'], 'control')
                    self.assertEqual(iterator.call_args.kwargs['expected_raw_sha256'], 'e' * 64)
                    self.assertEqual(iterator.call_args.kwargs['max_records'], w.BOUNDS['records'])
                    with w.aliases(96, p, digest):
                        self.assertEqual(w.fix.require_pins(p)['analysis_plan_sha256'], digest)
                    self.assertEqual(w.fix.require_pins(p), pins)
                    w.old.cash.verify_signal = 'audit-local mutation'
                    w.strategy.snapshot = 'compact-local mutation'
                    raise RuntimeError('after routing')
        self.assertTrue(all(getattr(m, k) is value for (m, k), value in zip(tracked, before)))

    def test_exact_four_gate_both_chunks_and_no_cross_currency_sum(self):
        rr = rows(); g = w.gate(rr, True)
        self.assertTrue(g['passed']); self.assertEqual(g['fade_minus_follow_stressed_USDG'], '0.3')
        self.assertEqual(w.combined({96: g, 100: g})['status'], 'conditional_candidate_only')
        once = dict(g, primary_closed=1)
        self.assertEqual(w.combined({96: once, 100: once})['status'], 'does_not_advance')
        self.assertFalse(w.gate(rr, False)['passed'])
        for changes in (dict(closed=0), dict(attempts=0, closed=0), dict(closed_stressed_cash='0'),
                        dict(unknown='missing close'), dict(pending_order=True)):
            copy_rows = copy.deepcopy(rr)
            primary = next(r for r in copy_rows if (r['venue'], r['rule']) == ('rh_lighter', 'depth_fade'))
            primary.update(changes)
            self.assertFalse(w.gate(copy_rows, True)['passed'])
        core_unknown = copy.deepcopy(rr); core_unknown[0]['complete'] = False
        self.assertFalse(w.gate(core_unknown, True)['passed'])
        with self.assertRaisesRegex(ValueError, 'exact_four_row_cohort'): w.gate(rr[:-1], True)
        with self.assertRaisesRegex(ValueError, 'exact_four_row_cohort'): w.gate(rr[:3] + rr[:1], True)

    def fixture_report(self, n, digest):
        directory = w.ledger(n); directory.mkdir()
        (directory / 'trace.jsonl.gz').write_bytes(gzip.compress(b'fixture\n', mtime=0))
        arms = {}
        for r in rows():
            net = '0.3' if r['venue'] == 'rh_lighter' and r['rule'] == 'depth_fade' else '0'
            episodes = [dict(cash_after_capital=net, stressed_net=r['closed_stressed_cash'])] if r['closed'] else []
            arms[r['rule'] + ':' + r['venue']] = dict(attempts=r['attempts'], closed=r['closed'], episodes=episodes,
                cash=str(600 + w.D(net)), complete=True, unknown=None, position=None, pending=None, counts={})
        summary = dict(error=None, complete_capture_verified=True, asset='LIT', sample=w.stem(n) + '-depth-lit',
            source='fixture/capture', manifest_sha256='d' * 64, plan_sha256=digest,
            trace_sha256=w.fix.sha(directory / 'trace.jsonl.gz'), arms=arms)
        (directory / 'summary.json.gz').write_bytes(gzip.compress(w.fix.encode(summary), mtime=0))
        audit = dict(status='passed', sample=summary['sample'], raw_capture_verified=True,
            summary_sha256=w.fix.sha(directory / 'summary.json.gz'), trace_sha256=summary['trace_sha256'])
        (directory / 'independent-audit.json').write_bytes(w.fix.encode(audit))
        return directory

    def test_reporter_exact_four_binding_and_refuses_bad_audit(self):
        p, digest = self.frozen(); directory = self.fixture_report(96, digest)
        pins = dict(source='fixture/capture', manifest_sha256='d' * 64, raw_sha256='e' * 64)
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'aliases', return_value=contextlib.nullcontext()), \
                patch.object(w.fix, 'require_pins', return_value=pins):
            result = w.report(96, digest)
        self.assertEqual(len(result['rows']), 4); self.assertTrue(result['gate']['passed'])
        self.assertEqual([r['collateral'] for r in result['rows']].count('USDG'), 2)
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'aliases', return_value=contextlib.nullcontext()), \
                patch.object(w.fix, 'require_pins', return_value=pins), self.assertRaisesRegex(ValueError, 'output_exists'):
            w.report(96, digest)
        other = self.fixture_report(100, digest)
        audit = w.read(other / 'independent-audit.json'); audit['trace_sha256'] = '0' * 64
        (other / 'independent-audit.json').write_bytes(w.fix.encode(audit))
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'aliases', return_value=contextlib.nullcontext()), \
                patch.object(w.fix, 'require_pins', return_value=pins), self.assertRaisesRegex(ValueError, 'audit_output_binding'):
            w.report(100, digest)
        self.assertFalse((w.fix.RESEARCH / (w.stem(100) + '-comparison.csv')).exists())

    def test_three_command_barrier_failed_first_preserved_second_runs(self):
        self.outputs(); p, digest = self.frozen()
        w.control(None, 'launch-claim.json', dict(plan_sha256=digest, launched_ns=w.FREEZE_NS - 1))
        calls = []
        def wait(n, *args):
            if n == 96: raise ValueError('known failed reservation')
        result = dict(plan_sha256=digest, number=100, gate=w.gate(rows(), True))
        snap = dict(manifest_sha256='d' * 64, source='fixture/capture')
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'wait_selected', side_effect=wait), \
                patch.object(w, 'aliases', return_value=contextlib.nullcontext()), \
                patch.object(w, 'BASE_SNAPSHOT', return_value=snap), patch.object(w.fix, 'require_pins'), \
                patch.object(w, 'packed', return_value=result), patch.object(w, 'command', side_effect=lambda args, d: calls.append(args)), \
                patch.object(w, 'alarm', return_value=contextlib.nullcontext()):
            total = w.supervise(digest)
        self.assertEqual([c[1] for c in calls], ['replay', 'audit', 'report'])
        self.assertTrue(all(c[c.index('--number') + 1] == '100' for c in calls))
        self.assertEqual(total['status'], 'does_not_advance')
        unavailable = w.read(w.controls(96) / 'unavailable.json')
        self.assertEqual((len(unavailable['rows']), unavailable['audit_denominator']), (4, 1))
        self.assertTrue(all(r['closed_stressed_cash'] is None for r in unavailable['rows']))
        self.assertEqual(w.read(w.controls(100) / 'terminal.json')['commands_completed'], 3)

    def test_storage_pending_caps_existing_and_unknown_interrupted_dispatch(self):
        self.outputs(); p, digest = self.frozen()
        w.control(None, 'launch-claim.json', dict(plan_sha256=digest, launched_ns=w.FREEZE_NS - 1))
        w.control(96, 'a.json', dict(value=1))
        with self.assertRaisesRegex(ValueError, 'output_exists'): w.control(96, 'a.json', dict(value=2))
        (w.controls(96) / 'evidence.pending').write_bytes(b'x' * 24576)
        with self.assertRaisesRegex(ValueError, 'category_peak_cap'): w.control(96, 'more.json', {})
        (w.controls(96) / 'evidence.pending').unlink()
        with patch.object(w, 'verify', return_value=p), patch.object(w, 'wait_selected', side_effect=KeyboardInterrupt()), \
                patch.object(w, 'alarm', return_value=contextlib.nullcontext()):
            w.supervise(digest)
        later = w.read(w.controls(100) / 'terminal.json')
        self.assertEqual(w.read(w.controls(96) / 'terminal.json')['status'], 'unavailable')
        self.assertIsNone(later['commands_completed']); self.assertIsNone(later['economic_evaluation'])
        self.assertTrue(later['dispatch_unavailable'])
        with patch.object(w, 'verify', return_value=p), patch.object(w.subprocess, 'Popen') as popen, \
                self.assertRaisesRegex(ValueError, 'existing_output'):
            w.launch(digest)
        popen.assert_not_called()
        # Shared runtime and outside reviews divide the same32768B grant.
        self.assertEqual(w.CONTROL_SHARES['shared_runtime'] + w.CONTROL_SHARES['outside_allocation_reviews'], 32768)
        shared_used = w.unique_bytes(w.OUT, recursive=False)
        with self.assertRaisesRegex(ValueError, 'category_peak_cap'):
            w.control(None, 'over-shared.json', dict(value='x' * (8192 - shared_used)))

    def test_child_timeout_cleanup_and_no_callback_network(self):
        child = Mock(); child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 1), -9]
        child.poll.return_value = None
        with patch.object(w.subprocess, 'Popen', return_value=child) as spawn, patch.object(w.os, 'killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                w.command(w.commands(96, 'a' * 64, 'b' * 64)[0], w.time.monotonic() + 1)
        argv = spawn.call_args.args[0]
        self.assertEqual(argv[:2], ['nice', '-n']); self.assertIn('-B', argv)
        self.assertTrue(spawn.call_args.kwargs['start_new_session']); kill.assert_called_once()
        self.assertEqual(child.wait.call_args.kwargs['timeout'], 5)


if __name__ == '__main__': unittest.main()
