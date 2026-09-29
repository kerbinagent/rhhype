"""Offline checks for the bounded RH/HL maker research collector."""

import asyncio
import gzip
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rh_maker_capture import (
    ASSETS, REQUESTS, RhMakerCapture, bounded_response, capture,
    freeze_normalization, normalize_metadata, selected_markets, subscriptions,
    valid_hl_ack, verify_metadata,
)


IDS = {'BTC': ('BTC', 1), 'ETH': ('ETH', 0),
       'NVDA': ('xyz:NVDA', 15), 'XAG': ('xyz:SILVER', 41)}


def fixture(root: Path):
    plan = root / 'plan.json'
    plan.write_text(json.dumps({'pairs': [
        {'asset': asset,
         'hl': {'venue': 'hyperliquid', 'asset': asset, 'market': hl},
         'other': {'venue': 'rh_lighter', 'asset': asset, 'market': rh}}
        for asset, (hl, rh) in IDS.items()]}))
    selected, plan_hash = selected_markets(plan)
    meta = root / 'metadata'
    meta.mkdir()
    rh_rows = []
    for asset, (_, market_id) in IDS.items():
        decimals = {'BTC': (1, 5), 'ETH': (2, 4),
                    'NVDA': (2, 4), 'XAG': (4, 2)}[asset]
        rh_rows.append({'symbol': asset, 'market_id': market_id,
                        'market_type': 'perp', 'status': 'active',
                        'multiplier': '1', 'quote_multiplier': 1,
                        'supported_price_decimals': decimals[0],
                        'price_decimals': decimals[0],
                        'supported_size_decimals': decimals[1],
                        'size_decimals': decimals[1],
                        'supported_quote_decimals': sum(decimals),
                        'min_base_amount': '0.01', 'min_quote_amount': '10',
                        'order_quote_limit': '100000',
                        'maker_fee': '0.0000', 'taker_fee': '0.0000'})
    bodies = {
        'rh_order_book_details': {'code': 200, 'order_book_details': rh_rows},
        'hl_meta_native': {'collateralToken': 0, 'universe': [
            {'name': 'BTC', 'szDecimals': 5}, {'name': 'ETH', 'szDecimals': 4}]},
        'hl_meta_xyz': {'collateralToken': 0, 'universe': [
            {'name': 'xyz:NVDA', 'szDecimals': 3, 'growthMode': 'enabled',
             'deployerFeeScale': '1'},
            {'name': 'xyz:SILVER', 'szDecimals': 2, 'growthMode': 'enabled',
             'deployerFeeScale': '1'}]},
    }
    for name, (method, url, body) in REQUESTS.items():
        raw = json.dumps(bodies[name]).encode()
        (meta / f'{name}.json').write_bytes(raw)
        (meta / f'{name}.request.json').write_text(json.dumps({
            'name': name, 'method': method, 'url': url, 'json_body': body,
            'request_started_utc_ns': 1, 'response_completed_utc_ns': 2,
            'status': 200, 'raw_file': f'{name}.json', 'raw_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}))
    normalized = freeze_normalization(meta, selected, plan_hash, plan)
    return plan, meta, selected, plan_hash, normalized


class Response:
    def __init__(self, chunks):
        self.chunks = chunks
        self.content = self

    async def iter_chunked(self, _):
        for chunk in self.chunks:
            yield chunk


class RhMakerCaptureTests(unittest.TestCase):
    def test_public_subscriptions_are_only_fast_l2_trades_rh_full_book_trades(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, selected, _, _ = fixture(Path(temp))
            hl = subscriptions('hyperliquid', selected['hyperliquid'])
            rh = subscriptions('rh_lighter', selected['rh_lighter'])
            self.assertEqual(len(hl), 8)
            self.assertEqual(len(rh), 8)
            self.assertEqual({row['subscription']['type'] for row in hl},
                             {'l2Book', 'trades'})
            self.assertTrue(all(row['subscription']['fast'] is True for row in hl[:4]))
            self.assertTrue(all(row['subscription']['type'] == 'trades' for row in hl[4:]))
            self.assertEqual({row['channel'].split('/')[0] for row in rh},
                             {'order_book', 'trade'})
            self.assertTrue(valid_hl_ack({'data': {'subscription':
                {'type': 'l2Book', 'coin': 'BTC', 'fast': True}}},
                selected['hyperliquid']))
            self.assertFalse(valid_hl_ack({'data': {'subscription':
                {'type': 'l2Book', 'coin': 'BTC', 'fast': False}}},
                selected['hyperliquid']))
            self.assertFalse(valid_hl_ack({'data': {'subscription':
                {'type': 'l2Book', 'coin': 'BTC'}}},
                selected['hyperliquid']))

    def test_metadata_fails_closed_and_preserves_explicit_grid_and_fees(self):
        with tempfile.TemporaryDirectory() as temp:
            _, meta, selected, plan_hash, normalized = fixture(Path(temp))
            self.assertEqual(set(normalized['markets']['rh_lighter']), set(ASSETS))
            self.assertEqual(normalized['markets']['rh_lighter']['XAG']['price_tick'], '0.0001')
            self.assertEqual(normalized['markets']['rh_lighter']['NVDA']['max_qty'], None)
            self.assertEqual(normalized['markets']['hyperliquid']['NVDA']['price_tick_semantics'],
                             'hl_perp')
            self.assertEqual(Decimal(normalized['markets']['hyperliquid']['NVDA']['taker_fee_bps']),
                             Decimal('0.9'))
            self.assertEqual(verify_metadata(meta, selected, plan_hash), normalized)
            raw = meta / 'rh_order_book_details.json'
            changed = raw.read_bytes()
            raw.write_bytes(b'[' + changed[1:])
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                normalize_metadata(meta, selected, plan_hash)

    def test_metadata_network_body_is_bounded_before_join(self):
        self.assertEqual(asyncio.run(bounded_response(Response([b'a', b'b']), 2)), b'ab')
        with self.assertRaisesRegex(ValueError, '5 MB'):
            asyncio.run(bounded_response(Response([b'ab', b'c']), 2))

    def test_terminal_signal_manifest_has_hash_and_copied_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, meta, selected, plan_hash, normalized = fixture(root)
            args = SimpleNamespace(out=root / 'output', metadata_dir=meta,
                                   seconds=3, max_bytes=1_500_000, markets=plan)

            async def fake_loop(run, venue):
                if venue == 'hyperliquid':
                    run.record({'kind': 'frame', 'venue': venue, 'market': 'BTC',
                                'channel': 'l2Book', 'generation': 'test',
                                'receipt_utc_ns': 1, 'annotation': {'source_max_ns': 1},
                                'payload': {'channel': 'l2Book'}})
                    run.finish('signal_sigint')
                else:
                    await run.stop.wait()

            with patch.object(RhMakerCapture, 'venue_loop', fake_loop):
                asyncio.run(capture(args, selected, plan_hash, normalized))
            manifest = json.loads((args.out / 'manifest.json').read_bytes())
            raw = (args.out / 'frames.jsonl.gz').read_bytes()
            self.assertEqual(manifest['end_reason'], 'signal_sigint')
            self.assertFalse(manifest['truncated'])
            self.assertEqual(manifest['frames_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(len(gzip.decompress(raw).splitlines()), 1)
            self.assertTrue((args.out / 'metadata/normalized.json').exists())
            self.assertEqual(manifest['calibration_seconds'], 3)
            self.assertEqual(manifest['holdout_seconds'], 0)
            self.assertLessEqual(sum(p.stat().st_size for p in args.out.rglob('*')
                                     if p.is_file()), args.max_bytes)

    def test_size_cap_still_writes_valid_terminal_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, meta, selected, plan_hash, normalized = fixture(root)
            args = SimpleNamespace(out=root / 'output', metadata_dir=meta,
                                   seconds=3, max_bytes=1_100_000, markets=plan)
            incompressible = os.urandom(150_000).hex()

            async def fake_loop(run, venue):
                if venue == 'hyperliquid':
                    run.record({'kind': 'frame', 'venue': venue, 'market': 'BTC',
                                'channel': 'l2Book', 'payload': incompressible})
                else:
                    await run.stop.wait()

            with patch.object(RhMakerCapture, 'venue_loop', fake_loop):
                asyncio.run(capture(args, selected, plan_hash, normalized))
            manifest = json.loads((args.out / 'manifest.json').read_bytes())
            self.assertEqual(manifest['end_reason'], 'compressed_size_cap')
            self.assertTrue(manifest['truncated'])
            self.assertEqual(manifest['dropped_complete_frame_on_cap'], 1)
            self.assertLessEqual(sum(p.stat().st_size for p in args.out.rglob('*')
                                     if p.is_file()), args.max_bytes)


if __name__ == '__main__':
    unittest.main()
