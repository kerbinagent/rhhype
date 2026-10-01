import sys,tempfile,unittest
from pathlib import Path
from collections import deque
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import core_spot_perp_limits as base
from core_spot_perp_reference_count import ReferenceBranch,reference
class ReferenceCountTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.archives=[]
  self.spot={'venue':'lighter','market':2049,'market_kind':'spot','asset':'LIT','step':'0.01','min_qty':.01,'min_notional':10,'fee_bps':0}
  self.perp=self.spot|{'market':120,'market_kind':'perp'};self.pair={'asset':'LIT','hl':self.spot,'other':self.perp}
 def tearDown(self):
  for archive in self.archives:archive.close()
  self.tmp.cleanup()
 def branch(self,cls,history,**kwargs):
  archive=base.Archive(Path(self.tmp.name)/f'{len(self.archives)}.gz',100000);self.archives.append(archive)
  shared={'history':{'LIT':deque(history)},'start':0.,'admissions':True,'archive':archive}
  b=cls([self.pair],100,60,shared,1,**kwargs)
  def book(m,bid,ask):return {'venue':'lighter','market':m['market'],'received':149.99,'engine_time':149.99,'valid':True,'generation':'test','sequence':1,'bids':[(bid,100)],'asks':[(ask,100)]}
  b.receive(book(self.spot,100.,100.01));b.receive(book(self.perp,100.10,100.11));b.tick(150.)
  return b
 def test_sparse_history_admits_only_sixty_without_leaking_hook(self):
  h=[(float(t),0.) for t in range(30,150,2)];saved=base.basis_reference
  sixty=self.branch(ReferenceBranch,h,minimum=60);self.assertEqual(sixty.sequence,1)
  self.assertIs(base.basis_reference,saved)
  ninety=self.branch(ReferenceBranch,h,minimum=90);original=self.branch(base.Branch,h)
  self.assertEqual(ninety.sequence,0);self.assertEqual(original.sequence,0)
  p=next(iter(sixty.positions.values()))
  self.assertEqual(p['reserved'],{'lighter':200.})
  for l in p['legs']:self.assertAlmostEqual(l['intent']['due']-l['intent']['created'],.4)
 def test_ninety_control_matches_original_and_time_guards_remain(self):
  h=[(float(t),0.) for t in range(25,149)]
  original=self.branch(base.Branch,h);control=self.branch(ReferenceBranch,h,minimum=90)
  self.assertEqual(original.sequence,1);self.assertEqual(list(original.positions.values()),list(control.positions.values()))
  self.assertIsNone(reference([(float(t),0.) for t in range(90,150)],150,60))
  self.assertIsNone(reference([(float(t),0.) for t in range(150,250)],150,60))
if __name__=='__main__':unittest.main()
