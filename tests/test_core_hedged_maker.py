"""Core source identity, timing, ledger and inherited queue/retirement controls."""
import unittest
from decimal import Decimal as D
from scripts.core_hedged_maker_base import Config,Book,NS,venue_key
from scripts.core_hedged_maker_retirement import RetirementGuardPassiveExitBranch as Branch
T=100*NS
RULE={'price_tick':'0.1','qty_step':'0.01','min_qty':'0.01','min_notional':'10','max_quote':'10000','maker_fee_bps':'0','taker_fee_bps':'0'}
META={'rh_lighter':RULE|{'venue':'rh_lighter'},'lighter':RULE|{'venue':'lighter'}}
DIAG={'reason':'quote','price':'100','quantity':'1'}
def book(v,t,**kw):
 d={'type':'book','venue':v,'source_venue':v,'asset':'ETH','market':'0','generation':'g','received_ns':T+int(t*NS),'source_ns':T+int(t*NS),'valid':True,'clock_valid':True,'bids':[[100,.5],[99.9,10]] if v=='rh_lighter' else [[100.2,10],[100.1,10]],'asks':[[100.4,10],[100.5,10]] if v=='rh_lighter' else [[100.3,10],[100.4,10]]}
 return d|kw
def trade(t,**kw):return {'type':'trade','venue':'rh_lighter','source_venue':'rh_lighter','asset':'ETH','generation':'g','received_ns':T+int(t*NS),'source_ns':T+int(t*NS),'clock_valid':True,'price':'100','qty':'1.5','trade_id':str(t),'side':'sell'}|kw
def branch():return Branch(Config('ETH',D(1000),'fixed_best',maker_latency_ns=400_000_000,cancel_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000),META,exit_policy='passive_best10s')
def start(b):
 b.process(book('rh_lighter',0));b.process(book('lighter',0),DIAG);b.process(book('rh_lighter',.4))
def match(b):
 start(b);b.process(trade(.5));b.process(book('lighter',.9));b.process(book('rh_lighter',.901))
 assert b.maker_pos==1 and b.hedge_pos==-1
class CoreMakerTests(unittest.TestCase):
 def test_actual_venue_mapping_and_reject_hl_book(self):
  self.assertEqual(venue_key('lighter'),'hedge');self.assertEqual(venue_key('rh_lighter'),'maker')
  self.assertEqual(venue_key('hyperliquid'),'hyperliquid')
  with self.assertRaises(ValueError):Book.parse(book('hyperliquid',0))
  b=branch();self.assertEqual(b.hedge.taker_fee_bps,0);self.assertFalse(b.hedge.valid_price(D('100.25')))
  self.assertEqual(b.summary()['source_venues'],{'maker':'rh_lighter','hedge':'lighter'})
 def test_hedge_needs_400ms_and_advanced_source(self):
  b=branch();start(b);b.process(trade(.5));b.process(book('lighter',.899));self.assertEqual(b.hedge_pos,0)
  b.process(book('lighter',.91,source_ns=T+899_000_000));self.assertEqual(b.hedge_pos,0)
  b.process(book('lighter',.92));self.assertEqual(b.hedge_pos,-1)
 def test_no_queue_fill_from_touch_and_duplicate(self):
  b=branch();start(b);b.process(trade(.5,qty='0.4'));self.assertEqual(b.maker_pos,0)
  b.process(trade(.6,qty='0.4',trade_id='0.5'));self.assertEqual(b.maker_pos,0)
  b.process(trade(.7,qty='0.2'));self.assertEqual(b.maker_pos,D('.1'))
 def test_full_roundtrip_cash_and_400ms_cover(self):
  b=branch();match(b)
  b.process(book('rh_lighter',2.91));b.process(book('lighter',2.91));self.assertIsNotNone(b.passive_ask)
  b.process(book('rh_lighter',3.32));b.process(book('lighter',3.32))
  b.process(trade(3.4,side='buy',price='100.4',qty='11'));self.assertEqual(b.maker_pos,0)
  b.process(book('lighter',3.799));self.assertEqual(b.hedge_pos,-1)
  b.process(book('lighter',3.801));self.assertEqual(b.hedge_pos,0)
  b.process(book('rh_lighter',3.81));b.tick(T+5_810_000_000)
  s=b.summary();self.assertIsNone(s['unknown_reason']);self.assertEqual(D(s['fee_only_complete_net']),D('.3'))
  self.assertEqual(D(s['cash_maker_usdg'])+D(s['cash_hedge_usdc']),D('.3'))
  self.assertEqual(D(s['stressed_complete_net']),D('.3')-D(s['reserve_cost'])-D(s['capital_cost']))
 def test_reject_hedge_keeps_obligation(self):
  b=branch();start(b);b.process(trade(.5));b.process(book('lighter',.91,bids=[[99,10],[98,10]]))
  self.assertEqual(b.maker_pos,1);self.assertEqual(b.hedge_pos,0);self.assertIsNotNone(b.fallback_requested_ns)
 def test_retirement_boundary_late_trade_unknown(self):
  b=branch();start(b);b.tick(T+5_400_000_000);b.process(book('rh_lighter',5.9))
  self.assertEqual(b.quote.cancel_due_ns,T+5_800_000_000)
  b.process(trade(7.9,source_ns=T+5_700_000_000,qty='.01'))
  self.assertEqual(b.unknown_reason,'late_retired_quote_flow');self.assertTrue(b.episodes[0]['execution_unknown'])
if __name__=='__main__':unittest.main()
