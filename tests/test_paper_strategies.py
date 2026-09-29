import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_strategies import StrategySelector, MAX_SAMPLES, POLICIES


PAIR = {'asset': 'BTC',
        'hl': {'venue': 'hyperliquid', 'market': 'BTC'},
        'other': {'venue': 'rh_lighter', 'market': 1}}
ROUTE = 'BTC|hyperliquid:BTC|rh_lighter:1'


def books(now, *, short_ask=102.1, long_source=None, short_source=None, skew=0):
    return {
        'hyperliquid:BTC': {'valid': True, 'bids': [(99.9, 100)], 'asks': [(100, 100)],
                            'received': now, 'engine_time': now if long_source is None else long_source,
                            'generation': 1},
        'rh_lighter:1': {'valid': True, 'bids': [(102, 100)], 'asks': [(short_ask, 100)],
                        'received': now + skew, 'engine_time': now + skew if short_source is None else short_source,
                        'generation': 1}}


def signal(now, edge=25, **kwargs):
    return {'route': ROUTE, 'buy': 'hyperliquid:BTC', 'sell': 'rh_lighter:1',
            'quantity': 10, 'buy_value': 1000, 'net_edge_usd': edge,
            'timestamp': now, 'skew_ms': 0, **kwargs}


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.selector = StrategySelector(SimpleNamespace(max_book_age=2))

    def observe(self, now, *, edge=25, **book_kwargs):
        self.selector.observe(PAIR, books(now, **book_kwargs), now, [signal(now, edge)])

    def warm(self, *, edge=-1, short_ask=102.1):
        # Negative entry signals still train the route's closing-spread model.
        for now in range(0, 124, 3):
            self.observe(now, edge=edge, short_ask=short_ask)

    def test_causal_warmup_excludes_current_sample(self):
        for now in range(0, 121, 3):
            self.observe(now, edge=-1)
        allowed, diagnostic = self.selector.allow('convergence', signal(120), 120)
        self.assertFalse(allowed)
        self.assertEqual(diagnostic['reason'], 'warmup')
        self.assertEqual(diagnostic['historical_samples'], 40)
        self.assertEqual(diagnostic['historical_span_seconds'], 117)
        allowed, diagnostic = self.selector.allow('convergence', signal(120.01), 120.01)
        self.assertTrue(allowed)
        self.assertEqual(diagnostic['historical_samples'], 41)
        self.assertAlmostEqual(diagnostic['historical_closing_spread_bps'], 220)
        self.assertAlmostEqual(diagnostic['forecast_net_usd'], 3)

    def test_conservative_uses_upper_tail_and_margin(self):
        self.warm()
        # Replace the upper quarter with more expensive executable unwinds.
        # The median stays low while the 75th percentile becomes adverse.
        for now in range(126, 171, 3):
            self.observe(now, edge=-1, short_ask=103.5)
        yes, median_diagnostic = self.selector.allow('convergence', signal(171, .30), 171)
        no, tail_diagnostic = self.selector.allow('conservative', signal(171, .30), 171)
        self.assertFalse(yes)
        self.assertFalse(no)
        self.assertEqual(median_diagnostic['reason'], 'forecast')
        self.assertEqual(tail_diagnostic['forecast_threshold_usd'], .5)
        self.assertTrue(self.selector.allow('convergence', signal(171, 25), 171)[0])
        self.assertFalse(self.selector.allow('conservative', signal(171, 25), 171)[0])
        self.assertGreater(self.selector.allow('conservative', signal(171, 25), 171)[1]['historical_closing_spread_bps'],
                           self.selector.allow('convergence', signal(171, 25), 171)[1]['historical_closing_spread_bps'])

    def test_both_source_times_advance_and_sampling_is_rate_limited(self):
        self.observe(0)
        self.observe(.5)
        self.assertEqual(len(self.selector.routes[ROUTE].samples), 1)
        self.observe(1.1, long_source=0, short_source=0)
        self.assertEqual(len(self.selector.routes[ROUTE].samples), 1)
        self.assertEqual(self.selector.observation_counts['source_not_advanced'], 1)
        self.observe(1.2)
        self.assertEqual(len(self.selector.routes[ROUTE].samples), 2)
        self.observe(2.3, skew=.3)
        self.assertEqual(len(self.selector.routes[ROUTE].samples), 2)
        self.assertEqual(self.selector.observation_counts['invalid_pair'], 1)

    def test_gate_skew_cooldown_and_state_restore(self):
        s = signal(0, .25)
        self.assertTrue(self.selector.allow('cooldown', s, 0)[0])
        self.selector.entered('cooldown', s, 0)
        self.assertEqual(self.selector.allow('cooldown', signal(30, 1), 30)[1]['reason'], 'cooldown')
        bad = signal(60, 1)
        bad['skew_ms'] = 251
        self.assertEqual(self.selector.allow('cooldown', bad, 60)[1]['reason'], 'skew')
        self.assertTrue(self.selector.allow('cooldown', signal(60, 1), 60)[0])
        self.assertEqual(self.selector.allow('cooldown', signal(60, 1), 60, existing_position=True)[1]['reason'], 'duplicate')
        saved = self.selector.export_state()
        restored = StrategySelector(SimpleNamespace(max_book_age=2))
        restored.restore_state(saved, 30)
        self.assertEqual(restored.allow('cooldown', signal(30, 1), 30)[1]['reason'], 'cooldown')
        self.assertEqual(restored.snapshot(30)['warm_routes'], 0)
        self.assertEqual(restored.allow('convergence', signal(30, 5), 30)[1]['reason'], 'warmup')

    def test_gap_removal_and_bounded_history(self):
        self.warm()
        self.assertEqual(self.selector.snapshot(123)['warm_routes'], 1)
        self.assertEqual(self.selector.allow('convergence', signal(200), 200)[1]['reason'], 'warmup')
        self.assertEqual(self.selector.snapshot(200)['sampled_routes'], 0)
        self.observe(201)
        self.selector.retain_routes([])
        self.assertEqual(self.selector.snapshot(201)['sampled_routes'], 0)
        self.assertEqual(set(self.selector.snapshot(201)['policies']), set(POLICIES))
        for now in range(300, 1301):
            self.observe(now)
        self.assertLessEqual(len(self.selector.routes[ROUTE].samples), MAX_SAMPLES)
        self.assertGreaterEqual(self.selector.routes[ROUTE].samples[0][0], 1300 - 900)


if __name__ == '__main__':
    unittest.main()
