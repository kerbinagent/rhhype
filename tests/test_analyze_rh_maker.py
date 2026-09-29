"""Offline end-to-end checks for the frozen RH maker replay coordinator."""
from __future__ import annotations

import copy
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_rh_maker
from scripts.maker_capture import BoundedGzip, SizeCapReached
from scripts.rh_maker_config import policy_metadata
from scripts.rh_maker_engine import Rules
from scripts.rh_maker_model import RhMakerModel


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'reports/rh-small-maker-v1/metadata'
NS = analyze_rh_maker.NS
START = 1_790_640_000 * NS  # 2026-09-29 00:00:00 UTC
CUTOFF = START + 1_800 * NS
END = START + 3_000 * NS


def book(venue, received_ns, *, bids=None, asks=None):
    return {
        'type': 'book', 'asset': 'BTC', 'venue': venue, 'generation': 'g',
        'received_ns': received_ns, 'source_ns': received_ns,
        'valid': True, 'clock_valid': True,
        'bids': bids or ([[100, .5], [99.9, 20]] if venue == 'rh_lighter'
                         else [[100.2, 20], [100.1, 20]]),
        'asks': asks or ([[100.4, 20], [100.5, 20]] if venue == 'rh_lighter'
                         else [[100.3, 20], [100.4, 20]]),
    }


def events(*, fill=True):
    # A few receipt-ordered observations span the prescribed 30-minute
    # calibration and 20-minute holdout; no wall-clock sleep or private data.
    rows = [book('rh_lighter', START), book('hyperliquid', START),
            book('rh_lighter', CUTOFF), book('hyperliquid', CUTOFF),
            book('rh_lighter', CUTOFF + 400_000_000)]
    if fill:
        rows += [
            {'type': 'trade', 'asset': 'BTC', 'venue': 'rh_lighter',
             'generation': 'g', 'received_ns': CUTOFF + 500_000_000,
             'source_ns': CUTOFF + 500_000_000, 'clock_valid': True,
             'price': 100, 'qty': 100, 'trade_id': '1', 'side': 'sell'},
            book('hyperliquid', CUTOFF + 700_000_000),
            book('rh_lighter', CUTOFF + 900_000_000),
            # Shallow HL bid prevents a new quote after the completed exit;
            # the deep ask still supports the existing short's buyback.
            book('hyperliquid', CUTOFF + 11_200_000_000,
                 bids=[[100.2, .001], [100.1, .001]]),
            book('rh_lighter', CUTOFF + 11_200_000_000,
                 bids=[[102, 20], [101.9, 20]],
                 asks=[[102.4, 20], [102.5, 20]]),
        ]
    else:
        rows += [book('rh_lighter', CUTOFF + 5_500_000_000),
                 book('rh_lighter', CUTOFF + 6_000_000_000)]
    rows.append({'type': 'end', 'received_ns': END, 'truncated': False})
    return rows


def branch(result, tier='standard'):
    return next(row for row in result['branches']
                if row['asset'] == 'BTC' and row['budget_usd'] == '1000'
                and row['policy'] == 'fixed_best' and row['tier'] == tier)


class AnalyzeRhMakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.capture = self.base / 'capture'
        self.capture.mkdir()
        shutil.copytree(FROZEN, self.capture / 'metadata')
        manifest = {
            'schema': 'rh-maker-public-capture-v1', 'read_only': True,
            'configured_seconds': 3000, 'calibration_seconds': 1800,
            'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
            'started_utc': '2026-09-29T00:00:00+00:00',
            'ended_utc': '2026-09-29T00:50:00+00:00',
            'end_reason': 'duration_limit', 'frames_sha256': '0' * 64,
            'metadata_normalized_sha256': hashlib.sha256(
                (self.capture / 'metadata/normalized.json').read_bytes()).hexdigest(),
        }
        (self.capture / 'manifest.json').write_text(json.dumps(manifest))

    def run_replay(self, rows, name='derived', **kwargs):
        return analyze_rh_maker.replay(self.capture, self.base / name,
                                       events=rows, **kwargs)

    def test_frozen_metadata_96_branches_and_closed_fee_reserve_capital_math(self):
        result = self.run_replay(events(fill=True))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['branches']), 96)
        self.assertEqual(len({(r['tier'], r['asset'], r['budget_usd'], r['policy'])
                              for r in result['branches']}), 96)
        self.assertEqual(result['cutoff_ns'], CUTOFF)
        self.assertEqual(result['ended_ns'], END)
        self.assertTrue(all(m['frozen'] for m in result['models'].values()))
        for tier in ('standard', 'premium'):
            self.assertEqual(set(result['metadata'][tier]), {'BTC', 'ETH', 'NVDA', 'XAG'})
            for asset in ('BTC', 'ETH', 'NVDA', 'XAG'):
                market = result['metadata'][tier][asset]
                self.assertEqual(market['rh']['collateral'], 'USDG')
                self.assertEqual(market['hl']['collateral'], 'USDC')
                self.assertEqual(Decimal(market['rh']['contract_multiplier']), 1)
                self.assertGreater(Decimal(market['rh']['qty_step']), 0)
                self.assertGreater(Decimal(market['hl']['qty_step']), 0)
                self.assertEqual(Decimal(market['hl']['taker_fee_bps']),
                                 Decimal('4.5' if asset in ('BTC', 'ETH') else '0.9'))
                self.assertEqual(Decimal(market['rh']['maker_fee_bps']),
                                 Decimal('0' if tier == 'standard' else '1.2'))

        standard, premium = branch(result), branch(result, 'premium')
        for row in (standard, premium):
            self.assertEqual(len(row['episodes']), 1)
            self.assertGreaterEqual(row['episodes'][0]['decided_ns'], CUTOFF)
            self.assertTrue(row['episodes'][0]['full_flow'])
            self.assertEqual(Decimal(row['rh_position']), 0)
            self.assertEqual(Decimal(row['hl_position']), 0)
            self.assertIsNone(row['unknown_reason'])
            self.assertEqual(row['metrics']['known_closed_filled_episodes'], 1)
            self.assertEqual(row['metrics']['total_result_known'], True)

        # Independently price the actual attributed base and executed legs.
        q = Decimal('9.96015')
        self.assertEqual(Decimal(standard['episodes'][0]['maker_attributed']), q)
        gross = q * (Decimal('100.2') - 100 + 102 - Decimal('100.3'))
        hl_fees = q * (Decimal('100.2') + Decimal('100.3')) * Decimal('4.5') / 10_000
        reserve = q * Decimal('100.2') * 5 / 10_000
        annual_seconds = Decimal(365 * 24 * 3600)
        capital = (q * 100 * Decimal('.2')
                   + q * (100 + Decimal('100.2')) * Decimal('10.5')) \
                  * Decimal('.05') / annual_seconds
        expected_standard = gross - hl_fees - reserve - capital
        self.assertEqual(Decimal(standard['fees_hl']), hl_fees)
        self.assertEqual(Decimal(standard['fees_rh']), 0)
        self.assertEqual(Decimal(standard['reserve_cost']), reserve)
        self.assertEqual(Decimal(standard['capital_cost']), capital)
        self.assertEqual(Decimal(standard['complete_net']), expected_standard)
        self.assertEqual(Decimal(standard['metrics']['closed_net_parity_usd']), expected_standard)
        premium_rh_fees = q * 100 * Decimal('1.2') / 10_000 \
                          + q * 102 * Decimal('3.5') / 10_000
        self.assertEqual(Decimal(premium['fees_rh']), premium_rh_fees)
        self.assertEqual(Decimal(premium['complete_net']), expected_standard - premium_rh_fees)

        # Rows are independent counterfactual portfolios conditional on parity.
        self.assertNotIn('combined_net', result)
        self.assertIn('parity', result['assumptions']['combined_usd_net'])
        report = (self.base / 'derived/REPORT.md').read_text()
        self.assertIn('Do not sum', report)
        with gzip.open(self.base / 'derived/audit.jsonl.gz', 'rt') as stream:
            audit = [json.loads(line) for line in stream]
        self.assertEqual(len(audit), result['audit_records'])
        observed = {r['event'] for r in audit if r['asset'] == 'BTC'
                    and r['budget_usd'] == 1000 and r['policy'] == 'fixed_best'
                    and r['tier'] == 'standard'}
        self.assertTrue({'maker_increment', 'hedge_result', 'exit_result',
                         'episode_flat'}.issubset(observed))

    def test_no_public_seller_flow_has_zero_closed_cash_and_no_fill(self):
        result = self.run_replay(events(fill=False))
        row = branch(result)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(row['counts'].get('maker_increment', 0), 0)
        self.assertEqual(row['metrics']['no_flow_episodes'], 1)
        self.assertEqual(row['metrics']['known_closed_filled_episodes'], 0)
        self.assertEqual(Decimal(row['complete_net']), 0)
        self.assertEqual(Decimal(row['fees_hl']), 0)
        self.assertEqual(Decimal(row['reserve_cost']), 0)
        self.assertEqual(Decimal(row['capital_cost']), 0)

    def test_metadata_digest_change_and_repeated_tier_fail_before_output(self):
        manifest_path = self.capture / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['metadata_normalized_sha256'] = 'f' * 64
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'metadata digest'):
            self.run_replay(events(), name='bad_hash')
        self.assertFalse((self.base / 'bad_hash').exists())
        manifest['metadata_normalized_sha256'] = hashlib.sha256(
            (self.capture / 'metadata/normalized.json').read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'tiers'):
            self.run_replay(events(), name='duplicate_tier',
                            tiers=('standard', 'standard'))
        self.assertFalse((self.base / 'duplicate_tier').exists())

    def test_frozen_raw_metadata_tamper_fails_before_branch_construction(self):
        raw = self.capture / 'metadata/rh_order_book_details.json'
        raw.write_bytes(raw.read_bytes() + b' ')
        result = self.run_replay(events(), name='tampered_raw')
        self.assertEqual(result['status'], 'replay_error')
        self.assertEqual(result['branches'], [])
        self.assertTrue(any('raw metadata integrity failure' in e
                            for e in result['errors']))

    def test_audit_cap_preserves_unhedged_inventory_as_unknown(self):
        class CapAfterMakerFill(BoundedGzip):
            def write(self, row):
                if (row.get('event') == 'hedge_scheduled'
                        and row.get('asset') == 'BTC'
                        and row.get('budget_usd') == 1000
                        and row.get('policy') == 'fixed_best'
                        and row.get('tier') == 'standard'):
                    raise SizeCapReached
                return super().write(row)

        with patch.object(analyze_rh_maker, 'BoundedGzip', CapAfterMakerFill):
            result = self.run_replay(events(fill=True), name='capped')
        row = branch(result)
        self.assertEqual(result['status'], 'audit_size_cap')
        self.assertGreater(Decimal(row['rh_position']), 0)
        self.assertEqual(Decimal(row['hl_position']), 0)
        self.assertIsNone(row['complete_net'])
        self.assertEqual(row['unknown_reason'], 'audit_size_cap')
        self.assertFalse(row['metrics']['total_result_known'])
        self.assertIn('unknown', (self.base / 'capped/REPORT.md').read_text())
        self.assertTrue((self.base / 'capped/analysis.json').exists())

    def test_receipt_regression_after_public_maker_flow_is_censored(self):
        rows = events(fill=True)
        rows.insert(6, book('hyperliquid', CUTOFF + 450_000_000))
        result = self.run_replay(rows, name='bad_order')
        row = branch(result)
        self.assertEqual(result['status'], 'replay_error')
        self.assertTrue(any('receipt order' in e for e in result['errors']))
        self.assertGreater(Decimal(row['rh_position']), 0)
        self.assertIsNone(row['complete_net'])
        self.assertEqual(row['unknown_reason'], 'replay_error')

    def test_calibration_reaches_adaptive_readiness_without_fit_injection(self):
        # 80 anchors, six receipt-ordered events each, cover nearly 20 minutes
        # of the declared 30-minute calibration. The first post-due HL book
        # resolves flow; the first paired 10–16 s books resolve closing marks.
        metadata = {'BTC': policy_metadata(self.capture / 'metadata')['BTC']}
        model = RhMakerModel(metadata, START)
        for i in range(80):
            anchor = START + (1 + 15 * i) * NS
            model.consume(book('rh_lighter', anchor))
            model.consume(book('hyperliquid', anchor))
            trade_at = anchor + 1_000_000
            model.consume({'type': 'trade', 'asset': 'BTC', 'venue': 'rh_lighter',
                           'generation': 'g', 'received_ns': trade_at,
                           'source_ns': trade_at, 'clock_valid': True,
                           'price': 100, 'qty': 1, 'trade_id': str(i),
                           'side': 'sell'})
            model.consume(book('hyperliquid', anchor + 201_000_000))
            close_at = anchor + 10_500_000_000
            model.consume(book('rh_lighter', close_at,
                               bids=[[102, 20], [101.9, 20]],
                               asks=[[102.4, 20], [102.5, 20]]))
            model.consume(book('hyperliquid', close_at))

        holdout = CUTOFF + NS
        model.consume(book('rh_lighter', holdout))  # Natural first holdout event freezes the fit.
        fit = model.fit
        route = fit['routes']['BTC|1000']
        self.assertTrue(route['flow_ready'])
        self.assertTrue(route['close_ready'])
        self.assertTrue(route['ready'])
        self.assertEqual((route['flow_admitted'], route['flow_resolved']), (80, 80))
        self.assertEqual((route['close_admitted'], route['close_resolved']), (81, 80))
        self.assertGreaterEqual(route['flow_resolved'], 20)
        self.assertGreaterEqual(route['close_resolved'], 30)
        self.assertGreaterEqual(route['flow_span_seconds'], 600)
        self.assertGreaterEqual(route['close_span_seconds'], 600)
        self.assertGreaterEqual(route['flow_coverage'], .5)
        self.assertGreaterEqual(route['close_coverage'], .5)
        self.assertEqual(fit['cutoff_ns'], CUTOFF)

        model.consume(book('hyperliquid', holdout))
        quote = model.quote('BTC', 1000, 'adaptive', now_ns=holdout)
        self.assertEqual(quote['reason'], 'quote')
        self.assertGreaterEqual(quote['forecast_net_usd'], .10)
        rh_rules = Rules.parse(metadata['BTC']['rh'])
        price = Decimal(str(quote['price']))
        quantity = Decimal(str(quote['quantity']))
        self.assertTrue(rh_rules.valid_price(price))
        self.assertTrue(rh_rules.valid_order(quantity, price))
        self.assertLess(price, Decimal('100.4'))
        self.assertLessEqual(price * quantity, Decimal('1000'))

        frozen = copy.deepcopy(fit)
        moved = holdout + NS
        model.consume(book('rh_lighter', moved,
                           bids=[[98, 20], [97.9, 20]],
                           asks=[[98.4, 20], [98.5, 20]]))
        model.consume(book('hyperliquid', moved,
                           bids=[[105, 20], [104.9, 20]],
                           asks=[[105.3, 20], [105.4, 20]]))
        model.consume({'type': 'trade', 'asset': 'BTC', 'venue': 'rh_lighter',
                       'generation': 'g', 'received_ns': moved + 1_000_000,
                       'source_ns': moved + 1_000_000, 'clock_valid': True,
                       'price': 98, 'qty': 1, 'trade_id': 'holdout', 'side': 'sell'})
        model.consume(book('hyperliquid', moved + 201_000_000,
                           bids=[[104, 20], [103.9, 20]],
                           asks=[[104.3, 20], [104.4, 20]]))
        self.assertIs(model.fit, fit)
        self.assertEqual(model.fit, frozen)


if __name__ == '__main__':
    unittest.main()
