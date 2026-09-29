"""Independent price/cost arithmetic and settled-window selection."""

import json
import gzip
from pathlib import Path
import sqlite3
import tempfile
import unittest

from unittest.mock import patch

from scripts import analyze_review_spreads as analyzer
from scripts.analyze_review_spreads import analyze, decompose, read_sample, read_window


CONFIG = {"margin_fraction": 0.1, "capital_rate": 0,
          "extra_cost_bps": 50}


def trade(*, settled=20, long_entry=100, short_entry=102,
          long_exit=99, short_exit=102, tid="one"):
    def leg(key, side, entry, exit_value):
        entry_fee = entry / 1000
        exit_fee = exit_value / 1000
        return {"key": key, "side": side, "entry_result": "filled",
                "quantity": 1, "entry_value": entry, "exit_value": exit_value,
                "entry_time": 1, "exit_time": 11,
                "entry_fee_bps": 10, "entry_fee": entry_fee,
                "exit_fee": exit_fee, "fees_usd": entry_fee + exit_fee,
                "price_pnl": (exit_value-entry) * (1 if side == "long" else -1),
                "exit_fills": [{"quantity": 1, "value": exit_value,
                                "fee_bps": 10, "fee": exit_fee}]}
    legs = [leg("L", "long", long_entry, long_exit),
            leg("S", "short", short_entry, short_exit)]
    gross = (short_entry-long_entry)-(short_exit-long_exit)
    fees = sum(item["fees_usd"] for item in legs)
    reserve = max(long_entry, short_entry) * 50 / 10000
    return {"id": tid, "asset": "XYZ", "strategy": "shadow_baseline",
            "status": "CLOSED", "created_at": 1, "closed_at": 11,
            "settled_at": settled, "legs": legs,
            "signal": {"buy": "L", "sell": "S", "quantity": 1,
                       "buy_value": 99, "sell_value": 102, "route": "XYZ|L|S"},
            "price_pnl": gross, "fees_usd": fees, "other_costs_usd": reserve,
            "capital_costs_usd": 0, "funding_usd": 0,
            "net_pnl_usd": gross-fees-reserve}


class SpreadAnalysisTests(unittest.TestCase):
    def test_positive_entry_spread_can_lose_before_any_cost(self):
        row = decompose(trade(), CONFIG)
        self.assertEqual(str(row["entry_spread"]), "2")
        self.assertEqual(str(row["exit_liability"]), "3")
        self.assertEqual(str(row["gross"]), "-1")
        self.assertEqual(str(row["entry_deterioration"]), "1")
        self.assertEqual(str(row["long_entry_fee"]), "0.1")
        self.assertEqual(str(row["short_entry_fee"]), "0.102")
        self.assertEqual(str(row["long_exit_fee"]), "0.099")
        self.assertEqual(str(row["short_exit_fee"]), "0.102")
        self.assertEqual(str(row["fees"]), "0.403")
        self.assertEqual(str(row["reserve"]), "0.51")
        self.assertEqual(str(row["net"]), "-1.913")

    def test_partial_exit_history_is_missing_coverage_not_zero(self):
        bad = trade()
        bad["legs"][0]["exit_fills"][0]["quantity"] = 0.5
        sample = {"trades": [bad], "config": CONFIG, "db_count": 1,
                  "expected_completed_count": 1, "review_coverage": "complete",
                  "strategy": "shadow_baseline", "review_sha256": "test",
                  "window_start_at": 10, "window_end_at": 20}
        report = analyze(sample)
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(report["validated"], 0)
        self.assertIn("incomplete", report["validation_errors"][0]["reason"])

    def test_settled_at_window_includes_earlier_close_and_strict_lower_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review_path, db_path = base / "review.json", base / "paper.sqlite3"
            review_path.write_text(json.dumps({
                "window_start_at": 10, "window_end_at": 20, "checkpoint_at": 20,
                "strategies": {"shadow_baseline": {
                    "expected_completed_count": 1, "coverage": "complete"}}}))
            db = sqlite3.connect(db_path)
            db.executescript("CREATE TABLE engine_state(id INTEGER PRIMARY KEY, updated REAL, payload TEXT);"
                             "CREATE TABLE trades(id TEXT, status TEXT, payload TEXT);")
            db.execute("INSERT INTO engine_state VALUES(1,?,?)",
                       (21, json.dumps({"engine": {"config": CONFIG}})))
            for settled in (10, 20, 21):
                row = trade(settled=settled, tid=str(settled))
                db.execute("INSERT INTO trades VALUES(?,?,?)",
                           (row["id"], row["status"], json.dumps(row)))
            db.commit()
            db.close()
            sample = read_window(db_path, review_path, "shadow_baseline")
            self.assertEqual([row["id"] for row in sample["trades"]], ["20"])
            self.assertTrue(analyze(sample)["coverage_complete"])

    def test_frozen_sample_rejects_excess_rows_and_decoded_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.json.gz"
            path.write_bytes(gzip.compress(json.dumps({"trades": [{}] * 5_001}).encode()))
            with self.assertRaisesRegex(ValueError, "5000 trades"):
                read_sample(path)
            path.write_bytes(gzip.compress(json.dumps({"trades": []}).encode()))
            with patch.object(analyzer, "MAX_DECODED_BYTES", 5):
                with self.assertRaisesRegex(ValueError, "decoded evidence"):
                    read_sample(path)

    def test_review_input_size_cap_precedes_database_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            review_path = Path(temporary) / "oversized.json"
            review_path.write_bytes(b" " * (analyzer.MAX_REVIEW_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "review exceeds"):
                read_window(Path(temporary) / "missing.sqlite3", review_path,
                            "shadow_baseline")


if __name__ == "__main__":
    unittest.main()
