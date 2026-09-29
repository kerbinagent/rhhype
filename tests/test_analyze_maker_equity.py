"""Focused checks for the unlaunched NVDA/XAG maker quote replay."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_maker_capture import trade_from_payload
from scripts.analyze_maker_equity import (
    SECOND, analyze, capture_truncates_window, cashflow, common_qty, eligible_leg, fees_from_frozen,
    first_activation_quote, first_delayed_exit, first_delayed_hedge,
    funding_boundary, hedge_due, plan_markets,
)
from scripts.maker_capture import select_markets


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "reports/maker-equity-v2/market-plan.json"
FEES = ROOT / "reports/maker-equity-v2/fee-inputs.json"


def quote(receipt, source, bid=100, ask=101, bid_size=20, ask_size=20):
    return {"receipt_ns": receipt, "source_ns": source, "bid": bid, "ask": ask,
            "bid_size": bid_size, "ask_size": ask_size}


class MakerEquityTest(unittest.TestCase):
    @staticmethod
    def tiny_data(*, receipt_skew=False, future_trade=False):
        from collections import Counter, defaultdict
        from datetime import datetime, timezone
        base = int(datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc).timestamp() * SECOND)
        anchor = base + 5 * SECOND
        selected, _ = select_markets(PLAN, assets=("NVDA", "XAG"))
        qs = defaultdict(list)
        source = anchor - 800_000_000
        qs[("hyperliquid", "NVDA")] = [quote(anchor - 100_000_000, source)
                                         | {"venue": "hyperliquid", "asset": "NVDA"}]
        qs[("lighter", "NVDA")] = [quote(anchor - (700_000_000 if receipt_skew else 100_000_000), source)
                                    | {"venue": "lighter", "asset": "NVDA"}]
        trades = defaultdict(list)
        if future_trade:
            trades[("hyperliquid", "NVDA")].append({"receipt_ns": anchor,
                "source_ns": anchor + 1, "price": 100, "qty": 1,
                "buy_aggressor": True, "id": "bad-clock"})
        manifest = {"selected_markets": selected,
                    "started_utc": datetime.fromtimestamp(base / SECOND, timezone.utc).isoformat(),
                    "ended_utc": datetime.fromtimestamp((base + 20 * SECOND) / SECOND, timezone.utc).isoformat(),
                    "generations": [{"venue": v} for v in ("hyperliquid", "lighter", "rh_lighter")],
                    "invalidations": {}, "errors": []}
        return {"manifest": manifest, "quotes": qs, "trades": trades,
                "counts": Counter(), "unknown_trade_market": 0, "bad_trade_fields": Counter()}

    def test_selected_hip3_ids_and_fees(self):
        selected, _ = select_markets(PLAN, assets=("NVDA", "XAG"))
        self.assertEqual(selected["hyperliquid"], {"NVDA": "xyz:NVDA", "XAG": "xyz:SILVER"})
        meta = plan_markets(PLAN, selected)
        self.assertEqual(meta["NVDA"]["lighter"]["market"], 110)
        self.assertEqual(meta["XAG"]["rh_lighter"]["market"], 41)
        self.assertEqual(fees_from_frozen(FEES)["NVDA"]["hyperliquid"],
                         {"maker": 0.3, "taker": 0.9})

    def test_default_capture_market_selection_stays_btc_eth(self):
        selected, _ = select_markets(ROOT / "data/paper-monitor/markets.json")
        self.assertEqual(set(selected["hyperliquid"]), {"BTC", "ETH"})

    def test_coin_mapping_rejects_wrong_trade(self):
        trade = {"type": "trade", "coin": "xyz:NVDA", "side": "B", "tid": 2,
                 "hash": "0xabc", "time": 1790000000000, "px": "100", "sz": "1"}
        receipt = 1790000000000 * 1_000_000
        self.assertIsNotNone(trade_from_payload("hyperliquid", "NVDA", trade, receipt,
                                                 expected_coin="xyz:NVDA"))
        self.assertIsNone(trade_from_payload("hyperliquid", "NVDA", trade, receipt,
                                              expected_coin="xyz:SILVER"))

    def test_common_lot_minimum_and_actual_leg(self):
        mk = {"step": "0.001", "min_qty": 0, "min_notional": 10}
        hk = {"step": "0.0001", "min_qty": .04, "min_notional": 10}
        self.assertEqual(common_qty("NVDA", mk, hk, 250), 4)
        self.assertTrue(eligible_leg(4, 250, hk))
        self.assertFalse(eligible_leg(4, 2, hk))
        self.assertFalse(eligible_leg(4, 250, hk | {"max_qty": 3}))

    def test_source_and_receipt_due_on_maker_activation(self):
        due = 10 * SECOND
        qs = [quote(due, due - 1), quote(due + 50_000_000, due + 30_000_000)]
        self.assertIs(first_activation_quote(qs, [q["receipt_ns"] for q in qs], due), qs[1])

    def test_hedge_first_eligible_shallow_censors_later_full(self):
        due = 10 * SECOND
        qs = [quote(due + 10, due + 5, bid_size=1), quote(due + 20, due + 15)]
        market = {"min_qty": 0, "min_notional": 10}
        got, status = first_delayed_hedge(qs, [q["receipt_ns"] for q in qs],
                                           due, due - SECOND, due + 10 * SECOND, "buy", 2, market)
        self.assertIsNone(got)
        self.assertEqual(status, "insufficient_hedge_top_depth")

    def test_hedge_processing_and_minimum(self):
        self.assertEqual(hedge_due(10 * SECOND, "hyperliquid"), 10 * SECOND + 100_000_000)
        self.assertEqual(hedge_due(10 * SECOND, "lighter"), 10 * SECOND + 400_000_000)
        due = 10 * SECOND
        qs = [quote(due + 10, due + 5)]
        got, status = first_delayed_hedge(qs, [due + 10], due, due, due + SECOND,
                                           "buy", 1, {"min_qty": 0, "min_notional": 101})
        self.assertIsNone(got)
        self.assertEqual(status, "hedge_minimum_or_maximum")

    def test_exit_first_pair_shallow_censors(self):
        hedge_at = 10 * SECOND
        maker_due = hedge_at + 5 * SECOND + 100_000_000
        hedge_due_ns = hedge_at + 5 * SECOND + 400_000_000
        maker = [quote(maker_due + 1, maker_due, bid_size=1),
                 quote(hedge_due_ns + 20, hedge_due_ns + 10)]
        hedge = [quote(hedge_due_ns + 1, hedge_due_ns)]
        market = {"min_qty": 0, "min_notional": 10}
        pair, status, _ = first_delayed_exit(maker, hedge, "hyperliquid", "lighter",
                                             hedge_at, hedge_at + 10 * SECOND,
                                             "buy", 2, market, market)
        self.assertIsNone(pair)
        self.assertEqual(status, "insufficient_exit_top_depth")

    def test_funding_hour_inclusive_and_cashflow(self):
        hour = 3600 * SECOND
        self.assertTrue(funding_boundary(hour, hour + SECOND))
        self.assertTrue(funding_boundary(hour - SECOND, hour))
        self.assertFalse(funding_boundary(hour + SECOND, hour + 2 * SECOND))
        fees = {"hyperliquid": {"maker": .3, "taker": .9},
                "lighter": {"maker": 0, "taker": 0}}
        entry_hedge = quote(0, 0, bid=101, ask=102)
        exit_maker = quote(0, 0, bid=100.5, ask=101)
        exit_hedge = quote(0, 0, bid=100.5, ask=101)
        x = cashflow("buy", 100, entry_hedge, exit_maker, exit_hedge,
                     1, "hyperliquid", "lighter", fees)
        self.assertAlmostEqual(x["gross_usd"], .5)
        self.assertAlmostEqual(x["four_fee_usd"], (100 * .3 + 100.5 * .9) / 10000)
        self.assertAlmostEqual(x["reserve_usd"], 101 * 5 / 10000)

    def test_terminal_capture_respects_earlier_hard_deadline(self):
        due = 10 * SECOND
        self.assertFalse(capture_truncates_window(due, due + 200_000_000,
                                                   due + 300_000_000))
        self.assertTrue(capture_truncates_window(due, due + 2 * SECOND,
                                                  due + 300_000_000))

    def test_fee_parser_rejects_coin_change(self):
        body = json.loads(FEES.read_text())
        body["markets"]["XAG"]["coin"] = "xyz:GOLD"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fee.json"
            p.write_text(json.dumps(body))
            with self.assertRaises(ValueError):
                fees_from_frozen(p)

    def test_decision_receipt_skew_has_distinct_gate(self):
        selected, _ = select_markets(PLAN, assets=("NVDA", "XAG"))
        cohorts, _ = analyze(self.tiny_data(receipt_skew=True), plan_markets(PLAN, selected),
                             fees_from_frozen(FEES))
        target = next(c for c in cohorts if c["asset"] == "NVDA" and
                      c["maker"] == "hyperliquid" and c["hedge"] == "lighter" and
                      c["side"] == "buy" and c["maker_delay_s"] == 1)
        self.assertEqual(target["all"]["decision_receipt_skew"], 1)

    def test_source_ahead_trade_invalidates_only_affected_maker_cohorts(self):
        selected, _ = select_markets(PLAN, assets=("NVDA", "XAG"))
        cohorts, _ = analyze(self.tiny_data(future_trade=True), plan_markets(PLAN, selected),
                             fees_from_frozen(FEES))
        affected = [c for c in cohorts if c["asset"] == "NVDA" and c["maker"] == "hyperliquid"]
        unaffected = [c for c in cohorts if c["asset"] == "NVDA" and c["maker"] == "lighter"]
        self.assertTrue(all(c["all"]["timing_unassessable_trade_clock"] == c["all"]["anchors"]
                            for c in affected))
        self.assertTrue(all(c["all"].get("timing_unassessable_trade_clock", 0) == 0
                            for c in unaffected))


if __name__ == "__main__":
    unittest.main()
