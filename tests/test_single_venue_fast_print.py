import math,unittest
from scripts.single_venue_fast_print import Probe,NS,VENUES

def book(v,t,source,m=100):
    return dict(type='book',asset='LIT',venue=v,received_ns=int(t*NS),source_ns=int(source*NS),
        valid=True,clock_valid=True,bids=[(m-.01,1)],asks=[(m+.01,1)])

def pair(p,t,source,local=100):
    for v in VENUES:p.process(book(v,t,source,local if v=='lighter' else 100))

def trade(t=1.11,source=1.1,qty=.3):
    return dict(type='trade',asset='LIT',venue='lighter',received_ns=int(t*NS),
        source_ns=int(source*NS),price=100,qty=qty,buy_aggressor=True)

class FastPrintTest(unittest.TestCase):
    def test_pre_source_strict_and_depth_selection(self):
        p=Probe();pair(p,1,1);p.process(trade(source=1))
        self.assertEqual(len(p.rows),0)
        self.assertEqual(p.counts['lighter:missing_strict_pre_pair'],1)
        p.process(trade(qty=.249));self.assertEqual(len(p.rows),0)
        p.process(trade(qty=.25));self.assertEqual(len(p.rows),1)
        self.assertEqual(p.rows[0]['decision_status'],'pending')

    def test_horizon_requires_both_source_and_receipt(self):
        p=Probe();pair(p,1,.99);p.process(trade());pair(p,1.12,1.115,101)
        r=p.rows[0];self.assertEqual(r['decision_status'],'matched')
        pair(p,1.222,1.215,100.5)
        self.assertNotIn('100',r['horizons'])
        pair(p,1.23,1.225,100.5)
        self.assertEqual(r['horizons']['100']['status'],'matched')
        self.assertAlmostEqual(r['horizons']['100']['target_fade_bps'],-10000*math.log(100.5/101))
        self.assertTrue(r['local_move_and_stable_reference'])

    def test_late_post_pair_remains_missing(self):
        p=Probe();pair(p,1,.99);p.process(trade());pair(p,1.361,1.35,101)
        self.assertEqual(p.rows[0]['decision_status'],'missing_post_pair_in_250ms')
        p.process(dict(type='end',received_ns=2*NS))
        self.assertEqual(p.rows[0]['horizons']['100']['status'],'no_decision')

    def test_invalidation_preserves_candidate_and_unknown_horizons(self):
        p=Probe();pair(p,1,.99);p.process(trade());pair(p,1.12,1.115)
        p.process(dict(type='invalidate',venue='lighter',received_ns=int(1.2*NS)))
        pair(p,1.23,1.225)
        self.assertEqual(p.rows[0]['horizons']['100']['status'],'invalidation_crossing')
        self.assertFalse(p.rows[0]['local_move_and_stable_reference'])

if __name__=='__main__':unittest.main()
