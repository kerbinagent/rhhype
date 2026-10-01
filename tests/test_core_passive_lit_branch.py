import unittest
from decimal import Decimal as D
from scripts.core_passive_hedged_base import Config,NS
from scripts.core_passive_lit_branch import CorePassiveBranch
from tests.test_core_passive_hedged import META,book,trade,T

class CorePassiveLitTests(unittest.TestCase):
 def branch(self,activation=100,budget=100):
  b=CorePassiveBranch(Config('ETH',D(budget),'adaptive',maker_latency_ns=activation*1_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,hold_ns=10*NS,take_profit_usd=D(1)),META,exit_policy='control10s')
  b.capture_start_ns=T-10*NS;return b
 def core(self,t):return book('lighter',t,bids=[[100.2,.1],[100.1,.1],[100,.5],[99.9,10]])
 def start(self,b):
  b.process(self.core(0));b.process(book('rh_lighter',0),{'reason':'quote','price':'80','quantity':'1'})
 def test_real_sources_and_100ms_activation_partial_ioc_roundtrip(self):
  b=self.branch();self.start(b);self.assertEqual(b.quote.price,D(100))
  self.assertEqual(b.quote.activation_due_ns,T+100_000_000)
  b.process(self.core(.1));b.process(trade(.2,qty='.55'));self.assertEqual(b.maker_pos,D('.05'))
  b.process(book('rh_lighter',.599));self.assertEqual(b.hedge_pos,0)
  b.process(book('rh_lighter',.601));self.assertEqual(b.hedge_pos,D('-.05'))
  b.process(self.core(.602));b.tick(T+11*NS)
  b.process(book('lighter',11.000));self.assertEqual(b.maker_pos,D('.05'))
  b.process(book('lighter',11.002));b.process(book('rh_lighter',11.003));b.tick(T+14*NS)
  self.assertEqual(b.maker_pos,0);self.assertEqual(b.hedge_pos,0);self.assertIsNone(b.unknown_reason)
  s=b.summary();self.assertEqual(D(s['cash_known']),D('-.005'))
  self.assertEqual(s['source_venues'],{'maker':'lighter','hedge':'rh_lighter'})
  self.assertEqual(D(s['cash_maker_usdc'])+D(s['cash_hedge_usdg']),D('-.005'))
 def test_latency_control_changes_only_activation_and_keeps_unknowns(self):
  fast,slow=self.branch(100),self.branch(400)
  for b in (fast,slow):self.start(b)
  self.assertEqual(fast.quote.price,slow.quote.price);self.assertEqual(fast.quote.qty,slow.quote.qty)
  self.assertEqual(slow.quote.activation_due_ns-fast.quote.activation_due_ns,300_000_000)
  slow.process(self.core(.1));slow.process(trade(.2,qty='.75'))
  self.assertEqual(slow.maker_pos,0)
  self.assertIsNone(slow.unknown_reason)
  slow.process(trade(.401,qty='.75'))
  self.assertIsNotNone(slow.unknown_reason)
 def test_actual_cutoff_resting_minimum_and_ioc_limits(self):
  b=self.branch();b.capture_start_ns=T-480*NS;self.start(b)
  # start() does not alter the capture start; the actual-state gate rejects.
  self.assertIsNone(b.quote)
  b=self.branch(budget=1);self.start(b);self.assertIsNone(b.quote)
  with b._ioc_rules():
   self.assertTrue(b.hedge.valid_order(D('.05'),D(100)))
   self.assertFalse(b.hedge.valid_order(D('.005'),D(100)))
   self.assertFalse(b.hedge.valid_order(D(101),D(100)))
  self.assertFalse(b.hedge.valid_order(D('.05'),D(100)))

if __name__=='__main__':unittest.main()
