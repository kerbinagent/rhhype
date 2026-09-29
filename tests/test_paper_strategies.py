import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_strategies import StrategySelector, MAX_SAMPLES, POLICIES, POLICY_VERSION


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


def confirmed_signal(now, edge=25, *, buy_source=None, sell_source=None,
                     buy_received=None, sell_received=None, generation=1, quantity=10):
    s = signal(now, edge)
    s.update(quantity=quantity,
             buy_source_time=now if buy_source is None else buy_source,
             sell_source_time=now if sell_source is None else sell_source,
             buy_received=now if buy_received is None else buy_received,
             sell_received=now if sell_received is None else sell_received,
             buy_generation=generation, sell_generation=generation)
    return s


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
        stale_pair = books(2.3)
        stale_pair['rh_lighter:1']['received'] = 1.1
        stale_pair['rh_lighter:1']['engine_time'] = 1.1
        self.selector.observe(PAIR, stale_pair, 2.3, [signal(2.3)])
        self.assertEqual(len(self.selector.routes[ROUTE].samples), 2)
        self.assertEqual(self.selector.observation_counts['invalid_pair'], 1)

    def test_v2_training_and_policy_skew_limits(self):
        self.assertEqual(POLICY_VERSION, 3)
        self.warm()
        paired = books(126)
        paired['rh_lighter:1']['received'] = 125.3
        paired['rh_lighter:1']['engine_time'] = 125.3
        self.selector.observe(PAIR, paired, 126, [signal(126, -1)])
        self.assertEqual(len(self.selector.route_history(ROUTE, 127)), 43)
        wide = signal(127, 25)
        wide['skew_ms'] = 700
        wide['source_skew_ms'] = 700
        self.assertTrue(self.selector.allow('convergence', wide, 127)[0])
        self.assertEqual(self.selector.allow('conservative', wide, 127)[1]['reason'], 'skew')
        self.assertEqual(self.selector.allow('cooldown', wide, 127)[1]['reason'], 'skew')
        self.assertEqual(self.selector.snapshot(127)['training_skew_limit_seconds'], 1.0)
        self.assertEqual(self.selector.snapshot(127)['conservative_skew_limit_seconds'], .25)
        too_wide = books(129)
        too_wide['rh_lighter:1']['received'] = 127.9
        too_wide['rh_lighter:1']['engine_time'] = 127.9
        self.selector.observe(PAIR, too_wide, 129, [signal(129, -1)])
        self.assertEqual(len(self.selector.route_history(ROUTE, 130)), 43)

    def test_v1_state_migrates_cooldown_and_counts(self):
        self.selector.entered('cooldown', signal(0, 1), 0)
        old = self.selector.export_state()
        old['version'] = 1
        restored = StrategySelector(SimpleNamespace(max_book_age=2))
        restored.restore_state(old, 30)
        self.assertEqual(restored.counts['cooldown']['entered'], 1)
        self.assertEqual(restored.allow('cooldown', signal(30, 1), 30)[1]['reason'], 'cooldown')
        self.assertEqual(restored.snapshot(30)['version'], 3)
        self.assertEqual(restored.snapshot(30)['sampled_routes'], 0)
        old['counts']['convergence'] = {'entered': 1}
        with self.assertRaisesRegex(ValueError, 'separate experiment'):
            StrategySelector(SimpleNamespace(max_book_age=2)).restore_state(old, 30)

    def test_confirmed_requires_later_independent_sources_and_original_quantity(self):
        self.warm()
        initial = confirmed_signal(124)
        allowed, diagnostic = self.selector.allow('confirmed', initial, 124)
        self.assertFalse(allowed)
        self.assertEqual(diagnostic['confirmation_status'], 'armed')
        lifecycle = self.selector.snapshot(124)['confirmation_lifecycle']
        self.assertEqual((lifecycle['armed'], lifecycle['pending'], lifecycle['accounting_residual']), (1, 1, 0))
        self.assertEqual(self.selector.confirmation_quantity(ROUTE), 10)
        self.assertEqual(self.selector.pending_confirmation_targets(124)[0]['due'], 125)
        same = confirmed_signal(125.1, buy_source=124, sell_source=124)
        self.assertEqual(self.selector.allow('confirmed', same, 125.1)[1]['confirmation_status'], 'awaiting_fresh_sources')
        one = confirmed_signal(125.2, buy_source=125.2, sell_source=124)
        self.assertEqual(self.selector.allow('confirmed', one, 125.2)[1]['confirmation_status'], 'awaiting_fresh_sources')
        self.assertEqual(self.selector.snapshot(125.2)['confirmation_waiting_checks']['fresh_sources'], 2)
        changed_size = confirmed_signal(125.3, quantity=11)
        self.assertEqual(self.selector.allow('confirmed', changed_size, 125.3)[1]['confirmation_status'],
                         'quantity_or_route_changed')
        self.assertIsNone(self.selector.confirmation_quantity(ROUTE))
        self.selector.allow('confirmed', confirmed_signal(126), 126)
        permitted, proof = self.selector.allow('confirmed', confirmed_signal(127.1), 127.1)
        self.assertTrue(permitted)
        self.assertEqual(proof['confirmation_status'], 'confirmed')
        self.assertEqual(proof['confirmed_quantity'], 10)
        self.assertEqual(proof['initial_edge_usd'], 25)
        self.assertAlmostEqual(proof['confirmation_age_seconds'], 1.1)
        self.assertAlmostEqual(proof['buy_source_advance_seconds'], 1.1)
        self.selector.entered('confirmed', confirmed_signal(127.1), 127.1)
        self.selector.entered('confirmed', confirmed_signal(127.1), 127.1)
        self.assertIsNone(self.selector.confirmation_quantity(ROUTE))
        lifecycle = self.selector.snapshot(127.1)['confirmation_lifecycle']
        self.assertEqual(lifecycle['armed'], 2)
        self.assertEqual(lifecycle['eligible_unique'], 1)
        self.assertEqual(lifecycle['completed_entered'], 1)
        self.assertEqual(lifecycle['terminal_reasons']['quantity_or_route_changed'], 1)
        self.assertEqual(lifecycle['accounting_residual'], 0)

    def test_confirmed_resets_on_generation_economics_expiry_and_cancel(self):
        self.warm()
        self.selector.allow('confirmed', confirmed_signal(124), 124)
        changed = confirmed_signal(125.2, generation=2)
        self.assertEqual(self.selector.allow('confirmed', changed, 125.2)[1]['confirmation_status'],
                         'generation_changed')
        self.assertIsNone(self.selector.confirmation_quantity(ROUTE))
        self.selector.allow('confirmed', confirmed_signal(126), 126)
        self.selector.observe(PAIR, books(126.1), 126.1, [signal(126.1, -.1)])
        self.assertIsNone(self.selector.confirmation_quantity(ROUTE))
        self.selector.allow('confirmed', confirmed_signal(127), 127)
        self.assertEqual(self.selector.allow('confirmed', confirmed_signal(131.1), 131.1)[1]['confirmation_status'],
                         'expired')
        self.assertIsNone(self.selector.confirmation_quantity(ROUTE))
        self.selector.allow('confirmed', confirmed_signal(132), 132)
        self.assertTrue(self.selector.cancel_confirmation(ROUTE, 'budget'))
        self.assertEqual(self.selector.snapshot(132)['confirmation_cancel_reasons']['budget'], 1)
        lifecycle = self.selector.snapshot(132)['confirmation_lifecycle']
        self.assertEqual(lifecycle['armed'], 4)
        self.assertEqual(lifecycle['terminal_total'], 4)
        self.assertEqual(lifecycle['accounting_residual'], 0)

    def test_confirmed_unknown_source_uses_receipt_with_explicit_evidence(self):
        self.warm()
        initial = confirmed_signal(124)
        initial['buy_source_time'] = None
        armed, first = self.selector.allow('confirmed', initial, 124)
        self.assertFalse(armed)
        self.assertEqual(first['source_time_fallbacks'], ['buy'])
        later = confirmed_signal(125.2)
        later['buy_source_time'] = None
        accepted, proof = self.selector.allow('confirmed', later, 125.2)
        self.assertTrue(accepted)
        self.assertEqual(proof['source_time_fallbacks'], ['buy'])
        self.assertEqual(proof['initial_source_time_fallbacks'], ['buy'])

    def test_v2_state_keeps_counters_and_cooldown_but_no_candidates(self):
        self.warm()
        self.selector.entered('cooldown', signal(124), 124)
        self.selector.allow('confirmed', confirmed_signal(124), 124)
        state = self.selector.export_state()
        state['version'] = 2
        restored = StrategySelector(SimpleNamespace(max_book_age=2))
        restored.restore_state(state, 150)
        self.assertEqual(restored.counts['cooldown']['entered'], 1)
        self.assertEqual(restored.allow('cooldown', signal(150), 150)[1]['reason'], 'cooldown')
        self.assertEqual(restored.snapshot(150)['pending_confirmations'], 0)
        self.assertEqual(restored.snapshot(150)['migrated_from_version'], 2)
        lifecycle = restored.snapshot(150)['confirmation_lifecycle']
        self.assertEqual(lifecycle['terminal_reasons']['restart_discarded'], 1)
        self.assertEqual(lifecycle['accounting_residual'], 0)

    def test_confirmation_route_removal_and_legacy_instrumentation_boundary(self):
        self.warm()
        self.selector.allow('confirmed', confirmed_signal(124), 124)
        self.selector.retain_routes([])
        lifecycle = self.selector.snapshot(124)['confirmation_lifecycle']
        self.assertEqual(lifecycle['terminal_reasons']['route_removed'], 1)
        self.assertEqual(lifecycle['accounting_residual'], 0)
        old = self.selector.export_state()
        for key in ('confirmation_instrumentation_version', 'confirmation_instrumentation_begin_at',
                    'confirmation_lifecycle_counts', 'confirmation_waiting_checks',
                    'confirmation_pending_at_export'):
            old.pop(key)
        restored = StrategySelector(SimpleNamespace(max_book_age=2))
        restored.restore_state(old, 130)
        fresh = restored.snapshot(130)
        self.assertEqual(fresh['confirmation_instrumentation_begin_at'], 130)
        self.assertEqual(fresh['confirmation_lifecycle']['armed'], 0)

    def test_confirmation_gate_and_unexecutable_terminal_counts_once(self):
        self.warm()
        self.selector.allow('confirmed', confirmed_signal(124), 124)
        self.assertEqual(self.selector.allow('confirmed', confirmed_signal(125, 0), 125)[1]['reason'], 'signal')
        self.assertFalse(self.selector.cancel_confirmation(ROUTE))
        self.selector.allow('confirmed', confirmed_signal(126), 126)
        self.selector.observe(PAIR, books(126.1), 126.1, [])
        lifecycle = self.selector.snapshot(126.1)['confirmation_lifecycle']
        self.assertEqual(lifecycle['terminal_reasons']['gate_signal'], 1)
        self.assertEqual(lifecycle['terminal_reasons']['observe_unexecutable'], 1)
        self.assertEqual(lifecycle['armed'], 2)
        self.assertEqual(lifecycle['terminal_total'], 2)
        self.assertEqual(lifecycle['accounting_residual'], 0)

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
        status = self.selector.snapshot(123)
        self.assertEqual(status['warm_routes'], 1)
        self.assertEqual(status['max_route_samples'], 42)
        self.assertEqual(status['max_route_span_seconds'], 123)
        prior = self.selector.route_history(ROUTE, 120)
        self.assertEqual(len(prior), 40)
        self.assertEqual(prior[-1][0], 117)
        prior.clear()
        self.assertEqual(len(self.selector.route_history(ROUTE, 123)), 41)
        self.assertEqual(self.selector.allow('convergence', signal(200), 200)[1]['reason'], 'warmup')
        expired = self.selector.snapshot(200)
        self.assertEqual(expired['sampled_routes'], 0)
        self.assertEqual(expired['max_route_samples'], 0)
        self.assertEqual(expired['max_route_span_seconds'], 0)
        self.assertEqual(self.selector.route_history(ROUTE, 200), [])
        self.observe(201)
        self.selector.retain_routes([])
        self.assertEqual(self.selector.snapshot(201)['sampled_routes'], 0)
        self.assertEqual(set(self.selector.snapshot(201)['policies']), set(POLICIES))
        for now in range(300, 1301):
            self.observe(now)
        self.assertLessEqual(len(self.selector.routes[ROUTE].samples), MAX_SAMPLES)
        self.assertGreaterEqual(self.selector.routes[ROUTE].samples[0][0], 1300 - 900)
        self.assertEqual(len(self.selector.route_history(ROUTE, 1301)), MAX_SAMPLES)


if __name__ == '__main__':
    unittest.main()
