import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core_rh_persistent_entry import Branch,Archive,confirmation_samples
class ConfirmationTests(unittest.TestCase):
 def test_future_stale_gapped_and_directional_histories(self):
  h=[(147,8),(148,8),(149,8)]
  self.assertEqual(confirmation_samples(h,150,0,True),h)
  self.assertIsNone(confirmation_samples(h,151,0,True))
  self.assertIsNone(confirmation_samples([(146,8),(148,8),(149,8)],150,0,True))
  self.assertIsNone(confirmation_samples(h,150,0,False))
  self.assertIsNone(confirmation_samples([(147,8),(148,0),(149,8),(151,8)],150,0,True))
 def test_spike_filtered_sustained_admitted_and_delayed_close(self):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   core={'venue':'lighter','market':1,'asset':'X','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   rh=core|{'venue':'rh_lighter'};pair={'asset':'X','hl':core,'other':rh}
   def book(m,t,bid,ask):return {'venue':m['venue'],'market':1,'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   for sustained in (False,True):
    history=deque((float(i),8. if sustained and i>=147 else 0.) for i in range(25,150))
    shared={'history':{'X':history},'start':0.,'admissions':True,'archive':archive}
    branches=[Branch([pair],100,60,shared,c) for c in (0,2)]
    for b in branches:
     b.receive(book(core,149.99,100.,100.01));b.receive(book(rh,149.99,100.10,100.11));b.tick(150.)
    self.assertEqual(branches[0].sequence,1);self.assertEqual(branches[1].sequence,int(sustained))
    if sustained:
     b=branches[1];p=next(iter(b.positions.values()))
     b.receive(book(core,150.39,100.,100.01));self.assertIsNone(p['legs'][0]['entry_time'])
     b.receive(book(core,150.41,100.,100.01));b.receive(book(rh,150.41,100.10,100.11));self.assertEqual(p['status'],'OPEN')
     b.tick(211.)
     b.receive(book(core,211.41,100.09,100.10));b.receive(book(rh,211.41,100.10,100.11));self.assertEqual(p['status'],'AWAITING_FUNDING')
     b.settle_funding(p['id'],{'complete':True,'cashflow_usd':0,'events':[]},211.42);self.assertFalse(b.positions)
     self.assertGreater(p['price_pnl'],0)
   archive.close()
if __name__=='__main__':unittest.main()
