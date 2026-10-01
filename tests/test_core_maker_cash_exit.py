import unittest
from decimal import Decimal as D
from scripts.core_maker_cash_exit import CashBuyBranch,CashSellBranch
from scripts.core_passive_lit_branch import CorePassiveBranch
from scripts.core_passive_sell_branch import CorePassiveSellBranch
from scripts.core_passive_hedged_base import Config,NS
from tests.test_core_passive_hedged import META,book,trade,T
class CashExitTests(unittest.TestCase):
 def test_cash_target_exits_both_sides_while_stressed_target_waits(self):
  for side,old,new in [('buy',CorePassiveBranch,CashBuyBranch),('sell',CorePassiveSellBranch,CashSellBranch)]:
   branches=[]
   for cls in (old,new):
    b=cls(Config('ETH',D(100),'adaptive',maker_latency_ns=100_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,hold_ns=10*NS,take_profit_usd=D('.01')),META,exit_policy='control10s');b.capture_start_ns=T-10*NS
    def core(t):return book('lighter',t,bids=[[100.2,10],[100.1,.1],[100,.5],[99.9,10]],asks=[[100.3,10],[100.4,.5],[100.5,10]])
    b.process(core(0));b.process(book('rh_lighter',0),{});b.process(core(.1))
    b.process(trade(.2,side='sell' if side=='buy' else 'buy',price='100' if side=='buy' else '100.5',qty='.7' if side=='buy' else '10.2'))
    b.process(book('rh_lighter',.601));b.process(core(.602));branches.append(b)
   self.assertIsNone(branches[0].exit_requested_ns)
   self.assertIsNotNone(branches[1].exit_requested_ns)
   self.assertEqual(branches[0].cash_maker+branches[0].cash_hedge,branches[1].cash_maker+branches[1].cash_hedge)
   self.assertEqual(branches[0].reserve_cost,branches[1].reserve_cost)
   mark=branches[1]._episode_executable_exit_mark(T+602_000_000)
   self.assertGreater(mark,D('.01'));self.assertLess(mark,D('.03'))
if __name__=='__main__':unittest.main()
