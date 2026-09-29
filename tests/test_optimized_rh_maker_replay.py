"""Original versus post-freeze cached replay on the same synthetic events."""

import copy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import analyze_rh_maker
from scripts.optimized_rh_maker_replay import cached_book_parse, replay_optimized
from scripts.rh_maker_engine import Book


ROOT = Path(__file__).resolve().parents[1]
FROZEN_METADATA = ROOT / 'reports/rh-small-maker-v1/metadata'
NS = 1_000_000_000
START = 1_790_640_000 * NS
CUTOFF = START + 1_800 * NS
END = START + 3_000 * NS
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')


def book(asset, venue, when, *, bids=None, asks=None):
    rh = venue == 'rh_lighter'
    return {'type': 'book', 'asset': asset, 'venue': venue,
            'generation': f'{venue}:generation-1', 'received_ns': when,
            'source_ns': when, 'clock_valid': True, 'valid': True,
            'bids': bids if bids is not None else
            ([[100, 20], [99.9, 20]] if rh else [[100.2, 20], [100.1, 20]]),
            'asks': asks if asks is not None else
            ([[100.4, 20], [100.5, 20]] if rh else [[100.3, 20], [100.4, 20]])}


def synthetic_events():
    rows = []
    for asset in ASSETS:
        rows.extend((book(asset, 'rh_lighter', START),
                     book(asset, 'hyperliquid', START)))
    for index, asset in enumerate(ASSETS):
        t = CUTOFF + index * 25 * NS
        rows.extend([
            book(asset, 'rh_lighter', t),
            book(asset, 'hyperliquid', t),
            book(asset, 'rh_lighter', t + 400_000_000),
            {'type': 'trade', 'asset': asset, 'venue': 'rh_lighter',
             'generation': 'rh_lighter:generation-1',
             'received_ns': t + 500_000_000,
             'source_ns': t + 500_000_000, 'clock_valid': True,
             'price': 100, 'qty': 100, 'trade_id': f'{asset}-1', 'side': 'sell'},
            book(asset, 'hyperliquid', t + 700_000_000),
            book(asset, 'rh_lighter', t + 900_000_000),
            book(asset, 'hyperliquid', t + 11_200_000_000,
                 bids=[[100.2, .001], [100.1, .001]]),
            book(asset, 'rh_lighter', t + 11_200_000_000,
                 bids=[[102, 20], [101.9, 20]],
                 asks=[[102.4, 20], [102.5, 20]]),
        ])
    rows.append(book('ETH', 'rh_lighter', CUTOFF + 110 * NS,
                     bids=[[101, 20], [102, 20]]))  # Invalid ordering, same branch errors.
    rows.sort(key=lambda x: x['received_ns'])
    rows.append({'type': 'end', 'received_ns': END, 'truncated': False})
    return rows


class OptimizedReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / 'capture'
        self.capture.mkdir()
        shutil.copytree(FROZEN_METADATA, self.capture / 'metadata')
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

    def test_shared_book_is_immutable_and_patch_restores(self):
        event = book('BTC', 'rh_lighter', CUTOFF)
        original_descriptor = Book.__dict__['parse']
        with cached_book_parse() as (stats, next_event):
            first = Book.parse(event)
            second = Book.parse(event)
            self.assertIs(first, second)
            self.assertIsInstance(first.bids, tuple)
            with self.assertRaises(FrozenInstanceError):
                first.bids = ()
            with self.assertRaises(TypeError):
                first.bids[0] = (0, 0)
            self.assertEqual(first.walk('sell', first.bids[0][1]),
                             Book.walk(first, 'sell', first.bids[0][1]))
            event['bids'][0][0] = 100.1
            next_event()
            third = Book.parse(event)
            self.assertIsNot(third, first)
            self.assertEqual(first.bids[0][0], 100)
            self.assertEqual(third.bids[0][0], Decimal('100.1'))
        self.assertIs(Book.__dict__['parse'], original_descriptor)
        self.assertEqual(stats['cache_hits'], 1)
        self.assertEqual(stats['cache_misses'], 2)

    def test_multiasset_two_tier_financial_and_ordered_audit_equivalence(self):
        original_descriptor = Book.__dict__['parse']
        events = synthetic_events()
        baseline = analyze_rh_maker.replay(
            self.capture, self.root / 'baseline', events=copy.deepcopy(events))
        optimized, provenance = replay_optimized(
            self.capture, self.root / 'optimized', events=copy.deepcopy(events))
        self.assertIs(Book.__dict__['parse'], original_descriptor)
        self.assertEqual(baseline['status'], 'complete')
        self.assertEqual(optimized['status'], baseline['status'])
        self.assertEqual(len(optimized['branches']), 96)
        self.assertGreater(sum(row['metrics']['known_closed_filled_episodes']
                               for row in optimized['branches']), 0)
        self.assertEqual(optimized['branches'], baseline['branches'])
        self.assertEqual(optimized['models'], baseline['models'])
        self.assertEqual(optimized['counts'], baseline['counts'])
        self.assertEqual(optimized['audit_records'], baseline['audit_records'])
        self.assertEqual(optimized['audit_sha256'], baseline['audit_sha256'])
        self.assertNotIn('implementation_variant', baseline)
        self.assertEqual(optimized['implementation_variant'], 'postfreeze_book_parse_cache')
        self.assertEqual(provenance['implementation_variant'], 'postfreeze_book_parse_cache')
        self.assertIn('Implementation variant: postfreeze_book_parse_cache',
                      (self.root / 'optimized/REPORT.md').read_text())
        with gzip.open(self.root / 'baseline/audit.jsonl.gz', 'rb') as left:
            original_rows = left.read().splitlines()
        with gzip.open(self.root / 'optimized/audit.jsonl.gz', 'rb') as right:
            cached_rows = right.read().splitlines()
        self.assertEqual(cached_rows, original_rows)
        self.assertGreater(provenance['cache']['cache_hits'], 0)
        self.assertEqual(provenance['analysis_sha256'], hashlib.sha256(
            (self.root / 'optimized/analysis.json').read_bytes()).hexdigest())

    def test_injected_generator_reusing_one_dict_clears_between_yields(self):
        def reused_events():
            shared = book('BTC', 'rh_lighter', START)
            yield shared
            shared['received_ns'] = START + NS
            shared['source_ns'] = START + NS
            shared['bids'][0][0] = 100.1
            yield shared
            yield {'type': 'end', 'received_ns': END, 'truncated': False}

        baseline = analyze_rh_maker.replay(
            self.capture, self.root / 'reuse_baseline', events=reused_events())
        optimized, provenance = replay_optimized(
            self.capture, self.root / 'reuse_cached', events=reused_events())
        self.assertEqual(optimized['branches'], baseline['branches'])
        self.assertEqual(optimized['audit_sha256'], baseline['audit_sha256'])
        self.assertGreaterEqual(provenance['cache']['cache_misses'], 2)


if __name__ == '__main__':
    unittest.main()
