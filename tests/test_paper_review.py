"""Bounded, read-only paper review checkpoints."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paper_review import review, MAX_REPORTS


def ledger(exact=0, estimated=0, closed=0, estimated_count=0, wins=0,
           aborted=0, fees=0, funding=0, started_at=None):
    result = {"closed_pnl_exact": exact, "closed_pnl_estimated": estimated,
              "closed_trades": closed, "estimated_trades": estimated_count,
              "closed_wins_exact": wins, "closed_wins_estimated": 0,
              "aborted_trades": aborted, "fees_usd": fees, "funding_usd": funding}
    if started_at is not None:
        result["started_at"] = started_at
    return result


def trade(ident, strategy, settled_at, pnl, *, failed=False, estimated=False,
          reasons=None):
    reasons = reasons or {}
    return {"id": ident, "asset": "XAG", "pair_id": "XAG|HL|AS",
            "strategy": strategy, "status": "CLOSED_ESTIMATED" if estimated else "CLOSED",
            "created_at": settled_at-20, "opened_at": settled_at-19,
            "exit_requested_at": settled_at-5, "closed_at": settled_at-1,
            "settled_at": settled_at, "exit_reason": "entry_failure" if failed else "max_hold",
            "net_pnl_usd": pnl,
            "legs": [{"venue": venue, "entry_result": "filled", "quantity": 2,
                      **({"entry_rejection_reason": reasons[venue]}
                         if venue in reasons else {})}
                     for venue in ("hyperliquid", "aster")]}


def aborted_trade(ident, strategy, closed_at, venue, reason):
    return {"id": ident, "strategy": strategy, "status": "ABORTED",
            "created_at": closed_at-1, "closed_at": closed_at,
            "legs": [{"venue": venue, "entry_result": "rejected",
                      "entry_rejection_reason": reason}]}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "paper"
        self.source.mkdir()
        self.out = self.root / "reviews"
        self.db = sqlite3.connect(self.source / "paper.sqlite3")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE engine_state (id INTEGER PRIMARY KEY, payload TEXT, updated REAL);
            CREATE TABLE trades (id TEXT PRIMARY KEY, status TEXT, ts REAL,
                                 closed_at REAL, payload TEXT);
        """)

    def checkpoint(self, at, ledgers, trades=(), shadow_started_at=None):
        state = {"engine": {"ledgers": ledgers, "shadow_started_at": shadow_started_at}}
        self.db.execute("INSERT INTO engine_state VALUES(1,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
                        (json.dumps(state), at))
        for item in trades:
            self.db.execute("INSERT OR REPLACE INTO trades VALUES(?,?,?,?,?)",
                            (item["id"], item["status"], item.get("settled_at", item["closed_at"]),
                             item["closed_at"], json.dumps(item)))
        self.db.commit()
        (self.source / "paper_snapshot.json").write_text(json.dumps({
            "status": "running", "updated_at": at-1, "pair_count": 10,
            "cpu_percent_one_core": 41.5, "resident_memory_mb": 120.25,
            "peak_rss_mb": 125.0, "loop_lag_ms": 2.5, "loop_lag_p95_ms": 4.0,
            "book_events_per_second": 321.5,
            "feeds": {"aster": {"connected": True, "messages": 5}},
            "entry_policies": {"version": 3, "sampled_routes": 8, "warm_routes": 6,
                               "pending_confirmations": 2,
                               "convergence_skew_limit_seconds": 0.8,
                               "max_route_samples": 12,
                               "confirmation_cancel_reasons": {"invalid_quote": 4},
                               "policies": {"confirmed": {"checked": 9,
                                                           "rejected_confirmation": 3,
                                                           "pending_confirmations": 2}}}}))

    def test_first_review_then_delta_and_failed_hedge_not_paired(self):
        self.checkpoint(10000, {"standard": ledger(exact=10, closed=10, wins=6,
                                                   fees=4, funding=2)},
                        [trade("old", "standard", 9950, -2)])
        first = review(self.source, self.out, now=10010)
        standard = first["strategies"]["standard"]
        self.assertTrue(first["first_review"])
        self.assertIsNone(standard["ledger_delta"])
        self.assertEqual(first["window_start_at"], 8800)
        self.assertEqual(standard["retained_completed_count"], 1)
        self.assertEqual(standard["coverage"], "unverifiable_without_prior_ledger")
        self.assertTrue(first["snapshot_health"]["not_atomic_with_db"])
        self.assertEqual(first["snapshot_health"]["snapshot_updated_at"], 9999)
        health = first["snapshot_health"]
        self.assertEqual(health["cpu_percent_one_core"], 41.5)
        self.assertEqual(health["resident_memory_mb"], 120.25)
        self.assertEqual(health["loop_lag_p95_ms"], 4)
        self.assertEqual(health["book_events_per_second"], 321.5)
        self.assertEqual(health["entry_policies"]["pending_confirmations"], 2)
        self.assertEqual(health["entry_policies"]["convergence_skew_limit_seconds"], .8)
        self.assertEqual(health["entry_policies"]["max_route_samples"], 12)
        self.assertEqual(health["entry_policies"]["policies"]["confirmed"]
                         ["rejected_confirmation"], 3)
        self.assertEqual(health["entry_policies"]["confirmation_cancel_reasons"]
                         ["invalid_quote"], 4)

        self.checkpoint(11200, {"standard": ledger(exact=15, closed=11, wins=7,
                                                    aborted=1, fees=5, funding=2.5)},
                        [trade("failed", "standard", 11000, 5, failed=True,
                               reasons={"hyperliquid": "price_limit",
                                        "aster": "min_notional"}),
                         aborted_trade("aborted", "standard", 10950, "aster", "no_depth")])
        second = review(self.source, self.out, now=11230)
        standard = second["strategies"]["standard"]
        self.assertEqual(second["window_start_at"], 10000)
        self.assertEqual(second["next_due_at"], 12410)
        self.assertEqual(standard["ledger_delta"]["closed_net_usd"], 5)
        self.assertEqual(standard["ledger_delta"]["fees_usd"], 1)
        self.assertEqual(standard["ledger_delta"]["funding_usd"], .5)
        self.assertEqual(standard["retained_completion_window"]["classes"]["failed_hedge"],
                         {"count": 1, "wins": 1, "net_usd": 5})
        self.assertEqual(standard["retained_completion_window"]["classes"]["paired"]["count"], 0)
        self.assertEqual(standard["retained_completion_window"]["aborted_count"], 1)
        self.assertEqual(standard["retained_completion_window"]["entry_rejections_by_venue"],
                         {"aster": {"min_notional": 1, "no_depth": 1},
                          "hyperliquid": {"price_limit": 1}})
        self.assertEqual(standard["retained_completion_window"]["retained_aborted_count"], 1)
        self.assertEqual(standard["aborted_coverage"], "complete")
        self.assertEqual(second["entry_rejections_by_venue"],
                         {"aster": {"min_notional": 1, "no_depth": 1},
                          "hyperliquid": {"price_limit": 1}})
        self.assertEqual(standard["retained_completion_window"]["exit_request_to_flat_seconds"]["median"], 4)
        self.assertEqual(standard["coverage"], "complete")
        self.assertEqual(json.loads((self.out / "latest.json").read_text())["checkpoint_at"], 11200)

    def test_lost_retention_is_disclosed_and_new_policy_keeps_start(self):
        self.checkpoint(10000, {"standard": ledger(closed=1)})
        review(self.source, self.out, now=10010)
        self.checkpoint(11200, {"standard": ledger(exact=3, closed=3),
                                "convergence": ledger(exact=2, closed=1, wins=1,
                                                      started_at=10500)},
                        [trade("one", "standard", 11100, 1),
                         trade("new", "convergence", 11000, 2)],
                        shadow_started_at=10500)
        report = review(self.source, self.out, now=11220)
        standard = report["strategies"]["standard"]
        self.assertEqual(standard["expected_completed_count"], 2)
        self.assertEqual(standard["retained_completed_count"], 1)
        self.assertEqual(standard["coverage"], "missing_or_extra_retained_trades")
        new = report["strategies"]["convergence"]
        self.assertTrue(new["new_since_previous"])
        self.assertEqual(new["started_at"], 10500)
        self.assertEqual(new["ledger_delta"]["closed_net_usd"], 2)
        self.assertEqual(new["coverage"], "complete")
        self.assertEqual(json.loads((self.out / "review_state.json").read_text())
                         ["strategy_started_at"]["convergence"], 10500)

    def test_paired_entry_deterioration_sign_and_missing_inputs(self):
        def filled(ident, settled_at, long_value, short_value, second_entry):
            item = trade(ident, "standard", settled_at, 1)
            item["created_at"] = 9900
            item["signal"] = {"buy": "hyperliquid:BTC", "sell": "aster:BTCUSDT",
                              "quantity": 2, "buy_value": 200, "sell_value": 204}
            item["legs"] = [
                {"key": "hyperliquid:BTC", "side": "long", "entry_result": "filled",
                 "quantity": 2, "entry_value": long_value, "entry_time": 9904},
                {"key": "aster:BTCUSDT", "side": "short", "entry_result": "filled",
                 "quantity": 2, "entry_value": short_value, "entry_time": second_entry},
            ]
            return item

        worse = filled("worse", 9950, 202, 202, 9904)  # +2 long, +2 short
        better = filled("better", 9960, 198, 206, 9908)  # -2 long, -2 short
        absent = filled("absent", 9970, 202, 202, None)
        absent.pop("signal")
        wrong_key = filled("wrong-key", 9980, 202, 202, None)
        wrong_key["signal"]["buy"] = "hyperliquid:OTHER"
        wrong_quantity = filled("wrong-quantity", 9985, 202, 202, None)
        wrong_quantity["signal"]["quantity"] = 3
        unequal = filled("unequal", 9990, 202, 202, 9904)
        unequal["legs"][1]["quantity"] = 1
        partial = filled("partial", 9995, 202, 202, 9904)
        partial["legs"][1]["entry_result"] = "partial"
        self.checkpoint(10000, {"standard": ledger(closed=7)},
                        [worse, better, absent, wrong_key, wrong_quantity,
                         unequal, partial])
        report = review(self.source, self.out, now=10010)
        summary = report["strategies"]["standard"]["retained_completion_window"]
        self.assertEqual(summary["classes"]["paired"]["count"], 5)
        self.assertEqual(summary["classes"]["other"]["count"], 2)
        deterioration = summary["paired_signal_to_entry_deterioration_usd"]
        self.assertEqual(deterioration["observed"], 2)
        self.assertEqual(deterioration["missing"], 3)
        self.assertEqual(deterioration["sum"], 0)
        self.assertEqual(deterioration["median"], 0)
        self.assertEqual(deterioration["p95"], 4)
        self.assertTrue(deterioration["positive_is_worse"])
        entry_time = summary["paired_entry_time_seconds"]
        self.assertEqual(entry_time["observed"], 2)
        self.assertEqual(entry_time["missing"], 3)
        self.assertEqual(entry_time["median"], 6)
        self.assertEqual(entry_time["p95"], 8)

    def test_retention_only_deletes_matching_archives(self):
        self.out.mkdir()
        for n in range(MAX_REPORTS + 2):
            (self.out / f"review-20200101T000000.{n:06d}Z.json").write_text("{}")
        unrelated = self.out / "notes.json"
        unrelated.write_text("keep")
        self.checkpoint(10000, {"standard": ledger()})
        review(self.source, self.out, now=10010)
        archives = sorted(self.out.glob("review-*.json"))
        self.assertEqual(len(archives), MAX_REPORTS)
        self.assertFalse((self.out / "review-20200101T000000.000000Z.json").exists())
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertLessEqual((self.out / "latest.json").stat().st_size, 256 * 1024)
        self.assertLessEqual((self.out / "review_state.json").stat().st_size, 64 * 1024)


if __name__ == "__main__":
    unittest.main()
