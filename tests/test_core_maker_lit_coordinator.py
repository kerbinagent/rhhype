import unittest
from decimal import Decimal as D
from scripts.core_hedged_maker_base import Config,NS
from scripts.replay_core_maker_lit_ioc_coordinator import CoordinatedIocBranch
from tests.test_core_hedged_maker import META,book,T
class CoordinatorTests(unittest.TestCase):
 def branch(self):
  b=CoordinatedIocBranch(Config('ETH',D(100),'adaptive',hold_ns=10*NS),META,exit_policy='control10s');b.offset=10;b.capture_start_ns=T-10*NS;return b
 def test_new_decision_recomputes_stale_prior_diagnostic(self):
  b=self.branch();b.process(book('rh_lighter',0,bids=[[100,1],[99,100]]))
  b.process(book('lighter',0),{'reason':'quote','price':'90','quantity':'1'})
  self.assertEqual(b.quote.price,D('99.9'));self.assertEqual(b.quote.qty,D('.99'))
 def test_actual_state_cutoff_is_enforced_even_when_input_says_quote(self):
  b=self.branch();b.capture_start_ns=T-480*NS
  b.process(book('rh_lighter',0,bids=[[100,1],[99,100]]));b.process(book('lighter',0),{'reason':'quote','price':'99.9','quantity':'1'})
  self.assertIsNone(b.quote)
 def test_active_quote_price_stays_fixed_after_cutoff(self):
  b=self.branch();b.process(book('rh_lighter',0,bids=[[100,1],[99,100]]));b.process(book('lighter',0),{'reason':'ignored'})
  b.process(book('rh_lighter',.4,bids=[[100,1],[99,100]]),{'reason':'ignored'})
  price=b.quote.price;b.capture_start_ns=T-480*NS
  b.process(book('lighter',.5),{'reason':'outside_admission_window'})
  self.assertEqual(b.quote.price,price);self.assertIsNone(b.quote.cancel_due_ns)
if __name__=='__main__':unittest.main()
