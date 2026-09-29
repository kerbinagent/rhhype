"""Real Linux PTY resize and Ctrl-C tests; no network requests."""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monitor import tui_lines
ROOT = Path(__file__).resolve().parents[1]


def snapshot():
    return {'updated_timestamp': time.time(), 'status': 'running', 'pairs': 100, 'rank_by': 'usd',
            'totals': {'paper_1000_episodes': 12, 'paper_1000_net_entry_sum_usd': 20,
                       'paper_1000_budgeted_sum_usd': 10},
            'all_time_top10': [{'asset': f'ASSET{i}', 'buy': 'hyperliquid:BTC', 'sell': 'rh_lighter:1',
                               'target_notional_usd': 1000, 'budgeted_edge_usd': 10-i,
                               'budgeted_edge_bps': 100-i, 'utc': '2026-09-29T05:00:00+00:00'} for i in range(10)],
            'retained_observations': 1000, 'max_rows': 100000, 'process_stats': {}, 'failed_discovery_venues': []}


class TerminalTests(unittest.TestCase):
    def test_layout_fits_normal_narrow_short_and_tiny_terminals(self):
        for columns, rows in [(120, 30), (80, 24), (50, 20), (30, 12), (10, 4), (1, 1)]:
            lines = tui_lines(snapshot(), '/tmp/test', columns, rows)
            self.assertLessEqual(len(lines), max(1, rows - 1))
            self.assertTrue(all(len(line) <= max(1, columns - 1) for line in lines))
        lines = tui_lines(snapshot(), '/tmp/test', 80, 24)
        self.assertTrue(any('ASSET9' in line for line in lines))
        lines = tui_lines(snapshot(), '/tmp/test', 30, 12)
        self.assertTrue(any('Showing' in line for line in lines))

    def exercise_pty(self, mode, signum=signal.SIGINT):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / 'leaderboard.json').write_text(json.dumps(snapshot()))
            master, slave = os.openpty()
            def terminal_session():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            if mode == 'viewer':
                command = [sys.executable, str(ROOT / 'scripts/monitor.py'), '--watch', '--out', d]
            else:
                # Hold discovery pending, exercising cancellation of an in-flight async task.
                code = "import asyncio,sys;sys.path.insert(0,sys.argv.pop(1));import monitor\nasync def pending(*args):\n await asyncio.sleep(3600)\nmonitor.discover=pending\nmonitor.main()"
                command = [sys.executable, '-c', code, str(ROOT / 'scripts'), '--tui', '--out', d]
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, preexec_fn=terminal_session)
            os.close(slave)
            transcript = bytearray()
            def read_for(seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], min(.1, max(0, deadline-time.monotonic())))
                    if ready:
                        try:
                            transcript.extend(os.read(master, 65536))
                        except OSError:
                            break
            try:
                for columns, rows in [(120, 30), (35, 10), (80, 24)]:
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
                    os.kill(process.pid, signal.SIGWINCH)
                    read_for(.8)
                    self.assertIsNone(process.poll(), transcript.decode(errors='replace'))
                if signum == signal.SIGINT:
                    os.write(master, b'\x03')  # Actual terminal Ctrl-C, not process.terminate().
                else:
                    os.kill(process.pid, signum)
                read_for(1)
                self.assertEqual(process.wait(timeout=5), 0, transcript.decode(errors='replace'))
                self.assertIn(b'\x1b[?25h', transcript)
                self.assertIn(b'\x1b[?1049l', transcript)
                self.assertNotIn(b'Traceback', transcript)
                self.assertGreaterEqual(transcript.count(b'\x1b[H\x1b[2J'), 3)
                if mode == 'collector':
                    self.assertEqual(json.loads((out/'leaderboard.json').read_text())['status'], 'stopped')
                    # Graceful shutdown released the OS lock.
                    with (out/'monitor.lock').open() as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                os.close(master)

    def test_viewer_resize_and_terminal_ctrl_c(self):
        self.exercise_pty('viewer')

    def test_collector_resize_and_terminal_ctrl_c(self):
        self.exercise_pty('collector')

    def test_collector_sigterm_flushes_and_exits(self):
        self.exercise_pty('collector', signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
