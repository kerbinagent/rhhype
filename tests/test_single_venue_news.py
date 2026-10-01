import datetime,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_news as news

class FakeClock:
    def __init__(self,t):self.t=t;self.m=0;self.sleeps=[]
    def wall(self):return self.t
    def mono(self):return self.m
    def sleep(self,s):self.sleeps.append(s);self.t+=s;self.m+=s

class NewsTest(unittest.TestCase):
    def test_bounded_wait_and_late_start(self):
        c=FakeClock(0);beats=[]
        news.wait_for_target(65,lambda:beats.append(c.t),c.wall,c.mono,c.sleep)
        self.assertEqual(c.sleeps,[30,30,5]);self.assertEqual(c.t,65)
        c=FakeClock(96)
        with self.assertRaisesRegex(TimeoutError,'missed_scheduled'):news.wait_for_target(65,lambda:None,c.wall,c.mono,c.sleep)
        c=FakeClock(0)
        with self.assertRaises(AssertionError):news.wait_for_target(news.MAX_WAIT_SECONDS+1,lambda:None,c.wall,c.mono,c.sleep)
    def test_wall_clock_backward_jump_cannot_extend_wait_forever(self):
        c=FakeClock(0)
        def sleep(s):c.m+=news.MAX_WAIT_SECONDS+1;c.t-=1
        with self.assertRaisesRegex(TimeoutError,'bounded_wait'):news.wait_for_target(65,lambda:None,c.wall,c.mono,sleep)
    def test_normal_endpoint_requires_event_coverage(self):
        def stamp(t):return datetime.datetime.fromtimestamp(t,datetime.timezone.utc).isoformat()
        def m(start,end):return dict(started_utc=stamp(start),ended_utc=stamp(end))
        self.assertTrue(news.coverage(m(news.EVENT-240,news.EVENT+360)))
        self.assertFalse(news.coverage(m(news.EVENT-149,news.EVENT+451)))
        self.assertFalse(news.coverage(m(news.EVENT-301,news.EVENT+299)))
    def test_both_original_families_and_native_ids_are_preserved(self):
        from scripts.single_venue_strategy import Study,PARAMS
        from scripts.single_venue_depth_strategy import DepthStudy
        for family,cls in (('relative',Study),('depth',DepthStudy)):
            news.configure(family)
            self.assertIs(news.study.Study,cls);self.assertIs(news.study.PARAMS,PARAMS)
            self.assertEqual(set(news.study.NAMES),set(news.ASSETS))
            self.assertEqual(len(news.SELECTED['lighter']),10)
            self.assertEqual(news.study.capture.HARD_BYTES-news.study.capture.METADATA_MAX_BYTES,news.RAW_BYTES+131072)
            for a in news.ASSETS:self.assertEqual(news.study.NAMES[a],'single-venue-news-'+family+'-'+a.lower())
            with patch.object(news.events,'iter_events') as read:
                news.study.iter_events('x',expected_manifest_sha256='hash',max_raw_bytes=news.HARD_BYTES)
                self.assertEqual(read.call_args.kwargs['max_decoded_bytes'],1073741824)
                self.assertEqual(read.call_args.kwargs['max_records'],1000000)
    def test_missed_start_never_launches_capture(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(news,'OUT',Path(td)),patch.object(news,'verify'),patch.object(news,'require_predecessor'),patch.object(news.study,'sha',return_value='x'),patch.object(news,'wait_for_target',side_effect=TimeoutError('late')),patch.object(news.subprocess,'run') as run:
                news.supervise();run.assert_not_called()
                self.assertFalse(json.loads((Path(td)/'terminal.json').read_bytes())['normal_endpoint'])
    def test_capture_failure_and_timeout_never_retry(self):
        for outcome in (type('Run',(),{'returncode':1})(),news.subprocess.TimeoutExpired('capture',720)):
            with tempfile.TemporaryDirectory() as td:
                with patch.object(news,'OUT',Path(td)),patch.object(news,'verify'),patch.object(news,'require_predecessor'),patch.object(news.study,'sha',return_value='x'),patch.object(news,'wait_for_target'),patch.object(news.subprocess,'run') as run:
                    if isinstance(outcome,Exception):run.side_effect=outcome
                    else:run.return_value=outcome
                    news.supervise();self.assertEqual(run.call_count,1)
                    self.assertFalse(json.loads((Path(td)/'terminal.json').read_bytes())['normal_endpoint'])
    def test_matching_independent_auditor_for_each_family(self):
        from scripts import audit_single_venue_study as cash
        from scripts import audit_single_venue_depth as depth
        news.configure('relative')
        with patch.object(cash,'audit') as audit:
            news.audit('relative','BTC','x')
            audit.assert_called_once_with('single-venue-news-relative-btc','x')
        news.configure('depth')
        with patch.object(depth,'run_audit') as audit:
            news.audit('depth','BTC','x');audit.assert_called_once_with('BTC','x')
    def test_eastern_time_conversion(self):
        from zoneinfo import ZoneInfo
        local=datetime.datetime(2026,10,2,8,30,tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(local.timestamp(),news.EVENT)

if __name__=='__main__':unittest.main()
