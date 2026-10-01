import copy,gzip,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_broad_relative as broad
from scripts import single_venue_compact_evidence as compact
from scripts import audit_single_venue_study as cash
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

    def test_original_rules_and_native_assets_with_independent_audits(self):
        from scripts.single_venue_strategy import Study,Features,Portfolio,PARAMS
        broad.configure()
        self.assertIs(broad.study.Study,Study);self.assertIs(broad.study.PARAMS,PARAMS)
        metadata={v:{} for v in cash.VS};events=[]
        for asset in broad.ASSETS:
            for venue in cash.VS:
                metadata[venue][asset]=dict(META,asset=asset,market=broad.SELECTED[venue][asset],venue=venue)
            for j in range(1500):
                t=j/10
                for venue in cash.VS:
                    stamp=t if venue=='rh_lighter' else t+.001
                    px=100.2 if venue=='rh_lighter' and 130<=t<141 else 100
                    e=book(stamp,venue=venue,bid=px-.01,ask=px+.01)
                    e.update(asset=asset,market=broad.SELECTED[venue][asset]);events.append(e)
        events.sort(key=lambda e:e['received_ns']);events.append(dict(type='end',received_ns=150*10**9))
        traces={a:[] for a in broad.ASSETS}
        studies={a:Study(broad.study.market_alias(metadata,a),0,traces[a].append) for a in broad.ASSETS}
        with patch('scripts.single_venue_strategy.snapshot',compact.compact_snapshot):
            for e in events:
                for a,s in studies.items():s.process(broad.study.dispatch(e,a))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan=root/'plan.json';plan.write_text('{}')
            for asset,s in studies.items():
                self.assertGreaterEqual(sum(r['kind']=='closed' for r in traces[asset]),2)
                self.assertTrue(all(r['book']['market']==broad.SELECTED[r['book']['venue']][asset]
                    for r in traces[asset] if 'book' in r))
                out=root/'reports/single-venue-research'/asset;out.mkdir(parents=True)
                (out/'trace.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in traces[asset])+'\n').encode()))
                result=dict(error=None,complete_capture_verified=True,plan_sha256=cash.sha(plan),trace_sha256=cash.sha(out/'trace.jsonl.gz'),manifest_sha256='0'*64,**s.summary())
                (out/'summary.json.gz').write_bytes(gzip.compress(json.dumps(result).encode()))
                alias=broad.study.market_alias(metadata,asset)
                def inputs(*args):return root,'0'*64,alias,0,broad.study.asset_events(iter(events),asset)
                with patch.object(cash,'ROOT',root),patch.object(cash,'PLAN',plan),patch.object(cash,'inputs',inputs),patch.object(cash,'match_book',compact.match_compact):
                    cash.audit(asset)

if __name__=='__main__':unittest.main()
