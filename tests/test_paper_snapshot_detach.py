"""A checkpoint snapshot must stop changing before its worker-thread JSON write."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.test_paper_engine import book, engine


class SnapshotDetachmentTests(unittest.TestCase):
    def test_snapshot_stays_fixed_as_live_episode_and_wallet_advance(self):
        e = engine()
        captured = e.snapshot(1000)
        original = json.dumps(captured, sort_keys=True, allow_nan=False)
        self.assertEqual(captured["active_episodes"][0]["samples"], 1)

        e.receive(book("hyperliquid", "BTC", 1000.2, 99.99, 100))
        e.receive(book("rh_lighter", 1, 1000.2, 102, 102.01))
        e.tick(1000.2)
        self.assertEqual(next(iter(e.episodes.values()))["samples"], 2)
        self.assertLess(e.ledgers["standard"]["wallets"]["hyperliquid"], 10000)
        self.assertEqual(json.dumps(captured, sort_keys=True, allow_nan=False), original)

    def test_nested_export_fields_do_not_alias_engine_state(self):
        e = engine()
        position = next(iter(e.positions.values()))
        position["funding"] = {"complete": False, "missing": [{"reason": "pending"}]}
        e.episode_history.append({"first": 999, "last": 999.1,
                                  "right_censored": True, "details": {"counts": [1]}})
        captured = e.snapshot(1000)
        original = json.dumps(captured, sort_keys=True, allow_nan=False)

        position["funding"]["missing"][0]["reason"] = "changed"
        e.episode_history[-1]["details"]["counts"].append(2)
        next(iter(e.top_signals.values()))["net_edge_usd"] = -1
        self.assertEqual(json.dumps(captured, sort_keys=True, allow_nan=False), original)
        self.assertEqual(json.loads(original), captured)


if __name__ == "__main__":
    unittest.main()
