"""Synthetic-only tests for the bounded RH maker lifecycle postprocessor."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_rh_maker, summarize_rh_maker_lifecycle as lifecycle
from scripts.maker_capture import BoundedGzip, SizeCapReached
from tests.test_analyze_rh_maker import FROZEN, events


class LifecycleSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.capture = self.base / 'synthetic_capture'
        self.capture.mkdir()
        shutil.copytree(FROZEN, self.capture / 'metadata')
        manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                    'configured_seconds': 3000, 'calibration_seconds': 1800,
                    'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
                    'started_utc': '2026-09-29T00:00:00+00:00',
                    'ended_utc': '2026-09-29T00:50:00+00:00',
                    'end_reason': 'duration_limit', 'frames_sha256': '0' * 64,
                    'metadata_normalized_sha256': hashlib.sha256(
                        (self.capture / 'metadata/normalized.json').read_bytes()).hexdigest()}
        (self.capture / 'manifest.json').write_text(json.dumps(manifest))

    def replay(self, rows, name='replay'):
        path = self.base / name
        analyze_rh_maker.replay(self.capture, path, events=rows)
        return path

    def test_completed_lifecycle_cash_costs_and_observed_durations(self):
        replay = self.replay(events(fill=True))
        result = lifecycle.summarize(replay, self.base / 'derived')
        self.assertEqual(result['branch_count'], 96)
        self.assertEqual(result['event_source'], 'injected_test_events')
        b = next(b for b in result['branches'] if (b['tier'], b['asset'],
            b['budget_usd'], b['policy']) == ('standard', 'BTC', '1000', 'fixed_best'))
        e, t = b['economics'], b['timing']
        self.assertTrue(b['primary_size'])
        self.assertFalse(b['primary_panel'])
        primary = [x for x in result['branches'] if x['primary_panel']]
        self.assertEqual({x['asset'] for x in primary}, {'BTC', 'ETH', 'NVDA', 'XAG'})
        self.assertTrue(all(x['policy'] == 'adaptive' and x['tier'] == 'standard'
                            and x['budget_usd'] == '1000' for x in primary))
        self.assertEqual(e['known_closed_filled_episodes'], 1)
        self.assertEqual(Decimal(e['closed_cash_after_fees_before_reserve_capital_parity_usd']),
                         Decimal('18.02563046625'))
        self.assertEqual(Decimal(e['closed_reserve_cost_usd']), Decimal('0.499003515'))
        self.assertEqual(Decimal(e['closed_capital_cost_usd']),
                         Decimal('0.00003351159677035768645357686454'))
        self.assertEqual(Decimal(e['closed_contribution_after_all_three_parity_usd']),
                         Decimal('17.52659343965322964231354642'))
        self.assertEqual(t['intervals']['decision_to_activation']['mean_seconds'], .4)
        self.assertEqual(t['intervals']['public_flow_to_hedge_result']['mean_seconds'], .2)
        self.assertEqual(t['intervals']['modeled_exit_request_to_flat']['mean_seconds'], .5)
        join = t['quote_residence_by_competitiveness']['join']
        self.assertEqual(join['modeled_quote_residence']['mean_seconds'], .5)
        self.assertEqual(join['activation_to_cancel_effectiveness_book']['mean_seconds'], .5)
        self.assertEqual(join['modeled_quote_residence']['count'], 1)
        self.assertEqual(b['hazard_counts']['quote_requested'], 1)
        self.assertEqual(b['hazard_counts']['activated'], 1)
        self.assertEqual(b['hazard_counts']['cancel_effective'], 1)
        self.assertIn('0', b['existing_five_minute_lifecycle'])
        self.assertEqual(json.loads((self.base / 'derived/lifecycle.json').read_text())['branch_count'], 96)
        report = (self.base / 'derived/REPORT.md').read_text()
        self.assertIn('never sum rows', report)
        self.assertIn('Primary panel: Standard, $1,000, adaptive', report)
        self.assertIn('modeled explicit fees', report)
        self.assertIn('not confirmed by a private order', report)

    def test_no_flow_is_zero_cost_and_not_an_observed_hedge(self):
        replay = self.replay(events(fill=False))
        result = lifecycle.summarize(replay, self.base / 'derived')
        b = next(b for b in result['branches'] if (b['tier'], b['asset'],
            b['budget_usd'], b['policy']) == ('standard', 'BTC', '1000', 'fixed_best'))
        self.assertEqual(Decimal(b['economics']['closed_cash_after_fees_before_reserve_capital_parity_usd']), 0)
        self.assertEqual(b['economics']['known_closed_filled_episodes'], 0)
        self.assertEqual(b['timing']['intervals']['public_flow_to_hedge_result']['count'], 0)
        self.assertEqual(b['hazard_counts']['quote_requested'], 1)

    def test_capped_audit_keeps_open_inventory_and_right_censored_intervals(self):
        class CapAfterMakerFill(BoundedGzip):
            def write(self, row):
                if (row.get('event') == 'hedge_scheduled' and row.get('tier') == 'standard'
                    and row.get('asset') == 'BTC' and row.get('budget_usd') == 1000
                    and row.get('policy') == 'fixed_best'):
                    raise SizeCapReached
                return super().write(row)
        with patch.object(analyze_rh_maker, 'BoundedGzip', CapAfterMakerFill):
            replay = self.replay(events(fill=True))
        result = lifecycle.summarize(replay, self.base / 'derived')
        b = next(b for b in result['branches'] if (b['tier'], b['asset'],
            b['budget_usd'], b['policy']) == ('standard', 'BTC', '1000', 'fixed_best'))
        self.assertEqual(result['replay_status'], 'audit_size_cap')
        self.assertIsNone(b['economics']['complete_branch_net_parity_usd'])
        self.assertGreater(Decimal(b['economics']['open_rh_base']), 0)
        self.assertEqual(b['timing']['intervals']['public_flow_to_hedge_result']['count'], 0)
        self.assertEqual(b['timing']['censored_intervals']['public_flow_to_hedge_result_lower_bound']['count'], 1)
        self.assertEqual(b['timing']['censored_counts']['quote_open_at_replay_end'], 1)
        self.assertEqual(b['timing']['censored_counts']['quote_interval_censored'], 1)
        timing_section = (self.base / 'derived/REPORT.md').read_text().split('## Timing and hazard', 1)[1]
        target_line = next(line for line in timing_section.splitlines()
                           if line.startswith('| standard | BTC | 1000 | fixed_best |'))
        self.assertTrue(target_line.endswith('| 1 / 1 / 0 |'), target_line)

    def test_verified_stream_rejects_tampered_gzip_and_short_line_cap(self):
        replay = self.replay(events(fill=True))
        audit = replay / 'audit.jsonl.gz'
        audit.write_bytes(audit.read_bytes() + b'x')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            lifecycle.summarize(replay, self.base / 'bad_digest')
        self.assertFalse((self.base / 'bad_digest').exists())
        audit.write_bytes(audit.read_bytes()[:-1])
        with patch.object(lifecycle, 'MAX_LINE_BYTES', 16):
            with self.assertRaisesRegex(ValueError, 'bound exceeded'):
                lifecycle.summarize(replay, self.base / 'short_line')
        self.assertFalse((self.base / 'short_line').exists())

    def test_hedge_delay_does_not_pair_with_earlier_unscheduled_flow(self):
        start = 10_000 * lifecycle.NS
        timeline = lifecycle.BranchTimeline(start, start + 20 * lifecycle.NS)
        timeline.consume({'event': 'maker_increment', 'ns': start + lifecycle.NS,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_anchor_missing', 'ns': start + lifecycle.NS})
        timeline.consume({'event': 'maker_increment', 'ns': start + 2 * lifecycle.NS,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_scheduled', 'ns': start + 2 * lifecycle.NS,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_result', 'ns': start + 2 * lifecycle.NS + 200_000_000,
                          'requested': '1', 'filled': '1'})
        timing = timeline.finish()
        self.assertEqual(timing['intervals']['public_flow_to_hedge_result']['count'], 1)
        self.assertEqual(timing['intervals']['public_flow_to_hedge_result']['mean_seconds'], .2)
        self.assertEqual(timing['censored_counts']['flow_without_hedge_result:replay_end'], 1)

    def test_unactivated_quote_wait_remains_censored(self):
        start = 10_000 * lifecycle.NS
        timeline = lifecycle.BranchTimeline(start, start + 20 * lifecycle.NS)
        timeline.consume({'event': 'quote_requested', 'ns': start,
                          'due_ns': start + 300_000_000,
                          'competitiveness': 'join'})
        timing = timeline.finish()
        self.assertEqual(timing['censored_counts']['quote_interval_censored'], 1)
        self.assertEqual(timing['censored_counts']['requested_without_observed_activation'], 1)
        self.assertEqual(timing['censored_intervals']['request_to_activation_lower_bound']['mean_seconds'], 20)
        self.assertEqual(timing['quote_residence_by_competitiveness']['join']['modeled_quote_residence']['count'], 0)

    def test_timed_out_hedge_cannot_steal_later_equal_quantity_result(self):
        start = 10_000 * lifecycle.NS
        timeline = lifecycle.BranchTimeline(start, start + 20 * lifecycle.NS)
        for seconds in (1, 2):
            at = start + seconds * lifecycle.NS
            timeline.consume({'event': 'maker_increment', 'ns': at, 'qty': '1'})
            timeline.consume({'event': 'hedge_scheduled', 'ns': at, 'qty': '1'})
        timeline.consume({'event': 'hedge_timeout', 'ns': start + 4 * lifecycle.NS,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_result', 'ns': start + 4 * lifecycle.NS + 200_000_000,
                          'requested': '1', 'filled': '1'})
        timing = timeline.finish()
        self.assertEqual(timing['intervals']['public_flow_to_hedge_result']['mean_seconds'], 2.2)
        self.assertEqual(timing['censored_counts']['flow_without_hedge_result:hedge_timeout'], 1)
        self.assertEqual(timing['censored_intervals']['public_flow_to_hedge_result_lower_bound']['mean_seconds'], 3)

    def test_post_only_reject_is_observed_rejection_not_unknown_cancel(self):
        start = 10_000 * lifecycle.NS
        timeline = lifecycle.BranchTimeline(start, start + 20 * lifecycle.NS)
        timeline.consume({'event': 'quote_requested', 'ns': start,
                          'due_ns': start + 300_000_000,
                          'competitiveness': 'join'})
        timeline.consume({'event': 'post_only_reject', 'ns': start + 400_000_000})
        timeline.consume({'event': 'episode_flat', 'ns': start + lifecycle.NS})
        timing = timeline.finish()
        self.assertEqual(timing['intervals']['decision_to_post_only_reject']['mean_seconds'], .4)
        self.assertEqual(timing['censored_counts'].get('quote_interval_censored', 0), 0)
        self.assertEqual(timing['censored_counts'].get('flat_without_cancel_observation', 0), 0)

    def test_hedge_schedule_requires_same_maker_event_time(self):
        start = 10_000 * lifecycle.NS
        timeline = lifecycle.BranchTimeline(start, start + 20 * lifecycle.NS)
        timeline.consume({'event': 'maker_increment', 'ns': start + lifecycle.NS,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_scheduled', 'ns': start + lifecycle.NS + 1,
                          'qty': '1'})
        timeline.consume({'event': 'hedge_result', 'ns': start + 2 * lifecycle.NS,
                          'requested': '1', 'filled': '1'})
        timing = timeline.finish()
        self.assertEqual(timing['intervals']['public_flow_to_hedge_result']['count'], 0)
        self.assertEqual(timing['censored_counts']['hedge_schedule_flow_pairing_ambiguous'], 1)
        self.assertEqual(timing['censored_counts']['hedge_result_without_schedule'], 1)


if __name__ == '__main__':
    unittest.main()
