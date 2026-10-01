import unittest,math
from scripts.single_venue_relative_gate_audit import scan,NS
def book(t,v,mid):
    return dict(type='book',asset='BTC',venue=v,received_ns=t*NS,source_ns=t*NS,
        bids=[[mid-.001,10]],asks=[[mid+.001,10]],valid=True,clock_valid=True)
def fixture(jump):
    e=[]
    for t in range(1,125):
        e.extend([book(t,'lighter',100*math.exp(jump/10000) if t==124 else 100),book(t,'rh_lighter',100)])
    return e+[dict(type='end',received_ns=126*NS)]
class GateAuditTest(unittest.TestCase):
    def test_necessary_gate_negative_and_positive_control(self):
        rows,_=scan(fixture(2),0)
        self.assertTrue(all(r['common_gate_pass']==0 for r in rows))
        rows,_=scan(fixture(6),0)
        self.assertTrue(all(r['admission_gap_rule_pass']==1 for r in rows))
    def test_invalidation_restarts_history(self):
        e=fixture(6);e.insert(-3,dict(type='invalidate',asset='BTC',venue='lighter',received_ns=123*NS))
        rows,_=scan(e,0)
        self.assertTrue(all(r['common_gate_pass']==0 for r in rows))
if __name__=='__main__':unittest.main()
