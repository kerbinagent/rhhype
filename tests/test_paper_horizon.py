import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_horizon import HorizonMarkoutObserver


def add(observer, route, now, closing, *, source=None, receipt=None, generation=1):
    source = now if source is None else source
    receipt = now if receipt is None else receipt
    return observer.observe(route, now, closing, 10, 1000,
                            source, source, receipt, receipt,
                            generation, generation)


class HorizonObserverTests(unittest.TestCase):
    def test_same_quote_cannot_train_its_own_forecast(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        for t, closing in ((0, 0), (12, 10), (24, 80), (36, 90)):
            add(o, 'BTC|buy|sell', t, closing)
        # At t=24, only the t=0 -> t=12 delta (+10) was mature. The
        # t=12 -> t=24 delta (+70) arrives on that same quote and is excluded.
        s = o.snapshot(36)
        self.assertEqual(s['counts']['scored_anchors'], 1)
        self.assertEqual(s['models']['horizon_delta']['mean_error_bps'], 0)

    def test_walk_forward_errors_use_only_prior_mature_outcomes(self):
        o = HorizonMarkoutObserver(min_anchors=2, min_anchor_span_seconds=12)
        for t, closing in ((0, 10), (12, 20), (24, 30), (36, 40)):
            self.assertTrue(add(o, 'BTC|buy|sell', t, closing))
        before = o.snapshot(36)
        self.assertEqual(before['warm_routes'], 1)
        self.assertEqual(before['counts'].get('scored_anchors', 0), 0)
        self.assertTrue(add(o, 'BTC|buy|sell', 48, 50))
        self.assertTrue(add(o, 'BTC|buy|sell', 60, 60))
        result = o.snapshot(60)
        self.assertEqual(result['counts']['matched_anchors'], 5)
        self.assertEqual(result['counts']['scored_anchors'], 2)
        self.assertEqual(result['models']['horizon_delta']['mean_absolute_error_bps'], 0)
        self.assertEqual(result['models']['persistence']['mean_absolute_error_bps'], 10)
        self.assertEqual(result['models']['historical_median']['mean_absolute_error_bps'], 32.5)

    def test_both_source_clocks_must_reach_horizon_without_interpolation(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        add(o, 'BTC|buy|sell', 0, 10)
        add(o, 'BTC|buy|sell', 12, 20, source=11.5)
        self.assertEqual(o.snapshot(12)['counts'].get('matched_anchors', 0), 0)
        add(o, 'BTC|buy|sell', 14, 25)
        self.assertEqual(o.snapshot(14)['counts']['matched_anchors'], 1)
        self.assertEqual(o.snapshot(14)['pending_anchors'], 1)
        # An absent future outcome is censored; no synthetic closing quote appears.
        self.assertEqual(o.snapshot(29)['censored']['outcome_missing'], 1)

    def test_generation_and_gap_censor_pending_anchors(self):
        o = HorizonMarkoutObserver()
        add(o, 'BTC|buy|sell', 0, 10)
        add(o, 'BTC|buy|sell', 2, 11, generation=2)
        s = o.snapshot(2)
        self.assertEqual(s['censored']['generation_changed'], 1)
        self.assertEqual(s['counts']['matched_anchors'] if 'matched_anchors' in s['counts'] else 0, 0)
        self.assertEqual(s['pending_anchors'], 1)
        add(o, 'BTC|buy|sell', 34, 12, generation=2)
        self.assertEqual(o.snapshot(34)['censored']['feed_gap'], 1)
        self.assertTrue(o.invalidate('BTC|buy|sell', 35, 'route_removed'))
        self.assertEqual(o.snapshot(35)['censored']['route_removed'], 1)
        self.assertFalse(o.invalidate('BTC|buy|sell', 35, 'route_removed'))

    def test_invalid_pair_and_unadvanced_source_do_not_train(self):
        o = HorizonMarkoutObserver()
        self.assertFalse(add(o, 'BTC|buy|sell', 0, 10, source=-3))
        self.assertTrue(add(o, 'BTC|buy|sell', 1, 10))
        self.assertFalse(add(o, 'BTC|buy|sell', 2, 11, source=1))
        s = o.snapshot(2)
        self.assertEqual(s['counts']['invalid_observation'], 1)
        self.assertEqual(s['counts']['source_not_advanced'], 1)
        self.assertEqual(s['max_route_observations'], 1)

    def test_route_and_history_caps_censor_evicted_pending(self):
        o = HorizonMarkoutObserver(max_routes=2, max_observations=3)
        add(o, 'A|buy|sell', 0, 10)
        add(o, 'B|buy|sell', 0, 10)
        add(o, 'C|buy|sell', 0, 10)
        s = o.snapshot(0)
        self.assertEqual(s['sampled_routes'], 2)
        self.assertEqual(s['censored']['evicted'], 1)
        for t in (1, 2, 3, 4):
            add(o, 'B|buy|sell', t, 10+t)
        self.assertEqual(o.snapshot(4)['max_route_observations'], 3)


if __name__ == '__main__':
    unittest.main()
