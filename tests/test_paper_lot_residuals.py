"""Exit quantities remain tradable after partial fills and old checkpoints."""

import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_engine import EngineConfig, PaperEngine, available_fill


def pair(step='.01'):
    hl = {'venue': 'hyperliquid', 'market': 'BTC', 'asset': 'BTC',
          'fee_bps': 4.5, 'step': step, 'min_qty': float(step),
          'min_notional': 10, 'collateral': 'USDC'}
    other = dict(hl, venue='rh_lighter', market=1, fee_bps=0)
    return {'asset': 'BTC', 'hl': hl, 'other': other, 'metadata_timestamp': 1000}


def book(venue, market, when, size=100, generation='g1'):
    bid, ask = (99.99, 100) if venue == 'hyperliquid' else (102, 102.01)
    return {'venue': venue, 'market': market, 'bids': [(bid, size)],
            'asks': [(ask, size)], 'received': when, 'engine_time': when,
            'valid': True, 'generation': generation}


def opened_engine(step='.01'):
    cfg = EngineConfig(holding_seconds=5, strategies=('standard',), capital_rate=0)
    e = PaperEngine([pair(step)], cfg, now=1000)
    e.receive(book('hyperliquid', 'BTC', 1000))
    e.receive(book('rh_lighter', 1, 1000))
    e.tick(1000)
    e.receive(book('hyperliquid', 'BTC', 1000.2))
    e.receive(book('rh_lighter', 1, 1000.5))
    p = next(iter(e.positions.values()))
    assert p['status'] == 'OPEN'
    e.tick(1005.6)
    return e, p


class LotResidualTests(unittest.TestCase):
    def test_near_lot_position_residual_fills_only_if_displayed_depth_covers_lot(self):
        for step, residual in (('.01', 0.009999999999999787),
                               ('.001', 0.0009999999999996678)):
            with self.subTest(step=step):
                q, _, _ = available_fill([(100, 1)], residual, step)
                self.assertEqual(q, float(step))
                q, _, _ = available_fill([(100, residual)], residual, step)
                self.assertEqual(q, 0)

    def test_repeated_partials_conserve_lots_and_wait_for_new_eligible_book(self):
        e, p = opened_engine()
        hl, other = p['legs']
        entry = Decimal(str(hl['quantity']))
        self.assertEqual(entry, Decimal('9.79'))

        # The other leg closes while Hyperliquid is still partially exposed.
        e.receive(book('rh_lighter', 1, 1006.1))
        self.assertEqual(other['remaining'], 0)
        for i in range(8):
            when = 1005.8 + i * .2
            e.receive(book('hyperliquid', 'BTC', when, size=1.22))
            expected = entry - Decimal('1.22') * (i + 1)
            self.assertEqual(Decimal(str(hl['remaining'])), expected)
            self.assertEqual(sum((Decimal(str(f['quantity'])) for f in hl['exit_fills']),
                                 Decimal(0)) + Decimal(str(hl['remaining'])), entry)
        self.assertEqual(hl['remaining'], .03)
        self.assertEqual(p['status'], 'EXITING')

        due = hl['intent']['due']
        e.tick(due + .001)
        self.assertEqual(hl['remaining'], .03)  # A clock tick cannot reuse a book.
        e.receive(book('hyperliquid', 'BTC', due + .01, size=.02))
        self.assertEqual(hl['remaining'], .01)
        next_due = hl['intent']['due']
        e.receive(book('hyperliquid', 'BTC', next_due - .01, size=1))
        self.assertEqual(hl['remaining'], .01)
        e.receive(book('hyperliquid', 'BTC', next_due + .01, size=.01))
        self.assertEqual(hl['remaining'], 0)
        self.assertEqual(p['status'], 'AWAITING_FUNDING')
        self.assertEqual(sum((Decimal(str(f['quantity'])) for f in hl['exit_fills']),
                             Decimal(0)), entry)

    def test_legacy_checkpoint_noisy_last_lot_restores_and_exits(self):
        e, p = opened_engine()
        hl = p['legs'][0]
        e.receive(book('hyperliquid', 'BTC', 1005.8, size=9.78))
        self.assertEqual(hl['remaining'], .01)
        e.receive(book('rh_lighter', 1, 1006.1))
        state = copy.deepcopy(e.export_state())
        saved = next(iter(state['positions'].values()))
        saved['legs'][0]['remaining'] = 0.009999999999999787
        saved['legs'][0]['intent']['quantity'] = 0.009999999999999787
        restored = PaperEngine([pair()], e.config, state=state, now=1006.2)
        leg = next(iter(restored.positions.values()))['legs'][0]
        self.assertEqual(leg['remaining'], .01)
        self.assertEqual(leg['intent']['generation'], 'restart-invalidated')
        restored.receive(book('hyperliquid', 'BTC', 1006.3))
        self.assertEqual(leg['remaining'], .01)  # First book reissues after restart.
        self.assertGreater(leg['intent']['due'], 1006.3)
        first_due = leg['intent']['due']
        restored.receive(book('hyperliquid', 'BTC', first_due + .01,
                              size=.009999999999999787))
        self.assertEqual(leg['remaining'], .01)  # Real displayed depth is below a lot.
        restored.receive(book('hyperliquid', 'BTC', first_due + .02, size=.01))
        self.assertEqual(leg['remaining'], .01)  # Reissued intent has a new delay.
        restored.receive(book('hyperliquid', 'BTC', leg['intent']['due'] + .01, size=.01))
        self.assertEqual(leg['remaining'], 0)
        self.assertEqual(next(iter(restored.positions.values()))['status'], 'AWAITING_FUNDING')


if __name__ == '__main__':
    unittest.main()
