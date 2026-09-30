"""Synthetic causal evidence checks; no capture or strategy replay."""
import unittest
from copy import deepcopy
from pathlib import Path
from scripts.analyze_rejected_target_reach import reconstruct, scan_events, evaluate, verify_result
from scripts.analyze_rh_passive_exit import RESULT_SCHEMA
from tests.test_rh_maker_engine import T, NS, book, trade


class RejectedTargetReachTests(unittest.TestCase):
    def attempt(self, tier='standard', policy='passive_target10s'):
        row = {'event': 'passive_target_abstain', 'ns': T + NS, 'tier': tier,
               'asset': 'BTC', 'budget_usd': 1000, 'exit_policy': policy,
               'reason': 'target_above_5bp_ask_cap', 'required_price': '100.455',
               'capped_price': '100.45020'}
        hedge = {'ns': T, 'hold_due_ns': T + (60 if policy.endswith('60s') else 10) * NS}
        return reconstruct(row, hedge, {tier: {'BTC': {'rh': {'price_tick': '0.1'}}}})

    def test_original_rounding_and_tier_delay(self):
        row = self.attempt()
        self.assertEqual(row['target_price'], '100.5')
        self.assertEqual(row['logged_asof_ask'], '100.4')
        self.assertEqual(row['hypothetical_activation_ns'], T + 1_300_000_000)
        self.assertEqual(self.attempt('premium')['hypothetical_activation_ns'], T + 1_100_000_000)
        self.assertEqual(self.attempt(policy='passive_target60s')['hold_deadline_ns'], T + 60 * NS)

    def test_missing_cost_or_hedge_is_unreconstructable(self):
        row = self.attempt()
        self.assertEqual(reconstruct(row, None, {})['reconstruction_status'], 'unreconstructable')

    def test_exact_asof_book_and_current_callback(self):
        row = self.attempt()
        events = [book('rh_lighter', T), book('hyperliquid', T + NS),
                  {'type': 'end', 'received_ns': T + 11 * NS}]
        scan_events(iter(events), [row])
        self.assertEqual(row['reconstruction_status'], 'reconstructed')
        self.assertEqual(row['asof_rh_book']['received_ns'], T)
        self.assertEqual(row['target_request_callback']['venue'], 'hyperliquid')

    def test_hindsight_ask_or_ambiguous_callback_rejected(self):
        for callbacks in ([book('rh_lighter', T + NS, asks=[[100.3, 10]])],
                          [book('rh_lighter', T + NS), book('hyperliquid', T + NS)]):
            row = self.attempt()
            scan_events(iter([book('rh_lighter', T), *callbacks,
                              {'type': 'end', 'received_ns': T + 11 * NS}]), [row])
            self.assertTrue(row['reconstruction_status'].startswith('unreconstructable'))

    def test_source_and_receipt_boundaries_and_late_reach(self):
        row = {**self.attempt(), 'reconstruction_status': 'reconstructed'}
        start, due = row['hypothetical_activation_ns'], row['hold_deadline_ns']
        events = [trade(start + 1, source=start - 1, side='buy', price=101, tid='pre-source'),
                  trade(start, source=start, side='buy', price=100.5, tid='activation-tie'),
                  trade(due + 1, source=due, side='buy', price=100.5, tid='late-receipt'),
                  trade(due + 2, source=due + 1, side='buy', price=101, tid='post-source')]
        out = evaluate(row, events, [], [])
        self.assertEqual(out['eligible_new_buy_prints'], 2)
        self.assertEqual(out['timely_reaching_prints'], 1)
        self.assertEqual(out['late_receipt_reaching_prints'], 1)
        self.assertEqual(evaluate(row, events[2:], [], [])['reach_status'], 'observed_late_receipt_reach_only')

    def test_invalid_or_sell_print_cannot_reach(self):
        row = {**self.attempt(), 'reconstruction_status': 'reconstructed'}
        event = trade(T + 2 * NS, side='buy', price=101)
        invalids = [{**event, 'clock_valid': False}, {**event, 'qty': 0},
                    {**event, 'price': 'NaN'}, {**event, 'side': 'sell'},
                    {**event, 'source_ns': T + 3 * NS}]
        self.assertEqual(evaluate(row, invalids, [], [])['eligible_new_buy_prints'], 0)

    def test_invalid_interval_and_book_proxy_gap_stay_uncertain(self):
        row = self.attempt()
        events = [book('rh_lighter', T), book('hyperliquid', T + NS),
                  {'type': 'invalidate', 'venue': 'rh_lighter', 'asset': 'BTC',
                   'received_ns': T + 2 * NS, 'scope': 'trade', 'reason': 'gap'},
                  {'type': 'end', 'received_ns': T + 11 * NS}]
        trades, issues, _ = scan_events(iter(events), [row])
        out = evaluate(row, trades, issues, [])
        self.assertEqual(out['reach_status'], 'observed_nonreach')
        self.assertTrue(out['coverage_or_identity_uncertain'])
        self.assertTrue(any(x.get('scope') == 'trade' and x['end_ns'] == T + 11 * NS
                            for x in out['coverage_issues']))

    def test_cross_generation_exact_duplicates_are_not_new_evidence(self):
        row = self.attempt()
        event = trade(T + 2 * NS, side='buy', price=101, tid='repeat')
        events = [book('rh_lighter', T), book('hyperliquid', T + NS), event,
                  {**event, 'received_ns': T + 3 * NS, 'generation': 'reconnect'},
                  {'type': 'end', 'received_ns': T + 11 * NS}]
        trades, _, scan = scan_events(iter(events), [row])
        self.assertEqual(len(trades), 1)
        self.assertEqual(scan['additional_cross_generation_duplicates'], 1)

    def test_strict_provenance_refuses_injection_other_capture_and_terminal(self):
        capture = Path('/tmp/synthetic-stopped-capture')
        hashes = dict(manifest='manifest', raw='raw', audit='audit', protocol='protocol', metadata='metadata')
        protocol = {'source_sha256': {'synthetic': 'hash'}}
        result = {'schema': RESULT_SCHEMA, 'event_source': 'verified_capture',
                  'capture': str(capture), 'status': 'complete', 'errors': [],
                  'source_sha256': protocol['source_sha256'], 'capture_manifest_sha256': 'manifest',
                  'raw_sha256': 'raw', 'audit_sha256': 'audit', 'protocol_sha256': 'protocol',
                  'metadata_normalized_sha256': 'metadata', 'terminal_event': {
                      'type': 'end', 'truncated': False, 'raw_sha_verified': True,
                      'raw_gzip_sha256': 'raw', 'manifest_sha256': 'manifest'}}
        verify_result(result, capture, hashes, protocol, {'frames_sha256': 'raw'})
        for field, value in (('schema', 'corrected-or-other'), ('event_source', 'injected'),
                             ('capture', '/tmp/other'), ('raw_sha256', 'wrong'),
                             ('audit_sha256', 'wrong')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_result({**result, field: value}, capture, hashes, protocol, {'frames_sha256': 'raw'})
        for field, value in (('truncated', True), ('raw_sha_verified', False),
                             ('raw_gzip_sha256', 'wrong'), ('manifest_sha256', 'wrong')):
            changed = deepcopy(result)
            changed['terminal_event'][field] = value
            with self.subTest(terminal=field), self.assertRaises(ValueError):
                verify_result(changed, capture, hashes, protocol, {'frames_sha256': 'raw'})


if __name__ == '__main__':
    unittest.main()
