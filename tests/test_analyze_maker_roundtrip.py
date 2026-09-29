"""Non-archive checks for the frozen conditional maker round-trip policy."""

import unittest

from scripts.analyze_maker_roundtrip import (
    SECOND, conditional_roundtrip, first_exit_pair, first_full_flow,
    first_hedge_quote,
)


def quote(receipt_s, source_s, bid=99.0, ask=101.0, bid_size=2.0, ask_size=2.0):
    return {"receipt_ns": int(receipt_s * SECOND), "source_ns": int(source_s * SECOND),
            "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size}


class MakerRoundtripTests(unittest.TestCase):
    def test_full_flow_is_strict_and_uses_receipt_order(self):
        arrival = 10 * SECOND
        trades = [
            {"receipt_ns": 11 * SECOND, "source_ns": 10 * SECOND, "id": 1,
             "buy_aggressor": True, "price": 101.0, "qty": 1.0},
            {"receipt_ns": 12 * SECOND, "source_ns": 11 * SECOND, "id": 2,
             "buy_aggressor": True, "price": 101.0, "qty": 1.0},
            {"receipt_ns": 13 * SECOND, "source_ns": 12 * SECOND, "id": 3,
             "buy_aggressor": True, "price": 101.0, "qty": 0.1},
        ]
        receipts = [t["receipt_ns"] for t in trades]
        event = first_full_flow(trades, receipts, arrival, 15 * SECOND,
                                "sell", 100.0, ahead=1.0, qty=1.0)
        self.assertEqual(event["receipt_ns"], 13 * SECOND)
        self.assertEqual(event["source_ns"], 12 * SECOND)
        self.assertAlmostEqual(event["cumulative_qualifying_qty"], 2.1)

    def test_shallow_first_time_valid_hedge_is_censored(self):
        series = [quote(10.1, 9.9, bid_size=10),  # pre-flow source, skipped
                  quote(10.2, 10.1, bid_size=0.5),
                  quote(10.3, 10.2, bid_size=10)]
        found, status = first_hedge_quote(series, [q["receipt_ns"] for q in series],
                                          10 * SECOND, 10 * SECOND, "buy", 1.0)
        self.assertIsNone(found)
        self.assertEqual(status, "insufficient_hedge_top_depth")

    def test_shallow_first_time_valid_exit_pair_is_censored(self):
        maker = [quote(20.1, 20.0, bid_size=0.2), quote(20.4, 20.3, bid_size=2)]
        hedge = [quote(20.2, 20.1, ask_size=2), quote(20.5, 20.4, ask_size=2)]
        pair, status = first_exit_pair(maker, hedge, 20 * SECOND, "buy", 1.0)
        self.assertIsNone(pair)
        self.assertEqual(status, "insufficient_exit_top_depth")

    def test_four_own_notional_fees_and_larger_entry_reserve(self):
        hedge_entry = quote(12, 12, bid=100, ask=102)
        maker_exit = quote(22, 22, bid=99, ask=101)
        hedge_exit = quote(22, 22, bid=100, ask=102)
        result = conditional_roundtrip("sell", 100, hedge_entry, maker_exit, hedge_exit,
                                       qty=1, maker_venue="hyperliquid", hedge_venue="lighter")
        # Short maker: 100-101, long hedge: 100-102. HL maker 1.5bp of100,
        # HL taker exit 4.5bp of101; Core Standard is zero.
        self.assertAlmostEqual(result["conditional_gross_usd"], -3.0)
        self.assertAlmostEqual(result["four_fee_usd"], 100 * .00015 + 101 * .00045)
        self.assertAlmostEqual(result["five_bp_larger_entry_reserve_usd"], 102 * .0005)
        self.assertAlmostEqual(result["conditional_net_after_reserve_usd"],
                               -3 - result["four_fee_usd"] - .051)


if __name__ == "__main__":
    unittest.main()
