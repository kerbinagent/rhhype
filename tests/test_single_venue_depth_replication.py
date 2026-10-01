import json,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_depth_replication as r
from scripts.single_venue_depth_strategy import DepthStudy

class ReplicationTest(unittest.TestCase):
    def test_only_capture_selection_paths_and_bounds_change(self):
        capture=r.study.capture;original_main=capture.main;original_replay=r.study.replay
        changes=[(r.study,k) for k in ('PLAN','ASSETS','NAMES')]+[(capture,k) for k in ('PLAN','OUT','SELECTED','HARD_BYTES')]+[(r.events,'HARD_BYTES')]
        with ExitStack() as stack:
            for obj,key in changes:stack.enter_context(patch.object(obj,key,getattr(obj,key)))
            r.configure()
            self.assertIs(r.study.Study,DepthStudy)
            self.assertIs(capture.main,original_main);self.assertIs(r.study.replay,original_replay)
            self.assertEqual(r.study.ASSETS,('LIT',));self.assertEqual(capture.HARD_BYTES,r.events.HARD_BYTES)
            self.assertEqual(capture.OUT,r.ROOT/'reports/single-venue-depth-replication/capture')
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/'plan.json';p.write_text(json.dumps({'selected':r.SELECTED}))
                self.assertEqual(capture.select_three(p)[0],r.SELECTED)
            for venue,markets in r.SELECTED.items():
                self.assertEqual(capture.subscriptions(venue,markets),[
                    {'type':'subscribe','channel':'order_book/'+markets['LIT']},
                    {'type':'subscribe','channel':'trade/'+markets['LIT']}])

if __name__=='__main__':unittest.main()
