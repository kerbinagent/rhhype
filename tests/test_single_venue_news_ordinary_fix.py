"""Synthetic contracts only; never inspect captured research outcomes."""
import gzip,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_news_ordinary_fix as f
from scripts import single_venue_news_ordinary_fix_readout as report
from scripts import audit_single_venue_study as cash
from scripts import audit_single_venue_depth as depth_audit

class OrdinaryFixTest(unittest.TestCase):
    def setUp(self):
        # Family configuration intentionally uses fresh process globals in production.
        self.modules=[f.news.study,f.news.study.capture,f.ordinary,cash,
            f.news.previous.events,f.compact.strategy,f.compact.runner]
        self.saved=[dict(m.__dict__) for m in self.modules]
    def tearDown(self):
        for m,s in zip(self.modules,self.saved):
            for k in set(m.__dict__)-set(s):del m.__dict__[k]
            m.__dict__.update(s)
    def plan(self):
        return dict(status='frozen',original_capture_plan_sha256=f.CAPTURE_PLAN_SHA,
            capture_plan=str(f.news.PLAN.relative_to(f.ROOT)),capture_root='reports/single-venue-news/capture',
            control_root='reports/single-venue-news-ordinary-fix-v1',output_stem='single-venue-news-ordinary-fix',
            assets=list(f.news.ASSETS),selected=f.news.SELECTED,families=['relative','depth'],
            execution_parameters=f.news.PARAMS,duration_seconds=600,capture_hard_bytes=f.BOUNDS['raw_bytes'],
            scheduled_start_epoch=f.news.TARGET,event_epoch=f.news.EVENT,adapter_bounds=f.BOUNDS,
            output_caps=f.CAPS,source_pins=[dict(path='source.py',sha256='new-source')])
    def test_separate_protocol_hashes_and_frozen_source_contract(self):
        p=self.plan();old={k:p[k] for k in ('assets','selected','families','execution_parameters',
            'duration_seconds','capture_hard_bytes','scheduled_start_epoch','event_epoch')}
        def digest(path):return f.CAPTURE_PLAN_SHA if path==f.news.PLAN else 'new-source'
        with patch.object(f,'read',return_value=p),patch.object(f,'sha',side_effect=digest),patch.object(f.news,'verify',return_value=old),patch.object(f,'configure') as config:
            self.assertIs(f.verify('depth'),p);config.assert_called_once_with(p,'depth')
            p['status']='DRAFT'
            with self.assertRaisesRegex(AssertionError,'not_frozen'):f.verify()
            p['status']='frozen';p['original_capture_plan_sha256']='successor'
            with self.assertRaises(AssertionError):f.verify()

    def test_normal_coverage_and_full_input_inventory_are_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'reports/single-venue-news';cap=out/'capture';md=cap/'metadata';md.mkdir(parents=True)
            original=root/'original.json';original.write_text('{}');analysis=root/'analysis.json';analysis.write_text('{}')
            for name in f.news.study.capture.REQUESTS:
                for suffix in ('.json.gz','.request.json'):(md/(name+suffix)).write_bytes(b'{}')
            for name in ('market_plan.json','normalized.json'):(md/name).write_text('{}')
            raw=cap/'frames.jsonl.gz';raw.write_bytes(gzip.compress(b'fixture'))
            def stamp(epoch):return f.datetime.datetime.fromtimestamp(epoch,f.datetime.timezone.utc).isoformat()
            manifest=dict(market_plan_sha256=f.CAPTURE_PLAN_SHA,end_reason='duration_limit',truncated=False,
                started_utc=stamp(f.news.EVENT-240),ended_utc=stamp(f.news.EVENT+360),selected_markets=f.news.SELECTED,frames_sha256=f.sha(raw))
            (cap/'manifest.json').write_text(json.dumps(manifest));digest=f.sha(cap/'manifest.json')
            terminal=dict(status='capture_completed',plan_sha256=f.CAPTURE_PLAN_SHA,end_reason='duration_limit',manifest_sha256=digest)
            (cap/'terminal.json').write_text(json.dumps(terminal))
            supervisor=dict(state='finished',normal_endpoint=True,event_coverage_valid=True,plan_sha256=f.CAPTURE_PLAN_SHA,terminal=terminal)
            (out/'terminal.json').write_text(json.dumps(supervisor));p=dict(capture_root=str(cap.relative_to(root)))
            with patch.object(f,'ROOT',root),patch.object(f,'PLAN',analysis),patch.object(f.news,'OUT',out),patch.object(f.news,'PLAN',original),patch.object(f.ordinary,'_metadata',return_value=({'market_plan_sha256':f.CAPTURE_PLAN_SHA},{})):
                pins=f.input_snapshot(p);self.assertEqual(len(pins['files']),16)
                self.assertEqual(pins['capture_plan_sha256'],f.CAPTURE_PLAN_SHA)
                self.assertEqual(pins['analysis_plan_sha256'],f.sha(analysis))
                self.assertIn(str((md/'rh_markets.request.json').relative_to(root)),pins['files'])
                (cap/'extra').write_bytes(b'x')
                with self.assertRaisesRegex(AssertionError,'inventory'):f.input_snapshot(p)
                (cap/'extra').unlink();raw.write_bytes(b'changed')
                with self.assertRaises(AssertionError):f.input_snapshot(p)
                supervisor['normal_endpoint']=False
                with self.assertRaisesRegex(AssertionError,'incomplete'):f.require_terminal(supervisor)
                supervisor['normal_endpoint']=True;supervisor['plan_sha256']='analysis-hash'
                with self.assertRaises(AssertionError):f.require_terminal(supervisor)
                manifest['ended_utc']=stamp(f.news.EVENT+299)
                self.assertFalse(f.news.coverage(manifest))

    def test_corrected_adapter_bounds_and_both_independent_auditor_routes(self):
        p=self.plan()
        for family,study_class in (('relative',f.news.Study),('depth',f.news.DepthStudy)):
            study=f.configure(p,family)
            self.assertIs(study.Study,study_class);self.assertEqual(study.PLAN,f.PLAN)
            self.assertEqual(study.capture.PLAN,f.news.PLAN);self.assertEqual(study.capture.OUT,f.news.OUT/'capture')
            self.assertEqual(study.NAMES['BTC'],'single-venue-news-ordinary-fix-'+family+'-btc')
            self.assertIs(study.iter_events,f.events)
            self.assertEqual(f.ordinary.MAX_DECODED_BYTES,1073741824);self.assertEqual(f.ordinary.MAX_RECORDS,1000000)
            with patch.object(f,'verify',side_effect=lambda fam:f.configure(p,fam) and p),patch.object(f,'require_pins'),patch.object(cash,'audit') as audited:
                f.audit(family,'BTC','manifest')
                audited.assert_called_once_with(study.NAMES['BTC'],'manifest')
                self.assertEqual(cash.PLAN,f.PLAN);self.assertIs(cash.match_book,f.compact.match_compact)
                if family=='relative':self.assertIs(cash.inputs,study.multi_inputs)
                else:self.assertIsInstance(cash.verify_signal.__self__,depth_audit.SignalAudit)
        with patch.object(f,'read',side_effect=[p,dict(manifest_sha256='m',analysis_plan_sha256='a',raw_sha256='raw')]),patch.object(f,'sha',return_value='a'),patch.object(f.ordinary,'iter_events',return_value=iter(())) as adapted:
            list(f.events(Path('/synthetic'),expected_manifest_sha256='m',max_raw_bytes=50593792))
            self.assertEqual(adapted.call_args.kwargs,dict(expected_manifest_sha256='m',expected_raw_sha256='raw',max_raw_bytes=50593792,max_decoded_bytes=1073741824,max_records=1000000,max_ids=500000))

    def test_immutable_outputs_and_prepublication_caps(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/'evidence'
            with self.assertRaises(AssertionError):f.publish(target,b'12345',4)
            self.assertFalse(target.exists());f.publish(target,b'1234',4,directory_cap=5)
            with self.assertRaises(FileExistsError):f.publish(target,b'new',4)
            with self.assertRaisesRegex(AssertionError,'directory'):f.publish(root/'more',b'xx',4,directory_cap=5)
            self.assertFalse((root/'more').exists());self.assertEqual(target.read_bytes(),b'1234')
            packed=root/'packed.gz';packed.write_bytes(gzip.compress(b'x'*100))
            with self.assertRaisesRegex(AssertionError,'decoded'):report.packed_json(packed,100,20)

    def test_wait_command_deadlines_and_failure_preserve_no_retry_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=dict(control_root='control');(root/'control').mkdir()
            with patch.object(f.news,'OUT',root/'missing'):
                with self.assertRaises(TimeoutError):f.await_terminal(lambda:None,wall=lambda:f.TERMINAL_DEADLINE+1)
                with self.assertRaises(TimeoutError):f.await_terminal(lambda:None,wall=lambda:0,mono=iter([0,f.MAX_WAIT_SECONDS]).__next__)
            with patch.object(f,'ROOT',root),patch.object(f,'verify',return_value=p),patch.object(f,'sha',return_value='analysis'),patch.object(f,'await_terminal',return_value={}),patch.object(f,'input_snapshot',return_value={'manifest_sha256':'digest'}),patch.object(f,'command',side_effect=[None,RuntimeError('fixture')]) as cmd,patch.object(f,'make_readout') as readout:
                with self.assertRaises(SystemExit):f.supervise()
                self.assertEqual(cmd.call_count,2);readout.assert_not_called()
                terminal=json.loads((root/'control/analysis-terminal.json').read_bytes())
                self.assertFalse(terminal['success']);self.assertEqual(terminal['completed_commands'],1)
                self.assertEqual(terminal['error'],'RuntimeError: fixture')
            seq=list(f.commands('m'));self.assertEqual(len(seq),24)
            for offset,family in ((0,'relative'),(12,'depth')):
                self.assertEqual(seq[offset][1:],[ 'replay',family,'m'])
                self.assertEqual([x[3] for x in seq[offset+1:offset+11]],list(f.news.ASSETS))
                self.assertEqual(seq[offset+11],['scripts/single_venue_news_ordinary_fix_readout.py',family])
            with patch.object(f.subprocess,'Popen') as run:
                child=run.return_value;child.wait.return_value=0;child.poll.return_value=0
                f.command(['fixture'],110,mono=lambda:10);self.assertEqual(child.wait.call_args.kwargs['timeout'],30)
                self.assertEqual(run.call_args.args[0][:3],['nice','-n','19'])
                child.wait.side_effect=[f.subprocess.TimeoutExpired('fixture',30),0]
                heartbeats=[];f.command(['fixture'],1010,mono=lambda:10,heartbeat=lambda:heartbeats.append(1))
                self.assertEqual(heartbeats,[1])
                with self.assertRaises(TimeoutError):f.command(['fixture'],10,mono=lambda:10)
                self.assertEqual(run.call_count,2)
                child.wait.side_effect=None;child.poll.return_value=None
                with self.assertRaisesRegex(TimeoutError,'command_deadline'):f.command(['fixture'],1000,mono=iter([10,10,610]).__next__)
                child.kill.assert_called_once()

    def test_all_100_rows_and_20_vacuous_audits_are_required_for_readout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);research=root/'research';research.mkdir();cap=root/'capture';cap.mkdir()
            old=root/'original.json';old.write_text(json.dumps({'recorded_utc':'2026-01-01T00:00:00+00:00'}))
            analysis=root/'analysis.json';analysis.write_text('{}')
            (cap/'manifest.json').write_text(json.dumps({'started_utc':'2026-02-01T00:00:00+00:00'}))
            p=dict(output_stem='single-venue-news-ordinary-fix',assets=list(f.news.ASSETS),capture_root='capture')
            pins=dict(manifest_sha256='manifest',raw_sha256='raw')
            for family,rules in (('relative',('gap_fade','leader_follow','local_shock_fade')),('depth',('depth_fade','depth_follow'))):
                for asset in p['assets']:
                    name=p['output_stem']+'-'+family+'-'+asset.lower();out=research/name;out.mkdir()
                    (out/'trace.jsonl.gz').write_bytes(gzip.compress(b''))
                    arm=dict(episodes=[],cash='600',complete=True,unknown=None,position=None,pending=None,attempts=0,closed=0,counts={})
                    summary=dict(sample=name,asset=asset,source='capture',error=None,complete_capture_verified=True,
                        manifest_sha256='manifest',plan_sha256=f.sha(analysis),trace_sha256=f.sha(out/'trace.jsonl.gz'),feature_counts={},
                        arms={r+':'+v:arm for r in rules for v in ('rh_lighter','lighter')})
                    (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(summary).encode()))
                    audit=dict(status='passed',sample=name,raw_capture_verified=True,summary_sha256=f.sha(out/'summary.json.gz'),
                        trace_sha256=f.sha(out/'trace.jsonl.gz'),signal_checks_vacuous=True,fill_checks_vacuous=True)
                    (out/'independent-audit.json').write_text(json.dumps(audit))
            with patch.object(f,'ROOT',root),patch.object(f,'RESEARCH',research),patch.object(f,'PLAN',analysis),patch.object(f.news,'PLAN',old),patch.object(f,'verify',return_value=p),patch.object(f,'require_pins',return_value=pins):
                for family in ('relative','depth'):report.main(family)
                report.combined_readout(p)
                text=(research/(p['output_stem']+'-readout.txt')).read_text()
                self.assertIn('Total arms=100',text);self.assertIn('Vacuous signal audits=20; vacuous fill audits=20',text)
                with self.assertRaises(AssertionError):report.main('relative')
                auditfile=research/(p['output_stem']+'-depth-btc')/'independent-audit.json'
                auditfile.write_text('{}')
                with self.assertRaises(AssertionError):report.combined_readout(p)

if __name__=='__main__':unittest.main()
