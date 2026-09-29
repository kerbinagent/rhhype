import unittest
from decimal import Decimal

from scripts.analyze_rh_quote_distance import (
    GRACE, NS, first_queue, ladder_price, make_branches, observe_trade,
    quote_qty, summarize,
)


class QuoteDistanceTests(unittest.TestCase):
    def test_outward_tick_rounding_and_size(self):
        self.assertEqual(ladder_price("100", 2, ".01", "bid"), Decimal("99.98"))
        self.assertEqual(ladder_price("100", 2, ".01", "ask"), Decimal("100.02"))
        self.assertEqual(ladder_price("100.005", 0, ".01", "bid"), Decimal("100.00"))
        self.assertEqual(ladder_price("100.005", 0, ".01", "ask"), Decimal("100.01"))
        self.assertEqual(quote_qty(100, Decimal("99.98"), ".01"), Decimal("1.00"))

    def test_same_price_queue_and_bid_ask_flow(self):
        book = {"bids": [["100", "3"], ["99.98", "4"]],
                "asks": [["100.02", "2"], ["100.04", "6"]]}
        self.assertEqual(first_queue(book, "bid", Decimal("99.98")), 4)
        self.assertEqual(first_queue(book, "ask", Decimal("100.04")), 6)
        meta = {"price_tick": ".01", "size_step": ".01",
                "min_qty": ".01", "min_notional": "10"}
        bid = next(x for x in make_branches("T", 0, book, meta)
                   if x["side"] == "bid" and x["offset_bps"] == 2 and x["budget_usd"] == 100)
        bid["ahead_qty"] = Decimal("4")
        due, activated = 300_000_000, 400_000_000
        def flow(side, price, qty, source, receipt):
            return {"side": side, "price": price, "qty": qty,
                    "source_ns": source, "received_ns": receipt}
        observe_trade(bid, flow("buy", "99.98", 10, NS, NS), activated, activated, due, 10*NS)
        self.assertEqual(bid["qualified_flow_qty"], 0)
        observe_trade(bid, flow("sell", "99.97", 4, NS, NS), activated, activated, due, 10*NS)
        self.assertEqual(bid["possible_qty"], 0)
        observe_trade(bid, flow("sell", "99.98", "0.5", 2*NS, 2*NS), activated, activated, due, 10*NS)
        self.assertEqual(bid["possible_qty"], Decimal("0.5"))
        self.assertEqual(bid["through_qty"], 4)
        self.assertEqual(bid["at_qty"], Decimal("0.5"))
        ask = next(x for x in make_branches("T", 0, book, meta)
                   if x["side"] == "ask" and x["offset_bps"] == 2 and x["budget_usd"] == 100)
        ask["ahead_qty"] = 0
        observe_trade(ask, flow("buy", ask["quote_price"], 1, NS, NS), activated, activated, due, 10*NS)
        self.assertEqual(ask["possible_qty"], min(ask["quantity"], Decimal(1)))

    def test_pre_observation_trade_is_ambiguous_and_late_is_excluded(self):
        b = {"side": "bid", "quote_price": Decimal(100), "quantity": Decimal(1),
             "ahead_qty": Decimal(0), "at_qty": Decimal(0), "through_qty": Decimal(0),
             "qualified_flow_qty": Decimal(0), "possible_qty": Decimal(0),
             "touch_count": 0, "reason": None}
        pre = {"side": "sell", "price": 100, "qty": 1,
               "source_ns": 350_000_000, "received_ns": 450_000_000}
        observe_trade(b, pre, 400_000_000, 500_000_000, 300_000_000, 10*NS)
        self.assertEqual(b["reason"], "ambiguous_trade_clock_or_queue_initialization")
        b["reason"] = None
        late = dict(pre, source_ns=11*NS, received_ns=11*NS)
        observe_trade(b, late, 400_000_000, 500_000_000, 300_000_000, 10*NS)
        self.assertEqual(b["touch_count"], 0)
        delayed = dict(pre, source_ns=NS, received_ns=NS+GRACE+1)
        observe_trade(b, delayed, 400_000_000, 500_000_000, 300_000_000, 10*NS)
        self.assertEqual(b["reason"], "ambiguous_trade_clock_or_queue_initialization")


if __name__ == "__main__":
    unittest.main()
