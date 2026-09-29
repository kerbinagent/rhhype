"""Layout and terminal lifecycle tests for the read-only paper viewer."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paper_ui import tui_lines, read_watch_snapshot

ROOT = Path(__file__).resolve().parents[1]


def snapshot():
    return {
        "updated_at": time.time(), "status": "running", "pair_count": 47,
        "strategies": {
            tier: {"closed_pnl_exact": 12.3, "closed_pnl_estimated": 1.2,
                   "open_liquidation_pnl": -2.3, "open_positions": 2,
                   "fees_usd": 3.4, "funding_usd": -0.2,
                   "other_costs_usd": 0.4, "capital_costs_usd": 0.1,
                   "closed_winning_sum_usd": 15.1,
                   "closed_losing_sum_usd": -2.8,
                   "incomplete_trades": 1, "pending_funding": 1}
            for tier in ("standard", "plus", "premium")},
        "top_signals": [
            {"asset": f"ASSET{i}", "buy": "hyperliquid:BTC",
             "sell": "rh_lighter:1", "strategy": "standard",
             "net_edge_usd": 10 - i, "net_edge_bps": 100 - i,
             "timestamp": time.time()}
            for i in range(10)],
        "positions": [{"asset": "BTC", "strategy": "standard",
                       "age_seconds": 30, "liquidation_pnl": -0.5}],
        "feeds": {"hyperliquid": {"status": "streaming"}},
        "latency": {"100": {"triggered": 5, "observed": 4,
                              "survived": 3, "missing": 1}},
        "storage": {"rows": 10, "max_rows": 100},
    }


class LayoutTests(unittest.TestCase):
    def test_full_screen_shows_ledger_and_all_ten_signals(self):
        lines = tui_lines(snapshot(), 80, 24)
        self.assertLessEqual(len(lines), 23)
        self.assertTrue(all(len(line) <= 79 for line in lines))
        joined = "\n".join(lines)
        self.assertIn("Closed exact", joined)
        self.assertIn("estimated / open liquidation", joined)
        self.assertIn("Other", joined)
        self.assertIn("Pen", joined)
        self.assertIn("ASSET9", joined)
        self.assertIn("NOT trade P&L", joined)
        self.assertIn("Pen funding", joined)
        self.assertIn("? unknown", joined)
        self.assertIn("100ms target: 3/4 positive, 1 missing", joined)
        self.assertIn("Closed win/loss sums USD", joined)
        self.assertIn("Std +15.1/-2.8", joined)

    def test_tiny_terminal_and_untrusted_metadata(self):
        data = snapshot()
        data["status"] = "\033[31m\n🚀"
        data["top_signals"][0]["asset"] = "\033[0mWIDE界\n"
        for columns, rows in ((120, 30), (80, 24), (50, 20),
                              (30, 12), (10, 4), (1, 1)):
            lines = tui_lines(data, columns, rows)
            self.assertLessEqual(len(lines), max(1, rows - 1))
            self.assertTrue(all(len(line) <= max(1, columns - 1) for line in lines))
            self.assertNotIn("\033", "\n".join(lines))
            self.assertTrue(all(ord(c) < 127 for line in lines for c in line))
        self.assertIn("Showing", "\n".join(tui_lines(data, 30, 12)))

    def test_missing_snapshot_explains_writer_lock_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paper_snapshot.json'
            missing=read_watch_snapshot(path)
            self.assertIn('Collector is not running', '\n'.join(tui_lines(missing,80,24)))
            self.assertFalse((path.parent/'paper.lock').exists())
            with (path.parent/'paper.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                waiting=read_watch_snapshot(path)
                self.assertIn('Collector is running', '\n'.join(tui_lines(waiting,80,24)))
            path.write_text(json.dumps(snapshot()))
            self.assertEqual(read_watch_snapshot(path)['status'],'running')

    def test_missing_and_bad_snapshot_fields(self):
        for data in (None, {}, {"strategies": [], "top_signals": "bad",
                               "feeds": [], "positions": {}, "updated_at": "bad"}):
            lines = tui_lines(data, 80, 24)
            self.assertTrue(lines)
            self.assertTrue(all(len(line) <= 79 for line in lines))


class PtyTests(unittest.TestCase):
    def test_resize_and_control_c_restore_terminal(self):
        for stop in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "paper_snapshot.json"
                path.write_text(json.dumps(snapshot()))
                master, slave = os.openpty()

                def terminal_session():
                    os.setsid()
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                process = subprocess.Popen(
                    [sys.executable, str(ROOT / "scripts/paper_ui.py"), str(path)],
                    stdin=slave, stdout=slave, stderr=slave,
                    preexec_fn=terminal_session)
                os.close(slave)
                transcript = bytearray()

                def read_for(seconds):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select([master], [], [],
                                                     min(0.1, max(0, deadline-time.monotonic())))
                        if ready:
                            try:
                                transcript.extend(os.read(master, 65536))
                            except OSError:
                                break

                try:
                    for columns, rows in ((120, 30), (35, 10), (80, 24)):
                        fcntl.ioctl(master, termios.TIOCSWINSZ,
                                    struct.pack("HHHH", rows, columns, 0, 0))
                        os.kill(process.pid, signal.SIGWINCH)
                        read_for(0.65)
                        self.assertIsNone(process.poll(), transcript.decode(errors="replace"))
                    if stop == signal.SIGINT:
                        os.write(master, b"\x03")
                    else:
                        os.kill(process.pid, stop)
                    read_for(0.7)
                    self.assertEqual(process.wait(timeout=5), 0,
                                     transcript.decode(errors="replace"))
                    self.assertGreaterEqual(transcript.count(b"\x1b[H\x1b[2J"), 3)
                    self.assertIn(b"\x1b[?25h", transcript)
                    self.assertIn(b"\x1b[?1049l", transcript)
                    self.assertNotIn(b"Traceback", transcript)
                    self.assertEqual(json.loads(path.read_text())["status"], "running")
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    os.close(master)

    def test_collector_runtime_pty_snapshot_and_clean_shutdown(self):
        """Run the real event loop with discovery stubbed, without any network I/O."""
        code = (
            "import sys; sys.path.insert(0,sys.argv.pop(1)); "
            "import paper_monitor as pm\n"
            "async def empty(*args, **kwargs): return ([], [])\n"
            "pm.legacy.discover = empty\n"
            "pm.main(sys.argv[1:])\n"
        )
        for mode in ("duration", "ctrl_c", "sigterm"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                master, slave = os.openpty()

                def terminal_session():
                    os.setsid()
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                command = [sys.executable, "-c", code, str(ROOT / "scripts"),
                           "--tui", "--out", directory, "--report-seconds", "0.5"]
                if mode == "duration":
                    command += ["--duration", "2.2"]
                process = subprocess.Popen(command, stdin=slave, stdout=slave,
                                           stderr=slave, preexec_fn=terminal_session)
                os.close(slave)
                transcript = bytearray()

                def read_for(seconds):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select([master], [], [],
                                                     min(0.1, max(0, deadline-time.monotonic())))
                        if ready:
                            try:
                                transcript.extend(os.read(master, 65536))
                            except OSError:
                                break

                try:
                    for columns, rows in ((120, 30), (35, 10), (80, 24)):
                        fcntl.ioctl(master, termios.TIOCSWINSZ,
                                    struct.pack("HHHH", rows, columns, 0, 0))
                        os.kill(process.pid, signal.SIGWINCH)
                        read_for(0.55)
                        self.assertIsNone(process.poll(), transcript.decode(errors="replace"))
                    if mode == "ctrl_c":
                        os.write(master, b"\x03")
                    elif mode == "sigterm":
                        os.kill(process.pid, signal.SIGTERM)
                    deadline = time.monotonic() + 5
                    while process.poll() is None and time.monotonic() < deadline:
                        read_for(0.1)
                    read_for(0.1)
                    self.assertEqual(process.wait(timeout=5), 0,
                                     transcript.decode(errors="replace"))
                    path = Path(directory) / "paper_snapshot.json"
                    report = json.loads(path.read_text())
                    self.assertEqual(report["status"], "stopped")
                    self.assertEqual(report["pair_count"], 0)
                    self.assertEqual(set(report["strategies"]),
                                     {"standard", "plus", "premium"})
                    self.assertGreaterEqual(transcript.count(b"\x1b[H\x1b[2J"), 3)
                    self.assertIn(b"\x1b[?25h", transcript)
                    self.assertIn(b"\x1b[?1049l", transcript)
                    self.assertNotIn(b"Traceback", transcript)
                    with (Path(directory) / "paper.lock").open() as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
