import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_maker_spread_hurdle import analyze, cost_at_bid, required_discount, walk


class SpreadHurdleTest(unittest.TestCase):
    def test_cost_and_discount_are_monotone(self):
        args = (1.0, 100.0, 101.0, 102.0, 0.9)
        at_best = cost_at_bid(100.0, *args)
        self.assertLess(at_best, 0)
        gap = required_discount(100.0, *args)
        self.assertGreater(gap, 0)
        bid = 100.0 * (1 - gap / 10000)
        self.assertAlmostEqual(cost_at_bid(bid, *args), 0, places=8)
        self.assertLess(cost_at_bid(bid + .01, *args), 0)

    def test_size_walk_and_shallow_depth(self):
        levels = [[100, 1], [101, 2]]
        self.assertEqual(walk(levels, 2), 201)
        self.assertIsNone(walk(levels, 4))

    def test_only_stopped_archive_and_expected_coverage(self):
        result = analyze()
        self.assertEqual(result['counts']['NVDA:anchors'], 83)
        self.assertEqual(result['counts']['XAG:anchors'], 83)
        self.assertEqual(result['rh_only_summary']['NVDA']['n'], 78)
        self.assertEqual(result['rh_only_summary']['XAG']['n'], 80)
        self.assertEqual(result['summary']['NVDA|1000']['n'], 15)
        self.assertEqual(result['summary']['XAG|1000']['n'], 16)
        self.assertEqual(len(result['retained_rows']), 124)
        self.assertTrue(all(row['required_below_rh_best_bps'] > 0 for row in result['retained_rows']))


if __name__ == '__main__':
    unittest.main()
