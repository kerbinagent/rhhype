from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from fixed_markout_observer import FixedResearchObserver, arguments
from paper_fixed_markout import FixedQuantityMarkoutObserver, standard_fee_bps
from paper_horizon import HorizonMarkoutObserver


ROUTE = 'BTC|hyperliquid:BTC|lighter:1'
FORECASTS = {'historical_median': 100, 'persistence': 50,
             'horizon_delta': 25, 'conditional_linear': 20}


def book(venue, market, now, bid, ask, sequence, *, bid_size=100,
         ask_size=100, generation=1, valid=True, source=None):
    return {'venue': venue, 'market': market, 'valid': valid,
            'bids': [(bid, bid_size)] if valid else [],
            'asks': [(ask, ask_size)] if valid else [],
            'received': now, 'engine_time': now-.05 if source is None else source,
            'sequence': sequence, 'generation': generation}


def quote(q=10):
    return {'quantity': q, 'entry_value': 100*q,
            'short_entry_value': 102*q,
            'long_liquidation_value': 99*q,
            'short_buyback_value': 103*q}


def pair():
    return {'asset': 'BTC', 'hl': {'venue': 'hyperliquid', 'market': 'BTC',
                                  'step': '.01', 'min_qty': .01,
                                  'min_notional': 10, 'fee_bps': 1},
            'other': {'venue': 'lighter', 'market': 1,
                      'step': '.01', 'min_qty': .01, 'min_notional': 10,
                      'published_fee_floor_bps': 2}}


class FixedMarkoutTests(unittest.TestCase):
    def test_original_quantity_and_four_asymmetric_quote_fees(self):
        model = FixedQuantityMarkoutObserver()
        a = book('hyperliquid', 'BTC', 1000, 99, 100, 1)
        b = book('lighter', 1, 1000, 102, 103, 1)
        self.assertTrue(model.on_pair(ROUTE, 1000, a, b))
        self.assertTrue(model.anchor(ROUTE, 1000, quote(), 1, 2, FORECASTS))
        future_a = book('hyperliquid', 'BTC', 1013, 100, 101, 2)
        future_b = book('lighter', 1, 1013, 100, 101, 2)
        self.assertTrue(model.on_pair(ROUTE, 1013, future_a, future_b))
        row = model.snapshot(1013)['terminal_rows'][0]
        self.assertEqual(row['quantity'], 10)
        self.assertEqual(row['gross_capture_usd'], 10)
        self.assertAlmostEqual(row['buy_entry_fee_usd'], .1)
        self.assertAlmostEqual(row['sell_entry_fee_usd'], .204)
        self.assertAlmostEqual(row['buy_exit_fee_usd'], .1)
        self.assertAlmostEqual(row['sell_exit_fee_usd'], .202)
        self.assertAlmostEqual(row['net_after_four_fees_usd'], 9.394)
        self.assertEqual(row['capital_elapsed_seconds'], 13)
        self.assertAlmostEqual(row['capital_reserve_usd'],
                               (1000+1020)*.05*13/(365*86400))
        self.assertGreater(row['net_after_reserves_usd'], 0)
        self.assertTrue(row['screen_flags']['conditional_linear_gt_0.25'])
        self.assertIn('historical_median_gt_0.25', row['screen_flags'])
        self.assertIn('horizon_delta_gt_0.25', row['screen_flags'])
        selected = model.snapshot(1013)['selected_anchor_coverage']
        self.assertEqual(selected['conditional_linear_gt_0.25']['matched'], 1)
        self.assertEqual(selected['conditional_linear_gt_0.25']['censored'], 0)
        self.assertEqual(selected['conditional_linear_gt_0.25']['after_reserve_positive'], 1)
        self.assertAlmostEqual(selected['conditional_linear_gt_0.25']['mean_after_reserve_net_usd'],
                               row['net_after_reserves_usd'])
        self.assertAlmostEqual(model.snapshot(1013)['all_v2_scored_coverage']['mean_after_reserve_net_usd'],
                               row['net_after_reserves_usd'])
        self.assertEqual(model.counts['anchors'],
                         model.counts['matched_anchors']+model.counts['censored_anchors'])

    def test_first_eligible_shallow_exit_censors_even_if_later_price_improves(self):
        model = FixedQuantityMarkoutObserver()
        self.assertTrue(model.on_pair(ROUTE, 1000,
            book('hyperliquid', 'BTC', 1000, 99, 100, 1),
            book('lighter', 1, 1000, 102, 103, 1)))
        model.anchor(ROUTE, 1000, quote(), 1, 2)
        self.assertTrue(model.on_pair(ROUTE, 1013,
            book('hyperliquid', 'BTC', 1013, 100, 101, 2, bid_size=5),
            book('lighter', 1, 1013, 100, 101, 2)))
        self.assertTrue(model.on_pair(ROUTE, 1014,
            book('hyperliquid', 'BTC', 1014, 120, 121, 3),
            book('lighter', 1, 1014, 99, 100, 3)))
        snapshot = model.snapshot(1014)
        self.assertEqual(snapshot['censored']['future_exit_depth'], 1)
        self.assertEqual(snapshot['counts'].get('matched_anchors', 0), 0)
        self.assertEqual(len(snapshot['terminal_rows']), 1)

    def test_source_advancement_generation_and_stop_accounting(self):
        model = FixedQuantityMarkoutObserver()
        a = book('hyperliquid', 'BTC', 1000, 99, 100, 1)
        b = book('lighter', 1, 1000, 102, 103, 1)
        model.on_pair(ROUTE, 1000, a, b)
        model.anchor(ROUTE, 1000, quote(), 0, 0)
        same_source = book('hyperliquid', 'BTC', 1013, 99, 100, 2,
                           source=a['engine_time'])
        self.assertFalse(model.on_pair(ROUTE, 1013, same_source,
            book('lighter', 1, 1013, 102, 103, 2)))
        self.assertEqual(model.snapshot(1013)['pending_anchors'], 1)
        model.finish(1013)
        self.assertEqual(model.censored['stopped_pending'], 1)
        self.assertEqual(model.counts['anchors'],
                         model.counts['matched_anchors']+model.counts['censored_anchors'])
        self.assertFalse(model.on_pair(ROUTE, 1014, a, b))
        changed = FixedQuantityMarkoutObserver()
        changed.on_pair(ROUTE, 1000, a, b)
        changed.anchor(ROUTE, 1000, quote(), 0, 0)
        changed.on_pair(ROUTE, 1013,
            book('hyperliquid', 'BTC', 1013, 99, 100, 2, generation=2),
            book('lighter', 1, 1013, 102, 103, 2))
        self.assertEqual(changed.censored['generation_changed'], 1)

    def test_future_source_tolerance_and_selected_censor_coverage(self):
        model = FixedQuantityMarkoutObserver()
        a = book('hyperliquid', 'BTC', 1000, 99, 100, 1)
        b = book('lighter', 1, 1000, 102, 103, 1)
        a['engine_time'] = 1000.3
        self.assertFalse(model.on_pair(ROUTE, 1000, a, b))
        self.assertEqual(model.rejections['stale_source'], 1)
        a['engine_time'] = 999.95
        model.on_pair(ROUTE, 1000, a, b)
        model.anchor(ROUTE, 1000, quote(), 1, 2, FORECASTS)
        model.on_pair(ROUTE, 1013,
            book('hyperliquid', 'BTC', 1013, 100, 101, 2, bid_size=1),
            book('lighter', 1, 1013, 100, 101, 2))
        scored = model.snapshot(1013)['all_v2_scored_coverage']
        self.assertEqual((scored['anchors'], scored['matched'], scored['censored'], scored['pending']),
                         (1, 0, 1, 0))
        cohort = model.snapshot(1013)['selected_anchor_coverage']['conditional_linear_gt_0.25']
        self.assertEqual(cohort['censored'], 1)
        self.assertEqual(cohort['censored_fraction'], 1)

    def test_terminal_export_and_route_pending_are_hard_bounded(self):
        model = FixedQuantityMarkoutObserver(max_routes=1, max_terminal_rows=1)
        for index, route in enumerate((ROUTE, 'ETH|hyperliquid:ETH|lighter:2')):
            now = 1000+index*20
            model.on_pair(route, now,
                          book('hyperliquid', 'BTC', now, 99, 100, 1),
                          book('lighter', 1, now, 102, 103, 1))
            model.anchor(route, now, quote(), 0, 0)
        self.assertEqual(model.censored['evicted'], 1)
        model.finish(1020)
        snap = model.snapshot(1020)
        self.assertLessEqual(len(snap['terminal_rows']), 1)
        self.assertEqual(snap['counts']['terminal_export_dropped'], 1)
        self.assertEqual(snap['counts']['anchors'],
                         snap['counts'].get('matched_anchors', 0)+snap['counts']['censored_anchors'])

    def test_wrapper_resolves_original_quantity_when_new_adaptive_entry_fails(self):
        observer = FixedResearchObserver([pair()])
        observer.on_book(book('hyperliquid', 'BTC', 1000, 99, 100, 1))
        observer.on_book(book('lighter', 1, 1000.1, 102, 103, 1))
        self.assertEqual(observer.fixed.counts['anchors'], 2)
        observer.on_book(book('hyperliquid', 'BTC', 1013, 100, 101, 2,
                              ask_size=.001))
        observer.on_book(book('lighter', 1, 1013.1, 100, 101, 2))
        self.assertEqual(observer.fixed.counts['matched_anchors'], 1)
        # The opposite direction needs HL asks at its original q and is
        # properly censored because that same ask side is shallow.
        self.assertEqual(observer.fixed.censored['future_exit_depth'], 1)
        self.assertGreater(observer.stats['rejected_new_anchor_depth_or_lot'], 0)
        self.assertEqual(observer.fixed.snapshot(1013.1)['pending_anchors'], 0)

    def test_horizon_callback_freezes_before_current_pair_trains(self):
        callbacks = []
        model = HorizonMarkoutObserver(min_anchors=1,
                                       min_anchor_span_seconds=0,
                                       on_anchor=lambda route, obs, prediction:
                                       callbacks.append((obs.now, prediction)))
        for now, closing in ((1000, 0), (1012, 10), (1024, 80)):
            model.observe('A|buy|sell', now, closing, 10, 1000,
                          now-.05, now-.05, now, now, 1, 1)
        self.assertIsNone(callbacks[0][1])
        self.assertIsNone(callbacks[1][1])
        self.assertEqual(callbacks[2][1]['horizon_delta'], 90)
        self.assertEqual(model.snapshot(1024)['counts']['matched_anchors'], 2)

    def test_frozen_fee_floor_and_duration_cap(self):
        self.assertEqual(standard_fee_bps(pair()['other']), 2)
        self.assertEqual(standard_fee_bps({'venue': 'lighter'}), 0)
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            standard_fee_bps({'venue': 'hyperliquid', 'fee_bps': -1})
        for invalid in (-.1, float('nan'), float('inf')):
            with self.subTest(floor=invalid), self.assertRaisesRegex(ValueError, 'nonnegative'):
                standard_fee_bps({'venue': 'lighter',
                                  'published_fee_floor_bps': invalid})
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            arguments(['--markets', '/tmp/markets.json', '--duration', '2401'])
        for option in ('--duration', '--report-seconds', '--notional',
                       '--min-volume', '--max-metadata-age-hours'):
            with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                arguments(['--markets', '/tmp/markets.json', option, 'nan'])


if __name__ == '__main__':
    unittest.main()
