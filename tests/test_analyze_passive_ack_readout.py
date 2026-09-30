"""Generated completed artifact contracts; no active scenario outcomes are read."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_passive_ack_readout as readout
from scripts import analyze_rh_passive_exit as original
from scripts import replay_passive_ack_exploratory as wrapper
from tests.test_analyze_passive_correction_comparison import fixture, cohort, episode, score, DECISION, NS, GROUP


def ack_fixture(strict, corrected, selection, protocol, paths):
    result = deepcopy(strict)
    plan = wrapper.scenario_plan(selection)
    sources = wrapper.source_snapshot(protocol)
    for branch in result['branches']:
        labels = {'scenario_id': plan['scenario_id'], 'execution_assumed': True,
                  'private_ack_observed': False, 'native_trade_ids_stable_across_generations_assumed': True,
                  'assumed_maker_latency_ns': plan['effective_delays_by_tier'][branch['tier']]['maker_latency_ns'],
                  'assumed_cancel_latency_ns': plan['effective_delays_by_tier'][branch['tier']]['cancel_latency_ns']}
        branch.update(**labels, schema='rh-passive-assumed-ack-scenario-v1', actual_fills_observed=False,
                      guaranteed_profit_bound=False)
        for ep in branch['episodes']:
            ep.update(labels)
    stopped = {field: strict[field] for field in ('protocol_sha256', 'capture_manifest_sha256', 'raw_sha256',
                'metadata_normalized_sha256', 'started_ns', 'cutoff_ns', 'ended_ns', 'entry_admission_end_ns', 'intended_end_ns')}
    stopped['readout_references'] = {**{f'{name}_analysis': str(paths[name]) for name in ('strict', 'corrected')},
        **{f'{name}_analysis_sha256': original.digest(paths[name]) for name in ('strict', 'corrected')}}
    result.update(schema=wrapper.SCHEMA, original_result_schema=original.RESULT_SCHEMA,
                  implementation_variant=wrapper.VARIANT, study_classification=wrapper.CLASSIFICATION,
                  original_frozen_v1_result=False, retirement_corrected_v1_result=False,
                  prospective_result=False, pre_holdout_freeze_claimed=False,
                  execution_assumed=True, private_ack_observed=False, actual_fills_observed=False,
                  guaranteed_profit_bound=False, native_trade_ids_stable_across_generations_assumed=True,
                  source_snapshots_are_not_prospective_freezes=True,
                  ack_scenario=plan, active_ack_execution_assumptions=plan,
                  runtime_factory_override={**wrapper.RUNTIME_FACTORY, 'scenario_selection': selection, 'scenario_id': plan['scenario_id']},
                  original_coordinator_assumptions=strict['assumptions'],
                  assumptions={**strict['assumptions'], 'timing': 'deterministic assumed private ACK clocks; previous received raw anchor; public trade receipt notification model'},
                  source_sha256_extra={name: sources[name] for name in wrapper.EXTRA_SOURCES},
                  actual_dependency_sha256_before=sources, actual_dependency_sha256_after=sources,
                  stopped_capture_provenance=stopped, exploratory_disclosure=wrapper.DISCLOSURE,
                  combined_model_changes=['deterministic maker/cancel ACK clocks', 'ordered obligation coverage checks',
                        'preceding raw-book anchor and late revision checks',
                        'native trade-ID stability, dedupe, cap and conflict evidence',
                        'outer historical execution evidence checks after earlier halt'])
    return result


class AckReadoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        strict, corrected, protocol_path, self.freeze = fixture(self.root, later_admission=False)
        directory = self.root / 'protocol'
        directory.mkdir()
        self.protocol = directory / 'protocol.json'
        protocol_path.rename(self.protocol)
        self.paths = {name: self.root / name / 'analysis.json' for name in readout.RUNS}
        for path in self.paths.values():
            path.parent.mkdir()
        self.results = {'strict': strict, 'corrected': corrected}
        for name in ('strict', 'corrected'):
            self.paths[name].write_text(json.dumps(self.results[name]))
        protocol = original._bounded_json(self.protocol)
        for name in ('base', 'plus200'):
            self.results[name] = ack_fixture(strict, corrected, name, protocol, self.paths)
        self.write_scenarios()
        self.out = self.root / 'readout'

    def write_scenarios(self):
        for name in ('base', 'plus200'):
            self.paths[name].write_text(json.dumps(self.results[name]))

    def selected(self, result, name=None):
        if name:
            return next(b for b in result[name]['branches'] if readout.comparison._key(b) == (*GROUP, 'control10s'))
        return next(b for b in result['branches'] if readout.comparison._key(b) == (*GROUP, 'control10s'))

    def run_analysis(self):
        return readout.analyze(self.paths, self.protocol, self.freeze, self.out)

    def test_completed_exact_provenance_publishes_all_branches_six_alignments_and_helper_hashes(self):
        result = self.run_analysis()
        self.assertEqual((result['branch_count'], result['alignment_rows']), (128, 768))
        self.assertEqual(len(result['actual_ack_dependency_sha256']), 21)
        self.assertTrue(set(readout.HELPER_ARTIFACTS).issubset(result['helper_artifact_sha256']))
        state = self.selected(result)['runs']['base']
        self.assertEqual(state['net_semantics'], 'conditional_known_assumed_execution_model')
        self.assertEqual(state['conditional_known_complete_portfolio_net_usd'], '0')
        self.assertIsNone(result['causal_profit_improvement'])
        self.assertIsNone(result['combined_branch_portfolio_net'])
        self.assertTrue((self.out / 'REPORT.md').exists())

    def test_unknown_stays_unknown_and_attrition_target_cap_counters_remain_visible(self):
        branch = self.selected(self.results, 'base')
        branch.update(unknown_reason='assumed_ack_coverage_gap_open_obligation',
                      first_unknown_ns=DECISION + 4 * NS, complete_net=None,
                      counts={'passive_target_abstain': 7, 'assumed_ack_timer_cap': 2, 'unknown': 1})
        branch['episodes'][0]['execution_unknown'] = True
        score(self.results['base'])
        result = readout.compare_readouts(self.results)
        state = self.selected(result)['runs']['base']
        self.assertIsNone(state['conditional_known_complete_portfolio_net_usd'])
        self.assertEqual(state['known_closed_episodes'], 0)
        self.assertEqual(state['first_halt_reason_family'], 'coverage_generation_clock')
        self.assertEqual(state['attrition_counters']['passive_target_abstain'], 7)
        self.assertEqual(state['attrition_counters']['assumed_ack_timer_cap'], 2)

    def test_common_entries_unmatched_admissions_and_unallocatable_exposure_are_distinct(self):
        for name in ('base', 'plus200'):
            branch = self.selected(self.results, name)
            branch['episodes'][0].update(entry_quote_price='100', entry_maker_qty='1', entry_rh_notional='100',
                entry_hl_qty='1', entry_hl_notional='100', entry_rh_fee='0', entry_hl_fee='0',
                first_full_hedge_ns=DECISION + NS, maker_attributed='1')
            score(self.results[name])
        later = cohort(DECISION + 20 * NS)
        self.results['plus200']['cohorts'].append(later)
        for branch in self.results['plus200']['branches']:
            if readout.comparison._key(branch)[:3] == GROUP and later['admitted'][branch['exit_policy']]:
                ep = episode(later['cohort_id'], 2)
                labels = {field: branch[field] for field in ('scenario_id', 'execution_assumed', 'private_ack_observed',
                    'native_trade_ids_stable_across_generations_assumed', 'assumed_maker_latency_ns', 'assumed_cancel_latency_ns')}
                ep.update(labels, decided_ns=DECISION + 20 * NS, flat_ns=DECISION + 30 * NS)
                branch['episodes'].append(ep)
                branch['delta_exposure_base_seconds'] = '3'
        score(self.results['plus200'])
        result = readout.compare_readouts(self.results)
        aligned = next(a for a in result['pairwise_alignments'] if readout.comparison._key(a) == (*GROUP, 'control10s')
                       and (a['left'], a['right']) == ('base', 'plus200'))
        self.assertEqual(len(aligned['common_admitted_cohort_ids']), 1)
        self.assertEqual(len(aligned['common_full_entry_match_cohort_ids']), 1)
        self.assertEqual(len(aligned['right_only_admissions']), 1)
        self.assertIsNone(aligned['unmatched_inventory_exposure'])
        self.assertFalse(aligned['exposure_allocation_available'])
        self.assertEqual(self.selected(result)['runs']['plus200']['delta_exposure_base_seconds'], '3')

    def test_frozen_historical_withholding_does_not_label_intact_ack_execution_validated(self):
        for name in readout.RUNS:
            branch = self.selected(self.results, name)
            branch.update(retired_passive_quote_guard_count=1, unknown_reason='unrelated_depth_loss',
                          first_unknown_ns=DECISION + 30 * NS, complete_net=None)
            score(self.results[name])
        result = readout.compare_readouts(self.results)
        row = self.selected(result)
        self.assertIsNone(row['runs']['strict']['validated_known_closed_after_reserve_capital_contribution_usd'])
        self.assertEqual(row['runs']['base']['retirement_guard_status'], 'outer_historical_guard_active_under_ACK_model')
        self.assertEqual(row['runs']['base']['conditional_known_closed_after_reserve_capital_contribution_usd'], '0')
        self.assertNotIn('validated_known_closed_after_reserve_capital_contribution_usd', row['runs']['base'])
        self.selected(self.results, 'base')['audit_truncated'] = True
        result = readout.compare_readouts(self.results)
        self.assertIsNone(self.selected(result)['runs']['base']['conditional_known_closed_after_reserve_capital_contribution_usd'])

    def test_schema_scenario_assumption_and_actual_source_mutations_reject(self):
        for field, value in (('schema', original.RESULT_SCHEMA), ('ack_scenario', wrapper.scenario_plan('plus200')),
                             ('native_trade_ids_stable_across_generations_assumed', False),
                             ('private_ack_observed', 0),
                             ('actual_dependency_sha256_after', {}), ('combined_model_changes', [])):
            with self.subTest(field=field):
                saved = deepcopy(self.results['base'])
                self.results['base'][field] = value
                self.write_scenarios()
                with self.assertRaises(ValueError):
                    self.run_analysis()
                self.results['base'] = saved
        self.assertFalse(self.out.exists())

    def test_missing_incomplete_injected_inputs_and_unknown_zero_claim_fail_closed(self):
        self.paths['plus200'].unlink()
        with patch.object(readout.comparison, '_validate_provenance') as verifier:
            with self.assertRaises(FileNotFoundError):
                self.run_analysis()
            verifier.assert_not_called()
        for field, value in (('status', 'replay_error'), ('event_source', 'injected_test_events')):
            saved = deepcopy(self.results['plus200'])
            self.results['plus200'][field] = value
            self.write_scenarios()
            with self.assertRaises(ValueError):
                self.run_analysis()
            self.results['plus200'] = saved
        branch = self.selected(self.results, 'base')
        branch['unknown_reason'] = 'unresolved'
        with self.assertRaisesRegex(ValueError, 'unresolved portfolio'):
            readout.compare_readouts(self.results)

    def test_completed_reference_hash_change_and_output_cap_refuse_before_publication(self):
        self.results['base']['stopped_capture_provenance']['readout_references']['strict_analysis_sha256'] = 'f' * 64
        self.write_scenarios()
        with self.assertRaisesRegex(ValueError, 'reference hash/path'):
            self.run_analysis()
        self.results['base']['stopped_capture_provenance']['readout_references']['strict_analysis_sha256'] = original.digest(self.paths['strict'])
        self.write_scenarios()
        with patch.object(readout, 'MAX_OUTPUT_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'output byte cap'):
                self.run_analysis()
        self.assertFalse(self.out.exists())
        with patch.object(readout, 'MAX_ALIGNMENT_COHORTS', 1):
            with self.assertRaisesRegex(ValueError, 'alignment cohort retention'):
                readout.compare_readouts(self.results)
        self.out.symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(ValueError, 'existing paths'):
            self.run_analysis()
        self.assertTrue(self.out.is_symlink())


if __name__ == '__main__':
    unittest.main()
