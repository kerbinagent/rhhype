"""Offline contracts for the future three-venue public capture wrapper."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import passive_three_venue_capture as three


def _core_row(asset, market):
    return {'market_id': market, 'symbol': asset, 'status': 'active', 'market_type': 'perp',
            'multiplier': '1.000000000000000000', 'quote_multiplier': 1,
            'supported_price_decimals': 2, 'price_decimals': 2,
            'supported_size_decimals': 4, 'size_decimals': 4,
            'supported_quote_decimals': 6, 'min_base_amount': '0.01',
            'min_quote_amount': '10', 'order_quote_limit': '1000000',
            'maker_fee': '0.0000', 'taker_fee': '0.0000'}


class ThreeVenueTests(unittest.TestCase):
    def test_monitor_route_is_three_distinct_venues(self):
        selected, digest = three.select_three(three.DEFAULT_MARKETS)
        self.assertEqual(selected['rh_lighter']['NVDA'], '15')
        self.assertEqual(selected['lighter']['NVDA'], '110')
        self.assertEqual(selected['hyperliquid']['XAG'], 'xyz:SILVER')
        self.assertEqual(len(digest), 64)

    def test_core_unit_and_identity_validation(self):
        selected, _ = three.select_three(three.DEFAULT_MARKETS)
        rows = [_core_row(a, int(selected['lighter'][a])) for a in three.ASSETS]
        two = {'markets': {'rh_lighter': {a: {} for a in three.ASSETS},
                           'hyperliquid': {a: {} for a in three.ASSETS}},
               'raw_requests': {}, 'sources': {}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in three.TWO_REQUESTS:
                (directory / f'{name}.json').write_text('{}')
                (directory / f'{name}.request.json').write_text('{}')
            def write():
                raw = json.dumps({'code': 200, 'order_book_details': rows}).encode()
                (directory / 'core_order_book_details.json').write_bytes(raw)
                (directory / 'core_order_book_details.request.json').write_text(json.dumps({
                    'method': 'GET', 'url': three.CORE_REQUEST[1], 'json_body': None,
                    'status': 200, 'raw_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}))
                for name, symbol in (('rh_asset_details', 'USDG'), ('core_asset_details', 'USDC')):
                    raw_assets = json.dumps({'code': 200, 'asset_details': [
                        {'symbol': symbol, 'margin_mode': 'enabled'}]}).encode()
                    (directory / f'{name}.json').write_bytes(raw_assets)
                    (directory / f'{name}.request.json').write_text(json.dumps({
                        'method': 'GET', 'url': three.REQUESTS[name][1], 'json_body': None,
                        'status': 200, 'raw_bytes': len(raw_assets),
                        'sha256': hashlib.sha256(raw_assets).hexdigest()}))
            write()
            with patch.object(three, 'normalize_two', return_value=two):
                result = three.normalize_metadata(directory, selected, 'hash')
                self.assertEqual(result['markets']['lighter']['NVDA']['market'], '110')
                self.assertEqual(result['markets']['lighter']['NVDA']['size_step'], '0.0001')
                rows[2]['multiplier'] = '1.1'
                write()
                with self.assertRaisesRegex(ValueError, 'multiplier'):
                    three.normalize_metadata(directory, selected, 'hash')
                rows[2]['multiplier'] = '1'
                rows[2]['symbol'] = 'AAPL'
                write()
                with self.assertRaisesRegex(ValueError, 'identity'):
                    three.normalize_metadata(directory, selected, 'hash')

    def test_trade_ids_dedupe_by_venue_market_generation(self):
        quality = three.ThreeVenueQuality()
        def frame(trade_id):
            return {'type': 'update/trade', 'channel': 'trade:1',
                    'trades': [{'trade_id_str': str(trade_id), 'timestamp': 1790730000000}],
                    'liquidation_trades': []}
        first = quality.inspect('rh_lighter', frame(7), 'rh_lighter:1')
        duplicate = quality.inspect('rh_lighter', frame(7), 'rh_lighter:1')
        core = quality.inspect('lighter', frame(7), 'lighter:1')
        next_generation = quality.inspect('rh_lighter', frame(7), 'rh_lighter:2')
        self.assertEqual(first['new_trade_ids'], 1)
        self.assertEqual(duplicate['duplicate_trade_ids'], 1)
        self.assertEqual(core['new_trade_ids'], 1)
        self.assertEqual(next_generation['new_trade_ids'], 1)
        self.assertEqual(quality.seen_count, 3)

    def test_bounds_and_dry_plan_no_socket(self):
        self.assertEqual(three.HARD_SECONDS, 3000)
        self.assertEqual(three.HARD_BYTES, 384_000_000)
        self.assertEqual(three.VENUES, ('rh_lighter', 'hyperliquid', 'lighter'))


if __name__ == '__main__':
    unittest.main()
