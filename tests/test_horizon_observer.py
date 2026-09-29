import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from horizon_observer import ResearchObserver, executable_mark, select_pairs
from paper_horizon import HorizonMarkoutObserver


def pair(venue='lighter', market=1, volume=2_000_000):
    hl = {'venue': 'hyperliquid', 'market': 'BTC', 'asset': 'BTC',
          'step': '.01', 'min_qty': .01, 'min_notional': 10, 'volume': volume}
    other = {'venue': venue, 'market': market, 'asset': 'BTC',
             'step': '.01', 'min_qty': .01, 'min_notional': 10, 'volume': volume}
    return {'asset': 'BTC', 'hl': hl, 'other': other, 'metadata_timestamp': 1000}


def book(venue, market, when, bid, ask, sequence, valid=True):
    return {'venue': venue, 'market': market,
            'bids': [(bid, 100)] if valid else [],
            'asks': [(ask, 100)] if valid else [],
            'received': when, 'engine_time': when-.05,
            'sequence': sequence, 'generation': f'{venue}:one', 'valid': valid}


class Model:
    def __init__(self):
        self.seen = []
        self.invalidated = []

    def observe(self, *args):
        self.seen.append(args)
        return True

    def invalidate(self, *args):
        self.invalidated.append(args)

    def snapshot(self, now):
        return {'observations': len(self.seen)}


class HorizonObserverTests(unittest.TestCase):
    def test_selection_prefers_liquid_ws_pair_without_aster(self):
        a = pair('aster', 'BTCUSDT', 9_000_000)
        b = pair('rh_lighter', 1, 3_000_000)
        c = pair('lighter', 1, 5_000_000)
        selected = select_pairs([a, b, c], max_pairs=1)
        self.assertEqual(selected, [c])

    def test_equal_lot_executable_closing_spread(self):
        p = pair()
        a = book('hyperliquid', 'BTC', 1000, 99, 100, 1)
        b = book('lighter', 1, 1000, 102, 103, 1)
        mark = executable_mark(p, p['hl'], p['other'], a, b)
        self.assertAlmostEqual(mark['quantity'], 9.8)
        self.assertAlmostEqual(mark['entry_value'], 980)
        self.assertAlmostEqual(mark['closing_bps'], 400)

    def test_both_sources_must_advance_and_gaps_invalidate(self):
        model = Model()
        observer = ResearchObserver([pair()], model, sample_limit=3)
        observer.on_book(book('hyperliquid', 'BTC', 1000, 99, 100, 1))
        observer.on_book(book('lighter', 1, 1000.1, 102, 103, 1))
        self.assertEqual(len(model.seen), 2)  # both directed routes
        first = model.seen[0]
        self.assertEqual(first[0], 'BTC|hyperliquid:BTC|lighter:1')
        self.assertEqual(first[3], 9.8)
        observer.on_book(book('lighter', 1, 1000.2, 102, 103, 2))
        self.assertEqual(len(model.seen), 2)
        observer.on_book(book('hyperliquid', 'BTC', 1000.3, 99, 100, 2))
        self.assertEqual(len(model.seen), 4)
        self.assertEqual(len(observer.latest), 3)
        invalid = book('lighter', 1, 1000.4, 102, 103, 3, valid=False)
        invalid['reason'] = 'disconnected'
        observer.on_book(invalid)
        self.assertEqual(len(model.invalidated), 2)
        self.assertNotIn('lighter:1', observer.books)

    def test_source_skew_and_missing_timestamp_are_rejected(self):
        model = Model()
        observer = ResearchObserver([pair()], model)
        a = book('hyperliquid', 'BTC', 1000, 99, 100, 1)
        b = book('lighter', 1, 1000.1, 102, 103, 1)
        b['engine_time'] = 998.0
        observer.on_book(a)
        observer.on_book(b)
        self.assertFalse(model.seen)
        self.assertGreater(observer.stats['rejected_stale_source'], 0)
        b['engine_time'] = None
        b['received'] = 1000.2
        observer.on_book(b)
        self.assertGreater(observer.stats['rejected_missing_source_identity'], 0)

    def test_real_markout_model_matches_forward_quote_after_twelve_seconds(self):
        model = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        observer = ResearchObserver([pair()], model)
        observer.on_book(book('hyperliquid', 'BTC', 1000, 99, 100, 1))
        observer.on_book(book('lighter', 1, 1000.1, 102, 103, 1))
        observer.on_book(book('hyperliquid', 'BTC', 1013, 99, 100, 2))
        observer.on_book(book('lighter', 1, 1013.1, 101, 102, 2))
        self.assertEqual(observer.stats['model_observations'], 4)
        self.assertEqual(model.counts['matched_anchors'], 2)


if __name__ == '__main__':
    unittest.main()
