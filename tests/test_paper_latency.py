"""Regression checks for sampled opportunities, delayed-book probes, and restart."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from paper_engine import PaperEngine
from tests.test_paper_engine import book, engine, pair


class PaperLatencyTests(unittest.TestCase):
    def test_depth_loss_ends_episode_as_observed_unexecutable(self):
        e = engine()
        self.assertEqual(len(e.episodes), 1)
        e.receive(book("rh_lighter", 1, 1000.2, 102, 102.01, size=.0001))
        e.tick(1000.2)
        self.assertEqual(len(e.episodes), 0)
        episode = e.episode_history[-1]
        self.assertEqual(episode["end_reason"], "observed_unexecutable")
        self.assertFalse(episode["right_censored"])
        self.assertGreaterEqual(episode["lifetime_upper_seconds"],
                                episode["lifetime_lower_seconds"])

    def test_new_episode_does_not_overwrite_old_probe(self):
        e = engine()
        old = {pid for pid, p in e.probes.items() if p["delay_ms"] == 1000}
        self.assertEqual(len(old), 1)
        e.receive(book("rh_lighter", 1, 1000.2, 99.99, 100.01))
        e.tick(1000.2)
        e.receive(book("rh_lighter", 1, 1000.4, 102, 102.01))
        e.tick(1000.4)
        new = {pid for pid, p in e.probes.items() if p["delay_ms"] == 1000}
        self.assertEqual(len(new), 2)
        self.assertTrue(old.issubset(new))
        self.assertEqual(e.probe_stats["1000"]["triggered"], 2)

    def test_invalid_book_censors_pending_probe(self):
        e = engine()
        invalid = book("rh_lighter", 1, 1000.05, 102, 102.01)
        invalid.update(valid=False, bids=[], asks=[], reason="disconnected")
        e.receive(invalid)
        self.assertEqual(e.probe_stats["1000"]["missing"], 1)
        self.assertEqual(e.probe_stats["1000"]["missing_invalid_book"], 1)
        self.assertEqual(len(e.probes), 0)

    def test_restart_censors_active_episode_and_pending_probes(self):
        e = engine()
        state = e.export_state()
        self.assertEqual(len(state["active_episodes"]), 1)
        restored = PaperEngine([pair()], e.config, state=state, now=1001)
        self.assertEqual(len(restored.episodes), 0)
        self.assertEqual(restored.episode_history[-1]["end_reason"], "restart")
        self.assertTrue(restored.episode_history[-1]["right_censored"])
        self.assertEqual(restored.probe_stats["1000"]["missing_restart"], 1)
        self.assertEqual(restored.snapshot(1001)["latency_by_strategy"]["standard"]["1000"]["missing"], 1)

    def test_shutdown_censors_and_reports_sampled_span(self):
        e = engine()
        e.censor_all("shutdown", 1000.5)
        self.assertEqual(e.episode_history[-1]["end_reason"], "shutdown")
        self.assertTrue(e.episode_history[-1]["right_censored"])
        self.assertEqual(len(e.probes), 0)
        summary = e.snapshot(1000.5)["episode_summary"]
        self.assertEqual(summary["finished"], 1)
        self.assertEqual(summary["right_censored"], 1)
        self.assertEqual(sum(summary["observed_positive_span_brackets"].values()), 1)


if __name__ == "__main__":
    unittest.main()
