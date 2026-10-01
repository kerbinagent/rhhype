import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core_rh_tight_control import Branch,Archive
class TightControlTest(unittest.TestCase):
 def test_same_drift_rejects_tight_leg_and_preserves_rescue(self):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   core={'venue':'lighter','market':1,'asset':'X','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   rh=core|{'venue':'rh_lighter'};pair={'asset':'X','hl':core,'other':rh}
   shared={'history':{'X':deque((float(i),0.) for i in range(25,149))},'start':0.,'admissions':True,'archive':archive}
   branches=[Branch([pair],100,60,shared,s) for s in (1,10)]
   def book(m,t,bid,ask):return {'venue':m['venue'],'market':m['market'],'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   for b in branches:
    b.receive(book(core,149.99,100.,100.01));b.receive(book(rh,149.99,100.10,100.11));b.tick(150.)
    self.assertEqual(b.sequence,1)
    b.receive(book(rh,150.41,100.10,100.11));b.receive(book(core,150.41,100.03,100.04))
   tight,control=branches;p=next(iter(tight.positions.values()));c=next(iter(control.positions.values()))
   self.assertEqual(p['status'],'EXITING');self.assertEqual(p['exit_reason'],'entry_failure');self.assertEqual(c['status'],'OPEN')
   self.assertEqual(next(l for l in p['legs'] if l['venue']=='lighter')['quantity'],0)
   tight.receive(book(rh,150.82,100.10,100.11));self.assertEqual(p['status'],'AWAITING_FUNDING');tight.settle_funding(p['id'],{'complete':True,'cashflow_usd':0,'events':[]},151.)
   self.assertLess(p['price_pnl'],0);self.assertFalse(tight.positions)
   self.assertEqual(c['status'],'OPEN');self.assertTrue(control.positions)
   self.assertAlmostEqual(sum(tight.ledgers['standard']['wallets'].values()),600+p['price_pnl']-p['capital_costs_usd'])
   archive.close()
if __name__=='__main__':unittest.main()
