import unittest
from decimal import Decimal

from scripts.analyze_hedge_venue_hurdle import (
    NS, common_step, fresh, matched_books, pair_cashflows, quantity, walk,
)


def b(venue, receipt, source=None):
    return {"venue": venue, "valid": True, "receipt_utc_ns": receipt,
            "source_utc_ns": receipt if source is None else source,
            "bids": [[100, 1], [99, 2]], "asks": [[101, 1], [102, 2]]}


class HedgeVenueHurdleTests(unittest.TestCase):
    def test_exact_qty_depth_walk_and_own_notional_four_fee_legs(self):
        self.assertEqual(walk([[100, 1], [99, 2]], Decimal("1.5")), Decimal("149.5"))
        self.assertIsNone(walk([[100, 1]], Decimal("1.5")))
        result = pair_cashflows(1, 100, 102, 101, 104, 4.5,
                                rh_maker_bps=1, rh_exit_bps=2, reserve_bps=5)
        self.assertEqual(result["gross"], Decimal("-1"))
        expected_fee = (Decimal("100") + Decimal("204") + Decimal("101") * Decimal("4.5")
                        + Decimal("104") * Decimal("4.5")) / 10_000
        self.assertEqual(result["fee"], expected_fee)
        self.assertEqual(result["reserve"], Decimal("101") * Decimal("5") / 10_000)

    def test_quantity_common_lot_and_budget(self):
        step = common_step("0.0001", "0.001", "0.01")
        self.assertEqual(step, Decimal("0.01"))
        q = quantity(250, 101, step)
        self.assertEqual(q, Decimal("2.47"))
        self.assertLessEqual(q * Decimal("101"), Decimal("250"))

    def test_no_future_or_stale_or_skewed_book_in_common_anchor(self):
        anchor = 10 * NS
        books = {("BTC", "rh_lighter"): b("rh_lighter", anchor),
                 ("BTC", "hyperliquid"): b("hyperliquid", anchor - NS // 2),
                 ("BTC", "lighter"): b("lighter", anchor - NS // 4)}
        self.assertIsNotNone(matched_books(books, "BTC", anchor))
        self.assertFalse(fresh(b("lighter", anchor + 1), anchor))
        books[("BTC", "lighter")] = b("lighter", anchor - 3 * NS)
        self.assertIsNone(matched_books(books, "BTC", anchor))
        books[("BTC", "lighter")] = b("lighter", anchor, source=anchor - 3 * NS)
        self.assertIsNone(matched_books(books, "BTC", anchor))


if __name__ == "__main__":
    unittest.main()
