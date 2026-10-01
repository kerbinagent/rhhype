import unittest
from decimal import Decimal as D
from scripts.core_passive_sell_branch import CorePassiveSellBranch
from scripts.core_passive_hedged_base import Config,NS
from tests.test_core_passive_hedged import META,book,trade,T

class SellTests(unittest.TestCase):
 def start(self):
  b=CorePassiveSellBranch(Config('ETH',D(100),'adaptive',maker_latency_ns=100_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,hold_ns=10*NS,take_profit_usd=D(1)),META)
  b.capture_start_ns=T-10*NS
  b.process(self.core(0));b.process(book('rh_lighter',0),{})
  return b
 def core(self,t):return book('lighter',t,asks=[[100.3,.1],[100.4,.5],[100.5,10]])
 def test_partial_sell_delay_depletion_and_flat_cash(self):
  b=self.start();self.assertEqual(b.quote.price,D('100.5'))
  b.process(self.core(.1));b.process(trade(.2,side='buy',price='100.5',qty='10.05'))
  self.assertEqual(b.maker_pos,D('-.05'))
  b.process(book('rh_lighter',.599));self.assertEqual(b.hedge_pos,0)
  b.process(book('rh_lighter',.601));self.assertEqual(b.hedge_pos,D('.05'))
  self.assertEqual(b.books['hedge'].asks[0][1],D('9.95'))
  b.process(self.core(.602));b.tick(T+11*NS)
  b.process(self.core(11.002));b.process(book('rh_lighter',11.003));b.tick(T+14*NS)
  self.assertIsNone(b.unknown_reason);self.assertEqual(b.maker_pos,0);self.assertEqual(b.hedge_pos,0)
  s=b.summary();self.assertEqual(D(s['cash_known']),D('.005'))
  self.assertEqual(D(s['episodes'][0]['entry_hedge_qty']),D('.05'))
 def test_retirement_equality_buy_flow_and_entry_cutoff(self):
  b=self.start();b.process(self.core(.1));b.tick(T+5_100_000_000);b.process(self.core(5.6))
  b.process(trade(7.6,side='buy',price='100.5',qty='.01',source_ns=T+5_400_000_000))
  self.assertEqual(b.unknown_reason,'late_retired_quote_flow');self.assertTrue(b.episodes[0]['execution_unknown'])
  b=self.start();b.capture_start_ns=T-480*NS;b.quote=None;b.process(self.core(.01),{})
  self.assertIsNone(b.quote)

if __name__=='__main__':unittest.main()
