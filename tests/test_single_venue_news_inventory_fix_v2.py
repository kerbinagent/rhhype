"""Synthetic inventory, binding, and failure controls; no captured raw reads."""
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import single_venue_news_inventory_fix_v2 as w


def successor(old):
    plan = copy.deepcopy(old)
    plan.update(schema='single-venue-news-inventory-fix-v2', status='frozen',
                previous_analysis_plan=w.OLD_PLAN_PIN, preparation=w.PREPARATION,
                failed_analysis_terminal=w.FAILED_TERMINAL, capture_status=w.CAPTURE_STATUS,
                control_root=w.CONTROL_ROOT, output_stem=w.OUTPUT_STEM,
                output_caps={**old['output_caps'], 'controls': w.CONTROL_CAP},
                source_pins=old['source_pins'] + [dict(path=x, sha256='synthetic') for x in (w.SOURCE, w.TEST)])
    return plan


class InventoryFixTests(unittest.TestCase):
    def test_default_dry_has_no_reads_or_commands(self):
        with patch.object(w.fix, 'read', side_effect=AssertionError('read')) as read, \
             patch.object(w.subprocess, 'Popen', side_effect=AssertionError('command')) as popen:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(w.main([]), 0)
            self.assertEqual(json.loads(output.getvalue())['commands'], 0)
            read.assert_not_called(); popen.assert_not_called()

    def test_successor_scope_pins_and_runtime_configuration(self):
        old = w.fix.read(w.OLD_PLAN, 16384)
        plan = successor(old)
        fake = {'state': 'finished', 'success': False, 'economic_evaluation': False,
                'error': 'AssertionError: capture_inventory_changed'}
        with patch.object(w, '_pinned', return_value=Path(__file__)), \
             patch.object(w, '_old_contract', return_value=old), \
             patch.object(w.fix, 'read', side_effect=lambda path, cap=0: fake if path == w.ROOT/w.FAILED_TERMINAL['path'] else plan), \
             patch.object(w.fix, 'configure') as configured, \
             patch.object(Path, 'stat') as stat:
            stat.return_value.st_size = 1000
            with patch.object(Path, 'is_symlink', return_value=False):
                prior_plan = w.fix.PLAN; w.fix.PLAN = w.PLAN
                try:
                    self.assertIs(w.verify('depth'), plan)
                    configured.assert_called_once_with(plan, 'depth')
                    baseline = copy.deepcopy(plan)
                    for change in (lambda p: p.update(status='draft'),
                                   lambda p: p.update(control_root='old'),
                                   lambda p: p['execution_parameters'].update(fee=99),
                                   lambda p: p['source_pins'].pop(),
                                   lambda p: p['output_caps'].update(controls=65536)):
                        plan.clear(); plan.update(copy.deepcopy(baseline)); change(plan)
                        with self.assertRaises(AssertionError): w.verify()
                    plan.clear(); plan.update(baseline)
                finally: w.fix.PLAN = prior_plan

    def test_final_status_required_and_complete_inventory_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); out = root/'reports/single-venue-news'; cap = out/'capture'
            md = cap/'metadata'; md.mkdir(parents=True)
            original = root/'original.json'; original.write_text('{}')
            analysis = root/'analysis.json'; analysis.write_text('{}')
            for name in w.fix.news.study.capture.REQUESTS:
                for suffix in ('.json.gz', '.request.json'):
                    (md/(name+suffix)).write_bytes(b'{}')
            for name in ('market_plan.json', 'normalized.json'): (md/name).write_text('{}')
            raw = cap/'frames.jsonl.gz'; raw.write_bytes(gzip.compress(b'synthetic'))
            started = '2026-10-02T12:26:00+00:00'; ended = '2026-10-02T12:36:01+00:00'
            manifest = dict(market_plan_sha256=w.fix.CAPTURE_PLAN_SHA, end_reason='duration_limit',
                truncated=False, started_utc=started, ended_utc=ended,
                selected_markets=w.fix.news.SELECTED, frames_sha256=w.fix.sha(raw),
                compressed_payload_bytes=100, payload_records=20)
            (cap/'manifest.json').write_text(json.dumps(manifest))
            digest = w.fix.sha(cap/'manifest.json')
            terminal = dict(status='capture_completed', plan_sha256=w.fix.CAPTURE_PLAN_SHA,
                            end_reason='duration_limit', manifest_sha256=digest)
            (cap/'terminal.json').write_text(json.dumps(terminal))
            supervisor = dict(state='finished', normal_endpoint=True, event_coverage_valid=True,
                              plan_sha256=w.fix.CAPTURE_PLAN_SHA, terminal=terminal)
            (out/'terminal.json').write_text(json.dumps(supervisor))
            status = dict(compressed_bytes=90, records=19, elapsed_seconds=599,
                          economic_evaluation=False, errors=[])
            (cap/'status.json').write_text(json.dumps(status))
            plan = {'capture_root': str(cap.relative_to(root))}
            with patch.object(w, 'ROOT', root), patch.object(w, 'PLAN', analysis), \
                 patch.object(w.fix.news, 'OUT', out), patch.object(w.fix.news, 'PLAN', original), \
                 patch.object(w.fix.news, 'coverage', return_value=True), \
                 patch.object(w.fix.ordinary, '_metadata', return_value=({'market_plan_sha256':w.fix.CAPTURE_PLAN_SHA}, {})), \
                 patch.object(w, '_pinned', return_value=cap/'status.json'):
                pins = w.input_snapshot(plan)
                self.assertEqual(len(pins['files']), 17)
                self.assertIn(str((cap/'status.json').relative_to(root)), pins['files'])
                (cap/'status.json').unlink()
                with self.assertRaises(FileNotFoundError): w.input_snapshot(plan)
                (cap/'status.json').write_text(json.dumps(status))
                (cap/'extra.json').write_text('{}')
                with self.assertRaisesRegex(AssertionError, 'capture_inventory_changed'): w.input_snapshot(plan)
                (cap/'extra.json').unlink()
                status['records'] = 21; (cap/'status.json').write_text(json.dumps(status))
                with self.assertRaisesRegex(AssertionError, 'capture_status_not_prior_heartbeat'): w.input_snapshot(plan)

    def test_original_24_commands_and_child_binding(self):
        with patch.object(w.fix, 'sha', return_value='p'*64):
            sequence = list(w.commands('m'))
        self.assertEqual(len(sequence), 24)
        self.assertEqual([row[1] for row in sequence].count('replay'), 2)
        self.assertEqual([row[1] for row in sequence].count('audit'), 20)
        self.assertEqual([row[1] for row in sequence].count('readout'), 2)
        self.assertEqual([row[3] for row in sequence if row[1] == 'audit'][:10], list(w.fix.news.ASSETS))
        self.assertTrue(all(row[0] == w.SOURCE for row in sequence))
        saved = (w.fix.PLAN, w.fix.verify, w.fix.input_snapshot, w.fix.commands, w.fix.CAPS)
        try:
            w.install()
            self.assertIs(w.fix.verify, w.verify)
            self.assertIs(w.fix.input_snapshot, w.input_snapshot)
            self.assertIs(w.fix.commands, w.commands)
            self.assertEqual(w.fix.CAPS['controls'], 49152)
        finally:
            w.fix.PLAN, w.fix.verify, w.fix.input_snapshot, w.fix.commands, w.fix.CAPS = saved

    def test_launch_claim_failure_receipt_and_no_reclaim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fake_plan = dict(control_root=w.CONTROL_ROOT)
            with patch.object(w, 'ROOT', root), patch.object(w.fix, 'ROOT', root), patch.object(w, 'PLAN', root/'plan.json'), \
                 patch.object(w, 'verify', return_value=fake_plan), \
                 patch.object(w.fix, 'sha', return_value='a'*64), \
                 patch.object(w.subprocess, 'Popen', side_effect=OSError('synthetic_spawn')):
                with self.assertRaises(OSError): w.launch('a'*64)
                out = root/w.CONTROL_ROOT
                self.assertTrue((out/'launch-claim.json').exists())
                failure = json.loads((out/'wrapper-terminal.json').read_bytes())
                self.assertEqual(failure['status'], 'launch_failed')
                self.assertFalse(failure['economic_evaluation'])
                with self.assertRaises(FileExistsError): w.launch('a'*64)

    def test_post_evaluation_failure_records_observed_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); out = root/w.CONTROL_ROOT; out.mkdir(parents=True)
            def failure():
                (out/'analysis-terminal.json').write_text(json.dumps(dict(
                    state='finished', success=False, economic_evaluation=True,
                    completed_commands=3, error='synthetic_audit_failure')))
                raise SystemExit(1)
            with patch.object(w, 'ROOT', root), patch.object(w.fix, 'ROOT', root), \
                 patch.object(w, 'PLAN', root/'plan.json'), \
                 patch.object(w.fix, 'sha', return_value='a'*64), \
                 patch.object(w, 'verify', return_value={}), \
                 patch.object(w.fix, 'supervise', side_effect=failure):
                with self.assertRaises(SystemExit): w.supervise('a'*64)
            receipt = json.loads((out/'wrapper-terminal.json').read_bytes())
            self.assertEqual(receipt['status'], 'failed')
            self.assertTrue(receipt['economic_evaluation'])
            self.assertIn('SystemExit', receipt['error'])

    def test_post_spawn_process_receipt_failure_stage_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = dict(control_root=w.CONTROL_ROOT)
            real_control = w.fix.control
            def control(plan, name, value, **kwargs):
                if name == 'analysis-process.json': raise OSError('synthetic_receipt_failure')
                return real_control(plan, name, value, **kwargs)
            class Child:
                pid = 123
                def wait(self): return 1
            child = Child()
            with patch.object(w, 'ROOT', root), patch.object(w.fix, 'ROOT', root), \
                 patch.object(w, 'PLAN', root/'plan.json'), \
                 patch.object(w, 'verify', return_value=plan), \
                 patch.object(w.fix, 'sha', return_value='a'*64), \
                 patch.object(w.fix, 'control', side_effect=control), \
                 patch.object(w.os, 'killpg') as kill_group, \
                 patch.object(w.subprocess, 'Popen', return_value=child) as spawned:
                with self.assertRaises(OSError): w.launch('a'*64)
            receipt = json.loads((root/w.CONTROL_ROOT/'wrapper-terminal.json').read_bytes())
            self.assertEqual(receipt['status'], 'process_receipt_failed')
            self.assertIsNone(receipt['economic_evaluation'])
            kill_group.assert_called_once_with(123, w.signal.SIGKILL)
            self.assertEqual(spawned.call_args.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertEqual(spawned.call_args.args[0][1], '-B')


if __name__ == '__main__': unittest.main()
