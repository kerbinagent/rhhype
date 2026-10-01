import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paradex_core_shortterm import Branch,Archive,interpolate_index,funding_settlement
from paper_engine import taker_delay
class TestParadexCore(unittest.TestCase):
 def test_funding_and_delay_lifecycle(self):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   a={'venue':'lighter','market':1,'asset':'BTC','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   c=a|{'venue':'paradex','market':'BTC-USD-PERP'};pair={'asset':'BTC','hl':a,'other':c}
   def f(t):return {'created':t,'published':t,'received':t,'index':t*.001,'premium':28.8,'period_hours':8}
   shared={'history':{'BTC':deque((float(i),0.) for i in range(25,149))},'funding':{'BTC':deque([f(145.)])},'start':0.,'admissions':True,'archive':archive}
   branch=Branch([pair],100,10,shared)
   self.assertEqual(taker_delay(c,'standard',branch.config),.4)
   def book(m,t,bid,ask):return {'venue':m['venue'],'market':m['market'],'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   branch.receive(book(a,149.99,99.99,100.));branch.receive(book(c,149.99,100.08,100.09));branch.tick(150.)
   self.assertEqual(branch.sequence,1);pos=next(iter(branch.positions.values()))
   branch.receive(book(a,150.39,99.99,100.));self.assertIsNone(pos['legs'][0]['entry_time'])
   branch.receive(book(a,150.41,99.99,100.));branch.receive(book(c,150.41,100.08,100.09));self.assertEqual(pos['status'],'OPEN')
   branch.tick(160.42);branch.receive(book(a,160.83,100.08,100.09));branch.receive(book(c,160.83,100.08,100.09));self.assertEqual(pos['status'],'AWAITING_FUNDING')
   rows=[f(t) for t in (150.,155.,160.,165.)];settle=funding_settlement(pos,rows,166.)
   self.assertTrue(settle['estimated']);self.assertAlmostEqual(settle['cashflow_usd'],pos['legs'][1]['quantity']*.01042)
   branch.settle_funding(pos['id'],settle,166.);self.assertEqual(pos['status'],'CLOSED_ESTIMATED');self.assertFalse(branch.positions)
   self.assertEqual(len(branch.retail_requests),2)
   archive.close()
 def test_funding_gap_and_limits(self):
  rows=[{'created':1.,'index':1.},{'created':10.,'index':2.}]
  self.assertIsNone(interpolate_index(rows,5.));self.assertIsNone(interpolate_index(rows,11.))
  obj=object.__new__(Branch);obj.retail_requests=deque([5.1,5.2,5.3]);self.assertFalse(obj.retail_allowed(5.4));self.assertTrue(obj.retail_allowed(7.))
if __name__=='__main__':unittest.main()
