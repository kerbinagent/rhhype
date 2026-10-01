import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_executable_shock as batch

class BatchTests(unittest.TestCase):
    def test_configuration_keeps_functions_and_distinct_paths(self):
        original=(batch.study.capture.main,batch.study.replay,batch.ExecutableStudy)
        paths=[];names=[]
        for index in batch.WINDOWS:
            batch.configure(index)
            self.assertEqual(original,(batch.study.capture.main,batch.study.replay,batch.study.Study))
            self.assertEqual(batch.events.HARD_BYTES,batch.study.capture.HARD_BYTES)
            self.assertEqual(batch.study.capture.HARD_SECONDS,600)
            paths.append(batch.study.capture.OUT);names.append(batch.study.NAMES['LIT'])
        self.assertEqual(len(set(paths)),3);self.assertEqual(len(set(names)),3)
        with self.assertRaises(AssertionError):batch.configure(4)

    def test_no_retry_or_later_capture_after_failed_window(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            with patch.object(batch,'OUT',out),patch.object(batch,'verify'),patch.object(batch.study,'sha',return_value='p'),patch.object(batch.subprocess,'run') as run:
                run.return_value.returncode=1
                batch.supervise()
                self.assertEqual(run.call_count,1)
                terminal=json.loads((out/'terminal.json').read_bytes())
                self.assertFalse(terminal['all_windows_normal'])
                self.assertEqual(terminal['attempted_windows'],1)
                self.assertEqual(terminal['completed_windows'],0)

    def test_exactly_three_normal_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            def capture(command,**kwargs):
                index=int(command[-1]);target=out/f'window-{index}'/'capture'
                target.mkdir(parents=True)
                (target/'terminal.json').write_text(json.dumps({'end_reason':'duration_limit'}))
                self.assertEqual(kwargs['timeout'],720)
                return type('Run',(),{'returncode':0})()
            with patch.object(batch,'OUT',out),patch.object(batch,'verify'),patch.object(batch.study,'sha',return_value='p'),patch.object(batch.subprocess,'run',side_effect=capture) as run:
                batch.supervise()
                self.assertEqual(run.call_count,3)
                terminal=json.loads((out/'terminal.json').read_bytes())
                self.assertTrue(terminal['all_windows_normal'])
                self.assertEqual(terminal['completed_windows'],3)

if __name__=='__main__':unittest.main()
