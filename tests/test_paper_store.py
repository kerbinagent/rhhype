"""Durable state and bounded inspection records for the paper monitor."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paper_store import PaperStore, PaperStoreError


def signal(route, score, ts):
    return {"route": route, "strategy": "standard", "timestamp": ts,
            "net_edge_usd": score, "asset": route}


class PaperStoreTests(unittest.TestCase):
    def test_atomic_restart_config_and_top_distinct_routes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "paper.sqlite3"
            now = time.time()
            store = PaperStore(path, {"model": 4}, max_events=3)
            state = {"positions": [{"id": "open-1"}], "ledger": {"closed_pnl": 27}}
            store.checkpoint(state, signals=[signal(str(i), i, now) for i in range(15)])
            store.record_signal(signal("14", 100, now))
            snap = store.snapshot(now)
            self.assertEqual(snap["retained_events"], 3)
            self.assertEqual(snap["retained"]["events"], 3)
            self.assertLessEqual(snap["storage_stats"]["db_bytes"] + snap["storage_stats"]["wal_bytes"],
                                 snap["storage_stats"]["max_db_bytes"])
            self.assertEqual(len(snap["top_signals"]), 10)
            self.assertEqual(snap["top_signals"][0]["net_edge_usd"], 100)
            self.assertEqual(len({s["route"] for s in snap["top_signals"]}), 10)
            store.close()
            store = PaperStore(path, {"model": 4}, max_events=3)
            self.assertEqual(store.load_state(), state)
            self.assertEqual(store.snapshot(now)["storage_stats"]["signals_seen"], 16)
            store.close()
            with self.assertRaisesRegex(ValueError, "config/model differs"):
                PaperStore(path, {"model": 5})

    def test_trade_pruning_does_not_change_cumulative_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            store = PaperStore(Path(d) / "paper.db", {}, max_trades=2, window_seconds=10)
            now = time.time()
            state = {"closed_pnl": 135, "positions": [{"id": "active"}]}
            store.checkpoint(state, trades=[
                {"id": "active", "status": "open", "timestamp": now},
                *({"id": str(i), "status": "closed", "timestamp": now,
                   "closed_at": now, "pnl": i} for i in range(5)),
            ])
            snap = store.snapshot(now)
            self.assertEqual(snap["state"]["closed_pnl"], 135)
            self.assertEqual(snap["retained_trades"], 2)  # open + one closed
            store.maintenance(now + 11)
            self.assertEqual(store.snapshot(now + 11)["retained_trades"], 1)
            self.assertEqual(store.load_state(), state)
            store.close()

    def test_evidence_budgets_and_retrieval(self):
        with tempfile.TemporaryDirectory() as d:
            store = PaperStore(Path(d) / "paper.db", {}, evidence_max_bytes=600,
                               max_evidence_rows=2, per_evidence_max_bytes=400)
            now = time.time()
            for i in range(5):
                store.record_evidence(str(i), {"i": i, "book": [i] * 100}, "trade", now + i)
            snap = store.snapshot(now + 4)
            self.assertLessEqual(snap["retained_evidence"], 2)
            self.assertLessEqual(snap["evidence_bytes"], 600)
            self.assertEqual(store.get_evidence("4")["i"], 4)
            self.assertIsNone(store.get_evidence("0"))
            store.close()

    def test_failed_checkpoint_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as d:
            store = PaperStore(Path(d) / "paper.db", {}, max_db_mb=1)
            store.save_state({"closed_pnl": 5})
            with self.assertRaises(ValueError):
                store.checkpoint({"closed_pnl": 99},
                                 trades=[{"id": "partial", "status": "closed", "closed_at": time.time()}],
                                 signals=[{"route": "bad"}])
            self.assertEqual(store.load_state()["closed_pnl"], 5)
            self.assertEqual(store.snapshot()["retained_trades"], 0)
            # A database page cap is configured, and a failed oversized state
            # leaves its previous ledger checkpoint available.
            cap = store.db.execute("PRAGMA max_page_count").fetchone()[0]
            self.assertLessEqual(cap, 192)
            with self.assertRaises(ValueError):
                store.save_state({"blob": "x" * (PaperStore.STATE_LIMIT + 1)})
            self.assertEqual(store.load_state()["closed_pnl"], 5)
            store.close()

    def test_rollback_on_sqlite_full(self):
        with tempfile.TemporaryDirectory() as d:
            store = PaperStore(Path(d) / "paper.db", {}, max_db_mb=1)
            store.save_state({"closed_pnl": 5})
            # Force the live DB to its current page count, leaving no growth.
            pages = store.db.execute("PRAGMA page_count").fetchone()[0]
            store.db.execute(f"PRAGMA max_page_count={pages}")
            payload = {"closed_pnl": 99, "large": [f"{i:08x}" for i in range(50_000)]}
            with self.assertRaises(PaperStoreError):
                store.save_state(payload)
            self.assertEqual(store.load_state()["closed_pnl"], 5)
            store.close()

    def test_pinned_reader_stops_wal_growth_before_next_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "paper.db"
            store = PaperStore(path, {})
            store.save_state({"n": 1})
            reader = sqlite3.connect(path)
            try:
                reader.execute("BEGIN")
                self.assertIsNotNone(reader.execute("SELECT payload FROM engine_state").fetchone())
                store.save_state({"n": 2})  # Durable; reader pins this WAL.
                with self.assertRaisesRegex(PaperStoreError, "pinned by a reader"):
                    store.save_state({"n": 3})
                self.assertEqual(store.load_state(), {"n": 2})
            finally:
                reader.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
