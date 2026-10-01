import gzip,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_single_venue_strategy import book,META
from scripts.single_venue_clock_control import ClockStudy,ClockAudit,configure
from scripts import audit_single_venue_study as auditor
NS=10**9

class ClockControlTests(unittest.TestCase):
    def test_started_window_excluded(self):
        with self.assertRaises(AssertionError):configure(1)

    def test_missing_first_clock_expires_and_does_not_retry(self):
        rows=[];engine=ClockStudy({v:{'LIT':META} for v in auditor.VS},0,rows.append)
        for event in [book(123.1,venue='rh_lighter'),book(123.101),book(123.2,venue='rh_lighter')]:engine.process(event)
        self.assertFalse(rows)
        self.assertEqual(engine.counts['missing_clock_pair:lighter'],1)
        self.assertEqual(engine.counts['missing_clock_pair:rh_lighter'],1)

    def test_full_independent_cash_audit_and_wrong_schedule_rejection(self):
        events=[]
        for j in range(1219,1450):
            t=j/10;px=100 if t<128 else 100.05
            events += [book(t,bid=px-.01,ask=px+.01,venue='rh_lighter'),book(t+.001,bid=px-.01,ask=px+.01)]
        events.append(dict(type='end',received_ns=150*NS))
        trace=[];metadata={v:{'LIT':META} for v in auditor.VS};engine=ClockStudy(metadata,0,trace.append)
        for event in events:engine.process(event)
        self.assertEqual(sum(r['kind']=='closed' for r in trace),4)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan=root/'plan.json';plan.write_text('{}')
            out=root/'reports/single-venue-research/fixture';out.mkdir(parents=True)
            def write():
                blob=gzip.compress(('\n'.join(json.dumps(r) for r in trace)+'\n').encode(),mtime=0)
                (out/'trace.jsonl.gz').write_bytes(blob)
                result=dict(error=None,complete_capture_verified=True,plan_sha256=auditor.sha(plan),
                    trace_sha256=hashlib.sha256(blob).hexdigest(),manifest_sha256='0'*64,**engine.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode(),mtime=0))
            def check():
                tracker=ClockAudit(0)
                def observed():
                    for event in events:tracker.observe(event);yield event
                with patch.object(auditor,'ROOT',root),patch.object(auditor,'PLAN',plan),patch.object(auditor,'verify_signal',tracker.verify),patch.object(auditor,'inputs',lambda *args:(root,'0'*64,metadata,0,observed())):
                    auditor.audit('fixture')
            write();check()
            next(r for r in trace if r['kind']=='signal')['signal']['scheduled_ns']+=1
            write()
            with self.assertRaises(AssertionError):check()

if __name__=='__main__':unittest.main()
