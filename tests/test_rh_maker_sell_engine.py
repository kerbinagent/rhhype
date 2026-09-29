"""Synthetic execution checks for the separate RH-ask / HL-buy paper branch."""

import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config, NS, Rules
from scripts.rh_maker_sell_engine import MakerSellBranch, buy_limit_at_or_below


T = 100 * NS
META = {
    "rh": {"price_tick": "0.1", "qty_step": "0.01", "min_qty": "0.01",
           "min_notional": "10", "taker_fee_bps": "0"},
    "hl": {"price_tick_semantics": "hl_perp", "sz_decimals": 2,
           "qty_step": "0.01", "min_qty": "0.01", "min_notional": "10",
           "taker_fee_bps": "4.5"},
}
DIAG = {"policy": "fixed_best", "reason": "quote", "price": 101,
        "quantity": 1, "forecast_net_usd": -100}


def book(venue, at, *, bids=None, asks=None, source=None, generation="g"):
    if venue == "rh_lighter":
        bids = bids if bids is not None else [[100, 10], [99.9, 10]]
        asks = asks if asks is not None else [[101, 0.5], [101.1, 10]]
    else:
        bids = bids if bids is not None else [[100.1, 10], [100, 10]]
        asks = asks if asks is not None else [[100.2, 10], [100.3, 10]]
    return {"type": "book", "venue": venue, "asset": "BTC",
            "generation": generation, "received_ns": at,
            "source_ns": at if source is None else source,
            "clock_valid": True, "valid": True, "bids": bids, "asks": asks}


def trade(at, *, price=101, qty=1.5, source=None, side="buy", tid="a"):
    return {"type": "trade", "venue": "rh_lighter", "asset": "BTC",
            "generation": "g", "received_ns": at,
            "source_ns": at if source is None else source,
            "clock_valid": True, "side": side, "price": price,
            "qty": qty, "trade_id": tid}


def start(branch):
    branch.process(book("rh_lighter", T))
    branch.process(book("hyperliquid", T), DIAG)
    assert branch.quote is not None
    branch.process(book("rh_lighter", T + 400_000_000))
    assert branch.quote.activated_ns == T + 400_000_000


class MakerSellEngineTests(unittest.TestCase):
    def branch(self, **kwargs):
        return MakerSellBranch(Config("BTC", Decimal("1000"), "fixed_best", **kwargs), META)

    def test_full_short_long_roundtrip_has_correct_four_cash_legs(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        self.assertEqual(branch.rh_pos, Decimal("-1"))
        self.assertEqual(branch.cash_rh, Decimal("101"))
        branch.process(book("hyperliquid", T + 700_000_000))
        self.assertEqual(branch.hl_pos, Decimal("1"))
        self.assertEqual(branch.first_full_hedge_ns, T + 700_000_000)
        self.assertEqual(branch.cash_hl, Decimal("-100.24509"))
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(book("rh_lighter", T + 11_200_000_000,
                            asks=[[100.5, 10], [100.6, 10]]))
        branch.process(book("hyperliquid", T + 11_200_000_000,
                            bids=[[100.1, 10], [100, 10]]))
        result = branch.summary()
        gross = Decimal("101") - Decimal("100.2") - Decimal("100.5") + Decimal("100.1")
        fees = (Decimal("100.2") + Decimal("100.1")) * Decimal("4.5") / 10_000
        reserve = Decimal("101") * Decimal("5") / 10_000
        capital = ((Decimal("101") * Decimal("10.7")
                    + Decimal("100.2") * Decimal("10.5"))
                   * Decimal("0.05") / Decimal(365 * 86400))
        self.assertEqual(Decimal(result["rh_position"]), 0)
        self.assertEqual(Decimal(result["hl_position"]), 0)
        self.assertEqual(Decimal(result["cash_rh_usdg"]), Decimal("0.5"))
        self.assertEqual(Decimal(result["cash_hl_usdc"]), Decimal("-0.1") - fees)
        self.assertEqual(Decimal(result["fees_hl"]), fees)
        self.assertEqual(Decimal(result["reserve_cost"]), reserve)
        self.assertEqual(Decimal(result["capital_cost"]), capital)
        self.assertEqual(Decimal(result["complete_net"]), gross - fees - reserve - capital)
        self.assertEqual(result["direction"], "rh_maker_sell_hl_taker_buy")
        exit_request = next(row for row in result["audit"] if row["event"] == "exit_requested")
        self.assertEqual(exit_request["ns"], T + 10_700_000_000)

    def test_premium_rh_fees_use_actual_short_entry_and_buyback_notionals(self):
        branch = self.branch(tier="premium")
        branch.process(book("rh_lighter", T))
        branch.process(book("hyperliquid", T), DIAG)
        self.assertEqual(branch.quote.activation_due_ns, T + 100_000_000)
        branch.process(book("rh_lighter", T + 400_000_000))
        branch.process(trade(T + 500_000_000))
        branch.process(book("hyperliquid", T + 700_000_000))
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(book("rh_lighter", T + 11_200_000_000,
                            asks=[[100.5, 10], [100.6, 10]]))
        branch.process(book("hyperliquid", T + 11_200_000_000))
        result = branch.summary()
        expected_rh_fees = (Decimal("101") * Decimal("1.2")
                            + Decimal("100.5") * Decimal("3.5")) / 10_000
        expected_hl_fees = (Decimal("100.2") + Decimal("100.1")) * Decimal("4.5") / 10_000
        self.assertEqual(Decimal(result["fees_rh"]), expected_rh_fees)
        self.assertEqual(Decimal(result["fees_hl"]), expected_hl_fees)
        self.assertEqual(Decimal(result["cash_rh_usdg"]), Decimal("0.5") - expected_rh_fees)
        self.assertEqual(Decimal(result["cash_hl_usdc"]), Decimal("-0.1") - expected_hl_fees)
        self.assertIsNotNone(result["complete_net"])

    def test_unchanged_exit_books_make_completed_sell_path_lose_after_costs(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        branch.process(book("hyperliquid", T + 700_000_000))
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(book("rh_lighter", T + 11_200_000_000))
        branch.process(book("hyperliquid", T + 11_200_000_000))
        result = branch.summary()
        # The public ask has only 0.5 at 101, so the other 0.5 buys at 101.1.
        rh_buyback = Decimal("101.05")
        gross = Decimal("101") - Decimal("100.2") - rh_buyback + Decimal("100.1")
        self.assertEqual(gross, Decimal("-0.15"))
        self.assertEqual(Decimal(result["cash_rh_usdg"]), Decimal("101") - rh_buyback)
        self.assertEqual(Decimal(result["cash_hl_usdc"]),
                         Decimal("100.1") - Decimal("100.2") - Decimal(result["fees_hl"]))
        self.assertLess(Decimal(result["complete_net"]), gross)

    def test_through_flow_prices_maker_at_own_ask_and_hedges_increment_only(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000, price=101.2, qty=0.7))
        self.assertEqual(branch.rh_pos, Decimal("-0.2"))
        self.assertEqual(branch.cash_rh, Decimal("20.2"))
        self.assertEqual(branch.hedges[0].qty, Decimal("0.2"))
        self.assertTrue(branch.quote.through)
        self.assertEqual(branch.quote.cancel_due_ns, T + 800_000_000)
        branch.process(book("hyperliquid", T + 700_000_000))
        self.assertEqual(branch.hl_pos, Decimal("0.2"))

    def test_hl_buy_price_cap_rejects_and_retains_rh_short_obligation(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        branch.process(book("hyperliquid", T + 700_000_000,
                            asks=[[100.5, 10], [100.6, 10]]))
        self.assertEqual(branch.rh_pos, Decimal("-1"))
        self.assertEqual(branch.hl_pos, 0)
        self.assertEqual(branch.counts["hedge_result"], 1)
        self.assertIn("rh", branch.exits)
        self.assertIsNone(branch.summary()["complete_net"])

    def test_hl_buy_partial_hedge_preserves_both_inventories(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        branch.process(book("hyperliquid", T + 700_000_000,
                            asks=[[100.2, 0.2], [100.5, 10]]))
        self.assertEqual(branch.rh_pos, Decimal("-1"))
        self.assertEqual(branch.hl_pos, Decimal("0.2"))
        self.assertIn("rh", branch.exits)
        self.assertIn("hl", branch.exits)
        self.assertEqual(branch.counts["hedge_result"], 1)

    def test_first_eligible_postdue_book_and_strict_dynamic_buy_limit(self):
        rules = Rules.parse(META["hl"])
        upper = Decimal("100.3002")
        cap = buy_limit_at_or_below(rules, upper)
        self.assertLessEqual(cap, upper)
        self.assertTrue(rules.valid_price(cap))
        self.assertEqual(buy_limit_at_or_below(rules, Decimal("100.2346")), Decimal("100.23"))
        self.assertFalse(rules.valid_price(Decimal("100.234")))
        self.assertTrue(rules.valid_price(Decimal("123456")))  # HL integer exception.
        self.assertEqual(buy_limit_at_or_below(rules, Decimal("123456.7")), Decimal("123456"))
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        self.assertEqual(branch.hl_pos, 0)
        branch.process(book("hyperliquid", T + 600_000_000,
                            asks=[[100.2, 10], [100.3, 10]]))
        self.assertEqual(branch.hl_pos, 0)
        branch.process(book("hyperliquid", T + 700_000_000,
                            asks=[[100.2, 10], [100.3, 10]]))
        self.assertEqual(branch.hl_pos, 1)

    def test_late_buy_flow_before_cancel_effectiveness_adds_short_obligation(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000, qty=1, tid="first"))
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(trade(T + 950_000_000, source=T + 750_000_000,
                             qty=0.5, tid="late"))
        self.assertEqual(branch.rh_pos, Decimal("-1"))
        self.assertEqual(len(branch.hedges), 2)
        self.assertEqual(branch.counts["late_pending_cancel_flow"], 1)

    def test_later_partial_hedge_cannot_reset_first_pair_ten_second_clock(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000, qty=1, tid="first"))
        branch.process(book("hyperliquid", T + 700_000_000))
        first_full = branch.first_full_hedge_ns
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(trade(T + 950_000_000, source=T + 750_000_000,
                             qty=0.5, tid="late"))
        branch.process(book("hyperliquid", T + 1_200_000_000))
        self.assertEqual(branch.rh_pos, Decimal("-1"))
        self.assertEqual(branch.hl_pos, Decimal("1"))
        self.assertEqual(branch.first_full_hedge_ns, first_full)
        branch.tick(first_full + 10 * NS)
        self.assertEqual(branch.exit_requested_ns, first_full + 10 * NS)
        self.assertEqual(branch.exits["rh"].reason, "hold_deadline")

    def test_delayed_eligible_buyer_before_queue_snapshot_is_unknown(self):
        branch = self.branch()
        start(branch)  # First queue book source T+0.4 s, activation due T+0.3 s.
        branch.process(trade(T + 450_000_000, source=T + 350_000_000))
        self.assertEqual(branch.unknown_reason, "eligible_flow_before_queue_snapshot")
        self.assertEqual(branch.rh_pos, 0)

    def test_subminimum_increment_and_exit_remain_unknown_not_flat(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000, qty=0.55))
        self.assertEqual(branch.rh_pos, Decimal("-0.05"))
        branch.process(book("hyperliquid", T + 700_000_000))
        self.assertEqual(branch.hl_pos, 0)
        self.assertEqual(branch.counts["hedge_lot_or_min_reject"], 1)
        branch.process(book("rh_lighter", T + 1_200_000_000))
        self.assertEqual(branch.unknown_reason, "exit_order_lot_or_minimum_unknown")
        self.assertEqual(branch.rh_pos, Decimal("-0.05"))

    def test_fixed_best_ignores_model_net_but_reacts_to_ask_change(self):
        branch = self.branch()
        start(branch)
        self.assertEqual(branch.quote.price, Decimal("101"))
        branch.process(book("hyperliquid", T + 450_000_000), DIAG)
        self.assertIsNone(branch.quote.cancel_due_ns)
        branch.process(book("rh_lighter", T + 500_000_000,
                            asks=[[101.1, 10], [101.2, 10]]), DIAG)
        self.assertEqual(branch.quote.cancel_reason, "best_ask_changed")

    def test_sell_direction_early_all_cost_mark_and_funding_boundary(self):
        branch = self.branch()
        start(branch)
        branch.process(trade(T + 500_000_000))
        branch.process(book("hyperliquid", T + 700_000_000))
        branch.process(book("rh_lighter", T + 1_000_000_000,
                            asks=[[100.5, 10], [100.6, 10]]))
        self.assertEqual(branch.exit_requested_ns, T + 1_000_000_000)
        self.assertEqual(branch.exits["rh"].reason, "take_profit_mark")
        near_hour = self.branch()
        start(near_hour)
        near_hour.process(trade(T + 500_000_000))
        near_hour.tick(3600 * NS + 1)
        self.assertTrue(near_hour.funding_unknown)
        self.assertIsNone(near_hour.summary()["complete_net"])


if __name__ == "__main__":
    unittest.main()
