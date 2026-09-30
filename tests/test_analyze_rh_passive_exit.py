"""Stopped-only passive exit coordinator and cash-selection checks."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from scripts.analyze_rh_passive_exit import (
    POLICIES, build_protocol, verify_protocol, score_cohorts, replay,
    _funding_entry_blocked, _group_flat, NS,
)


def episode(cohort_id: str, cash: str, *, full=True, maker='1') -> dict:
    return {'cohort_id': cohort_id, 'maker_attributed': maker,
            'entry_quote_price': '100', 'entry_maker_qty': maker,
            'entry_rh_notional': str(100 * float(maker)),
            'entry_hl_qty': maker, 'entry_hl_notional': str(101 * float(maker)),
            'entry_rh_fee': '0', 'entry_hl_fee': '0.45',
            'first_full_hedge_ns': 1005 if full else None,
            'cash_known': cash, 'fee_only_net': cash,
            'reserve_cost': '0.05', 'capital_cost': '0.01',
            'stressed_net': str(float(cash) - 0.06),
            'funding_unknown': False}


def branch(policy: str, episodes: list[dict]) -> dict:
    return {'tier': 'standard', 'asset': 'XAG', 'budget_usd': '1000',
            'exit_policy': policy, 'episodes': episodes}


class PassiveExitAnalysisTests(unittest.TestCase):
    def test_same_entry_cash_and_unknown_coverage(self):
        a = 'XAG:1000:standard:1000'
        b = 'XAG:1000:standard:2000'
        cohorts = [
            {'cohort_id': a, 'tier': 'standard', 'asset': 'XAG',
             'budget_usd': 1000, 'decision_ns': 1000,
             'admitted': {policy: True for policy in POLICIES}},
            {'cohort_id': b, 'tier': 'standard', 'asset': 'XAG',
             'budget_usd': 1000, 'decision_ns': 2000,
             'admitted': {policy: True for policy in POLICIES}},
        ]
        branches = [
            branch('control10s', [episode(a, '-1.00'), episode(b, '-0.50', full=False)]),
            branch('passive_best10s', [episode(a, '-0.50')]),
            branch('passive_target10s', [episode(a, '1.00')]),
            branch('passive_target60s', [episode(a, '0.50')]),
        ]
        result = score_cohorts(cohorts, branches, {'fixed_best_quote_checks': 4})
        primary = result['primary_standard_xag_1000_target10_vs_control10']
        self.assertEqual(primary['n'], 1)
        self.assertEqual(primary['mean_usd'], '2.00')
        self.assertEqual(result['cohort_status_counts']['passive_target10s:unsettled_or_unknown'], 1)
        control = next(row for row in result['all_admitted_closed_by_branch']
                       if row['exit_policy'] == 'control10s')
        self.assertEqual(control['known_without_full_hedge'], 1)
        self.assertEqual(control['known_closed_fee_only_contribution_usd'], '-1.50')

    def test_entry_mismatch_and_malformed_cash_do_not_enter_pair(self):
        a = 'XAG:1000:standard:1000'
        cohort = {'cohort_id': a, 'tier': 'standard', 'asset': 'XAG',
                  'budget_usd': 1000, 'decision_ns': 1000,
                  'admitted': {policy: policy in ('control10s', 'passive_target10s')
                               for policy in POLICIES}}
        control = episode(a, '-1')
        target = episode(a, '1')
        target['entry_hl_notional'] = '102'
        branches = [branch(p, [control] if p == 'control10s' else
                           [target] if p == 'passive_target10s' else [])
                    for p in POLICIES]
        result = score_cohorts([cohort], branches, {})
        self.assertEqual(result['primary_standard_xag_1000_target10_vs_control10']['n'], 0)
        self.assertEqual(result['cohort_status_counts']['passive_target10s_vs_control10s:entry_mismatch'], 1)
        target['entry_hl_notional'] = '101'
        target['stressed_net'] = '999'
        with self.assertRaisesRegex(ValueError, 'net identity'):
            score_cohorts([cohort], branches, {})

    def test_partial_hedge_is_not_same_entry_complete(self):
        a = 'XAG:1000:standard:1000'
        cohort = {'cohort_id': a, 'tier': 'standard', 'asset': 'XAG',
                  'budget_usd': 1000, 'decision_ns': 1000,
                  'admitted': {policy: policy in ('control10s', 'passive_target10s')
                               for policy in POLICIES}}
        control = episode(a, '-1')
        target = episode(a, '1')
        target['entry_hl_qty'] = '.5'
        branches = [branch(p, [control] if p == 'control10s' else
                           [target] if p == 'passive_target10s' else [])
                    for p in POLICIES]
        result = score_cohorts([cohort], branches, {})
        self.assertEqual(result['primary_standard_xag_1000_target10_vs_control10']['n'], 0)
        self.assertEqual(result['cohort_status_counts']['passive_target10s:no_full_matched_entry'], 1)

    def test_funding_gate_and_group_obligations(self):
        hour = 3600 * NS
        self.assertFalse(_funding_entry_blocked(3500 * NS))
        self.assertTrue(_funding_entry_blocked(3520 * NS))
        self.assertTrue(_funding_entry_blocked(hour + NS))
        self.assertFalse(_funding_entry_blocked(hour + 2 * NS))
        clean = SimpleNamespace(quote=None, rh_pos=0, hl_pos=0, hedges=[], exits={},
                                unknown_reason=None, passive_ask=None, passive_buys=[],
                                fallback_requested_ns=None)
        self.assertTrue(_group_flat([clean]))
        busy = SimpleNamespace(**vars(clean))
        busy.passive_buys = [object()]
        self.assertFalse(_group_flat([clean, busy]))

    def test_protocol_hashes_sources_and_rejects_predating_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meta = root / 'metadata'
            meta.mkdir()
            (meta / 'normalized.json').write_text('{}')
            protocol = build_protocol('2026-09-29T22:00:00+00:00', meta)
            self.assertIn('scripts/rh_passive_exit_cache.py', protocol['source_sha256'])
            capture = root / 'capture'
            (capture / 'metadata').mkdir(parents=True)
            (capture / 'metadata/normalized.json').write_text('{}')
            manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                        'configured_seconds': 3000, 'calibration_seconds': 1800,
                        'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
                        'started_utc': '2026-09-29T22:00:01+00:00',
                        'ended_utc': '2026-09-29T22:50:01+00:00',
                        'metadata_normalized_sha256': protocol['metadata_normalized_sha256']}
            (capture / 'manifest.json').write_text(json.dumps(manifest))
            path = root / 'protocol.json'
            path.write_text(json.dumps(protocol))
            self.assertEqual(verify_protocol(path, capture)[2] + 1800 * NS,
                             verify_protocol(path, capture)[3])
            protocol['primary']['asset'] = 'BTC'
            path.write_text(json.dumps(protocol))
            with self.assertRaisesRegex(ValueError, 'primary contrast'):
                verify_protocol(path, capture)
            protocol['primary']['asset'] = 'XAG'
            path.write_text(json.dumps(protocol))
            manifest['started_utc'] = '2026-09-29T21:59:59+00:00'
            (capture / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'outside frozen timeline'):
                verify_protocol(path, capture)

    def test_synthetic_stopped_replay_has_128_identified_branches_and_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / 'capture'
            capture.mkdir()
            shutil.copytree(Path(__file__).resolve().parents[1] /
                            'reports/rh-small-maker-v1/metadata', capture / 'metadata')
            start = 1_796_083_200 * NS  # 2026-12-01 UTC, synthetic future data.
            def book(venue, at):
                return {'type': 'book', 'venue': venue, 'asset': 'BTC',
                        'generation': 'g', 'received_ns': at, 'source_ns': at,
                        'valid': True, 'clock_valid': True,
                        'bids': [[100, 20], [99.9, 20]] if venue == 'rh_lighter'
                                else [[100.1, 20], [100, 20]],
                        'asks': [[101, .5], [101.1, 20]] if venue == 'rh_lighter'
                                else [[100.2, 20], [100.3, 20]]}
            manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                        'configured_seconds': 3000, 'calibration_seconds': 1800,
                        'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
                        'started_utc': '2026-12-01T00:00:00+00:00',
                        'ended_utc': '2026-12-01T00:50:00+00:00',
                        'end_reason': 'duration_limit', 'frames_sha256': '0' * 64,
                        'metadata_normalized_sha256': build_protocol(
                            '2026-11-30T23:00:00+00:00', capture / 'metadata')
                            ['metadata_normalized_sha256']}
            (capture / 'manifest.json').write_text(json.dumps(manifest))
            protocol = root / 'protocol.json'
            protocol.write_text(json.dumps(build_protocol('2026-11-30T23:00:00+00:00',
                                                         capture / 'metadata')))
            events = [book('rh_lighter', start), book('hyperliquid', start),
                      book('rh_lighter', start + 1800 * NS),
                      book('hyperliquid', start + 1800 * NS),
                      {'type': 'end', 'received_ns': start + 3000 * NS,
                       'truncated': False}]
            result = replay(capture, root / 'out', protocol, events=events)
            self.assertEqual(result['status'], 'complete', result['errors'])
            self.assertEqual(len(result['branches']), 128)
            self.assertEqual(result['cohort_score']['primary_standard_xag_1000_target10_vs_control10']['n'], 0)
            self.assertEqual(result['event_source'], 'injected_test_events')
            self.assertGreater(result['cache']['book_misses'], 0)
            self.assertTrue((root / 'out/analysis.json').is_file())


if __name__ == '__main__':
    unittest.main()
