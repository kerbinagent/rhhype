import unittest,math
from unittest.mock import patch
from collections import defaultdict
from decimal import Decimal as D
from scripts import single_venue_residual_profile as p

def book(t,v,mid=100,asset='BTC',**kw):
    e=dict(type='book',asset=asset,venue=v,received_ns=int(t*p.NS),source_ns=int(t*p.NS),
        bids=[[mid-.01,10]],asks=[[mid+.01,10]],valid=True,clock_valid=True,generation=1)
    e.update(kw);return e
META={v:{'BTC':dict(qty_step='.01',min_qty='.01',min_notional='1')} for v in p.VS}
class FixedDecision:
    def __init__(self):self.books=defaultdict(dict)
    def process(self,e):
        if e['type']=='book':self.books[e['asset']][e['venue']]=e
        if e['type']=='invalidate':self.books[e['asset']].pop(e['venue'],None)
        return 4. if e['type']=='book' and e['received_ns']==200*p.NS and e['venue']=='rh_lighter' else None
def run(events):
    events=events+[dict(type='end',received_ns=600*p.NS)]
    with patch.object(p,'Basis',FixedDecision):return p.diagnose(events,META,0,['BTC'])
def row(rows,v,h):return next(r for r in rows if (r['venue'],r['bucket'],r['horizon'])==(v,'atleast3',h))
def seed():return [book(200,v) for v in p.VS]

class ResidualProfileTest(unittest.TestCase):
    def test_basis_embargo_and_asset_isolation(self):
        b=p.Basis();got={}
        for t in range(1,125):
            for a in ('BTC','ETH'):
                for v in p.VS:
                    mid=100*math.exp(.0006) if t==124 and a=='BTC' and v=='lighter' else 100
                    value=b.process(book(t,v,mid,a))
                    if value is not None:got[a]=value
        self.assertAlmostEqual(got['BTC'],6,places=8);self.assertEqual(got['ETH'],0)
        b.process(dict(type='invalidate',asset='BTC',venue='lighter',received_ns=125*p.NS))
        self.assertIsNone(b.process(book(125,'lighter',101)))
    def test_two_horizons_direction_and_reference_identity(self):
        e=seed()+[book(200.3,'rh_lighter')]+[book(200.4,v) for v in p.VS]
        e += [book(210.7,'rh_lighter',100.02),book(210.8,'lighter',99.98),book(210.8,'rh_lighter',100.02)]
        e += [book(260.7,'rh_lighter',100.10),book(260.8,'lighter',99.90),book(260.8,'rh_lighter',100.10)]
        rows=run(e)
        for v in p.VS:
            short,long=row(rows,v,10),row(rows,v,60)
            self.assertEqual(short['counts']['matched'],1);self.assertEqual(long['counts']['matched'],1)
            self.assertAlmostEqual(float(short['signed_quote_bps']['mean']),0,places=8)
            self.assertGreater(D(long['signed_quote_bps']['mean']),D(7))
            for r in (short,long):
                self.assertEqual(r['counts']['reference_matched'],1)
                self.assertLess(abs(D(r['signed_reference_bps']['mean'])+D(r['quote_minus_reference_bps']['mean'])-D(r['signed_quote_bps']['mean'])),D('1e-20'))
        self.assertEqual(row(rows,'lighter',10)['counts']['short_matched'],1)
        self.assertEqual(row(rows,'rh_lighter',10)['counts']['long_matched'],1)
    def test_bad_first_eligible_is_not_retried(self):
        e=seed()+[book(200.4,'lighter',valid=False),book(200.5,'lighter')]
        rows=run(e)
        for h in p.HORIZONS:
            r=row(rows,'lighter',h);self.assertEqual(r['counts']['missing_first_eligible'],1)
            self.assertEqual(r['signed_quote_bps']['n'],0)
    def test_missing_reference_does_not_drop_local_quote(self):
        e=seed()+[book(200.4,'lighter'),dict(type='invalidate',asset='BTC',venue='rh_lighter',received_ns=201*p.NS),
                  book(210.8,'lighter',99.9),book(260.8,'lighter',99.8)]
        rows=run(e)
        for h in p.HORIZONS:
            r=row(rows,'lighter',h);self.assertEqual(r['counts']['matched'],1);self.assertEqual(r['counts']['reference_missing'],1)
            self.assertEqual(row(rows,'rh_lighter',h)['counts']['invalidated'],1)
    def test_entry_cap_and_tail_missing_are_counted(self):
        rows=run(seed()+[book(200.4,'lighter',103)])
        for h in p.HORIZONS:
            self.assertEqual(row(rows,'lighter',h)['counts']['entry_quote_above_cap'],1)
            self.assertEqual(row(rows,'rh_lighter',h)['counts']['unresolved_at_end'],1)

if __name__=='__main__':unittest.main()
