import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_news_analysis as a

class AnalysisTest(unittest.TestCase):
    def test_only_terminal_normal_covered_capture_is_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);p=out/'terminal.json'
            with patch.object(a,'OUT',out):
                with self.assertRaises(TimeoutError):a.await_terminal(lambda:None,wall=lambda:a.TERMINAL_DEADLINE+1)
                for normal,covered in ((False,False),(True,False)):
                    p.write_text(json.dumps(dict(state='finished',normal_endpoint=normal,event_coverage_valid=covered,plan_sha256=a.CAPTURE_PLAN_SHA)))
                    with self.assertRaises(AssertionError):a.await_terminal(lambda:None)
                p.write_text(json.dumps(dict(state='finished',normal_endpoint=True,event_coverage_valid=True,plan_sha256=a.CAPTURE_PLAN_SHA)))
                self.assertTrue(a.await_terminal(lambda:None)['normal_endpoint'])
    def test_exact_command_order_and_no_retry_on_failure(self):
        seq=list(a.commands('digest'));self.assertEqual(len(seq),24)
        for offset,family in ((0,'relative'),(12,'depth')):
            self.assertEqual(seq[offset],['scripts/single_venue_news.py','replay',family,'digest'])
            self.assertEqual([args[3] for args in seq[offset+1:offset+11]],list(a.news.ASSETS))
            self.assertEqual(seq[offset+11],['scripts/single_venue_news_readout.py',family])
        with tempfile.TemporaryDirectory() as td:
            with patch.object(a,'OUT',Path(td)),patch.object(a,'verify'),patch.object(a,'sha',return_value='x'),patch.object(a,'await_terminal',return_value={}),patch.object(a,'pin_capture',return_value='digest'),patch.object(a,'command',side_effect=[None,RuntimeError('fixture')]) as cmd,patch.object(a,'make_readout') as report:
                a.supervise();self.assertEqual(cmd.call_count,2);report.assert_not_called()
                terminal=json.loads((Path(td)/'analysis-terminal.json').read_bytes())
                self.assertFalse(terminal['success']);self.assertEqual(terminal['completed_commands'],1)
    def test_incomplete_capture_never_starts_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(a,'OUT',Path(td)),patch.object(a,'verify'),patch.object(a,'sha',return_value='x'),patch.object(a,'await_terminal',side_effect=AssertionError('incomplete')),patch.object(a,'pin_capture') as pin,patch.object(a,'command') as cmd:
                a.supervise();pin.assert_not_called();cmd.assert_not_called()
                self.assertFalse(json.loads((Path(td)/'analysis-terminal.json').read_bytes())['economic_evaluation'])
    def test_per_command_and_total_time_bounds(self):
        ok=type('Run',(),dict(returncode=0,stderr=b''))()
        with patch.object(a.subprocess,'run',return_value=ok) as run:
            a.command(['fixture'],110,mono=lambda:10);self.assertEqual(run.call_args.kwargs['timeout'],100)
            a.command(['fixture'],1010,mono=lambda:10);self.assertEqual(run.call_args.kwargs['timeout'],600)
            with self.assertRaises(TimeoutError):a.command(['fixture'],10,mono=lambda:10)
            self.assertEqual(run.call_count,2)

if __name__=='__main__':unittest.main()
