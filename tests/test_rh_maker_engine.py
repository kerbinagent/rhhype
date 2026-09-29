import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config, MakerBranch, Rules, NS


T = 100 * NS
META = {
    "rh": {"price_tick": "0.1", "qty_step": "0.01", "min_qty": "0.01",
           "min_notional": "10", "taker_fee_bps": "0"},
    "hl": {"price_tick_semantics": "hl_perp", "sz_decimals": 2,
           "qty_step": "0.01", "min_qty": "0.01", "min_notional": "10",
           "taker_fee_bps": "4.5"},
}
DIAG = {"policy": "fixed_best", "reason": "quote", "price": 100,
        "quantity": 1, "forecast_net_usd": None}


def book(venue, at, bids=None, asks=None, source=None):
    return {"type": "book", "venue": venue, "asset": "BTC", "generation": "g",
            "received_ns": at, "source_ns": at if source is None else source,
            "clock_valid": True, "valid": True,
            "bids": bids or ([[100, 0.5], [99.9, 10]] if venue == "rh_lighter" else [[100.2, 10], [100.1, 10]]),
            "asks": asks or ([[100.4, 10], [100.5, 10]] if venue == "rh_lighter" else [[100.3, 10], [100.4, 10]])}


def trade(at, source=None, price=100, qty=1.5, tid="x", side="sell"):
    return {"type": "trade", "venue": "rh_lighter", "asset": "BTC", "generation": "g",
            "received_ns": at, "source_ns": at if source is None else source,
            "clock_valid": True, "price": price, "qty": qty, "trade_id": tid, "side": side}


def start(branch):
    branch.process(book("rh_lighter", T))
    branch.process(book("hyperliquid", T), DIAG)
    assert branch.quote is not None
    branch.process(book("rh_lighter", T + 400_000_000))


class MakerEngineTests(unittest.TestCase):
    def branch(self, **kwargs):
        return MakerBranch(Config("BTC", Decimal("1000"), "fixed_best", **kwargs), META)

    def test_adapter_names_queue_flow_and_complete_exit(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        self.assertEqual(b.rh_pos, Decimal("1"))
        self.assertEqual(b.quote.ahead_same, Decimal("0"))
        self.assertEqual(b.counts["maker_increment"], 1)
        b.process(book("hyperliquid", T + 700_000_000))
        self.assertEqual(b.hl_pos, Decimal("-1"))
        self.assertEqual(b.capital_base, Decimal("200.2"))
        self.assertEqual(b.first_full_hedge_ns, T + 700_000_000)
        b.process(book("rh_lighter", T + 900_000_000))
        b.process(book("rh_lighter", T + 11_200_000_000))
        b.process(book("hyperliquid", T + 11_200_000_000))
        s = b.summary()
        self.assertEqual(Decimal(s["rh_position"]), 0)
        self.assertEqual(Decimal(s["hl_position"]), 0)
        self.assertIsNotNone(s["complete_net"])
        self.assertEqual(s["episodes"][0]["full_flow"], True)
        self.assertEqual(s["fees_hl"], "0.090225")
        self.assertEqual(Decimal(s["reserve_cost"]), Decimal("0.05010"))
        exits = [row for row in s["audit"] if row["event"] == "exit_requested"]
        self.assertEqual(exits[0]["ns"], T + 10_700_000_000)
        self.assertEqual(Decimal(s["cash_rh_usdg"]) + Decimal(s["cash_hl_usdc"]),
                         Decimal(s["cash_known"]))

    def test_no_future_book_and_first_postdue_hedge_partial(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        self.assertEqual(b.hl_pos, Decimal("0"))  # Old 100.2 book is not a postdue fill.
        b.process(book("hyperliquid", T + 700_000_000,
                       bids=[[100.2, 0.2], [99, 10]]))
        self.assertEqual(b.hl_pos, Decimal("-0.2"))
        self.assertEqual(b.counts["hedge_result"], 1)
        self.assertEqual(b.counts["exit_requested"], 1)
        self.assertEqual(b.exits["rh"].reason, "partial_or_zero_hedge")

    def test_zero_hedge_price_cap_keeps_rh_obligation(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        b.process(book("hyperliquid", T + 700_000_000,
                       bids=[[99, 10], [98.9, 10]]))
        self.assertEqual(b.hl_pos, Decimal("0"))
        self.assertEqual(b.rh_pos, Decimal("1"))
        self.assertIn("rh", b.exits)
        self.assertEqual(b.counts["hedge_result"], 1)

    def test_valid_hl_ioc_can_partially_fill_below_order_minimum(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        b.process(book("hyperliquid", T + 700_000_000,
                       bids=[[100.2, 0.05], [99, 10]]))
        self.assertEqual(b.hl_pos, Decimal("-0.05"))
        self.assertEqual(b.rh_pos, Decimal("1"))
        self.assertIsNone(b.unknown_reason)
        self.assertIn("rh", b.exits)

    def test_tiny_maker_partial_cannot_submit_subminimum_hl_hedge(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000, qty=0.55))
        self.assertEqual(b.rh_pos, Decimal("0.05"))
        b.process(book("hyperliquid", T + 700_000_000))
        self.assertEqual(b.hl_pos, 0)
        self.assertEqual(b.counts["hedge_lot_or_min_reject"], 1)
        self.assertIn("rh", b.exits)

    def test_late_flow_after_emergency_rh_exit_creates_new_exit_obligation(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000, qty=1, tid="a"))
        b.process(book("hyperliquid", T + 700_000_000,
                       bids=[[99, 10], [98.9, 10]]))  # Zero HL hedge; emergency.
        b.process(book("rh_lighter", T + 1_200_000_000))  # Cancels and exits first 0.5 RH.
        self.assertEqual(b.rh_pos, 0)
        b.process(trade(T + 1_250_000_000, source=T + 750_000_000,
                        qty=0.5, tid="b"))
        self.assertEqual(b.rh_pos, Decimal("0.5"))
        b.process(book("hyperliquid", T + 1_500_000_000))
        self.assertIn("rh", b.exits)
        self.assertEqual(b.counts["maker_increment"], 2)

    def test_late_pending_cancel_flow_is_new_obligation(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000, qty=1.0, tid="a"))  # 0.5 maker increment.
        self.assertEqual(b.quote.cancel_due_ns, T + 800_000_000)
        b.process(book("rh_lighter", T + 900_000_000))  # Cancellation observed.
        b.process(trade(T + 950_000_000, source=T + 750_000_000,
                        qty=0.5, tid="b"))
        self.assertEqual(b.rh_pos, Decimal("1.0"))
        self.assertEqual(b.counts["maker_increment"], 2)
        self.assertEqual(b.counts["late_pending_cancel_flow"], 1)
        self.assertEqual(len(b.hedges), 2)
        self.assertIsNone(b.unknown_reason)

    def test_above_bid_sell_after_cancel_due_does_not_censor(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000, qty=1, tid="a"))
        b.process(trade(T + 850_000_000, price=100.1, qty=1, tid="above"))
        self.assertIsNone(b.unknown_reason)

    def test_preactivation_unrelated_flow_does_not_kill(self):
        b = self.branch()
        b.process(book("rh_lighter", T))
        b.process(book("hyperliquid", T), DIAG)
        b.process(trade(T + 100_000_000, side="buy"))
        b.process(trade(T + 200_000_000, tid="old"))
        self.assertIsNone(b.unknown_reason)
        b.process(book("rh_lighter", T + 400_000_000))
        self.assertIsNotNone(b.quote.activated_ns)

    def test_delayed_eligible_flow_before_queue_snapshot_is_unknown(self):
        b = self.branch()
        start(b)  # Queue snapshot source T+0.4 s, modeled activation T+0.3 s.
        b.process(trade(T + 450_000_000, source=T + 350_000_000,
                        price=100, qty=1, tid="delayed"))
        self.assertEqual(b.unknown_reason, "eligible_flow_before_queue_snapshot")

    def test_flat_invalid_book_recovers_but_open_invalid_book_censors(self):
        b = self.branch()
        malformed = book("rh_lighter", T, bids=[[101, 1]], asks=[[100, 1]])
        b.process(malformed)
        self.assertIsNone(b.unknown_reason)
        self.assertNotIn("rh", b.books)
        b.process(book("rh_lighter", T + 100_000_000))
        b.process(book("hyperliquid", T + 100_000_000), DIAG)
        self.assertIsNotNone(b.quote)
        bad_open = book("rh_lighter", T + 200_000_000,
                        bids=[[101, 1]], asks=[[100, 1]])
        b.process(bad_open)
        self.assertTrue(b.unknown_reason.startswith("invalid_book_during_obligation:"))
        self.assertNotIn("rh", b.books)

    def test_stale_source_cannot_activate_and_submin_exit_is_unknown(self):
        b = self.branch()
        b.process(book("rh_lighter", T))
        b.process(book("hyperliquid", T), DIAG)
        b.process(book("rh_lighter", T + 400_000_000, source=T + 100_000_000))
        self.assertIsNone(b.quote.activated_ns)
        b.process(book("rh_lighter", T + 500_000_000))
        self.assertIsNotNone(b.quote.activated_ns)
        b.rh_pos = Decimal("0.01")  # <$10 residual cannot be silently flattened.
        b._start_exit(T + 500_000_000, "test")
        b.process(book("rh_lighter", T + 1_000_000_000))
        self.assertEqual(b.unknown_reason, "exit_order_lot_or_minimum_unknown")
        self.assertEqual(b.rh_pos, Decimal("0.01"))

    def test_hl_limit_rounds_toward_stricter_side(self):
        r = Rules.parse(META["hl"])
        lower = Decimal("99.94555")
        limit = r.sell_limit_at_or_above(lower)
        self.assertGreaterEqual(limit, lower)
        self.assertTrue(r.valid_price(limit))
        self.assertFalse(r.valid_price(Decimal("99.94555")))

    def test_early_exit_uses_executable_all_cost_mark(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        b.process(book("hyperliquid", T + 700_000_000))
        b.process(book("rh_lighter", T + 1_000_000_000,
                       bids=[[101, 10], [100.9, 10]], asks=[[101.2, 10]]))
        self.assertEqual(b.exit_requested_ns, T + 1_000_000_000)
        self.assertEqual(b.counts["take_profit_mark"], 1)
        self.assertEqual(b.exits["rh"].reason, "take_profit_mark")

    def test_unfilled_quote_charges_no_actual_entry_capital_and_sink_preserves_audit(self):
        rows = []
        b = MakerBranch(Config("BTC", Decimal("1000"), "fixed_best", max_audit=2),
                        META, audit_sink=rows.append)
        start(b)
        b.tick(T + 5_300_000_000)  # Third audit row: rest expiry/cancel request.
        self.assertEqual(b.capital_cost, 0)
        self.assertEqual(b.capital_base, 0)
        self.assertIsNone(b.unknown_reason)
        self.assertGreaterEqual(len(rows), 2)
        self.assertGreater(b.summary()["audit_omitted_from_summary"], 0)

    def test_hour_boundary_marks_funding_unknown(self):
        b = self.branch()
        start(b)
        b.process(trade(T + 500_000_000))
        b.process(book("hyperliquid", T + 700_000_000))
        b.tick(3600 * NS + 1)
        self.assertTrue(b.funding_unknown)
        self.assertIsNone(b.summary()["complete_net"])

    def test_funding_boundary_is_episode_local_while_lifetime_remains_unknown(self):
        b = self.branch()
        h = 3600 * NS - 5 * NS

        def episode(t, tid):
            b.process(book("rh_lighter", t))
            b.process(book("hyperliquid", t), DIAG)
            b.process(book("rh_lighter", t + 400_000_000))
            b.process(trade(t + 500_000_000, tid=tid))
            b.process(book("hyperliquid", t + 700_000_000))
            b.process(book("rh_lighter", t + 900_000_000))
            b.process(book("rh_lighter", t + 11_200_000_000))
            b.process(book("hyperliquid", t + 11_200_000_000))

        episode(h, "first")
        self.assertEqual(len(b.episodes), 1)
        self.assertTrue(b.episodes[0]["funding_unknown"])
        episode(h + 13 * NS, "second")
        self.assertEqual(len(b.episodes), 2)
        self.assertFalse(b.episodes[1]["funding_unknown"])
        self.assertTrue(b.summary()["funding_unknown"])
        self.assertIsNone(b.summary()["complete_net"])


if __name__ == "__main__":
    unittest.main()
