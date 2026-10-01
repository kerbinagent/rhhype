import unittest
from decimal import Decimal as D
from scripts.core_passive_fair_sell import FairSellBranch
from scripts.core_passive_hedged_base import Config,Book,NS
from tests.test_core_passive_hedged import META,book,T

class FairValueTests(unittest.TestCase):
 def branch(self):
  b=FairSellBranch(Config('ETH',D(100),'adaptive',maker_latency_ns=100_000_000,hold_ns=10*NS,take_profit_usd=D('.06')),META,exit_policy='control10s')
  b.capture_start_ns=T;b.books={'maker':Book.parse(book('lighter',100,bids=[[100,10],[99,10]],asks=[[100.1,10],[101,10]])),'hedge':Book.parse(book('rh_lighter',100,bids=[[100,10]],asks=[[100.1,10]]))}
  b.references.extend((T+i*NS,D(-10)) for i in range(10,101));b.last_sample=T+100*NS
  return b
 def test_embargo_budget_and_forecast_floor(self):
  b=self.branch();self.assertEqual(b.model(T+100*NS)['reason'],'reference_warmup')
  b.references.appendleft((T+9*NS,D(-10)))
  baseline=b.model(T+100*NS);self.assertEqual(baseline['reason'],'quote')
  self.assertEqual(len(baseline['reference_rows']),90)
  self.assertEqual(baseline['reference_rows'][-1][0],T+98*NS)
  b.references[-1]=(T+100*NS,D(5000))
  self.assertEqual(b.model(T+100*NS)['price'],baseline['price'])
  self.assertGreaterEqual(D(baseline['forecast_cash']),D('.06'))
  self.assertLessEqual(D(baseline['quantity'])*D(baseline['price']),D(100))
  self.assertLessEqual(D(baseline['hedge_entry_value']),D(100))
 def test_live_quote_cancel_when_fair_floor_rises(self):
  b=self.branch();b.references.appendleft((T+9*NS,D(-10)))
  b._on_diagnostic({},T+100*NS);self.assertIsNotNone(b.quote)
  b.quote.activated_ns=T+100_100_000_000
  b.books['hedge']=Book.parse(book('rh_lighter',100.2,bids=[[100.2,10]],asks=[[100.3,10]]))
  b._on_diagnostic({},T+100_200_000_000)
  self.assertEqual(b.quote.cancel_reason,'model_reprice_or_threshold')
  self.assertEqual(b.quote.cancel_due_ns,T+100_600_000_000)
if __name__=='__main__':unittest.main()
