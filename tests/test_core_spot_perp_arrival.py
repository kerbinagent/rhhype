import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core_spot_perp_arrival import Branch,Archive,arrival_sample
class TestSpotPerp(unittest.TestCase):
 def run_case(self,reject_perp):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   spot={'venue':'lighter','market':2049,'market_kind':'spot','asset':'LIT','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   perp=spot|{'market':120,'market_kind':'perp'};pair={'asset':'LIT','hl':spot,'other':perp}
   shared={'history':{'LIT':deque((float(i),0.) for i in range(25,149))},'start':0.,'admissions':True,'archive':archive}
   branch=Branch([pair],100,10,shared)
   def book(m,t,bid,ask):return {'venue':'lighter','market':m['market'],'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   branch.receive(book(spot,149.99,100.,100.01));branch.receive(book(perp,149.99,100.10,100.11));branch.tick(150.)
   self.assertEqual(branch.sequence,1);p=next(iter(branch.positions.values()));self.assertEqual(p['reserved'],{'lighter':200.})
   long=next(l for l in p['legs'] if l['side']=='long');short=next(l for l in p['legs'] if l['side']=='short')
   self.assertEqual(long['market'],2049);self.assertEqual(short['market'],120)
   branch.receive(book(spot,150.41,100.,100.01));branch.receive(book(perp,150.41,100.00 if reject_perp else 100.10,100.11))
   spot_cash=branch.ledgers['standard']['wallets']['lighter']-long['entry_value'];self.assertGreaterEqual(spot_cash,0.)
   if reject_perp:
    self.assertEqual(p['status'],'EXITING');self.assertEqual(short['quantity'],0)
    branch.receive(book(spot,150.82,100.,100.01));self.assertEqual(p['exit_reason'],'entry_failure')
   else:
    self.assertEqual(p['status'],'OPEN');branch.tick(160.42)
    branch.receive(book(spot,160.83,100.08,100.09));branch.receive(book(perp,160.83,100.08,100.09))
   self.assertEqual(p['status'],'AWAITING_FUNDING');branch.settle_funding(p['id'],{'complete':True,'cashflow_usd':0,'events':[]},161.)
   actual=600-long['entry_value']+long['exit_value']+short['price_pnl']-p['capital_costs_usd']
   self.assertAlmostEqual(actual,branch.ledgers['standard']['wallets']['lighter'])
   self.assertGreater(p['price_pnl'],0) if not reject_perp else self.assertLess(p['price_pnl'],0)
   self.assertFalse(branch.positions);archive.close()
 def test_arrival_spacing_and_sync(self):
  h=deque();a={'received':100.,'engine_time':99.9,'valid':True,'bids':[(100.,1)],'asks':[(101.,1)]};b=a|{'received':100.1,'engine_time':100.}
  self.assertIsNotNone(arrival_sample(h,a,b,100.1,'X'))
  self.assertIsNone(arrival_sample(h,a,b,100.9,'X'))
  self.assertIsNone(arrival_sample(h,a,b|{'received':101.2},101.2,'X'))
  self.assertIsNotNone(arrival_sample(h,a|{'received':101.2,'engine_time':101.1},b|{'received':101.3,'engine_time':101.2},101.3,'X'))
  self.assertEqual(len(h),2)
 def test_paired_cash_inventory(self):self.run_case(False)
 def test_failed_perp_retains_spot_rescue_loss(self):self.run_case(True)
if __name__=='__main__':unittest.main()
