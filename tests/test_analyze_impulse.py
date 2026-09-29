"""Stopped impulse quote analysis keeps cumulative and retained evidence distinct."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_impulse import MAX_INPUT_BYTES, analyze, markdown, read_snapshot, write_report
from paper_impulse import ImpulseObserver
from tests.test_paper_impulse import META, arm_and_confirm, book


PAIR = "BTC|hyperliquid:BTC|lighter:1"


def entry_fields(trigger, due, entry):
    return {"entry_time": entry, "entry_buy_value": 1000, "entry_sell_value": 1010,
            "entry_hl_source_time": due+.1, "entry_other_source_time": due+.2,
            "entry_hl_received": due+.25, "entry_other_received": entry,
            "entry_hl_source_delay_seconds": .1, "entry_other_source_delay_seconds": .2,
            "entry_hl_token": [1, "h2", due+.1, due+.25],
            "entry_other_token": [1, "o2", due+.2, entry]}


def complete(candidate, delay, *, trigger=1000, entry=1000.8, gross=8):
    due = trigger+.1+delay
    exit_due = entry+5.5
    exit_time = exit_due+.2
    return {"model_version": 1, "pair": PAIR, "candidate_id": candidate,
            "direction": "hl_buy", "trigger_time": trigger,
            "confirmation_time": trigger+.1, "quantity": 10,
            "delay_seconds": delay, "entry_due": due,
            "status": "complete", "censor_reason": None,
            "terminal_time": exit_time, **entry_fields(trigger, due, entry),
            "exit_time": exit_time, "exit_due": exit_due,
            "exit_hl_source_time": exit_due+.05,
            "exit_other_source_time": exit_due+.1,
            "exit_hl_received": exit_due+.15,
            "exit_other_received": exit_time,
            "exit_hl_source_delay_seconds": .05,
            "exit_other_source_delay_seconds": .1,
            "exit_long_value": gross+994, "exit_short_buyback_value": 1004,
            "gross_capture_usd": gross,
            "buy_entry_fee": 1, "sell_entry_fee": 1,
            "buy_exit_fee": 1, "sell_exit_fee": 1,
            "four_fees_usd": 4, "reserve_usd": .5,
            "capital_usd": .1, "net_after_reserve_usd": gross-4.6}


def censored(candidate, delay, reason, *, trigger=1300, with_entry=False):
    due = trigger+.1+delay
    row = {"model_version": 1, "pair": PAIR, "candidate_id": candidate,
           "direction": "other_buy", "trigger_time": trigger,
           "confirmation_time": trigger+.1, "quantity": 10,
           "delay_seconds": delay, "entry_due": due,
           "status": "censored", "censor_reason": reason,
           "terminal_time": trigger+9}
    if with_entry: row.update(entry_fields(trigger, due, due+.3))
    return row


def fixture():
    rows = [complete("c1", .5), complete("c1", 1.0, entry=1001.3, gross=6),
            censored("c2", .5, "entry_depth"),
            censored("c2", 1.0, "exit_missing", with_entry=True)]
    by_delay = {
        "0.5": {"candidates": 2, "paired_entry_quotes": 1,
                "scenario_complete": 1, "scenario_entry_depth": 1},
        "1.0": {"candidates": 2, "paired_entry_quotes": 2,
                "scenario_complete": 1, "scenario_exit_missing": 1}}
    per = {f"{PAIR}|hl_buy|0.5": {"candidates": 1, "paired_entry_quotes": 1,
                                  "scenario_complete": 1},
           f"{PAIR}|hl_buy|1": {"candidates": 1, "paired_entry_quotes": 1,
                                "scenario_complete": 1},
           f"{PAIR}|other_buy|0.5": {"candidates": 1, "scenario_entry_depth": 1},
           f"{PAIR}|other_buy|1": {"candidates": 1, "paired_entry_quotes": 1,
                                   "scenario_exit_missing": 1}}
    return {"status": "stopped", "updated_at": 1400,
            "model": {"model_version": 1, "finished": True,
                "metric": "paired impulse quote; no fills",
                "fee_assumption": "four frozen Standard taker fees",
                "rh_usdg_usdc_assumption": "parity quote screen only",
                "comparison_control": "same candidates at 0.5s and 1s only",
                "entry_delays_seconds": [.5, 1.0],
                "pending_arms": 0, "pending_scenarios": 0,
                "counts": {"armed": 2, "arm_terminal": 2,
                           "confirmed_candidates": 2, "paired_entry_quotes": 3,
                           "scenario_complete": 2, "scenario_entry_depth": 1,
                           "scenario_exit_missing": 1, "terminal_export_dropped": 0,
                           "positive_quote_outcomes": 2},
                "gates": {"history_warmup": 30, "impulse_small": 4},
                "censored": {"entry_depth": 1, "exit_missing": 1},
                "arm_outcomes": {"confirmed": 2},
                "by_pair": {PAIR: {"confirmed_candidates": 2,
                                  "paired_entry_quotes": 3}},
                "by_delay": by_delay, "by_pair_direction_delay": per,
                "mean_complete_net_after_reserve_usd": 2.4,
                "terminal_rows": rows}}


class ImpulseAnalysisTests(unittest.TestCase):
    def test_same_candidate_comparison_and_quote_distributions(self):
        result = analyze(fixture())
        self.assertEqual(result["validation_warnings"], [])
        self.assertEqual(result["all_run"]["candidate_scenario_accounting_residual"], 0)
        self.assertEqual(result["all_run"]["arm_accounting_residual"], 0)
        self.assertEqual(result["all_run"]["by_delay_counters"]["0.5"]["scenario_accounting_residual"], 0)
        self.assertEqual(result["retained_export"]["complete"], 2)
        self.assertEqual(result["retained_export"]["censored"], 2)
        paired = result["paired_same_candidate"]
        self.assertEqual((paired["both_scenarios_retained"], paired["both_scenarios_complete"]), (2, 1))
        self.assertEqual(paired["stress_minus_primary_net_after_reserve_usd"]["median"], -2)
        primary = result["retained_by_delay"]["0.5"]
        self.assertEqual(primary["quote_economics"]["distributions_usd"]["net_after_four_fees_usd"]["mean"], 4)
        self.assertEqual(primary["quote_economics"]["after_reserve_capital_positive_fraction"], 1)
        self.assertAlmostEqual(primary["timing_seconds"]["entry_hl_source_after_due"]["median"], .1)
        self.assertAlmostEqual(primary["timing_seconds"]["exit_other_receipt_after_due"]["median"], .2)
        self.assertEqual(result["retained_by_delay"]["1.0"]["with_paired_entry_quote"], 2)
        self.assertAlmostEqual(primary["timing_seconds"]["entry_collector_after_confirmation"]["median"], .7)
        self.assertEqual(len(result["retained_by_pair_direction"]), 2)
        self.assertEqual(len(result["retained_by_five_minute_trigger_block_utc"]), 2)
        self.assertEqual(len(result["retained_by_pair_direction_and_five_minute_block_utc"]), 2)
        self.assertIn("not fills or cash P&L", markdown(result))

    def test_missing_stays_censored_and_export_truncation_is_explicit(self):
        snapshot = fixture()
        snapshot["model"]["terminal_rows"] = snapshot["model"]["terminal_rows"][-2:]
        snapshot["model"]["counts"]["terminal_export_dropped"] = 2
        result = analyze(snapshot)
        self.assertEqual(result["all_run"]["counts"]["scenario_complete"], 2)
        self.assertEqual(result["retained_export"]["complete"], 0)
        self.assertEqual(result["retained_export"]["all_run_complete_not_retained"], 2)
        self.assertIsNone(result["retained_by_delay"]["0.5"]["quote_economics"]["distributions_usd"]["net_after_reserve_usd"]["mean"])
        self.assertEqual(result["retained_by_delay"]["0.5"]["censor_reasons"]["entry_depth"], 1)
        self.assertTrue(result["retained_export"]["export_truncated"])
        self.assertEqual(result["paired_same_candidate"]["both_scenarios_complete"], 0)

    def test_stopped_bounds_and_arithmetic_validation(self):
        snapshot = fixture()
        snapshot["status"] = "running"
        with self.assertRaisesRegex(ValueError, "stopped/finished"):
            analyze(snapshot)
        snapshot = fixture()
        snapshot["model"]["terminal_rows"] *= 1251
        with self.assertRaisesRegex(ValueError, "5000"):
            analyze(snapshot)
        snapshot = fixture()
        snapshot["model"]["terminal_rows"][0]["four_fees_usd"] = 5
        with self.assertRaisesRegex(ValueError, "four fees do not reconcile"):
            analyze(snapshot)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"oversized.json"
            with path.open("wb") as output:
                output.seek(MAX_INPUT_BYTES)
                output.write(b"x")
            with self.assertRaisesRegex(ValueError, "32 MiB"):
                read_snapshot(path)

    def test_duplicate_retained_scenario_and_report_output(self):
        snapshot = fixture()
        snapshot["model"]["terminal_rows"][1]["delay_seconds"] = .5
        snapshot["model"]["terminal_rows"][1]["entry_due"] = 1000.6
        with self.assertRaisesRegex(ValueError, "duplicate retained scenario"):
            analyze(snapshot)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"pilot.json"
            path.write_text(json.dumps(fixture()))
            result = analyze(read_snapshot(path))
            out = Path(root)/"report"
            write_report(result, out, "latest")
            self.assertEqual(json.loads((out/"latest.json").read_text())["all_run"]["counts"]["armed"], 2)
            self.assertIn("## Same-candidate paired comparison", (out/"latest.md").read_text())

    def test_generated_stopped_observer_snapshot_integrates(self):
        model = ImpulseObserver(extra_cost_bps=0)
        arm_and_confirm(model)
        for when, hl_mid, sequence, changed in (
                (1033.9, 100.5, 36, "other"),
                (1034.4, 100.5, 37, "hl"),
                (1039.5, 100, 38, "other"),
                (1040.0, 100, 39, "hl")):
            model.on_event(PAIR, when,
                           book("hyperliquid", "BTC", when, hl_mid, sequence),
                           book("lighter", 1, when, 100, sequence), changed, META)
        model.finish(1040)
        snapshot = {"status": "stopped", "updated_at": 1040,
                    "model": model.snapshot(1040)}
        result = analyze(json.loads(json.dumps(snapshot)))
        self.assertEqual(result["all_run"]["candidate_scenario_accounting_residual"], 0)
        self.assertEqual(result["paired_same_candidate"]["both_scenarios_complete"], 1)
        self.assertEqual(result["retained_export"]["complete"], 2)
        self.assertEqual(result["validation_warnings"], [])


if __name__ == "__main__": unittest.main()
