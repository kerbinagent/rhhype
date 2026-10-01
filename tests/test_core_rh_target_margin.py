import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core_rh_target_margin import Branch,Archive

class TargetMarginTests(unittest.TestCase):
 def test_both_confirmed_but_different_forecast_hurdles(self):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   core={'venue':'lighter','market':1,'asset':'X','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   rh=core|{'venue':'rh_lighter'};pair={'asset':'X','hl':core,'other':rh}
   def book(m,t,bid,ask):return {'venue':m['venue'],'market':1,'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   for gap,expected in ((.07,(1,0)),(.10,(1,1))):
    history=deque((float(i),8. if i>=147 else 0.) for i in range(25,150))
    shared={'history':{'X':history},'start':0.,'admissions':True,'archive':archive}
    branches=[Branch([pair],100,60,shared,target) for target in (1,6)]
    for b in branches:
     self.assertEqual(b.confirm_seconds,2)
     self.assertEqual(b.config.take_profit_usd,b.target_bps*.01)
     b.receive(book(core,149.99,100.,100.01));b.receive(book(rh,149.99,100.+gap,100.01+gap));b.tick(150.)
    self.assertEqual(tuple(b.sequence for b in branches),expected)
    if gap==.10:
     high=branches[1];p=next(iter(high.positions.values()))
     high.receive(book(core,150.39,100.,100.01));self.assertIsNone(p['legs'][0]['entry_time'])
     high.receive(book(core,150.41,100.,100.01));high.receive(book(rh,150.41,100.10,100.11));self.assertEqual(p['status'],'OPEN')
     high.receive(book(core,151.,100.05,100.06));high.receive(book(rh,151.,100.10,100.11));high.tick(151.)
     self.assertEqual(p['status'],'OPEN')
     high.receive(book(core,152.,100.09,100.10));high.receive(book(rh,152.,100.10,100.11));high.tick(152.)
     self.assertEqual(p['exit_reason'],'take_profit');self.assertEqual(p['status'],'EXITING')
   archive.close()

if __name__=='__main__':unittest.main()
