import unittest
from types import SimpleNamespace as S
from decimal import Decimal as D
from scripts.replay_core_maker_lit import quote_diagnostic
class OffsetPlannerTests(unittest.TestCase):
 def test_offset_grid_depth_and_fixed_rest_price(self):
  b=S(quote=None,offset=5,maker=S(price_tick=D('.00001'),qty_step=D('.01')),hedge=S(qty_step=D('.01')),cfg=S(budget_usd=D(100)))
  maker={'bids':[[4,10],[3.98,100]]};hedge={'bids':[[4,100]]}
  d=quote_diagnostic(b,maker,hedge);self.assertEqual(d,{'reason':'quote','price':'3.9980','quantity':'25'})
  self.assertEqual(quote_diagnostic(b,{'bids':[[4,10]]},hedge)['reason'],'book_depth_does_not_cover_better_queue')
  b.quote=S(price=D('3.9980'),qty=D(25));self.assertEqual(quote_diagnostic(b,{'bids':[[3.99,10]]},hedge),d)
if __name__=='__main__':unittest.main()
