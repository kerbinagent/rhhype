import unittest
from decimal import Decimal as D
from scripts.core_hedged_maker_base import Config,NS
from scripts.core_maker_ioc_minimum_scenario import IocMinimumScenarioBranch
from tests.test_core_hedged_maker import META,book,trade,T
class IocMinimumTests(unittest.TestCase):
 def branch(self):return IocMinimumScenarioBranch(Config('ETH',D(100),'adaptive',hold_ns=10*NS,take_profit_usd=D(1)),META,exit_policy='control10s')
 def test_small_partial_hedges_and_flattens_with_latency(self):
  b=self.branch();diag={'reason':'quote','price':'100','quantity':'1'}
  b.process(book('rh_lighter',0));b.process(book('lighter',0),diag);b.process(book('rh_lighter',.4),diag)
  b.process(trade(.5,qty='.55'));self.assertEqual(b.maker_pos,D('.05'))
  b.process(book('lighter',.899));self.assertEqual(b.hedge_pos,0)
  b.process(book('lighter',.901));self.assertEqual(b.hedge_pos,D('-.05'))
  self.assertEqual(b.maker.min_notional,D(10));self.assertEqual(b.hedge.min_notional,D(10))
  b.process(book('rh_lighter',.902));b.tick(T+11*NS)
  b.process(book('rh_lighter',11.300));self.assertEqual(b.maker_pos,D('.05'))
  b.process(book('rh_lighter',11.302));b.process(book('lighter',11.303));b.tick(T+14*NS)
  self.assertEqual(b.maker_pos,0);self.assertEqual(b.hedge_pos,0);self.assertIsNone(b.unknown_reason)
  self.assertEqual(D(b.summary()['cash_known']),D('-.005'))
 def test_resting_minimum_and_ioc_grid_and_maximum_remain(self):
  b=self.branch();b.process(book('rh_lighter',0));b.process(book('lighter',0),{'reason':'quote','price':'100','quantity':'.05'});self.assertIsNone(b.quote)
  with b._ioc_rules():
   self.assertTrue(b.hedge.valid_order(D('.05'),D(100)))
   self.assertFalse(b.hedge.valid_order(D('.005'),D(100)))
   self.assertFalse(b.hedge.valid_order(D('101'),D(100)))
  self.assertFalse(b.hedge.valid_order(D('.05'),D(100)))
if __name__=='__main__':unittest.main()
