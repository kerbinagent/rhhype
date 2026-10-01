import ast,copy,gzip,hashlib,inspect,json,tempfile,textwrap,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_single_venue_strategy import book,META
from scripts.single_venue_strategy import Portfolio
from scripts.single_venue_executable_strategy import ExecutableStudy,WideAdmissionPortfolio,quote_features
from scripts.audit_single_venue_executable import ExecutableAudit
from scripts.audit_single_venue_depth import tracked
from scripts import audit_single_venue_executable_cash as audit
from scripts import single_venue_compact_evidence as compact
NS=10**9
METADATA={v:{'LIT':META} for v in audit.VS}

def shock(side=-1,bid=None,ask=None,ref=100):
    local=100.1 if side==-1 else 99.9
    return [book(9.98,bid=ref-.01,ask=ref+.01,venue='rh_lighter'),book(9.981),
        dict(type='trade',asset='LIT',venue='lighter',market='120',trade_id=42,received_ns=int(10.01*NS),
             source_ns=10*NS,price=local,qty=25,buy_aggressor=side==-1),
        book(10.02,bid=ref-.01,ask=ref+.01,venue='rh_lighter'),
        book(10.021,bid=local-.01 if bid is None else bid,ask=local+.01 if ask is None else ask)]

def run(events):
    rows=[];study=ExecutableStudy(METADATA,0,rows.append)
    for event in events:study.process(event)
    return study,rows

class ExecutableTests(unittest.TestCase):
    def test_only_admission_interval_changed_in_execution_and_cash_audit(self):
        old=textwrap.dedent(inspect.getsource(Portfolio.admit))
        new=textwrap.dedent(inspect.getsource(WideAdmissionPortfolio.admit))
        expected=old.replace('122*NS','3*NS').replace('480*NS','570*NS')
        self.assertEqual(ast.dump(ast.parse(new)),ast.dump(ast.parse(expected)))
        self.assertIs(Portfolio.process,WideAdmissionPortfolio.process)
        self.assertIs(Portfolio.submit,WideAdmissionPortfolio.submit)
        old=Path('scripts/audit_single_venue_study.py').read_text()
        self.assertEqual(Path('scripts/audit_single_venue_executable_cash.py').read_text(),
            old.replace('assert 122*NS<=now-start<480*NS','assert 3*NS<=now-start<570*NS'))

    def test_admission_boundaries(self):
        for seconds,accepted in ((2.999,False),(3,True),(569.999,True),(570,False)):
            rows=[];p=WideAdmissionPortfolio('baseline_fade','lighter',META,0,rows.append)
            p.admit(dict(direction=1),book(seconds),int(seconds*NS))
            self.assertEqual(p.attempts,int(accepted))

    def test_spread_widening_alone_rejects_both_filters(self):
        _,rows=run(shock(bid=99.99,ask=100.11))
        self.assertEqual([r['signal']['rule'] for r in rows if r['kind']=='signal'],['baseline_fade'])

    def test_side_move_passes_without_reference_price_pass(self):
        _,rows=run(shock(bid=100.03,ask=100.05,ref=100.08))
        self.assertEqual([r['signal']['rule'] for r in rows if r['kind']=='signal'],['baseline_fade','side_fade'])

    def test_both_directions_and_reference_depth(self):
        for side in (-1,1):
            study,rows=run(shock(side));signals=[r['signal'] for r in rows if r['kind']=='signal']
            self.assertEqual(len(signals),3);self.assertTrue(all(s['direction']==side for s in signals))
            books=copy.deepcopy(study.detector.books);other=books['rh_lighter']
            levels='asks' if side==-1 else 'bids';other[levels]=[(100.01 if side==-1 else 99.99,.1)]
            self.assertFalse(quote_features(signals[0],books,META)['full_depth'])
            other[levels].append((100.2 if side==-1 else 99.8,100))
            f=quote_features(signals[0],books,META)
            self.assertTrue(f['full_depth']);self.assertLess(float(f['reference_depth_edge_bps']),0)

    def test_independent_raw_signal_fill_and_cash_audit_with_corruption(self):
        events=shock()
        for j in range(101,250):
            t=j/10;px=100.1 if t<15 else 100.05
            events += [book(t,venue='rh_lighter'),book(t+.001,bid=px-.01,ask=px+.01)]
        events.append(dict(type='end',received_ns=30*NS))
        with patch('scripts.single_venue_strategy.snapshot',compact.compact_snapshot):study,trace=run(events)
        self.assertEqual(sum(r['kind']=='closed' for r in trace),3)
        self.assertTrue(all('levels_sha256' in r['book'] for r in trace if 'book' in r))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan=root/'plan.json';plan.write_text('{}');out=root/'reports/single-venue-research/fixture';out.mkdir(parents=True)
            def write():
                data=gzip.compress(('\n'.join(json.dumps(r) for r in trace)+'\n').encode(),mtime=0)
                (out/'trace.jsonl.gz').write_bytes(data)
                result=dict(error=None,complete_capture_verified=True,plan_sha256=audit.sha(plan),trace_sha256=hashlib.sha256(data).hexdigest(),manifest_sha256='0'*64,**study.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode(),mtime=0))
            def check():
                tracker=ExecutableAudit(METADATA)
                with patch.object(audit,'ROOT',root),patch.object(audit,'PLAN',plan),patch.object(audit,'match_book',compact.match_compact),patch.object(audit,'verify_signal',tracker.verify),patch.object(audit,'inputs',lambda *args:(root,'0'*64,METADATA,0,tracked(iter(events),tracker))):audit.audit('fixture')
            write();check()
            f=next(r for r in trace if r['kind']=='signal')['signal']['execution_filter'];old=f['reference_value'];f['reference_value']='12345'
            write()
            with self.assertRaises(AssertionError):check()
            f['reference_value']=old
            r=next(r for r in trace if r['kind']=='ioc');r['value']='12345';write()
            with self.assertRaises(AssertionError):check()

if __name__=='__main__':unittest.main()
