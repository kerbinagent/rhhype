"""Delayed public-flow evidence must survive retirement of a canceled quote."""

import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config, NS
from scripts.rh_maker_late_flow_guard import (GuardedMakerBuyBranch,
                                              GuardedMakerSellBranch, RetiredQuote)


T = 100 * NS
META = {
    "rh": {"price_tick": "0.1", "qty_step": "0.01", "min_qty": "0.01",
           "min_notional": "10", "taker_fee_bps": "0"},
    "hl": {"price_tick_semantics": "hl_perp", "sz_decimals": 2,
           "qty_step": "0.01", "min_qty": "0.01", "min_notional": "10",
           "taker_fee_bps": "4.5"},
}


def book(venue, at, *, bids=None, asks=None, generation="g"):
    if venue == "rh_lighter":
        bids = bids if bids is not None else [[100, 0.5], [99.9, 10]]
        asks = asks if asks is not None else [[101, 0.5], [101.1, 10]]
    else:
        bids = bids if bids is not None else [[100.1, 10], [100, 10]]
        asks = asks if asks is not None else [[100.2, 10], [100.3, 10]]
    return {"type": "book", "venue": venue, "asset": "BTC",
            "received_ns": at, "source_ns": at, "generation": generation,
            "valid": True, "clock_valid": True, "bids": bids, "asks": asks}


def trade(at, source, side, price, *, qty=0.01, generation="g", tid="late"):
    return {"type": "trade", "venue": "rh_lighter", "asset": "BTC",
            "received_ns": at, "source_ns": source, "generation": generation,
            "clock_valid": True, "side": side, "price": price,
            "qty": qty, "trade_id": tid}


def start(branch, sell=False):
    branch.process(book("rh_lighter", T))
    branch.process(book("hyperliquid", T),
                   {"reason": "quote", "price": 101 if sell else 100,
                    "quantity": 1, "forecast_net_usd": -100})
    assert branch.quote is not None
    branch.process(book("rh_lighter", T + 400_000_000))
    assert branch.quote.activated_ns is not None


def retire_no_flow(branch):
    branch.tick(T + 5_300_000_000)  # Activation due T+.3, rest expires T+5.3.
    assert branch.quote.cancel_due_ns == T + 5_600_000_000
    branch.process(book("rh_lighter", T + 5_700_000_000))
    assert branch.quote.canceled_ns == T + 5_700_000_000
    branch.tick(T + 7_700_000_000)  # Old base engine would retire the quote.
    assert branch.quote is None


class LateFlowGuardTests(unittest.TestCase):
    def buy_branch(self, **kwargs):
        return GuardedMakerBuyBranch(Config("BTC", Decimal(1000), "fixed_best", **kwargs), META)

    def sell_branch(self, **kwargs):
        return GuardedMakerSellBranch(Config("BTC", Decimal(1000), "fixed_best", **kwargs), META)

    def test_old_buy_quote_late_tiny_sell_marks_episode_unknown_without_fill(self):
        branch = self.buy_branch()
        start(branch)
        retire_no_flow(branch)
        self.assertEqual(branch.summary()["retired_quote_guard_count"], 1)
        self.assertEqual(branch.episodes[0]["cash_known"], "0")
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        branch.process(trade(T + 7_800_000_000, T + 5_500_000_000,
                             "sell", 100, qty=0.01))
        result = branch.summary()
        self.assertEqual(result["unknown_reason"], "late_retired_quote_flow")
        self.assertIsNone(result["complete_net"])
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))
        self.assertEqual((branch.cash_rh, branch.cash_hl), (0, 0))
        self.assertEqual(result["late_retired_flow_count"], 1)
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertEqual(branch.episodes[0]["late_retired_flow"]["source_ns"],
                         T + 5_500_000_000)
        self.assertTrue(any(row["event"] == "late_retired_quote_flow"
                            for row in result["audit"]))

    def test_late_old_flow_is_caught_even_with_new_quote_pending(self):
        branch = self.buy_branch()
        start(branch)
        retire_no_flow(branch)
        branch.process(book("rh_lighter", T + 7_740_000_000))
        branch.process(book("hyperliquid", T + 7_750_000_000),
                       {"reason": "quote", "price": 100, "quantity": 1})
        self.assertIsNotNone(branch.quote)
        new_quote = branch.quote
        branch.process(trade(T + 7_800_000_000, T + 5_500_000_000,
                             "sell", 100))
        self.assertIs(branch.quote, new_quote)
        self.assertEqual(branch.episodes[0]["execution_unknown_reason"],
                         "late_retired_quote_flow")
        self.assertEqual(branch.unknown_reason, "late_retired_quote_flow")

    def test_sell_guard_reverses_flow_side_and_price_condition(self):
        branch = self.sell_branch()
        start(branch, sell=True)
        retire_no_flow(branch)
        branch.process(trade(T + 7_800_000_000, T + 5_500_000_000,
                             "buy", 101.1, qty=0.01))
        self.assertEqual(branch.unknown_reason, "late_retired_quote_flow")
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertEqual(branch.episodes[0]["late_retired_flow"]["quote_price"], "101")
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))

    def test_cancel_endpoint_is_ambiguous_but_nonmatching_evidence_is_not(self):
        branch = self.buy_branch()
        start(branch)
        retire_no_flow(branch)
        for side, price, source, generation in [
            ("buy", 100, T + 5_500_000_000, "g"),
            ("sell", 100.1, T + 5_500_000_000, "g"),
            ("sell", 100, T + 5_700_000_000, "g"),
        ]:
            branch.process(trade(T + 7_800_000_000, source, side, price,
                                 generation=generation, tid=f"{side}-{price}-{source}-{generation}"))
        self.assertIsNone(branch.unknown_reason)
        branch.process(trade(T + 7_900_000_000, T + 5_600_000_000,
                             "sell", 100, tid="endpoint"))
        self.assertEqual(branch.unknown_reason, "late_retired_quote_flow")

    def test_reconnect_generation_does_not_hide_late_old_flow(self):
        branch = self.buy_branch()
        start(branch)
        retire_no_flow(branch)
        branch.process(trade(T + 7_800_000_000, T + 5_500_000_000,
                             "sell", 100, generation="reconnected"))
        self.assertEqual(branch.unknown_reason,
                         "late_retired_quote_flow_generation_ambiguous")
        row = branch.episodes[0]
        self.assertTrue(row["execution_unknown"])
        self.assertEqual(row["execution_unknown_reason"],
                         "late_retired_quote_flow_generation_ambiguous")
        self.assertEqual(row["late_retired_flow"]["generation"], "reconnected")
        self.assertEqual(row["late_retired_flow"]["quote_generation"], "g")
        self.assertEqual((branch.cash_rh, branch.cash_hl, branch.rh_pos, branch.hl_pos),
                         (0, 0, 0, 0))

    def test_receipt_at_retirement_is_not_subsequent_evidence(self):
        branch = self.buy_branch()
        start(branch)
        retire_no_flow(branch)
        branch.process(trade(T + 7_700_000_000, T + 5_500_000_000,
                             "sell", 100))
        self.assertIsNone(branch.unknown_reason)

    def test_full_fill_has_no_unfilled_remainder_guard(self):
        branch = self.buy_branch(hold_ns=NS)
        start(branch)
        branch.process(trade(T + 500_000_000, T + 500_000_000,
                             "sell", 100, qty=1.5, tid="full"))
        self.assertEqual(branch.quote.remaining, 0)
        branch.process(book("hyperliquid", T + 700_000_000))
        branch.process(book("rh_lighter", T + 900_000_000))
        branch.process(book("rh_lighter", T + 2_200_000_000))
        branch.process(book("hyperliquid", T + 2_200_000_000))
        branch.tick(T + 2_900_000_000)
        self.assertIsNone(branch.quote)
        self.assertEqual(branch.summary()["retired_quote_guard_count"], 0)
        branch.process(trade(T + 3_000_000_000, T + 750_000_000,
                             "sell", 100, tid="later"))
        self.assertIsNone(branch.unknown_reason)

    def test_quote_rejected_before_activation_has_no_guard(self):
        branch = self.buy_branch()
        branch.process(book("rh_lighter", T))
        branch.process(book("hyperliquid", T),
                       {"reason": "quote", "price": 100, "quantity": 1})
        branch.process(book("rh_lighter", T + 400_000_000,
                            bids=[[99.9, 10]], asks=[[100, 10]]))
        self.assertIsNone(branch.quote)
        self.assertEqual(branch.summary()["retired_quote_guard_count"], 0)
        branch.process(trade(T + 7_800_000_000, T + 350_000_000,
                             "sell", 100))
        self.assertIsNone(branch.unknown_reason)

    def test_guard_capacity_marks_unknown_without_retiring_current_quote(self):
        branch = self.buy_branch(max_episodes=1)
        start(branch)
        branch.retired_quotes.append(RetiredQuote(
            0, "sell", Decimal(100), Decimal(1), T, T, T + 1,
            "old-generation", T + 2))
        branch.tick(T + 5_300_000_000)
        branch.process(book("rh_lighter", T + 5_700_000_000))
        branch.tick(T + 7_700_000_000)
        self.assertEqual(branch.unknown_reason, "retired_quote_guard_cap")
        self.assertIsNotNone(branch.quote)
        self.assertEqual(len(branch.retired_quotes), 1)


if __name__ == "__main__":
    unittest.main()
