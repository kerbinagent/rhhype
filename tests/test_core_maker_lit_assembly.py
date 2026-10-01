import unittest
from decimal import Decimal as D
from scripts.replay_core_maker_lit_corrected import OffsetControlBranch
from scripts.core_hedged_maker_base import Config,NS
from tests.test_core_hedged_maker import META,book,trade,T
DIAG={'reason':'quote','price':'99.9','quantity':'1'}
class OffsetAssemblyTests(unittest.TestCase):
 def branch(self):return OffsetControlBranch(Config('ETH',D(100),'adaptive',hold_ns=10*NS),META,exit_policy='control10s')
 def test_constructor_and_quote_rest_keep_offset(self):
  b=self.branch();self.assertEqual(b.cfg.policy,'adaptive');self.assertFalse(b._passive)
  b.process(book('rh_lighter',0));b.process(book('lighter',0),DIAG)
  b.process(book('rh_lighter',.4),DIAG);self.assertIsNotNone(b.quote.activated_ns)
  self.assertIsNone(b.quote.cancel_due_ns);self.assertEqual(b.quote.price,D('99.9'))
  b.process(book('lighter',1),DIAG);b.process(book('rh_lighter',1),DIAG)
  self.assertIsNone(b.quote.cancel_due_ns)
 def test_preactivation_flow_remains_unknown(self):
  b=self.branch();b.process(book('rh_lighter',0));b.process(book('lighter',0),DIAG)
  b.process(trade(.41,price='99.9',qty='20'))
  self.assertIsNotNone(b.unknown_reason);self.assertEqual(b.maker_pos,0)
 def test_refuses_other_exit_or_hold(self):
  with self.assertRaises(ValueError):OffsetControlBranch(Config('ETH',D(100),'adaptive'),META,exit_policy='passive_best10s')
  with self.assertRaises(ValueError):OffsetControlBranch(Config('ETH',D(100),'adaptive',hold_ns=60*NS),META,exit_policy='control10s')
if __name__=='__main__':unittest.main()
