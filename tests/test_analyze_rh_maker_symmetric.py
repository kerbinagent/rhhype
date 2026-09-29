"""Synthetic future-capture integration for the separate symmetric replay."""
from __future__ import annotations

from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import analyze_rh_maker_symmetric as symmetric

ROOT = Path(__file__).resolve().parents[1]
FROZEN_META = ROOT / 'reports/rh-small-maker-v1/metadata'
NS = symmetric.NS
START = 1_796_083_200 * NS  # 2026-12-01 UTC; synthetic future capture only
CUTOFF = START + 1_800 * NS
END = START + 3_000 * NS


def book(venue, at, *, bids=None, asks=None):
    return {'type': 'book', 'venue': venue, 'asset': 'BTC', 'generation': 'g',
            'received_ns': at, 'source_ns': at, 'valid': True, 'clock_valid': True,
            'bids': bids if bids is not None else
            ([[100, 20], [99.9, 20]] if venue == 'rh_lighter'
             else [[100.1, 20], [100, 20]]),
            'asks': asks if asks is not None else
            ([[101, .5], [101.1, 20]] if venue == 'rh_lighter'
             else [[100.2, 20], [100.3, 20]])}


def sell_fill_events():
    return [book('rh_lighter', START), book('hyperliquid', START),
            book('rh_lighter', CUTOFF), book('hyperliquid', CUTOFF),
            book('rh_lighter', CUTOFF + 400_000_000),
            {'type': 'trade', 'venue': 'rh_lighter', 'asset': 'BTC',
             'generation': 'g', 'received_ns': CUTOFF + 500_000_000,
             'source_ns': CUTOFF + 500_000_000, 'clock_valid': True,
             'side': 'buy', 'price': 101, 'qty': 100, 'trade_id': 'synthetic-1'},
            book('hyperliquid', CUTOFF + 700_000_000),
            book('rh_lighter', CUTOFF + 900_000_000),
            book('hyperliquid', CUTOFF + 11_200_000_000,
                 bids=[[100.1, 20], [100, 20]],
                 asks=[[100.2, .001], [100.3, .001]]),
            book('rh_lighter', CUTOFF + 11_200_000_000,
                 asks=[[100.5, 20], [100.6, 20]]),
            {'type': 'end', 'received_ns': END, 'truncated': False}]


class AnalyzeSymmetricTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.capture = self.base / 'future_capture'
        self.capture.mkdir()
        shutil.copytree(FROZEN_META, self.capture / 'metadata')
        meta_hash = symmetric.digest(self.capture / 'metadata/normalized.json')
        self.manifest = {
            'schema': 'rh-maker-public-capture-v1', 'read_only': True,
            'configured_seconds': 3000, 'calibration_seconds': 1800,
            'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
            'started_utc': '2026-12-01T00:00:00+00:00',
            'ended_utc': '2026-12-01T00:50:00+00:00',
            'end_reason': 'duration_limit', 'frames_sha256': '0' * 64,
            'metadata_normalized_sha256': meta_hash,
        }
        self._write_manifest()
        protocol = symmetric.build_protocol('2026-11-30T23:00:00+00:00',
                                            'research/rh-maker-sell-followup.md',
                                            self.capture / 'metadata')
        self.protocol = self.base / 'protocol.json'
        self.protocol.write_text(json.dumps(protocol))

    def _write_manifest(self):
        (self.capture / 'manifest.json').write_text(json.dumps(self.manifest))

    def run_replay(self, rows=None, name='analysis'):
        return symmetric.replay(self.capture, self.base / name, self.protocol,
                                events=sell_fill_events() if rows is None else rows)

    @staticmethod
    def branch(result, direction='sell', tier='standard'):
        return next(row for row in result['branches']
                    if row['direction'] == direction and row['tier'] == tier
                    and row['asset'] == 'BTC' and row['budget_usd'] == '1000'
                    and row['policy'] == 'fixed_best')

    def test_192_independent_identified_branches_and_sell_model_engine_economics(self):
        result = self.run_replay()
        self.assertEqual(result['status'], 'complete', result['errors'])
        self.assertEqual(len(result['branches']), 192)
        keys = {(r['direction'], r['tier'], r['asset'], r['budget_usd'], r['policy'])
                for r in result['branches']}
        self.assertEqual(len(keys), 192)
        self.assertEqual(set(result['models']), {'buy', 'sell'})
        self.assertTrue(result['models']['sell']['standard']['frozen'])
        self.assertEqual(result['event_source'], 'injected_test_events')
        self.assertEqual(result['protocol_sha256'], symmetric.digest(self.protocol))
        self.assertEqual(result['source_sha256']['scripts/rh_maker_sell_engine.py'],
                         symmetric.digest(ROOT / 'scripts/rh_maker_sell_engine.py'))
        sell = self.branch(result)
        buy = self.branch(result, direction='buy')
        self.assertEqual(sell['orientation'], 'rh_maker_sell_hl_taker_buy')
        self.assertEqual(buy['orientation'], 'rh_maker_buy_hl_taker_sell')
        self.assertEqual(len(sell['episodes']), 1)
        self.assertEqual(sell['metrics']['known_closed_filled_episodes'], 1)
        q = Decimal(sell['episodes'][0]['maker_attributed'])
        self.assertGreater(q, 0)
        gross = q * (Decimal('101') - Decimal('100.2') - Decimal('100.5') + Decimal('100.1'))
        hl_fees = q * (Decimal('100.2') + Decimal('100.1')) * Decimal('4.5') / 10_000
        reserve = q * Decimal('101') * 5 / 10_000
        capital = ((q * Decimal('101') * Decimal('10.7')
                    + q * Decimal('100.2') * Decimal('10.5'))
                   * Decimal('.05') / Decimal(365 * 86400))
        self.assertEqual(Decimal(sell['fees_rh']), 0)
        self.assertEqual(Decimal(sell['fees_hl']), hl_fees)
        self.assertEqual(Decimal(sell['reserve_cost']), reserve)
        self.assertLess(abs(Decimal(sell['capital_cost']) - capital), Decimal('1e-25'))
        self.assertEqual(Decimal(sell['cash_rh_usdg']), q * Decimal('.5'))
        self.assertEqual(Decimal(sell['cash_hl_usdc']), -q * Decimal('.1') - hl_fees)
        self.assertLess(abs(Decimal(sell['complete_net']) -
                            (gross - hl_fees - reserve - capital)), Decimal('1e-25'))
        premium = self.branch(result, tier='premium')
        premium_rh_fees = q * (Decimal('101') * Decimal('1.2')
                               + Decimal('100.5') * Decimal('3.5')) / 10_000
        self.assertEqual(Decimal(premium['fees_rh']), premium_rh_fees)
        self.assertEqual(Decimal(premium['complete_net']), Decimal(sell['complete_net']) - premium_rh_fees)
        self.assertNotIn('combined_net', result)
        with gzip.open(self.base / 'analysis/audit.jsonl.gz', 'rt') as stream:
            audit = [json.loads(line) for line in stream]
        self.assertTrue(audit)
        self.assertTrue(all(row['direction'] in ('buy', 'sell') for row in audit))
        self.assertLessEqual((self.base / 'analysis/audit.jsonl.gz').stat().st_size,
                             symmetric.AUDIT_CAP)
        self.assertLessEqual((self.base / 'analysis/analysis.json').stat().st_size
                             + (self.base / 'analysis/REPORT.md').stat().st_size,
                             symmetric.SUMMARY_CAP)
        report = (self.base / 'analysis/REPORT.md').read_text()
        self.assertIn('| sell | standard | BTC | 1000 | fixed_best |', report)
        self.assertIn('| buy | standard | BTC | 1000 | fixed_best |', report)

    def test_future_freeze_source_and_metadata_integrity_fail_before_output(self):
        self.manifest['started_utc'] = '2026-09-29T00:00:00+00:00'
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, 'before symmetric protocol'):
            self.run_replay(name='old_capture')
        self.assertFalse((self.base / 'old_capture').exists())
        self.manifest['started_utc'] = '2026-12-01T00:00:00+00:00'
        self._write_manifest()
        protocol = json.loads(self.protocol.read_text())
        protocol['source_sha256']['scripts/rh_maker_sell_engine.py'] = '0' * 64
        self.protocol.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            self.run_replay(name='bad_code')
        self.assertFalse((self.base / 'bad_code').exists())
        protocol = symmetric.build_protocol('2026-11-30T23:00:00+00:00',
                                            'research/rh-maker-sell-followup.md',
                                            self.capture / 'metadata')
        self.protocol.write_text(json.dumps(protocol))
        self.manifest['metadata_normalized_sha256'] = 'f' * 64
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            self.run_replay(name='bad_metadata')
        self.assertFalse((self.base / 'bad_metadata').exists())

    def test_incomplete_capture_preserves_unknown_open_inventory(self):
        rows = sell_fill_events()
        rows = rows[:7] + [{'type': 'end', 'received_ns': CUTOFF + 800_000_000,
                            'truncated': True}]
        self.manifest['ended_utc'] = '2026-12-01T00:30:01+00:00'
        self.manifest['end_reason'] = 'interrupted'
        self._write_manifest()
        result = self.run_replay(rows, name='incomplete')
        self.assertEqual(result['status'], 'capture_incomplete')
        sell = self.branch(result)
        self.assertLess(Decimal(sell['rh_position']), 0)
        self.assertGreater(Decimal(sell['hl_position']), 0)
        self.assertIsNone(sell['complete_net'])
        self.assertFalse(sell['metrics']['total_result_known'])

    def test_late_flow_uncertainty_excludes_closed_contribution(self):
        row = {'budget_usd': '1000', 'complete_net': None, 'episodes': [
            {'flat_ns': CUTOFF + NS, 'maker_attributed': '1', 'no_flow': False,
             'funding_unknown': False, 'execution_unknown': True,
             'cash_known': '10', 'reserve_cost': '1', 'capital_cost': '1'},
            {'flat_ns': CUTOFF + 2 * NS, 'maker_attributed': '1', 'no_flow': False,
             'funding_unknown': False, 'cash_known': '3', 'reserve_cost': '1',
             'capital_cost': '0'},
        ]}
        metrics = symmetric.symmetric_outcome_metrics(row, CUTOFF, END)
        self.assertEqual(metrics['closed_episodes'], 2)
        self.assertEqual(metrics['execution_unknown_episodes'], 1)
        self.assertEqual(metrics['known_closed_filled_episodes'], 1)
        self.assertEqual(Decimal(metrics['closed_net_parity_usd']), 2)
        self.assertEqual(metrics['five_minute_blocks']['0']['execution_unknown'], 1)
        self.assertFalse(metrics['total_result_known'])

    def test_guarded_retired_sell_quote_late_flow_excludes_apparent_closed_gain(self):
        rows = sell_fill_events()
        rows[5]['qty'] = 1.5  # 0.5 queue ahead, one base filled, remainder retired.
        rows.insert(-1, {'type': 'trade', 'venue': 'rh_lighter', 'asset': 'BTC',
                         'generation': 'g', 'received_ns': CUTOFF + 12 * NS,
                         'source_ns': CUTOFF + 700_000_000, 'clock_valid': True,
                         'side': 'buy', 'price': 101, 'qty': 2,
                         'trade_id': 'delayed-retired-flow'})
        result = self.run_replay(rows, name='late_flow')
        self.assertEqual(result['status'], 'complete', result['errors'])
        sell = self.branch(result)
        self.assertEqual(Decimal(sell['rh_position']), 0)
        self.assertEqual(Decimal(sell['hl_position']), 0)
        self.assertEqual(sell['unknown_reason'], 'late_retired_quote_flow')
        self.assertEqual(sell['execution_unknown_episodes'], 1)
        self.assertTrue(sell['episodes'][0]['execution_unknown'])
        self.assertEqual(sell['metrics']['closed_episodes'], 1)
        self.assertEqual(sell['metrics']['known_closed_filled_episodes'], 0)
        self.assertEqual(Decimal(sell['metrics']['closed_net_parity_usd']), 0)
        self.assertIsNone(sell['complete_net'])
        self.assertEqual(result['source_sha256']['scripts/rh_maker_late_flow_guard.py'],
                         symmetric.digest(ROOT / 'scripts/rh_maker_late_flow_guard.py'))


if __name__ == '__main__':
    unittest.main()
