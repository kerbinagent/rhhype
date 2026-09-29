import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_horizon import HorizonMarkoutObserver, MODEL_VERSION


def add(observer, route, now, closing, *, source=None, receipt=None, generation=1):
    source = now if source is None else source
    receipt = now if receipt is None else receipt
    return observer.observe(route, now, closing, 10, 1000,
                            source, source, receipt, receipt,
                            generation, generation)


class HorizonObserverTests(unittest.TestCase):
    def test_v2_linear_forecast_uses_only_prior_pairs_and_fixed_shrinkage(self):
        o = HorizonMarkoutObserver(min_anchors=3, min_anchor_span_seconds=24)
        for t, closing in ((0, 0), (12, 10), (24, 30), (36, 50), (48, 70), (60, 90)):
            add(o, 'BTC|buy|sell', t, closing)
        s = o.snapshot(60)
        self.assertEqual(s['model_version'], MODEL_VERSION)
        row = next(r for r in s['mature_rows'] if r['anchor_time'] == 48)
        self.assertEqual(row['frozen_predictions_bps']['historical_median'], 20)
        self.assertEqual(row['frozen_predictions_bps']['persistence'], 70)
        self.assertEqual(row['frozen_predictions_bps']['horizon_delta'], 90)
        # Mature training pairs at t=48 are (0,10), (10,30), (30,50).
        # beta_OLS=9/7; beta=1+(3/23)*(2/7), evaluated around mean_x=40/3.
        expected = 70 + 50/3 + (3/23)*(2/7)*(70-40/3)
        self.assertAlmostEqual(row['frozen_predictions_bps']['conditional_linear'], expected)
        self.assertEqual(s['models']['conditional_linear']['count'], 1)

    def test_v2_linear_degenerate_variance_uses_persistence_plus_mean_delta(self):
        o = HorizonMarkoutObserver(min_anchors=3, min_anchor_span_seconds=24)
        for t, closing in ((0, 5), (12, 5), (24, 5), (36, 8), (48, 20), (60, 21)):
            add(o, 'BTC|buy|sell', t, closing)
        s = o.snapshot(60)
        row = next(r for r in s['mature_rows'] if r['anchor_time'] == 48)
        self.assertEqual(row['frozen_predictions_bps']['conditional_linear'], 21)
        self.assertGreaterEqual(s['counts']['linear_degenerate_variance'], 1)

    def test_v2_per_route_error_prevents_global_cancellation(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        for route, last in (('A|buy|sell', 30), ('B|buy|sell', 50)):
            for t, closing in ((0, 0), (12, 10), (24, 20), (36, last)):
                add(o, route, t, closing)
        s = o.snapshot(36)
        self.assertEqual(s['models']['horizon_delta']['mean_absolute_error_bps'], 10)
        self.assertEqual(s['per_route']['A|buy|sell']['models']['horizon_delta']['mean_absolute_error_bps'], 0)
        self.assertEqual(s['per_route']['B|buy|sell']['models']['horizon_delta']['mean_absolute_error_bps'], 20)
        self.assertEqual(s['per_route']['A|buy|sell']['matched_anchors'], 3)
        self.assertEqual(s['per_route']['B|buy|sell']['scored_anchors'], 1)

    def test_v2_mature_export_and_route_metrics_are_hard_bounded(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0,
                                   max_export_rows=2, max_routes=2)
        for t in (0, 12, 24, 36, 48):
            add(o, 'A|buy|sell', t, 10+t)
        s = o.snapshot(48)
        self.assertEqual(len(s['mature_rows']), 2)
        self.assertEqual([r['anchor_time'] for r in s['mature_rows']], [24, 36])
        self.assertEqual(s['counts']['mature_export_dropped'], 2)
        self.assertEqual(s['per_route']['A|buy|sell']['matched_anchors'], 4)
        self.assertIn('anchor_quantity', s['mature_rows'][0])
        self.assertIn('outcome_sell_source_time', s['mature_rows'][0])
        self.assertEqual(s['mature_rows'][0]['model_version'], MODEL_VERSION)
        self.assertEqual(s['mature_rows'][0]['anchor_buy_generation'], '1')
        add(o, 'B|buy|sell', 48, 0)
        add(o, 'C|buy|sell', 48, 0)
        self.assertLessEqual(len(o.snapshot(48)['per_route']), 2)
        self.assertFalse(add(o, 'C|buy|sell', 49, 1_000_001))

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

    def test_rate_limited_fresh_quote_resolves_outcome_without_becoming_training_sample(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        add(o, 'BTC|buy|sell', 0, 10)
        add(o, 'BTC|buy|sell', 12, 20, source=11.5)
        self.assertFalse(add(o, 'BTC|buy|sell', 12.5, 30, source=12.5))
        s = o.snapshot(12.5)
        self.assertEqual(s['counts']['matched_anchors'], 1)
        self.assertEqual(s['counts']['anchors'], 2)
        self.assertEqual(s['counts']['observations'], 2)
        self.assertEqual(s['counts']['resolved_only_observations'], 1)
        self.assertEqual(s['mature_rows'][0]['outcome_time'], 12.5)
        self.assertEqual(s['pending_anchors'], 1)
        # A repeat of the resolved-only source cannot become a sampled anchor.
        self.assertFalse(add(o, 'BTC|buy|sell', 13, 31, source=12.5))
        self.assertEqual(o.snapshot(13)['counts']['source_not_advanced'], 1)
        self.assertTrue(add(o, 'BTC|buy|sell', 24, 40))
        s = o.snapshot(24)
        self.assertEqual(s['counts']['matched_anchors'], 2)
        self.assertEqual(s['counts']['anchors'], 3)

    def test_anchor_intervals_can_overlap_four_seconds(self):
        o = HorizonMarkoutObserver()
        add(o, 'BTC|buy|sell', 0, 10)
        add(o, 'BTC|buy|sell', 12, 20, source=11.5)
        add(o, 'BTC|buy|sell', 16, 30)
        add(o, 'BTC|buy|sell', 24, 40)
        rows = o.snapshot(24)['mature_rows']
        self.assertEqual([(r['anchor_time'], r['outcome_time']) for r in rows],
                         [(0, 16), (12, 24)])

    def test_resolved_only_outcomes_still_obey_mature_memory_cap(self):
        o = HorizonMarkoutObserver(max_observations=2, min_anchors=1,
                                   min_anchor_span_seconds=0)
        for when, source in ((0, 0), (12, 11.5), (12.5, 12.5),
                             (24, 23), (24.5, 24.5), (36, 35), (36.5, 36.5)):
            add(o, 'BTC|buy|sell', when, 10+when, source=source)
        s = o.snapshot(36.5)
        self.assertEqual(s['counts']['matched_anchors'], 3)
        self.assertEqual(s['max_route_mature_anchors'], 2)
        self.assertEqual(len(s['mature_rows']), 3)

    def test_route_lifetime_and_active_generation_accounting(self):
        o = HorizonMarkoutObserver(min_anchors=1, min_anchor_span_seconds=0)
        add(o, 'BTC|buy|sell', 0, 10, generation=1)
        add(o, 'BTC|buy|sell', 2, 20, generation=2)
        s = o.snapshot(2)['per_route']['BTC|buy|sell']
        self.assertEqual((s['anchors'], s['matched_anchors'], s['censored_anchors']), (2, 0, 1))
        self.assertEqual(s['censored_by_reason'], {'generation_changed': 1})
        self.assertEqual(s['active_segment']['generation'], {'buy': '2', 'sell': '2'})
        self.assertEqual((s['active_segment']['anchors'], s['active_segment']['pending_anchors']), (1, 1))
        o.snapshot(20)
        s = o.snapshot(20)['per_route']['BTC|buy|sell']
        self.assertEqual(s['censored_anchors'], 2)
        self.assertEqual(s['censored_by_reason'],
                         {'generation_changed': 1, 'outcome_missing': 1})
        self.assertEqual(s['active_segment']['censored_by_reason'], {'outcome_missing': 1})
        self.assertEqual(s['anchors'],s['matched_anchors']+s['censored_anchors']+s['pending_anchors'])
        s = o.snapshot(33)['per_route']['BTC|buy|sell']
        self.assertFalse(s['active'])
        self.assertIsNone(s['active_segment'])
        self.assertEqual(s['censored_anchors'], 2)

    def test_metric_eviction_prefers_inactive_route(self):
        o = HorizonMarkoutObserver(max_routes=2)
        add(o, 'A|buy|sell', 0, 10)
        add(o, 'B|buy|sell', 1, 10)
        o.invalidate('B|buy|sell', 2)
        add(o, 'C|buy|sell', 3, 10)
        s = o.snapshot(3)
        self.assertIn('A|buy|sell', s['per_route'])
        self.assertIn('C|buy|sell', s['per_route'])
        self.assertNotIn('B|buy|sell', s['per_route'])
        self.assertEqual(s['per_route']['A|buy|sell']['anchors'], 1)

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
