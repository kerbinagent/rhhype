"""Offline fixed-quantity quote analysis uses full-run counters and retained rows separately."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_fixed_markout import (COHORTS, MAX_INPUT_BYTES, analyze, markdown,
                                   read_snapshot, write_report)


def scored(route, when, net, reserve_net, screens, *, status="matched"):
    flags = {f"{model}_gt_{threshold}": value > float(threshold)
             for model, value in screens.items() for threshold in ("0", "0.25")}
    row = {"status": status, "route": route, "anchor_time": when,
           "frozen_forecasts_bps": {model: 1 for model in screens},
           "prediction_screens_usd": screens, "screen_flags": flags}
    if status == "matched":
        row.update(gross_capture_usd=net+1, total_four_fees_usd=1,
                   net_after_four_fees_usd=net, net_after_reserves_usd=reserve_net,
                   buy_entry_fee_usd=.25, sell_entry_fee_usd=.25,
                   buy_exit_fee_usd=.25, sell_exit_fee_usd=.25)
    else:
        row["censor_reason"] = "future_exit_depth"
    return row


def fixture():
    btc = "BTC|hyperliquid:BTC|lighter:1"
    eth = "ETH|hyperliquid:ETH|lighter:2"
    rows = [
        scored(btc, 1000, 1, .5,
               {"conditional_linear": .5, "persistence": .2,
                "historical_median": -.1, "horizon_delta": .3}),
        scored(btc, 1001, -1, -1.5,
               {"conditional_linear": -.5, "persistence": .1,
                "historical_median": .4, "horizon_delta": .2}),
        scored(btc, 1002, 0, 0,
               {"conditional_linear": .7, "persistence": .1,
                "historical_median": -.2, "horizon_delta": .4},
               status="censored"),
        {"status": "matched", "route": eth, "anchor_time": 1300,
         "frozen_forecasts_bps": None, "prediction_screens_usd": None,
         "screen_flags": {}, "gross_capture_usd": 3,
         "total_four_fees_usd": 1, "net_after_four_fees_usd": 2,
         "net_after_reserves_usd": 1.5,
         "buy_entry_fee_usd": .25, "sell_entry_fee_usd": .25,
         "buy_exit_fee_usd": .25, "sell_exit_fee_usd": .25},
    ]
    cohorts = {}
    for cohort in COHORTS:
        selected = [row for row in rows if row["screen_flags"].get(cohort)]
        cohorts[cohort] = {"anchors": len(selected),
                           "matched": sum(row["status"] == "matched" for row in selected),
                           "censored": sum(row["status"] == "censored" for row in selected),
                           "pending": 0}
    return {"status": "stopped", "updated_at": 1400,
            "fixed_markout": {"model_version": 1, "finished": True,
                "pending_anchors": 0, "horizon_seconds": 12, "deadline_seconds": 16,
                "metric": "quoted fixed-quantity capture; no fills",
                "fee_assumption": "frozen Standard taker fees",
                "counts": {"paired_observations": 9, "anchors": 4, "warmup_anchors": 1,
                           "v2_scored_anchors": 3, "matched_anchors": 3,
                           "matched_scored_anchors": 2, "censored_anchors": 1,
                           "censored_scored_anchors": 1, "terminal_export_dropped": 0},
                "censored": {"future_exit_depth": 1},
                "all_v2_scored_coverage": {"anchors": 3, "matched": 2,
                                           "censored": 1, "pending": 0},
                "selected_anchor_coverage": cohorts, "terminal_rows": rows}}


class FixedMarkoutAnalysisTests(unittest.TestCase):
    def test_retained_quote_distributions_and_common_anchor_errors(self):
        result = analyze(fixture())
        self.assertEqual(result["all_run"]["counts"]["anchors"], 4)
        self.assertEqual(result["all_run"]["counts"]["paired_observations"], 9)
        self.assertEqual(result["all_run"]["censor_reasons"]["future_exit_depth"], 1)
        self.assertEqual(result["retained_export"]["matched"], 3)
        self.assertEqual(result["retained_export"]["censored"], 1)
        self.assertFalse(result["retained_export"]["export_truncated"])
        scored_summary = result["retained_quote_summaries"]["v2_scored_matched"]
        self.assertEqual(scored_summary["net_after_four_fees_usd"]["mean"], 0)
        self.assertAlmostEqual(scored_summary["net_after_four_fees_usd"]["p10"], -.8)
        self.assertEqual(scored_summary["net_after_four_fees_usd"]["median"], 0)
        self.assertAlmostEqual(scored_summary["net_after_four_fees_usd"]["p90"], .8)
        self.assertEqual(scored_summary["four_fee_positive_fraction"], .5)
        self.assertEqual(scored_summary["four_fee_components_usd"]["buy_entry_fee_usd"]["mean"], .25)
        selected = result["retained_quote_summaries"]["selected_matched"]["conditional_linear_gt_0.25"]
        self.assertEqual(selected["matched_rows"], 1)
        self.assertEqual(selected["net_after_four_fees_usd"]["mean"], 1)
        full_selected = result["all_run"]["selected_cohort_coverage"]["conditional_linear_gt_0.25"]
        self.assertEqual((full_selected["anchors"], full_selected["matched"], full_selected["censored"]),
                         (2, 1, 1))
        paired = result["paired_four_model_dollar_forecast_errors"]
        self.assertEqual(paired["common_scored_matched_anchor_count"], 2)
        self.assertEqual({row["paired_anchor_count"] for row in paired["models"].values()}, {2})
        self.assertEqual(paired["models"]["conditional_linear"]["error_actual_minus_forecast_usd"]["mean"], 0)
        self.assertEqual(paired["models"]["conditional_linear"]["rmse_usd"], .5)
        self.assertEqual(set(result["by_asset"]), {"BTC", "ETH"})
        self.assertEqual(set(result["by_five_minute_anchor_block_utc"]),
                         {"1970-01-01T00:15:00+00:00", "1970-01-01T00:20:00+00:00"})
        self.assertEqual(result["by_asset"]["BTC"]["matched"]["matched_rows"], 2)
        self.assertIn("not orders, fills, realized P&L", markdown(result))
        self.assertEqual(result["validation_warnings"], [])

    def test_export_truncation_does_not_replace_all_run_counts(self):
        snap = fixture()
        snap["fixed_markout"]["terminal_rows"] = snap["fixed_markout"]["terminal_rows"][-2:]
        snap["fixed_markout"]["counts"]["terminal_export_dropped"] = 2
        result = analyze(snap)
        self.assertEqual(result["all_run"]["counts"]["matched_anchors"], 3)
        self.assertEqual(result["retained_export"]["matched"], 1)
        self.assertEqual(result["retained_export"]["missing_matched_from_export"], 2)
        self.assertTrue(result["retained_export"]["export_truncated"])
        self.assertEqual(result["retained_quote_summaries"]["matched"]["matched_rows"], 1)

    def test_censored_only_route_remains_in_retained_breakdown(self):
        snap = fixture()
        snap["fixed_markout"]["terminal_rows"][2]["route"] = "SOL|hyperliquid:SOL|lighter:3"
        result = analyze(snap)
        sol = result["by_asset"]["SOL"]
        self.assertEqual(sol["retained_terminal_counts"]["matched"], 0)
        self.assertEqual(sol["retained_terminal_counts"]["censored"], 1)
        self.assertEqual(sol["matched"]["matched_rows"], 0)
        self.assertIsNone(sol["matched"]["net_after_four_fees_usd"]["mean"])
        self.assertIn("| SOL | 0 | 1 |", markdown(result))

    def test_refuses_running_partial_oversized_and_invalid_rows(self):
        snap = fixture()
        snap["status"] = "running"
        with self.assertRaisesRegex(ValueError, "stopped/finished"):
            analyze(snap)
        snap["status"] = "stopped"
        snap["fixed_markout"]["finished"] = False
        with self.assertRaisesRegex(ValueError, "stopped/finished"):
            analyze(snap)
        snap = fixture()
        snap["fixed_markout"]["terminal_rows"] = [snap["fixed_markout"]["terminal_rows"][0]] * 5001
        with self.assertRaisesRegex(ValueError, "5000"):
            analyze(snap)
        snap = fixture()
        snap["fixed_markout"]["terminal_rows"][0]["prediction_screens_usd"].pop("persistence")
        with self.assertRaisesRegex(ValueError, "incomplete frozen dollar screens"):
            analyze(snap)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "oversized.json"
            with path.open("wb") as output:
                output.seek(MAX_INPUT_BYTES)
                output.write(b"x")
            with self.assertRaisesRegex(ValueError, "32 MiB"):
                read_snapshot(path)

    def test_written_json_and_markdown_are_strict_and_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "pilot.json"
            path.write_text(json.dumps(fixture()))
            result = analyze(read_snapshot(path))
            out = Path(root) / "report"
            write_report(result, out, "latest")
            body = json.loads((out / "latest.json").read_text())
            self.assertEqual(body["all_run"]["counts"]["anchors"], 4)
            self.assertIn("## Paired four-model forecast errors", (out / "latest.md").read_text())
            self.assertLess((out / "latest.json").stat().st_size, 200_000)


if __name__ == "__main__": unittest.main()
