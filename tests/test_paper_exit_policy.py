"""Profit targets schedule actual delayed exits, never synthetic winning fills."""
import unittest
from tests.test_paper_engine import engine,book


class ExitPolicyTests(unittest.TestCase):
    def opened(self):
        e=engine(take_profit_usd=.10)
        e.receive(book('hyperliquid','BTC',1000.2,99.99,100))
        e.receive(book('rh_lighter',1,1000.5,102,102.01))
        return e,next(iter(e.positions.values()))

    def test_profit_target_is_net_of_all_costs_and_exits_are_delayed(self):
        e,p=self.opened()
        e.receive(book('hyperliquid','BTC',1001,100.4,100.41))
        e.receive(book('rh_lighter',1,1001,101.8,101.81))
        self.assertGreater(e.liquidation(p,1001),.10)
        e.tick(1001)
        self.assertEqual(p['status'],'EXITING')
        self.assertEqual(p['exit_reason'],'take_profit')
        self.assertEqual(p['exit_requested_at'],1001)
        self.assertGreater(p['legs'][0]['remaining'],0)
        # The market can reverse after the trigger, making actual exits lose.
        e.receive(book('hyperliquid','BTC',1001.3,99,99.01))
        e.receive(book('rh_lighter',1,1001.5,103,103.01))
        self.assertEqual(p['status'],'AWAITING_FUNDING')
        self.assertLess(p['price_net_before_funding'],0)

    def test_positive_gross_move_below_net_target_does_not_close(self):
        e,p=self.opened()
        e.receive(book('hyperliquid','BTC',1001,100.01,100.02))
        e.receive(book('rh_lighter',1,1001,101.98,101.99))
        self.assertLess(e.liquidation(p,1001),.10)
        e.tick(1001)
        self.assertEqual(p['status'],'OPEN')

    def test_max_hold_requests_exit_even_when_books_are_missing(self):
        e,p=self.opened()
        e.books.clear()
        e.tick(p['exit_due'])
        self.assertEqual(p['status'],'EXITING')
        self.assertEqual(p['exit_reason'],'max_hold')
        self.assertTrue(all(l['remaining']>0 for l in p['legs']))
        self.assertEqual(e.ledgers['standard']['closed_trades'],0)

    def test_profit_trigger_rejects_unsynchronized_books(self):
        e,p=self.opened()
        e.receive(book('hyperliquid','BTC',1000.6,100.4,100.41))
        e.receive(book('rh_lighter',1,1001.8,101.8,101.81))
        e.tick(1001.8)
        self.assertEqual(p['status'],'OPEN')

    def test_unknown_funding_blocks_profit_trigger_but_not_deadline(self):
        e,p=self.opened();p['exit_due']=3610
        e.receive(book('hyperliquid','BTC',3601,100.4,100.41))
        e.receive(book('rh_lighter',1,3601,101.8,101.81))
        e.tick(3601)
        self.assertEqual(p['status'],'OPEN')
        e.tick(3610)
        self.assertEqual(p['exit_reason'],'max_hold')


if __name__=='__main__':unittest.main()
