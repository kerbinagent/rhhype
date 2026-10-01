import copy,gzip,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_broad as broad
from scripts import single_venue_compact_evidence as compact
from scripts.audit_single_venue_executable import cash,ExecutableAudit,tracked
from tests.test_single_venue_executable import shock
from tests.test_single_venue_strategy import book,META

class BroadTests(unittest.TestCase):
    def test_archived_catalog_identity_for_all_twenty_markets(self):
        broad.configure()
        source=Path('reports/single-venue-depth-batch/window-3/capture/metadata')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in broad.study.capture.REQUESTS:
                for suffix in ('.json.gz','.request.json'):
                    shutil.copyfile(source/(name+suffix),root/(name+suffix))
            (root/'market_plan.json').write_text(json.dumps({'selected':broad.SELECTED}))
            metadata=broad.study.capture.verify_metadata(root,broad.SELECTED,broad.study.sha(root/'market_plan.json'))['markets']
            for venue,markets in metadata.items():
                self.assertEqual(set(markets),set(broad.ASSETS))
                for asset,m in markets.items():
                    self.assertEqual((m['asset'],m['market']),(asset,broad.SELECTED[venue][asset]))
                    self.assertIs(broad.study.market_alias(metadata,asset)[venue]['LIT'],m)
            self.assertEqual(len(broad.study.capture.subscriptions('lighter',broad.SELECTED['lighter'])),20)

    def test_adapter_passes_explicit_new_bounds(self):
        broad.configure()
        with patch.object(broad.events,'iter_events') as read:
            broad.study.iter_events('fixture',expected_manifest_sha256='x',max_raw_bytes=broad.HARD_BYTES)
            self.assertEqual(read.call_args.kwargs,dict(expected_manifest_sha256='x',max_raw_bytes=broad.HARD_BYTES,
                max_decoded_bytes=broad.DECODED_BYTES,max_records=broad.RECORDS,max_ids=broad.TRADE_IDS))

    def test_single_capture_no_retry_on_failure_or_timeout(self):
        for outcome in (type('Run',(),{'returncode':1})(),broad.subprocess.TimeoutExpired('capture',720)):
            with tempfile.TemporaryDirectory() as td:
                with patch.object(broad,'OUT',Path(td)),patch.object(broad,'verify'),patch.object(broad,'require_predecessor'),patch.object(broad.study,'sha',return_value='x'),patch.object(broad.subprocess,'run') as run:
                    if isinstance(outcome,Exception):run.side_effect=outcome
                    else:run.return_value=outcome
                    broad.supervise();self.assertEqual(run.call_count,1)
                    self.assertFalse(json.loads((Path(td)/'terminal.json').read_bytes())['normal_endpoint'])

    def test_no_launch_before_predecessor_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'terminal.json'
            with patch.object(broad,'PREDECESSOR',path):
                with self.assertRaises(FileNotFoundError):broad.require_predecessor()
                path.write_text('{"state":"collecting"}')
                with self.assertRaises(AssertionError):broad.require_predecessor()
                path.write_text('{"state":"finished"}');broad.require_predecessor()

    def test_all_assets_independent_fills_and_cash_audits(self):
        broad.configure();metadata={v:{} for v in cash.VS};events=[]
        for asset in broad.ASSETS:
            for venue in cash.VS:
                metadata[venue][asset]=dict(META,asset=asset,market=broad.SELECTED[venue][asset],venue=venue)
            native=shock()
            for j in range(101,250):
                t=j/10;px=100.1 if t<15 else 100.05
                native.extend((book(t,venue='rh_lighter'),book(t+.001,bid=px-.01,ask=px+.01)))
            for e in native:
                e['asset']=asset;e['market']=broad.SELECTED[e['venue']][asset]
            events.extend(native)
        events.sort(key=lambda e:e['received_ns']);events.append(dict(type='end',received_ns=30*10**9))
        traces={a:[] for a in broad.ASSETS}
        studies={a:broad.ExecutableStudy(broad.study.market_alias(metadata,a),0,traces[a].append) for a in broad.ASSETS}
        with patch('scripts.single_venue_strategy.snapshot',compact.compact_snapshot):
            for e in events:
                for a,s in studies.items():s.process(broad.study.dispatch(e,a))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan=root/'plan.json';plan.write_text('{}')
            for asset,s in studies.items():
                self.assertEqual(sum(r['kind']=='closed' for r in traces[asset]),3)
                self.assertTrue(all(r['book']['market']==broad.SELECTED[r['book']['venue']][asset]
                    for r in traces[asset] if 'book' in r))
                out=root/'reports/single-venue-research'/asset;out.mkdir(parents=True)
                (out/'trace.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in traces[asset])+'\n').encode()))
                result=dict(error=None,complete_capture_verified=True,plan_sha256=cash.sha(plan),trace_sha256=cash.sha(out/'trace.jsonl.gz'),manifest_sha256='0'*64,**s.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode()))
                alias=broad.study.market_alias(metadata,asset);tracker=ExecutableAudit(alias)
                def inputs(*args):return root,'0'*64,alias,0,tracked(broad.study.asset_events(iter(events),asset),tracker)
                with patch.object(cash,'ROOT',root),patch.object(cash,'PLAN',plan),patch.object(cash,'inputs',inputs),patch.object(cash,'verify_signal',tracker.verify),patch.object(cash,'match_book',compact.match_compact):
                    cash.audit(asset)

if __name__=='__main__':unittest.main()
