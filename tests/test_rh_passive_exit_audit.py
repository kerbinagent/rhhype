"""Independent passive-exit accounting and adversarial lifecycle checks."""

import unittest
from decimal import Decimal

from tests.test_rh_passive_exit_engine import activate_exit, branch, matched_entry
from tests.test_rh_maker_engine import T, book, trade


class PassiveExitAuditTests(unittest.TestCase):
    def test_four_actual_notional_cash_legs_reconcile_independently(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=11, tid="exit"))
        b.process(book("hyperliquid", T + 3_500_000_000))
        b.process(book("rh_lighter", T + 3_700_000_000))
        b.tick(T + 5_700_000_000)
        summary = b.summary()
        fills = [row for row in summary["audit"] if row["event"] == "fill"]
        self.assertEqual([(r["venue"], r["side"], r["maker"]) for r in fills],
                         [("rh", "buy", True), ("hl", "sell", False),
                          ("rh", "sell", True), ("hl", "buy", False)])
        cash = Decimal(0)
        for row in fills:
            value = Decimal(row["value"])
            fee_bps = Decimal("4.5") if row["venue"] == "hl" else Decimal(0)
            cash += value if row["side"] == "sell" else -value
            cash -= value * fee_bps / 10_000
        self.assertEqual(cash, Decimal(summary["fee_only_complete_net"]))
        self.assertEqual(Decimal(summary["stressed_complete_net"]),
                         cash - Decimal(summary["reserve_cost"])
                         - Decimal(summary["capital_cost"]))

    def test_two_buybacks_share_one_first_eligible_hl_ask(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=10.5, tid="first"))
        b.process(trade(T + 3_320_000_000, source=T + 3_310_000_000,
                        side="buy", price=100.4, qty=.5, tid="second"))
        self.assertEqual(len(b.passive_buys), 2)
        self.assertEqual(b.rh_pos, 0)
        b.process(book("hyperliquid", T + 3_500_000_000,
                       asks=[[100.3, .5], [102, 10]]))
        self.assertEqual(b.counts["passive_hl_buy_result"], 2)
        self.assertEqual(b.hl_pos, Decimal("-0.5"))
        self.assertEqual(b.rh_pos, 0)
        self.assertEqual(b.fallback_reason, "partial_or_zero_passive_hl_buy")
        self.assertIsNone(b.summary()["complete_net"])

    def test_actual_retired_partial_ask_late_print_invalidates_closed_episode(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=10.5, tid="partial"))
        b.process(book("hyperliquid", T + 3_500_000_000))
        b.process(book("rh_lighter", T + 3_700_000_000))
        b.tick(T + 10_700_000_000)
        b.tick(T + 12_100_000_000)
        b.process(book("hyperliquid", T + 12_300_000_000))
        b.process(book("rh_lighter", T + 12_500_000_000))
        self.assertEqual(len(b.episodes), 1)
        self.assertFalse(b.episodes[0].get("execution_unknown", False))
        cash_before = (b.cash_rh, b.cash_hl)
        b.process(trade(T + 12_600_000_000, source=T + 3_400_000_000,
                        side="buy", price=100.4, qty=.01, tid="late_after_flat"))
        self.assertEqual(b.unknown_reason, "retired_passive_quote_late_flow")
        self.assertTrue(b.episodes[0]["execution_unknown"])
        self.assertEqual((b.cash_rh, b.cash_hl), cash_before)
        self.assertIsNone(b.summary()["complete_net"])


if __name__ == "__main__":
    unittest.main()
