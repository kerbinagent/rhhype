"""First-quote and fixed-quantity guards for the exploratory size diagnostic."""

import unittest
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.analyze_maker_equity import fees_from_frozen, plan_markets
from scripts.analyze_size_sensitivity import (
    SECOND, analyze, cashflow, due_time, first_leg, fixed_qty, summarize,
)
from scripts.maker_capture import select_markets


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "reports/maker-equity-v2/market-plan.json"
FEES = ROOT / "reports/maker-equity-v2/fee-inputs.json"


def q(receipt, source, bid=100, ask=101, bid_size=20, ask_size=20, venue="hyperliquid"):
    return {"receipt_ns": receipt, "source_ns": source, "bid": bid, "ask": ask,
            "bid_size": bid_size, "ask_size": ask_size, "venue": venue, "asset": "NVDA"}


class SizeSensitivityTest(unittest.TestCase):
    def setUp(self):
        self.selected, _ = select_markets(PLAN, assets=("NVDA", "XAG"))
        self.meta = plan_markets(PLAN, self.selected)
        self.fees = fees_from_frozen(FEES)

    def test_fixed_common_lot_and_anchor_minimum(self):
        buy = self.meta["NVDA"]["hyperliquid"]
        sell = self.meta["NVDA"]["lighter"]
        self.assertEqual(fixed_qty("NVDA", 100, 250, buy, 249, sell), .4)
        self.assertIsNone(fixed_qty("NVDA", 100, 5000, buy, 4999, sell))
        self.assertEqual(fixed_qty("XAG", 250, 50, self.meta["XAG"]["hyperliquid"],
                                   49.9, self.meta["XAG"]["rh_lighter"]), 5.0)

    def test_delays_and_first_shallow_quote_no_retry(self):
        t = 20 * SECOND
        self.assertEqual(due_time(t, "hyperliquid"), t + 100_000_000)
        self.assertEqual(due_time(t, "lighter"), t + 400_000_000)
        s = [q(t + 10, t + 5, ask_size=1), q(t + 20, t + 15, ask_size=20)]
        quote, status = first_leg(s, [x["receipt_ns"] for x in s], t, t + 10 * SECOND,
                                  t + 20 * SECOND, "buy", 2, self.meta["NVDA"]["hyperliquid"])
        self.assertIs(quote, s[0])
        self.assertEqual(status, "shallow_first_quote")

    def test_source_due_and_capture_deadline(self):
        t = 20 * SECOND
        s = [q(t, t - 1), q(t + 50, t + 25)]
        got, status = first_leg(s, [x["receipt_ns"] for x in s], t, t + SECOND,
                                t + 2 * SECOND, "sell", 1, self.meta["NVDA"]["hyperliquid"])
        self.assertIs(got, s[1])
        self.assertEqual(status, "eligible")
        self.assertEqual(first_leg([], [], t, t + 200_000_000, t + 300_000_000,
                                   "buy", 1, self.meta["NVDA"]["hyperliquid"])[1],
                         "missing_first_quote")
        self.assertEqual(first_leg([], [], t, t + 2 * SECOND, t + 300_000_000,
                                   "buy", 1, self.meta["NVDA"]["hyperliquid"])[1],
                         "terminal_capture")

    def test_four_own_taker_fees_and_capital(self):
        t = 20 * SECOND
        be = q(t, t, bid=99, ask=100)
        se = q(t + SECOND, t + SECOND, bid=102, ask=103, venue="lighter")
        bx = q(t + 6 * SECOND, t + 6 * SECOND, bid=101, ask=102)
        sx = q(t + 7 * SECOND, t + 7 * SECOND, bid=100, ask=101, venue="lighter")
        x = cashflow(1, be, se, bx, sx, "hyperliquid", "lighter", self.fees["NVDA"])
        self.assertAlmostEqual(x["gross_usd"], 2)
        self.assertAlmostEqual(x["four_fee_usd"], (100 + 101) * .9 / 10000)
        self.assertAlmostEqual(x["reserve_usd"], 102 * 5 / 10000)
        self.assertGreater(x["capital_usd"], 0)

    def test_analyzer_preserves_one_leg_unresolved_and_intersection(self):
        base = int(datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc).timestamp() * SECOND)
        a = base + 5 * SECOND
        quotes = defaultdict(list)
        quotes[("hyperliquid", "NVDA")] = [
            q(a - 100_000_000, a - 200_000_000),
            q(a + 200_000_000, a + 150_000_000),
            q(a + 5_700_000_000, a + 5_650_000_000)]
        quotes[("lighter", "NVDA")] = [
            q(a - 100_000_000, a - 200_000_000, bid=102, ask=103, venue="lighter"),
            q(a + 500_000_000, a + 450_000_000, bid=102, ask=103,
              bid_size=1, ask_size=1, venue="lighter"),
            q(a + 6_000_000_000, a + 5_950_000_000, bid=101, ask=102,
              venue="lighter")]
        data = {"manifest": {"selected_markets": self.selected,
                             "started_utc": datetime.fromtimestamp(base / SECOND, timezone.utc).isoformat(),
                             "ended_utc": datetime.fromtimestamp((base + 20 * SECOND) / SECOND, timezone.utc).isoformat(),
                             "generations": [{"venue": v} for v in ("hyperliquid", "lighter", "rh_lighter")],
                             "invalidations": {}, "errors": []},
                "quotes": quotes, "trades": defaultdict(list), "counts": Counter(),
                "bad_trade_fields": Counter(), "unknown_trade_market": 0}
        cases = analyze(data, self.meta, self.fees)
        target = [x for x in cases if x["asset"] == "NVDA" and x["buy"] == "hyperliquid"
                  and x["sell"] == "lighter" and x["target_usd"] == 1000
                  and x["anchor_utc"] == datetime.fromtimestamp(a / SECOND, timezone.utc).isoformat()][0]
        self.assertEqual(target["status"], "one_entry_leg_unresolved")
        self.assertEqual(target["buy_entry_status"], "eligible")
        self.assertEqual(target["sell_entry_status"], "shallow_first_quote")
        self.assertEqual(summarize(cases)["matched_complete_anchor_count"], 0)


if __name__ == "__main__":
    unittest.main()
