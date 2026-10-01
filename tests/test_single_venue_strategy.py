import sys
from pathlib import Path
from decimal import Decimal as D
import unittest
import tempfile, gzip, json, hashlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.single_venue_strategy import Portfolio, Features, NS, walk_ioc, pair_fresh
from scripts.single_venue_strategy import Study

META = dict(qty_step='.01', price_tick='.01', min_qty='.01', min_notional='10', taker_fee_bps='0')

def book(t, bid=99.99, ask=100.01, venue='lighter', depth=100):
    return dict(type='book', venue=venue, market='120' if venue == 'lighter' else '5',
        received_ns=int(t*NS), source_ns=int(t*NS), generation=venue+':1',sequence=int(t*1000),
        valid=True, clock_valid=True,bids=[(bid,depth)],asks=[(ask,depth)])

def start(side=1):
    logs=[];p=Portfolio('gap_fade','lighter',META,0,logs.append)
    p.admit(dict(direction=side),book(130),130*NS)
    return p,logs

class TestOneVenue(unittest.TestCase):
    def test_partial_ioc_does_not_turn_into_full_fill(self):
        b=book(1,depth=.4)
        q,v,_=walk_ioc(b,1,D('1'),D('100.02'))
        self.assertEqual(q,D('.4'));self.assertEqual(v,D('40.004'))

    def test_delayed_long_roundtrip_cash(self):
        p,logs=start()
        p.process(book(130.399));self.assertIsNotNone(p.pending);self.assertIsNone(p.position)
        p.process(book(130.4));q=D(p.position['quantity']);entry=D(p.position['entry_value'])
        p.process(book(140.4,bid=100.09,ask=100.11));self.assertEqual(p.pending['action'],'exit')
        p.process(book(140.8,bid=100.09,ask=100.11))
        self.assertIsNone(p.position);self.assertIsNone(p.unknown)
        capital=entry*D('.05')*D('10.4')/D(365*86400)
        self.assertEqual(p.cash,D(600)+q*D('.08')-capital)

    def test_short_profit_is_price_fall(self):
        p,_=start(-1);p.process(book(130.4));q=D(p.position['quantity'])
        p.process(book(140.4,bid=99.89,ask=99.91));p.process(book(140.8,bid=99.89,ask=99.91))
        self.assertEqual(D(p.episodes[0]['gross']),q*D('.08'))

    def test_receipt_after_due_with_source_before_due_cannot_fill(self):
        p,_=start();e=book(130.5);e['source_ns']=130_399_000_000;p.process(e)
        self.assertIsNone(p.position)
        p.process(book(132.5));self.assertEqual(p.unknown,'order_confirmation_timeout')

    def test_unsubmitable_partial_exit_retains_inventory(self):
        p,_=start();p.process(book(130.4,depth=.05));p.process(book(140.4))
        self.assertEqual(p.unknown,'exit_below_published_minimum')
        self.assertEqual(D(p.position['remaining']),D('.05'))

    def test_rejected_entry_zero_cash_pnl(self):
        p,_=start();p.process(book(130.4,bid=100.2,ask=100.3))
        self.assertIsNone(p.position);self.assertEqual(p.cash,D(600))
        self.assertEqual(p.counts['entry_no_fill'],1)

    def test_gap_does_not_require_other_venue_to_move_later(self):
        f=Features();signals=[]
        for i in range(130):
            f.process(book(i,venue='rh_lighter'))
            signals+=f.process(book(i+.01))
        self.assertFalse(signals)
        f.process(book(130,venue='rh_lighter',bid=100.19,ask=100.21))
        result=f.process(book(130.01))
        longs=[s for s in result if s['venue']=='lighter' and s['rule']=='gap_fade']
        self.assertEqual(len(longs),1);self.assertEqual(longs[0]['direction'],1)
        self.assertTrue(any(s['venue']=='lighter' and s['rule']=='leader_follow' for s in result))
        self.assertTrue(all(t<=longs[0]['t']-2*NS for t,_ in longs[0]['reference_rows']))

    def test_bad_pair_skew_rejected(self):
        self.assertFalse(pair_fresh({'lighter':book(2),'rh_lighter':book(1.5,venue='rh_lighter')},2*NS))

    def test_local_trade_shock_fades_only_when_reference_stays_stable(self):
        f=Features();signals=[]
        for j in range(1330):
            t=j/10
            f.process(book(t,venue='rh_lighter'))
            shocked=t>=130.1
            signals+=f.process(book(t+.001,bid=100.09 if shocked else 99.99,ask=100.11 if shocked else 100.01))
            if j%10==0:
                n=int((t+.05)*NS)
                f.process(dict(type='trade',venue='lighter',received_ns=n,source_ns=n,
                    qty=50 if t==130 else .1,price=100,buy_aggressor=True))
        shock=[s for s in signals if s['rule']=='local_shock_fade']
        self.assertTrue(shock)
        self.assertTrue(all(s['direction']==-1 and s['venue']=='lighter' for s in shock))
        self.assertGreaterEqual(shock[0]['shock']['flow']['notional'],5*shock[0]['shock']['baseline_median'])

    def test_full_raw_audit_accepts_cash_and_rejects_corrupted_fill(self):
        from scripts import audit_single_venue_study as a
        events=[]
        for j in range(1500):
            t=j/10
            # Reference jumps, target subsequently follows; independent arms can disagree.
            reference=100.2 if t>=130 else 100
            target=100.15 if t>=135 else 100
            events += [book(t,bid=reference-.01,ask=reference+.01,venue='rh_lighter'),
                       book(t+.001,bid=target-.01,ask=target+.01)]
        events.append(dict(type='end',received_ns=150*NS))
        trace=[];metadata={v:{'LIT':META} for v in ('lighter','rh_lighter')}
        s=Study(metadata,0,trace.append)
        for e in events:s.process(e)
        self.assertTrue(any(r['kind']=='closed' for r in trace))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan=root/'plan.json';plan.write_text('{}')
            out=root/'reports/single-venue-research/fixture';out.mkdir(parents=True)
            def write():
                raw=gzip.compress(('\n'.join(json.dumps(r) for r in trace)+'\n').encode(),mtime=0)
                (out/'trace.jsonl.gz').write_bytes(raw)
                result=dict(error=None,complete_capture_verified=True,plan_sha256=a.sha(plan),
                    trace_sha256=hashlib.sha256(raw).hexdigest(),manifest_sha256='0'*64,**s.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode(),mtime=0))
            write()
            with patch.object(a,'ROOT',root),patch.object(a,'PLAN',plan),patch.object(a,'inputs',
                    lambda *args:(root,'0'*64,metadata,0,iter(events))):
                a.audit('fixture')
                bad=next(r for r in trace if r['kind']=='ioc' and D(r['quantity'])>0)
                bad['value']=str(D(bad['value'])+1);write()
                with self.assertRaises(AssertionError):a.audit('fixture')

if __name__=='__main__': unittest.main()
