"""Synthetic offline contracts for separate source books, flow, and trust pins."""
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts import passive_three_venue_events as events
from scripts import passive_three_venue_capture as capture

BASE = 1_790_000_000_000_000_000


def row(kind, offset, venue='rh_lighter', market=None, **extra):
    return {'kind': kind, 'venue': venue, 'generation': f'{venue}:1',
            'receipt_utc_ns': BASE + offset * 1_000_000,
            'receipt_monotonic_ns': 10_000_000_000 + offset * 1_000_000,
            'market': market, **extra}


def book(offset, venue='rh_lighter', market='15', *, nonce=1, begin=None, source_offset=None):
    source = BASE + (offset - 20 if source_offset is None else source_offset) * 1_000_000
    body = {'nonce': nonce, 'last_updated_at': source // 1000,
            'bids': [{'price': '100', 'size': '3'}], 'asks': [{'price': '101', 'size': '5'}]}
    if begin is not None:
        body['begin_nonce'] = begin
    return row('frame', offset, venue, market, channel='order_book',
               annotation={'quality': 'wire_ok_snapshot' if begin is None else 'wire_ok',
                           'source_max_ns': source},
               payload={'type': 'subscribed/order_book' if begin is None else 'update/order_book',
                        'channel': f'order_book:{market}', 'order_book': body})


def trade(ident, offset, market=15):
    return {'type': 'trade', 'trade_id_str': str(ident), 'market_id': market,
            'timestamp': BASE // 1_000_000 + offset, 'is_maker_ask': True,
            'price': '100.5', 'size': '2'}


def flow(offset, venue='rh_lighter', market='15', *, trades=None, subscribed=False, **annotation):
    return row('frame', offset, venue, market, channel='trade',
               annotation={'quality': 'wire_ok', **annotation},
               payload={'type': 'subscribed/trade' if subscribed else 'update/trade',
                        'channel': f'trade:{market}', 'nonce': 1000 + offset,
                        'trades': trades if trades is not None else [trade(7, offset - 20, int(market))],
                        'liquidation_trades': [trade(9999, offset - 20, int(market))]})


def market_row(asset, market):
    return {'market_id': int(market), 'symbol': asset, 'status': 'active', 'market_type': 'perp',
            'multiplier': '1', 'quote_multiplier': 1, 'supported_price_decimals': 2,
            'price_decimals': 2, 'supported_size_decimals': 4, 'size_decimals': 4,
            'supported_quote_decimals': 6, 'min_base_amount': '0.01',
            'min_quote_amount': '10', 'order_quote_limit': '1000000',
            'maker_fee': '0', 'taker_fee': '0'}


def fixture(directory, rows):
    directory = Path(directory)
    directory.mkdir()
    metadata = directory / 'metadata'
    metadata.mkdir()
    plan_bytes = capture.DEFAULT_MARKETS.read_bytes()
    (metadata / 'market_plan.json').write_bytes(plan_bytes)
    selected, plan_hash = capture.select_three(metadata / 'market_plan.json')
    bodies = {
        'rh_order_book_details': {'code': 200, 'order_book_details': [
            market_row(a, m) for a, m in selected['rh_lighter'].items()]},
        'core_order_book_details': {'code': 200, 'order_book_details': [
            market_row(a, m) for a, m in selected['lighter'].items()]},
        'rh_asset_details': {'code': 200, 'asset_details': [{'symbol': 'USDG', 'margin_mode': 'enabled'}]},
        'core_asset_details': {'code': 200, 'asset_details': [{'symbol': 'USDC', 'margin_mode': 'enabled'}]},
        'hl_meta_native': {'collateralToken': 0, 'universe': [
            {'name': m, 'szDecimals': 4} for a, m in selected['hyperliquid'].items() if a in ('BTC', 'ETH')]},
        'hl_meta_xyz': {'collateralToken': 0, 'universe': [
            {'name': m, 'szDecimals': 4} for a, m in selected['hyperliquid'].items() if a in ('NVDA', 'XAG')]},
    }
    for name, (method, url, request_body) in capture.REQUESTS.items():
        raw = json.dumps(bodies[name]).encode()
        (metadata / f'{name}.json').write_bytes(raw)
        (metadata / f'{name}.request.json').write_text(json.dumps({
            'name': name, 'method': method, 'url': url, 'json_body': request_body,
            'status': 200, 'raw_file': f'{name}.json', 'raw_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'request_started_utc_ns': BASE - 2_000_000_000,
            'response_completed_utc_ns': BASE - 1_000_000_000}))
    capture.freeze_metadata(metadata, metadata / 'market_plan.json', selected, plan_hash)
    frames = gzip.compress(b''.join(json.dumps(r).encode() + b'\n' for r in rows), mtime=0)
    (directory / 'frames.jsonl.gz').write_bytes(frames)
    manifest = {'schema': 'passive-three-venue-public-capture-v1', 'read_only': True,
                'started_utc': datetime.fromtimestamp(BASE / 1e9, timezone.utc).isoformat(),
                'ended_utc': datetime.fromtimestamp(BASE / 1e9 + 30, timezone.utc).isoformat(),
                'configured_seconds': 30, 'configured_total_bytes': capture.HARD_BYTES,
                'compressed_payload_bytes': len(frames),
                'metadata_bytes': sum(p.stat().st_size for p in metadata.iterdir()),
                'selected_markets': selected, 'market_plan_sha256': plan_hash,
                'payload_records': len(rows), 'frames_sha256': hashlib.sha256(frames).hexdigest(),
                'end_reason': 'duration_limit', 'truncated': False, 'errors': []}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return directory, events.sha256(directory / 'manifest.json')


class ThreeVenueEventsTests(unittest.TestCase):
    def replay(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest = fixture(Path(tmp) / 'capture', rows)
            return list(events.iter_events(directory, expected_manifest_sha256=digest, **kwargs))

    def test_separate_books_and_common_flow_keep_own_market_role_and_fees(self):
        rows = [row('connection_open', 0), row('connection_open', 1, 'lighter'),
                row('connection_open', 2, 'hyperliquid'), book(100),
                book(110, 'lighter', '110'),
                row('frame', 120, 'hyperliquid', 'xyz:NVDA', channel='l2Book',
                    annotation={'quality': 'wire_ok', 'source_max_ns': BASE + 100_000_000},
                    payload={'channel': 'l2Book', 'data': {'coin': 'xyz:NVDA',
                             'time': BASE // 1_000_000 + 100,
                             'levels': [[{'px': '100', 'sz': '3'}], [{'px': '101', 'sz': '4'}]]}}),
                flow(200, subscribed=True), flow(210, 'lighter', '110', subscribed=True),
                flow(300), flow(310, 'lighter', '110'),
                row('frame', 320, 'hyperliquid', 'xyz:NVDA', channel='trades',
                    annotation={'quality': 'wire_ok'}, payload={'channel': 'trades', 'data': [
                        {'coin': 'xyz:NVDA', 'side': 'A', 'tid': 7, 'px': '100.5', 'sz': '2',
                         'time': BASE // 1_000_000 + 300}]}),
                flow(400, trades=[trade(7, 280)]),
                flow(410, 'lighter', '110', trades=[trade(7, 290, 110)])]
        result = self.replay(rows, hedge_venue='lighter')
        books = [e for e in result if e['type'] == 'book']
        self.assertEqual([e['source_venue'] for e in books], ['rh_lighter', 'lighter', 'hyperliquid'])
        core = books[1]
        self.assertEqual((core['venue'], core['source_market'], core['market'], core['role']),
                         ('lighter', '110', '110', 'hedge'))
        trades = [e for e in result if e['type'] == 'trade']
        self.assertEqual([e['source_venue'] for e in trades], ['rh_lighter', 'lighter', 'hyperliquid'])
        self.assertEqual([e['trade_id'] for e in trades], [7, 7, 7])
        self.assertEqual(result[-1]['counts']['duplicate_trade_ids:lighter'], 1)
        self.assertTrue(result[-1]['manifest_sha_verified'])
        self.assertEqual(result[-1]['metadata']['markets']['lighter']['NVDA']['taker_fee_bps'], '0')
        self.assertEqual([e['received_ns'] for e in result], sorted(e['received_ns'] for e in result))

    def test_nonce_gap_invalidates_core_only_and_requires_new_snapshot(self):
        result = self.replay([row('connection_open', 0), row('connection_open', 1, 'lighter'),
                              book(100), book(110, 'lighter', '110'),
                              book(200, 'lighter', '110', nonce=3, begin=2),
                              book(210, 'lighter', '110', nonce=4, begin=3),
                              book(220, nonce=2, begin=1), book(300, 'lighter', '110', nonce=5)])
        invalid = [e for e in result if e['type'] == 'invalidate' and e['scope'] == 'book']
        self.assertTrue(any(e['reason'] == 'nonce_gap' and e['source_venue'] == 'lighter' for e in invalid))
        self.assertFalse(any(e['reason'] == 'nonce_gap' and e['source_venue'] == 'rh_lighter' for e in invalid))
        self.assertEqual(len([e for e in result if e['type'] == 'book']), 4)

    def test_future_book_cannot_seed_delta(self):
        result = self.replay([row('connection_open', 0, 'lighter'),
                              book(100, 'lighter', '110', source_offset=200),
                              book(300, 'lighter', '110', nonce=2, begin=1)])
        self.assertFalse([e for e in result if e['type'] == 'book'])
        self.assertTrue(any(e.get('reason') == 'invalid_source_or_clock' for e in result))
        self.assertTrue(any(e.get('reason') == 'delta_without_snapshot' for e in result))

    def test_regressing_book_time_is_invalid_without_trusting_capture_flag(self):
        result = self.replay([row('connection_open', 0, 'lighter'),
                              book(100, 'lighter', '110'),
                              book(200, 'lighter', '110', nonce=2, begin=1, source_offset=70)])
        self.assertEqual(len([e for e in result if e['type'] == 'book']), 1)
        self.assertTrue(any(e.get('reason') == 'book_source_regression' for e in result))

    def test_core_trade_own_id_required_and_bad_batch_censors_only_core(self):
        result = self.replay([row('connection_open', 0), row('connection_open', 1, 'lighter'),
                              flow(200, 'lighter', '110', trades=[trade(1, 150, 15)]),
                              flow(300, 'lighter', '110'), flow(400)])
        self.assertEqual([e['source_venue'] for e in result if e['type'] == 'trade'], ['rh_lighter'])
        self.assertTrue(any('identity differs' in e.get('reason', '') for e in result))
        self.assertEqual(result[-1]['counts']['suppressed_trade_frames_after_invalidation'], 1)

    def test_close_error_invalidates_all_scopes_and_cannot_revive_generation(self):
        for kind in ('connection_close', 'connection_error', 'invalid_json', 'generation_invalidated'):
            with self.subTest(kind=kind):
                result = self.replay([row('connection_open', 0, 'lighter'), book(100, 'lighter', '110'),
                                      flow(200, 'lighter', '110'), row(kind, 300, 'lighter'),
                                      book(400, 'lighter', '110'), flow(500, 'lighter', '110')])
                self.assertEqual(len([e for e in result if e['type'] == 'book']), 1)
                self.assertEqual(len([e for e in result if e['type'] == 'trade']), 1)
                self.assertTrue(any(e.get('reason') == kind and e.get('scope') == 'book' for e in result))
                self.assertTrue(any(e.get('reason') == kind and e.get('scope') == 'trade' for e in result))

    def test_generation_change_dedupe_resets_without_book_splicing(self):
        new_open = dict(row('connection_open', 300, 'lighter'), generation='lighter:2')
        new_trade = dict(flow(400, 'lighter', '110'), generation='lighter:2')
        new_delta = dict(book(500, 'lighter', '110', nonce=2, begin=1), generation='lighter:2')
        result = self.replay([row('connection_open', 0, 'lighter'), book(100, 'lighter', '110'),
                              flow(200, 'lighter', '110'), new_open, new_trade, new_delta])
        self.assertEqual([e['source_generation'] for e in result if e['type'] == 'trade'],
                         ['lighter:1', 'lighter:2'])
        self.assertEqual(len([e for e in result if e['type'] == 'book']), 1)
        self.assertTrue(any(e.get('reason') == 'generation_change'
                            and e['source_generation'] == 'lighter:1' for e in result))

    def test_duplicate_in_batch_dedup_and_capacity_fail_before_partial_emit(self):
        rows = [row('connection_open', 0), flow(200, trades=[trade(1, 150), trade(1, 150)])]
        result = self.replay(rows)
        self.assertEqual(len([e for e in result if e['type'] == 'trade']), 1)
        self.assertEqual(result[-1]['counts']['duplicate_trade_ids:rh_lighter'], 1)
        result = self.replay([row('connection_open', 0), flow(200, trades=[trade(1, 150), trade(2, 150)])], max_ids=1)
        self.assertFalse([e for e in result if e['type'] == 'trade'])
        self.assertTrue(any(e.get('reason') == 'dedup_capacity_exceeded' for e in result))

    def test_hash_pins_reject_before_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest = fixture(Path(tmp) / 'capture', [row('connection_open', 0)])
            with self.assertRaisesRegex(ValueError, 'manifest: SHA-256 mismatch'):
                next(events.iter_events(directory, expected_manifest_sha256='0' * 64))
            with self.assertRaisesRegex(ValueError, 'external gzip: SHA-256 mismatch'):
                next(events.iter_events(directory, expected_manifest_sha256=digest, expected_raw_sha256='0' * 64))
            core_path = directory / 'metadata' / 'core_order_book_details.json'
            core_path.write_bytes(core_path.read_bytes().replace(b'"multiplier": "1"', b'"multiplier": "2"', 1))
            with self.assertRaisesRegex(ValueError, 'SHA-256 differs'):
                next(events.iter_events(directory, expected_manifest_sha256=digest))

    def test_stale_six_response_metadata_and_own_core_market_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest = fixture(Path(tmp) / 'capture', [])
            metadata = directory / 'metadata'
            path = metadata / 'core_order_book_details.request.json'
            provenance = json.loads(path.read_text())
            provenance['request_started_utc_ns'] = BASE - 1901_000_000_000
            provenance['response_completed_utc_ns'] = BASE - 1900_000_000_000
            path.write_text(json.dumps(provenance))
            selected, plan_hash = capture.select_three(metadata / 'market_plan.json')
            (metadata / 'normalized.json').unlink()
            capture.freeze_metadata(metadata, metadata / 'market_plan.json', selected, plan_hash)
            manifest = json.loads((directory / 'manifest.json').read_text())
            manifest['metadata_bytes'] = sum(p.stat().st_size for p in metadata.iterdir())
            (directory / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'metadata stale'):
                next(events.iter_events(directory, expected_manifest_sha256=events.sha256(directory / 'manifest.json')))
            core = json.loads((metadata / 'core_order_book_details.json').read_text())
            core['order_book_details'][2]['market_id'] = 15
            raw = json.dumps(core).encode()
            (metadata / 'core_order_book_details.json').write_bytes(raw)
            provenance['raw_bytes'] = len(raw)
            provenance['sha256'] = hashlib.sha256(raw).hexdigest()
            path.write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError, 'Core market identity'):
                capture.normalize_metadata(metadata, selected, plan_hash)

    def test_payload_caps_and_receipt_order_fail_closed(self):
        rows = [row('connection_open', 0), book(100)]
        with self.assertRaisesRegex(ValueError, 'decoded payload'):
            self.replay(rows, max_decoded_bytes=10)
        with self.assertRaisesRegex(ValueError, 'record count'):
            self.replay(rows, max_records=1)
        with self.assertRaisesRegex(ValueError, 'archive exceeds'):
            self.replay(rows, max_raw_bytes=10)
        with self.assertRaisesRegex(ValueError, 'moved backward'):
            self.replay([row('connection_open', 100), row('connection_close', 50)])

    def test_future_trade_batch_rejects_all_and_network_assumption_stays_separate(self):
        result = self.replay([row('connection_open', 0, 'lighter'),
                              flow(200, 'lighter', '110', trades=[trade(1, 150, 110), trade(2, 250, 110)])])
        self.assertFalse([e for e in result if e['type'] == 'trade'])
        metadata = result[-1]['metadata']
        core = events.hedge_execution_assumptions(metadata, 'lighter', network_delay_ms=70)
        hl = events.hedge_execution_assumptions(metadata, 'hyperliquid', network_delay_ms=70)
        self.assertEqual((core['processing_delay_ms'], core['network_delay_ms'], core['total_assumed_delay_ms']),
                         ('300', '70', '370'))
        self.assertEqual(hl['processing_delay_ms'], '150')
        self.assertEqual(core['fees_by_asset']['NVDA']['market'], '110')
        with self.assertRaisesRegex(ValueError, 'delay assumption'):
            events.hedge_execution_assumptions(metadata, 'lighter', network_delay_ms=None)


if __name__ == '__main__':
    unittest.main()
