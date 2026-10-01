import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core_rh_exit_target import ExitTargetBranch
from core_rh_persistent_entry import Archive
class ExitTargetTests(unittest.TestCase):
 def test_same_low_hurdle_entries_distinct_profit_exits_and_delay(self):
  with tempfile.TemporaryDirectory() as tmp:
   archive=Archive(Path(tmp)/'e.gz',100000)
   core={'venue':'lighter','market':1,'asset':'X','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
   rh=core|{'venue':'rh_lighter'};pair={'asset':'X','hl':core,'other':rh}
   def book(m,t,bid,ask):return {'venue':m['venue'],'market':1,'received':t,'engine_time':t,'valid':True,'generation':'test','sequence':int(t*100),'bids':[(bid,100)],'asks':[(ask,100)]}
   shared={'history':{'X':deque((float(i),0.) for i in range(25,150))},'start':0.,'admissions':True,'archive':archive}
   low,high=[ExitTargetBranch([pair],100,60,shared,t) for t in (1,6)]
   positions=[]
   for b in (low,high):
    b.receive(book(core,149.99,100.,100.01));b.receive(book(rh,149.99,100.07,100.08));b.tick(150.)
    self.assertEqual(b.sequence,1);self.assertEqual(b.confirm_seconds,0)
    p=next(iter(b.positions.values()));positions.append(p)
    b.receive(book(core,150.39,100.,100.01));self.assertIsNone(p['legs'][0]['entry_time'])
    b.receive(book(core,150.41,100.,100.01));b.receive(book(rh,150.41,100.07,100.08));self.assertEqual(p['status'],'OPEN')
    b.receive(book(core,151.,100.05,100.06));b.receive(book(rh,151.,100.07,100.08));b.tick(151.)
   self.assertEqual(positions[0]['status'],'EXITING');self.assertEqual(positions[1]['status'],'OPEN')
   high.receive(book(core,152.,100.09,100.10));high.receive(book(rh,152.,100.07,100.08));high.tick(152.)
   self.assertEqual(positions[1]['exit_reason'],'take_profit')
   high.receive(book(core,152.39,100.09,100.10));self.assertGreater(positions[1]['legs'][0]['remaining'],0)
   high.receive(book(core,152.41,100.09,100.10));high.receive(book(rh,152.41,100.07,100.08))
   self.assertEqual(positions[1]['status'],'AWAITING_FUNDING');archive.close()
if __name__=='__main__':unittest.main()
