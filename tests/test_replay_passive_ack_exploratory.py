"""Synthetic publication/provenance checks; no stopped market replay is run."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import replay_passive_ack_exploratory as wrapper
from scripts import analyze_rh_passive_exit as original
from scripts import rh_passive_exit_engine as engine
from tests.test_analyze_passive_correction_comparison import fixture
from tests.test_rh_maker_late_flow_guard import META


class ExploratoryAckWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.strict, self.corrected, protocol, self.freeze = fixture(self.root)
        self.capture = Path(self.strict['capture'])
        protocol_dir = self.root / 'protocol'
        protocol_dir.mkdir()
        self.protocol = protocol_dir / 'protocol.json'
        protocol.rename(self.protocol)
        self.strict_path = self.root / 'strict/analysis.json'
        self.corrected_path = self.root / 'corrected/analysis.json'
        self.strict_path.parent.mkdir()
        self.corrected_path.parent.mkdir()
        self.strict_path.write_text(json.dumps(self.strict))
        self.corrected_path.write_text(json.dumps(self.corrected))
        self.out = self.root / 'exploratory'
        self.addCleanup(setattr, engine, 'PassiveExitBranch', wrapper.ORIGINAL_CLASS)

    def fake_coordinator(self, capture, out, protocol):
        """Exercise the actual ACK factory for all 128 configs, not raw events."""
        self.assertIsNot(engine.PassiveExitBranch, wrapper.ORIGINAL_CLASS)
        result = deepcopy(self.strict)
        branches = []
        for source in self.strict['branches']:
            config = original.Config(source['asset'], int(source['budget_usd']), 'fixed_best',
                                     tier=source['tier'], hold_ns=(60 if source['exit_policy'].endswith('60s') else 10) * original.NS)
            branch = engine.PassiveExitBranch(config, META, exit_policy=source['exit_policy'])
            self.assertIsInstance(branch, wrapper.ack.AssumedAckPassiveExitBranch)
            summary = branch.summary()
            summary.update(first_unknown_ns=None, first_quote_requested_ns=None,
                           effective_quote_opportunity_seconds_before_unknown=0, group_book_quote_checks=0)
            branches.append(summary)
        result.update(branches=branches, cohorts=[], counts={})
        result['cohort_score'] = original.score_cohorts([], branches, {})
        out.mkdir()
        (out / 'analysis.json').write_text(json.dumps(result))
        (out / 'REPORT.md').write_text('temporary original-format result')
        return result

    def run_wrapper(self, selection='base', **kwargs):
        return wrapper.replay_exploratory(self.capture, self.out, self.protocol, selection=selection,
                                         strict_path=self.strict_path, corrected_path=self.corrected_path, **kwargs)

    def test_dry_default_never_reads_capture_or_runs_coordinator(self):
        stdout = StringIO()
        with patch.object(wrapper, 'verify_inputs') as verify, patch.object(original, 'replay') as replay, redirect_stdout(stdout):
            self.assertEqual(wrapper.main([]), 0)
        verify.assert_not_called()
        replay.assert_not_called()
        plan = json.loads(stdout.getvalue())
        self.assertTrue(plan['dry_plan'])
        self.assertFalse(plan['capture_read'])
        self.assertEqual([s['selection'] for s in plan['scenarios']], ['base', 'plus200'])
        self.assertEqual(len(plan['actual_dependencies_to_hash']), 21)

    def test_scenario_delays_add_to_already_normalized_tier_configs(self):
        base, longer = wrapper.scenario_plan('base'), wrapper.scenario_plan('plus200')
        self.assertEqual(base['effective_delays_by_tier']['standard']['maker_latency_ns'], 300_000_000)
        self.assertEqual(base['effective_delays_by_tier']['premium']['maker_latency_ns'], 100_000_000)
        self.assertEqual(longer['effective_delays_by_tier']['standard']['maker_latency_ns'], 500_000_000)
        self.assertEqual(longer['effective_delays_by_tier']['premium']['maker_latency_ns'], 300_000_000)
        for tier in original.TIERS:
            self.assertEqual(base['effective_delays_by_tier'][tier]['inherited_hl_ioc_latency_ns'],
                             longer['effective_delays_by_tier'][tier]['inherited_hl_ioc_latency_ns'])

    def test_staged_result_publishes_actual_128_factory_labels_and_postcapture_provenance(self):
        for selection in ('base', 'plus200'):
            with self.subTest(selection=selection):
                self.out = self.root / f'exploratory-{selection}'
                before_strict = self.strict_path.read_bytes()
                before_corrected = self.corrected_path.read_bytes()
                with patch.object(original, 'replay', side_effect=self.fake_coordinator):
                    result = self.run_wrapper(selection)
                self.assertIs(engine.PassiveExitBranch, wrapper.ORIGINAL_CLASS)
                self.assertEqual(result['schema'], wrapper.SCHEMA)
                self.assertEqual(result['study_classification'], 'EXPLORATORY POST-CAPTURE MODEL')
                self.assertFalse(result['prospective_result'])
                self.assertFalse(result['pre_holdout_freeze_claimed'])
                self.assertEqual(len(result['actual_dependency_sha256_before']), 21)
                self.assertEqual(result['actual_dependency_sha256_before'], result['actual_dependency_sha256_after'])
                self.assertEqual(result['ack_scenario']['selection'], selection)
                self.assertEqual(len(result['branches']), 128)
                self.assertTrue(all(b['execution_assumed'] and not b['actual_fills_observed'] for b in result['branches']))
                self.assertTrue(result['native_trade_ids_stable_across_generations_assumed'])
                self.assertEqual(result['original_coordinator_assumptions'], self.strict['assumptions'])
                self.assertIn('deterministic assumed private ACK', result['assumptions']['timing'])
                self.assertIsNone(result['causal_profit_improvement'])
                self.assertIsNone(result['summed_branch_portfolio_net'])
                self.assertEqual(self.strict_path.read_bytes(), before_strict)
                self.assertEqual(self.corrected_path.read_bytes(), before_corrected)
                self.assertFalse(list(self.root.glob('.ack-exploratory-*')))
                disk = json.loads((self.out / 'analysis.json').read_text())
                self.assertEqual(disk['schema'], wrapper.SCHEMA)
                report = (self.out / 'REPORT.md').read_text()
                self.assertTrue(report.startswith('# EXPLORATORY POST-CAPTURE ACK model replay'))
                self.assertIn('outer historical execution guards', report)
                self.assertNotIn('temporary original-format', report)

    def test_factory_binding_restores_on_replay_exception_and_refuses_nested_binding(self):
        with patch.object(original, 'replay', side_effect=RuntimeError('synthetic coordinator failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic coordinator failure'):
                self.run_wrapper()
        self.assertIs(engine.PassiveExitBranch, wrapper.ORIGINAL_CLASS)
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.ack-exploratory-*')))
        with wrapper.scenario_branch_binding('base'):
            with self.assertRaisesRegex(RuntimeError, 'already overridden'):
                with wrapper.scenario_branch_binding('plus200'):
                    pass
        self.assertIs(engine.PassiveExitBranch, wrapper.ORIGINAL_CLASS)

    def test_sources_or_reference_hashes_changed_during_replay_refuse_publication(self):
        protocol = original._bounded_json(self.protocol)
        before = wrapper.source_snapshot(protocol)
        after = dict(before, **{'scripts/replay_passive_ack_exploratory.py': 'f' * 64})
        with patch.object(wrapper, 'source_snapshot', side_effect=[before, after]), \
             patch.object(original, 'replay', side_effect=self.fake_coordinator):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.run_wrapper()
        self.assertFalse(self.out.exists())
        def change_reference(*args):
            result = self.fake_coordinator(*args)
            reference = json.loads(self.strict_path.read_text())
            reference['counts']['synthetic_added_counter'] = 1
            self.strict_path.write_text(json.dumps(reference))
            return result
        with patch.object(original, 'replay', side_effect=change_reference):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.run_wrapper()
        self.assertFalse(self.out.exists())

    def test_bad_raw_reference_provenance_or_incomplete_readout_fails_before_replay(self):
        for key, value in (('status', 'capture_incomplete'), ('raw_sha256', 'f' * 64),
                           ('source_sha256', {}), ('metadata_normalized_sha256', 'f' * 64)):
            with self.subTest(key=key):
                reference = deepcopy(self.corrected)
                reference[key] = value
                self.corrected_path.write_text(json.dumps(reference))
                with patch.object(original, 'replay') as replay:
                    with self.assertRaises(ValueError):
                        self.run_wrapper()
                    replay.assert_not_called()
                self.assertFalse(self.out.exists())
        self.corrected_path.write_text(json.dumps(self.corrected))
        path = self.capture / 'frames.jsonl.gz'
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'actual stopped capture raw'):
            self.run_wrapper()

    def test_injected_events_or_injected_result_terminal_mismatch_cannot_publish(self):
        with patch.object(wrapper, 'verify_inputs') as verify:
            with self.assertRaisesRegex(ValueError, 'injected events cannot publish'):
                self.run_wrapper(events=[])
            verify.assert_not_called()
        for mode in ('injected', 'terminal', 'wrong_scenario'):
            with self.subTest(mode=mode):
                def bad_result(*args):
                    result = self.fake_coordinator(*args)
                    if mode == 'injected':
                        result['event_source'] = 'injected_test_events'
                    elif mode == 'terminal':
                        result['terminal_event']['raw_gzip_sha256'] = 'f' * 64
                    else:
                        result['branches'][0]['scenario_id'] = 'wrong'
                    return result
                with patch.object(original, 'replay', side_effect=bad_result):
                    with self.assertRaises(ValueError):
                        self.run_wrapper()
                self.assertFalse(self.out.exists())
                self.assertIs(engine.PassiveExitBranch, wrapper.ORIGINAL_CLASS)

    def test_output_overlap_existing_target_and_dangling_symlink_are_refused(self):
        for out in (self.capture / 'nested', self.protocol.parent / 'nested',
                    self.strict_path.parent / 'nested', self.corrected_path.parent / 'nested'):
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                wrapper._check_output(out, self.capture, self.protocol, self.strict_path, self.corrected_path)
        self.out.symlink_to(self.root / 'absent-target')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.run_wrapper()
        self.assertTrue(self.out.is_symlink())
        self.out.unlink()
        self.out.mkdir()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.run_wrapper()

    def test_report_and_source_caps_refuse_before_publishing(self):
        with patch.object(wrapper, 'MAX_REPORT_BYTES', 1), patch.object(original, 'replay', side_effect=self.fake_coordinator):
            with self.assertRaisesRegex(ValueError, 'report byte cap'):
                self.run_wrapper()
        self.assertFalse(self.out.exists())
        with patch.object(wrapper, 'MAX_SOURCE_BYTES', 1), patch.object(original, 'replay') as replay:
            with self.assertRaisesRegex(ValueError, 'source read cap'):
                self.run_wrapper()
            replay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
