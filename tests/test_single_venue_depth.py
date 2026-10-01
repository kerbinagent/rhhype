import gzip,hashlib,json,tempfile,unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from tests.test_single_venue_strategy import book,META
from scripts.single_venue_depth_strategy import Detector,DepthStudy
from scripts.audit_single_venue_depth import SignalAudit,tracked
from scripts import audit_single_venue_study as auditor
NS=10**9

def initial():
    return [book(129.98,venue='rh_lighter'),book(129.981)]

def print_event():
    return dict(type='trade',asset='LIT',venue='lighter',market='120',trade_id=42,
        received_ns=int(130.01*NS),source_ns=130*NS,price=100.1,qty=25,buy_aggressor=True)

def post(local=100.1,reference=100):
    return [book(130.02,bid=reference-.01,ask=reference+.01,venue='rh_lighter'),
            book(130.021,bid=local-.01,ask=local+.01)]

class DepthTest(unittest.TestCase):
    def test_two_directions_only_after_new_post_book(self):
        d=Detector()
        for e in initial():self.assertEqual(d.process(e),[])
        self.assertEqual(d.process(print_event()),[])
        self.assertEqual(d.process(post()[0]),[])
        signals=d.process(post()[1])
        self.assertEqual({s['rule']:s['direction'] for s in signals},{'depth_fade':-1,'depth_follow':1})
        self.assertEqual(d.process(book(130.03)),[])

    def test_initial_post_rejection_not_retried_on_later_move(self):
        d=Detector()
        for e in initial()+[print_event()]+post(local=100):self.assertEqual(d.process(e),[])
        self.assertEqual(d.process(book(130.03,bid=100.2,ask=100.22)),[])

    def test_moving_reference_rejected(self):
        d=Detector()
        for e in initial()+[print_event()]+post(reference=100.1):self.assertEqual(d.process(e),[])

    def test_full_independent_execution_audit_and_corruption(self):
        events=initial()+[print_event()]+post()
        for j in range(1301,1450):
            t=j/10;target=100.1 if t<135 else 100.15
            events.extend([book(t,venue='rh_lighter'),book(t+.001,bid=target-.01,ask=target+.01)])
        events.append(dict(type='end',received_ns=150*NS))
        trace=[];metadata={v:{'LIT':META} for v in ('lighter','rh_lighter')}
        study=DepthStudy(metadata,0,trace.append)
        for e in events:study.process(e)
        self.assertEqual(sum(r['kind']=='closed' for r in trace),2)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan=root/'plan.json';plan.write_text('{}')
            out=root/'reports/single-venue-research/fixture';out.mkdir(parents=True)
            def write():
                data=gzip.compress(('\n'.join(json.dumps(r) for r in trace)+'\n').encode(),mtime=0)
                (out/'trace.jsonl.gz').write_bytes(data)
                result=dict(error=None,complete_capture_verified=True,plan_sha256=auditor.sha(plan),
                    trace_sha256=hashlib.sha256(data).hexdigest(),manifest_sha256='0'*64,**study.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode(),mtime=0))
            def check():
                tracker=SignalAudit()
                with patch.object(auditor,'ROOT',root),patch.object(auditor,'PLAN',plan),\
                     patch.object(auditor,'verify_signal',tracker.verify),patch.object(auditor,'inputs',\
                     lambda *args:(root,'0'*64,metadata,0,tracked(iter(events),tracker))):auditor.audit('fixture')
            write();check()
            row=next(r for r in trace if r['kind']=='ioc' and D(r['quantity'])>0)
            row['value']=str(D(row['value'])+1);write()
            with self.assertRaises(AssertionError):check()

if __name__=='__main__':unittest.main()
