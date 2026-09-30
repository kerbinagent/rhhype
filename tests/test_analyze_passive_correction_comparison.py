"""Offline artifact fixtures; no running capture or empirical replay is read."""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_passive_correction_comparison as comparison
from scripts import analyze_rh_passive_exit as original
from scripts import replay_passive_retirement_corrected as correction

NS = original.NS
START = 1_796_083_200 * NS
DECISION = START + 1803 * NS
GROUP = ('standard', 'XAG', 1000)


def branch(tier, asset, budget, policy, *, corrected=False):
    result = {'tier': tier, 'asset': asset, 'budget_usd': str(budget), 'exit_policy': policy,
              'episodes': [], 'counts': {}, 'unknown_reason': None, 'funding_unknown': False,
              'rh_position': '0', 'hl_position': '0', 'delta': '0', 'gross_inventory': '0',
              'cash_known': '0', 'reserve_cost': '0', 'capital_cost': '0', 'complete_net': '0',
              'passive_quote_open': False, 'passive_buy_intents_open': 0, 'fallback_pending': False,
              'cohort_id_active': None, 'first_unknown_ns': None, 'first_quote_requested_ns': None,
              'effective_quote_opportunity_seconds_before_unknown': 0, 'group_book_quote_checks': 0,
              'delta_exposure_base_seconds': '0', 'gross_inventory_base_seconds': '0'}
    if corrected:
        result.update(retirement_guard_revision='entry-same-receipt-v1', frozen_v1_result=False)
    return result


def cohort(when):
    return {'tier': GROUP[0], 'asset': GROUP[1], 'budget_usd': GROUP[2],
            'cohort_id': f'XAG:1000:standard:{when}', 'decision_ns': when,
            'admitted': {p: p in ('control10s', 'passive_target10s') for p in original.POLICIES}}


def episode(identifier, number=1, *, unknown=False, cash='0'):
    result = {'cohort_id': identifier, 'number': number, 'execution_unknown': unknown,
              'funding_unknown': False, 'cash_known': cash, 'fee_only_net': cash,
              'reserve_cost': '0', 'capital_cost': '0', 'stressed_net': cash,
              'maker_attributed': '0', 'first_full_hedge_ns': None}
    if unknown:
        result.update(execution_unknown_reason='late_retired_quote_flow',
                      late_retired_flow={'receipt_ns': DECISION + 8 * NS,
                                         'source_ns': DECISION + 5 * NS,
                                         'trade_id': '7'})
    return result


def score(result):
    result['cohort_score'] = original.score_cohorts(result['cohorts'], result['branches'], result['counts'])


def fixture(root, *, later_admission=True):
    capture = root / 'capture'
    metadata = capture / 'metadata'
    metadata.mkdir(parents=True)
    (metadata / 'normalized.json').write_text('{"synthetic_fixture":true}')
    protocol_path = root / 'protocol.json'
    protocol = original.build_protocol('2026-11-30T23:59:00+00:00', metadata)
    protocol_path.write_text(json.dumps(protocol))
    (capture / 'frames.jsonl.gz').write_bytes(gzip.compress(b'{"synthetic_only":true}\n', mtime=0))
    raw_hash = original.digest(capture / 'frames.jsonl.gz')
    manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                'configured_seconds': 3000, 'calibration_seconds': 1800, 'holdout_seconds': 1200,
                'configured_total_bytes': original.RAW_CAP, 'started_utc': '2026-12-01T00:00:00+00:00',
                'ended_utc': '2026-12-01T00:50:00+00:00', 'end_reason': 'duration_limit',
                'truncated': False, 'frames_sha256': raw_hash,
                'metadata_normalized_sha256': protocol['metadata_normalized_sha256']}
    (capture / 'manifest.json').write_text(json.dumps(manifest))
    freeze_path = root / 'freeze.json'
    freeze = correction.build_correction_freeze(protocol_path, capture,
                now=datetime(2026, 12, 1, 0, 10, tzinfo=timezone.utc))
    freeze_path.write_text(json.dumps(freeze))
    manifest_hash = original.digest(capture / 'manifest.json')
    strict = {'schema': original.RESULT_SCHEMA, 'status': 'complete', 'errors': [],
              'event_source': 'verified_capture', 'capture': str(capture),
              'capture_manifest_sha256': manifest_hash, 'raw_sha256': raw_hash,
              'protocol_sha256': original.digest(protocol_path), 'protocol_frozen_at': protocol['frozen_at'],
              'source_sha256': protocol['source_sha256'],
              'metadata_normalized_sha256': protocol['metadata_normalized_sha256'],
              'started_ns': START, 'cutoff_ns': START + 1800 * NS,
              'entry_admission_end_ns': START + 2920 * NS, 'ended_ns': START + 3000 * NS,
              'intended_end_ns': START + 3000 * NS, 'counts': {},
              'terminal_event': {'type': 'end', 'truncated': False, 'raw_sha_verified': True,
                                 'raw_gzip_sha256': raw_hash, 'manifest_sha256': manifest_hash},
              'assumptions': {'synthetic': True}, 'metadata': {'synthetic': True}, 'models': {'synthetic': True},
              'branches': [branch(*key) for key in itertools.product(
                  original.TIERS, original.ASSETS, original.SIZES, original.POLICIES)],
              'cohorts': [cohort(DECISION)]}
    corrected = deepcopy(strict)
    corrected.update(schema=correction.RESULT_SCHEMA, original_result_schema=original.RESULT_SCHEMA,
                     implementation_variant=correction.VARIANT, original_frozen_v1_result=False,
                     runtime_class_override=correction.RUNTIME_OVERRIDE,
                     source_sha256_extra=freeze['source_sha256_extra'],
                     correction_freeze={'path': str(freeze_path), 'sha256': original.digest(freeze_path),
                                        'frozen_at': freeze['frozen_at'],
                                        'conservative_holdout_lower_bound_ns': freeze['conservative_holdout_lower_bound_ns'],
                                        'actual_capture_started_ns': START, 'actual_holdout_cutoff_ns': START + 1800 * NS,
                                        'frozen_after_capture_started': True, 'disclosure': freeze['timing_disclosure']})
    for result, is_corrected in ((strict, False), (corrected, True)):
        for ledger in result['branches']:
            if is_corrected:
                ledger.update(retirement_guard_revision='entry-same-receipt-v1', frozen_v1_result=False)
            if comparison._key(ledger)[:3] == GROUP and ledger['exit_policy'] in ('control10s', 'passive_target10s'):
                ledger['episodes'] = [episode(result['cohorts'][0]['cohort_id'], unknown=is_corrected)]
                ledger['first_quote_requested_ns'] = DECISION
                ledger['effective_quote_opportunity_seconds_before_unknown'] = 8 if is_corrected else 1197
                if is_corrected:
                    ledger.update(unknown_reason='late_retired_quote_flow', complete_net=None,
                                  first_unknown_ns=DECISION + 8 * NS)
    if later_admission:
        strict['cohorts'].append(cohort(DECISION + 20 * NS))
        for ledger in strict['branches']:
            if comparison._key(ledger)[:3] == GROUP and ledger['exit_policy'] in ('control10s', 'passive_target10s'):
                ledger['episodes'].append(episode(strict['cohorts'][1]['cohort_id'], 2, cash='5'))
                ledger.update(cash_known='5', complete_net='5', delta_exposure_base_seconds='3')
    score(strict)
    score(corrected)
    return strict, corrected, protocol_path, freeze_path


class CorrectionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.strict, self.corrected, self.protocol, self.freeze = fixture(self.root)

    def selected(self, result):
        return next(b for b in result['branches'] if comparison._key(b) == (*GROUP, 'control10s'))

    def test_false_zero_becomes_unknown_and_later_admission_denominators_stay_separate(self):
        result = comparison.compare_results(self.strict, self.corrected)
        self.assertEqual(result['branch_count'], 128)
        ledger = self.selected(result)
        self.assertEqual((ledger['strict']['admitted_cohorts'], ledger['corrected']['admitted_cohorts']), (2, 1))
        self.assertEqual((ledger['strict']['retained_candidate_cohorts'], ledger['corrected']['retained_candidate_cohorts']), (2, 1))
        self.assertEqual((ledger['strict']['known_closed_episodes'], ledger['corrected']['known_closed_episodes']), (2, 0))
        self.assertEqual((ledger['strict']['complete_portfolio_net_usd'], ledger['corrected']['complete_portfolio_net_usd']), ('5', None))
        self.assertEqual(ledger['corrected']['known_closed_after_reserve_capital_contribution_usd'], '0')
        change = next(e for e in result['execution_unknown_changes'] if e['exit_policy'] == 'control10s')
        self.assertEqual(change['strict']['known_after_reserve_capital_contribution_usd'], '0')
        self.assertIsNone(change['corrected']['known_after_reserve_capital_contribution_usd'])
        self.assertFalse(change['strict']['execution_unknown'])
        self.assertTrue(change['corrected']['execution_unknown'])
        self.assertEqual(len(ledger['common_admitted_cohort_ids']), 1)
        self.assertEqual(len(ledger['strict_only_admitted_cohort_ids']), 1)
        self.assertFalse(ledger['admission_histories_identical'])
        self.assertFalse(ledger['effective_observation_time_identical'])
        self.assertEqual(ledger['corrected']['first_halt_ns'], DECISION + 8 * NS)
        self.assertEqual((ledger['strict']['delta_exposure_base_seconds'], ledger['corrected']['delta_exposure_base_seconds']), ('3', '0'))
        self.assertIsNone(result['primary_standard_xag_1000']['cross_variant_profit_improvement'])
        self.assertIsNone(result['summed_branch_portfolio_net'])

    def test_all_provenance_hashes_validate_and_publish_bounded_artifacts(self):
        old_path, new_path = self.root / 'strict.json', self.root / 'corrected.json'
        old_path.write_text(json.dumps(self.strict))
        new_path.write_text(json.dumps(self.corrected))
        result = comparison.analyze(old_path, new_path, self.protocol, self.freeze, self.root / 'comparison')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['provenance']['source_sha256']), 18)
        self.assertEqual(len(result['provenance']['source_sha256_extra']), 2)
        self.assertFalse(result['provenance']['raw_decoding_performed'])
        report = (self.root / 'comparison/REPORT.md').read_text()
        self.assertIn('5 / unknown', report)
        self.assertIn('do not establish causal profit improvement', report)

    def test_mismatched_capture_protocol_assumptions_or_terminal_provenance_rejected(self):
        for field, value in (('raw_sha256', 'f' * 64), ('capture_manifest_sha256', 'f' * 64),
                             ('protocol_sha256', 'f' * 64), ('source_sha256', {}),
                             ('assumptions', {'changed': True}), ('models', {'changed': True}),
                             ('metadata_normalized_sha256', 'f' * 64)):
            with self.subTest(field=field):
                variant = deepcopy(self.corrected)
                variant[field] = value
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    comparison._validate_provenance(self.strict, variant, self.protocol, self.freeze)

    def test_injected_events_incomplete_status_and_wrong_variant_fail(self):
        for field, value in (('status', 'capture_incomplete'), ('event_source', 'injected_test_events'),
                             ('schema', original.RESULT_SCHEMA), ('implementation_variant', 'another'),
                             ('source_sha256_extra', {}), ('runtime_class_override', {})):
            with self.subTest(field=field):
                variant = deepcopy(self.corrected)
                variant[field] = value
                with self.assertRaises(ValueError):
                    comparison._validate_provenance(self.strict, variant, self.protocol, self.freeze)

    def test_actual_raw_and_frozen_extra_hash_mismatch_fail(self):
        raw = Path(self.strict['capture']) / 'frames.jsonl.gz'
        original_bytes = raw.read_bytes()
        raw.write_bytes(original_bytes[:-1] + bytes([original_bytes[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'actual capture raw SHA-256'):
            comparison._validate_provenance(self.strict, self.corrected, self.protocol, self.freeze)
        raw.write_bytes(original_bytes)
        freeze = json.loads(self.freeze.read_text())
        freeze['source_sha256_extra'][correction.EXTRA_SOURCES[0]] = '0' * 64
        self.freeze.write_text(json.dumps(freeze))
        with self.assertRaisesRegex(ValueError, 'correction source hash mismatch'):
            comparison._validate_provenance(self.strict, self.corrected, self.protocol, self.freeze)

    def test_unknown_episode_cannot_claim_zero_total_portfolio(self):
        ledger = self.selected(self.corrected)
        ledger['complete_net'] = '0'
        score(self.corrected)
        with self.assertRaisesRegex(ValueError, 'unresolved portfolio'):
            comparison.compare_results(self.strict, self.corrected)

    def test_cohort_score_cannot_hide_episode_unknown_or_changed_denominator(self):
        ledger = self.selected(self.corrected)
        ledger['episodes'][0]['execution_unknown'] = False
        with self.assertRaisesRegex(ValueError, 'cohort score differs'):
            comparison.compare_results(self.strict, self.corrected)
        ledger['episodes'][0]['execution_unknown'] = True
        self.corrected['cohorts'][0]['admitted']['control10s'] = False
        with self.assertRaisesRegex(ValueError, 'admission identity'):
            comparison.compare_results(self.strict, self.corrected)

    def test_missing_results_fail_before_touching_source_and_output_cap_fails_before_publication(self):
        with patch.object(comparison, '_validate_provenance') as verifier:
            with self.assertRaises(FileNotFoundError):
                comparison.analyze(self.root / 'missing-strict', self.root / 'missing-corrected',
                                   self.protocol, self.freeze, self.root / 'out')
            verifier.assert_not_called()
        old_path, new_path = self.root / 'strict.json', self.root / 'corrected.json'
        old_path.write_text(json.dumps(self.strict))
        new_path.write_text(json.dumps(self.corrected))
        with patch.object(comparison, 'MAX_OUTPUT_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'output exceeds'):
                comparison.analyze(old_path, new_path, self.protocol, self.freeze, self.root / 'too-large')
        self.assertFalse((self.root / 'too-large').exists())


if __name__ == '__main__':
    unittest.main()
