import tempfile,json,shutil,unittest
from pathlib import Path
from scripts.single_venue_multi import dispatch,market_alias,asset_events
from scripts import single_venue_multi_capture as capture
from scripts.single_venue_strategy import Study
from tests.test_single_venue_strategy import book,META

class TestMulti(unittest.TestCase):
    def test_real_market_metadata_is_not_relabelled(self):
        source=Path('reports/single-venue-capture/metadata')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in capture.REQUESTS:
                for suffix in ('.json.gz','.request.json'):shutil.copyfile(source/(name+suffix),root/(name+suffix))
            (root/'market_plan.json').write_text(json.dumps({'selected':capture.SELECTED}))
            m=capture.verify_metadata(root,capture.SELECTED,capture.sha(root/'market_plan.json'))['markets']
            for v in m:
                self.assertEqual(set(m[v]),{'LIT','VVV','ZEC'})
                for a in m[v]:
                    self.assertEqual(m[v][a]['asset'],a)
                    self.assertEqual(m[v][a]['market'],capture.SELECTED[v][a])
                    self.assertEqual(market_alias(m,a)[v]['LIT']['asset'],a)

    def test_cross_asset_book_cannot_fill_order(self):
        s=Study({v:{'LIT':META} for v in ('lighter','rh_lighter')},0,lambda x:None)
        arm=s.arms['gap_fade','lighter'];arm.admit({'direction':1},book(130),130*10**9)
        other=book(130.5);other['asset']='ZEC';other['market']='90'
        s.process(dispatch(other,'VVV'))
        self.assertIsNone(arm.position);self.assertIsNotNone(arm.pending)
        other=book(133);other['asset']='ZEC';other['market']='90'
        s.process(dispatch(other,'VVV'))
        self.assertEqual(arm.unknown,'order_confirmation_timeout')

    def test_single_asset_event_identity_preserved(self):
        e=book(1);e['asset']='VVV';e['market']='69'
        self.assertIs(dispatch(e,'VVV'),e)
        self.assertEqual(dispatch(e,'LIT')['type'],'control')

    def test_audit_clock_coalescing_preserves_economics(self):
        metadata={v:{'LIT':META} for v in ('lighter','rh_lighter')}
        raw=[]
        for j in range(1500):
            t=j/10
            for v in ('rh_lighter','lighter'):
                stamp=t if v=='rh_lighter' else t+.001
                foreign=book(stamp,venue=v);foreign['asset']='ZEC';foreign['market']='90' if v=='lighter' else '4'
                raw.append(foreign)
                native=book(stamp,venue=v,bid=100.19 if v=='rh_lighter' and t>=130 else 99.99,
                            ask=100.21 if v=='rh_lighter' and t>=130 else 100.01)
                native['asset']='VVV';native['market']='69' if v=='lighter' else '8';raw.append(native)
        raw.append(dict(type='end',received_ns=150*10**9))
        def run(events):
            trace=[];s=Study(metadata,0,trace.append)
            for e in events:s.process(e)
            return s.summary(),trace
        self.assertEqual(run(dispatch(e,'VVV') for e in raw),run(asset_events(iter(raw),'VVV')))

if __name__=='__main__':unittest.main()
