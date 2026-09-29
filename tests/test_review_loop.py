import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_loop import run_loop


class FakeClockStop:
    def __init__(self):
        self.now = 0
        self.stopped = False
        self.waits = []
    def is_set(self):return self.stopped
    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
    def clock(self):return self.now


class ReviewLoopTests(unittest.TestCase):
    def test_resumes_existing_due_time_and_keeps_twenty_minute_cadence(self):
        with tempfile.TemporaryDirectory() as out:
            Path(out, 'review_state.json').write_text(json.dumps({'next_due_at': 100}))
            timer = FakeClockStop(); seen = []
            def capture(source, target, *, now, interval_seconds):
                seen.append(now)
                if len(seen) == 3:timer.stopped = True
                return {'checkpoint_at': now, 'next_due_at': now + interval_seconds}
            run_loop('unused', out, 1200, timer, clock=timer.clock, review_fn=capture)
            self.assertEqual(seen, [100, 1300, 2500])
            self.assertLessEqual(max(timer.waits), 60)

    def test_failure_retries_without_advancing_baseline_deadline(self):
        with tempfile.TemporaryDirectory() as out:
            timer = FakeClockStop(); seen = []
            def capture(source, target, *, now, interval_seconds):
                seen.append(now)
                if len(seen) == 1:raise ValueError('stale checkpoint')
                timer.stopped = True
                return {'checkpoint_at': now, 'next_due_at': 1200}
            with self.assertLogs('paper_review_loop', logging.ERROR):
                run_loop('unused', out, 1200, timer, clock=timer.clock, review_fn=capture)
            self.assertEqual(seen, [0, 60])
