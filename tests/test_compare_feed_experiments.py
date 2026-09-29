"""Comparison keeps cumulative ledgers apart from bounded retained rows."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_feed_experiments import compare, markdown, probe_row, read_run, write_report


PAIR = {"asset": "BTC", "category": "crypto",
        "hl": {"venue": "hyperliquid", "market": "BTC", "fee_bps": 4.5,
               "step": ".01", "min_qty": 0, "min_notional": 10},
        "other": {"venue": "lighter", "market": 1, "fee_bps": 0,
                  "step": ".01", "min_qty": 0, "min_notional": 10}}
PAIR_ID = "BTC|hyperliquid:BTC|lighter:1"


def trade(ident, closed_at, *, source=None, failed=False):
    observation = {"book_source": source} if source else None
    legs = [{"venue": "hyperliquid", "side": "long", "quantity": 10,
             "entry_time": closed_at - 10, "entry_value": 1000, "entry_fee": .45,
             "entry_observation": observation},
            {"venue": "lighter", "side": "short", "quantity": 10,
             "entry_time": closed_at - 9.9, "entry_value": 1010, "entry_fee": 0,
             "entry_observation": observation}]
    return {"id": ident, "strategy": "standard", "status": "CLOSED",
            "asset": "BTC", "pair_id": PAIR_ID, "created_at": closed_at - 10.5,
            "closed_at": closed_at, "settled_at": closed_at + .1,
            "exit_requested_at": closed_at - .5 if source else None,
            "exit_reason": "entry_failure" if failed else "holding_period",
            "net_pnl_usd": -2, "signal": {"route": PAIR_ID, "quantity": 10,
                                              "opening_edge_usd": 9.5}, "legs": legs}


def run(label, checkpoint, trades, closed_total):
    ledger = {"closed_trades": closed_total, "estimated_trades": 0,
              "closed_pnl_exact": -2 * closed_total, "closed_pnl_estimated": 0,
              "closed_wins_exact": 0, "closed_losses_exact": closed_total,
              "aborted_trades": 0, "entry_attempts": closed_total,
              "closed_profit_sum_exact": 0, "closed_loss_sum_exact": -2 * closed_total}
    return {"path": label, "config": {"model": 4}, "pairs": {PAIR_ID: PAIR},
            "snapshot": {"updated_at": checkpoint + .2, "status": "running",
                         "hl_quote_mode": "depth" if label == "depth" else "bbo_plus_depth",
                         "cpu_percent_one_core": 20, "loop_lag_p95_ms": 3,
                         "book_events_per_second": 300},
            "state": {"engine": {"ledgers": {"standard": ledger}, "shadow_started_at": 10}},
            "checkpoint_at": checkpoint, "sqlite_updated_at": checkpoint,
            "trades": trades, "retained_closed_at_checkpoint": len(trades),
            "query_truncated": False}


class FeedComparisonTests(unittest.TestCase):
    def test_probe_targets_and_instrumented_strategies_use_snapshot_time(self):
        depth, bbo = run("depth", 100, [], 0), run("bbo", 101, [], 0)
        depth["snapshot"].update({
            "updated_at": 105,
            "latency": {"100": {"triggered": 10, "observed": 7, "survived": 5,
                                "missing": 2, "actual_delay_ms_sum": 3500,
                                "actual_delay_ms_min": 200, "actual_delay_ms_max": 900},
                        "300": {"triggered": 1, "observed": 0, "missing": 0}},
            "latency_by_strategy": {
                "standard": {"100": {"triggered": 4, "observed": 3, "survived": 2,
                                      "missing": 1, "actual_delay_ms_sum": 1200}},
                "confirmed": {"100": {"triggered": 0}}}})
        bbo["snapshot"]["latency"] = {"100": {"triggered": 2, "observed": 2,
                                                 "survived": 1, "missing": 0,
                                                 "actual_delay_ms_sum": 800}}
        result = compare(depth, bbo, now=106)
        snap = result["snapshot_performance_separate_times"]["depth"]
        self.assertEqual(snap["snapshot_at"], 105)
        self.assertEqual(result["checkpoint_at"]["depth"], 100)
        probes = snap["latency_probes"]
        aggregate = probes["aggregate_fee_scenario_observations_correlated"]
        self.assertEqual(set(aggregate), {"100", "300"})
        self.assertEqual(aggregate["100"]["pending"], 1)
        self.assertEqual(aggregate["100"]["observed_coverage_fraction"], .7)
        self.assertEqual(aggregate["100"]["average_actual_delay_ms"], 500)
        self.assertEqual(aggregate["100"]["minimum_actual_delay_ms"], 200)
        self.assertEqual(aggregate["100"]["maximum_actual_delay_ms"], 900)
        self.assertEqual(set(probes["by_instrumented_strategy"]), {"standard"})
        self.assertNotIn("p95", json.dumps(probes))
        report = markdown(result)
        self.assertIn("## 100 ms latency probe", report)
        self.assertIn("| depth | 1970-01-01T00:01:45+00:00 | 10 | 7 | 5 | 2 | 1 | 70.0% | 500.0 | 200.0 / 900.0 |", report)
        self.assertIn("not that a completed trade profited", report)

    def test_probe_zero_denominator_and_invalid_counts(self):
        empty = probe_row({"triggered": 0, "observed": 0, "missing": 0})
        self.assertEqual(empty["pending"], 0)
        self.assertIsNone(empty["observed_coverage_fraction"])
        self.assertIsNone(empty["average_actual_delay_ms"])
        invalid = probe_row({"triggered": 2, "observed": 3, "missing": 0,
                             "survived": 1, "actual_delay_ms_sum": 900})
        self.assertIsNone(invalid["pending"])
        self.assertIsNone(invalid["observed_coverage_fraction"])
        self.assertIsNone(invalid["average_actual_delay_ms"])
        self.assertIn("resolved_exceeds_triggered", invalid["validation_errors"])
        self.assertIsNone(probe_row({"triggered": -1})["pending"])

    def test_common_cutoff_and_ledger_separation(self):
        depth = run("depth", 105, [trade("d1", 90), trade("d2", 103)], 2)
        bbo = run("bbo", 100, [trade("b1", 91, source="bbo")], 1)
        result = compare(depth, bbo, now=106, skew_limit=5)
        row = result["portfolios_independent_do_not_sum"]["standard"]
        self.assertEqual(result["common_retained_cutoff"], 100)
        self.assertEqual(row["depth"]["closed_total"], 2)
        self.assertEqual(row["bbo"]["closed_total"], 1)
        self.assertEqual(row["retained_diagnostics"]["depth"]["retained_closed_common_cutoff"], 1)
        self.assertEqual(row["retained_diagnostics"]["depth"]["coverage_fraction_own_checkpoint"], 1)
        self.assertEqual(row["retained_diagnostics"]["depth"]["common_cutoff_fraction_of_lifetime"], .5)
        self.assertIn("entry_observation_instrumentation_differs", result["comparability_flags"])
        self.assertEqual(result["comparison_status"], "interim")
        self.assertEqual(row["retained_diagnostics"]["bbo"]["hyperliquid_entry_book_source_counts"]["bbo"], 1)
        self.assertEqual(row["retained_diagnostics"]["depth"]["retained_categories"]["crypto"]["closed"], 1)
        self.assertIn("No automatic feed promotion", markdown(result))

    def test_detects_config_pair_and_time_mismatch(self):
        depth, bbo = run("depth", 120, [], 0), run("bbo", 100, [], 0)
        bbo["config"] = {"model": 5}
        bbo["pairs"] = {}
        result = compare(depth, bbo, now=121, skew_limit=5)
        self.assertIn("configs_differ", result["comparability_flags"])
        self.assertIn("pair_universe_or_economics_differ", result["comparability_flags"])
        self.assertIn("checkpoint_skew_exceeds_limit", result["comparability_flags"])

    def test_settlement_cutoff_and_early_exit_residual_are_explicit(self):
        late_settlement = trade("d1", 90)
        late_settlement["settled_at"] = 101
        depth = run("depth", 105, [late_settlement], 1)
        bbo = run("bbo", 100, [trade("b1", 91, source="bbo")], 1)
        bbo["snapshot"]["status"] = "stopped"
        depth["snapshot"]["status"] = "stopped"
        bbo["state"]["engine"]["positions"] = {"stuck": {
            "id": "stuck", "strategy": "standard", "status": "EXITING",
            "asset": "BTC", "created_at": 20, "exit_requested_at": 30,
            "legs": [{"remaining": .009999999999999, "step": ".01", "venue": "hyperliquid"},
                     {"remaining": 0, "step": ".01", "venue": "lighter"}]}}
        result = compare(depth, bbo, now=106)
        diag = result["portfolios_independent_do_not_sum"]["standard"]["retained_diagnostics"]["depth"]
        self.assertEqual(diag["retained_closed_common_cutoff"], 0)
        self.assertEqual(result["comparison_status"], "early_stop_due_quantity_bug")
        self.assertIn("early_stop_due_quantity_bug", result["comparability_flags"])
        self.assertEqual(result["portfolios_independent_do_not_sum"]["standard"]
                         ["outstanding_at_checkpoint"]["bbo"]["aged_one_lot_exit_residual_count"], 1)
        self.assertIn("Do not rank feeds", markdown(result))

    def test_short_sqlite_read_and_bounded_written_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "depth"
            path.mkdir()
            (path / "paper_config.json").write_text(json.dumps({"model": 4}))
            (path / "markets.json").write_text(json.dumps({"pairs": [PAIR]}))
            (path / "paper_snapshot.json").write_text(json.dumps({"updated_at": 100,
                                                                   "hl_quote_mode": "depth"}))
            db = sqlite3.connect(path / "paper.sqlite3")
            db.execute("CREATE TABLE engine_state(id INTEGER PRIMARY KEY,payload TEXT,updated REAL)")
            db.execute("CREATE TABLE trades(id TEXT,status TEXT,closed_at REAL,payload TEXT)")
            state = {"saved_at": 100, "engine": {"ledgers": {"standard": {}},
                                                 "shadow_started_at": 10}}
            db.execute("INSERT INTO engine_state VALUES(1,?,100)", (json.dumps(state),))
            for i in range(2):
                item = trade(str(i), 90 + i)
                db.execute("INSERT INTO trades VALUES(?,?,?,?)",
                           (item["id"], item["status"], item["closed_at"], json.dumps(item)))
            db.commit()
            db.close()
            observed = read_run(path, max_trades=1)
            self.assertEqual(observed["retained_closed_at_checkpoint"], 2)
            self.assertEqual(len(observed["trades"]), 1)
            self.assertTrue(observed["query_truncated"])
            result = compare(observed, run("bbo", 100, [], 0), now=101)
            out = Path(root) / "report"
            write_report(result, out, "latest")
            self.assertTrue((out / "latest.md").exists())
            self.assertTrue((out / "latest.json").exists())
            self.assertLess((out / "latest.json").stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
