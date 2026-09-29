import unittest
from decimal import Decimal

from scripts.analyze_rh_small_amm import evaluate_quote, valid_hl_book


class SmallAmmQualityTests(unittest.TestCase):
    def setUp(self):
        self.book = {"time": 1000, "levels": [
            [{"px": "100", "sz": "2"}, {"px": "99", "sz": "3"}],
            [{"px": "101", "sz": "2"}, {"px": "102", "sz": "3"}]]}

    def test_book_requires_finite_sorted_uncrossed_and_source_before_receipt(self):
        self.assertIsNone(valid_hl_book(self.book, 1001))
        self.assertEqual(valid_hl_book(dict(self.book, time=1002), 1001), "book_clock")
        crossed = dict(self.book, levels=[[{"px": "102", "sz": "2"}], [{"px": "101", "sz": "2"}]])
        self.assertEqual(valid_hl_book(crossed, 1001), "crossed_book")
        bad = dict(self.book, levels=[[{"px": "NaN", "sz": "2"}], self.book["levels"][1]])
        self.assertEqual(valid_hl_book(bad, 1001), "nonpositive_or_nonfinite_level")

    def test_nonlot_hedge_is_flagged_not_rounded(self):
        row = {"hl_book": self.book, "hl_book_received_ms": 1000,
               "block_time_ms": 1000, "current_multiplier": "1"}
        quote = {"side": "buy", "usd_amount": "100", "token_qty": "1.0001",
                 "underlying_shares": "1.0001", "hl_walk_value_usdc": "100.0100",
                 "hl_exact_lot": False, "hl_source_vs_block_ms": 0,
                 "hl_receipt_vs_quote_ms": 0, "received_ms": 1000,
                 "entry_gross_gap_usd_at_parity": "0.0100",
                 "hl_entry_fee_usdc": "0.009000900",
                 "modeled_5bp_reserve_usd": "0.05000500"}
        meta = {"size_step": "0.001", "derived_taker_bps": "0.9"}
        result = evaluate_quote(row, quote, meta)
        self.assertEqual(result["status"], "quality_checked")
        self.assertFalse(result["exact_hl_lot"])
        self.assertTrue(result["near_time_2s"])
        self.assertEqual(Decimal(result["entry_gap_after_one_hl_fee"]),
                         Decimal(quote["entry_gross_gap_usd_at_parity"]) -
                         Decimal(quote["hl_entry_fee_usdc"]))
        self.assertEqual(Decimal(result["entry_gap_after_one_fee_reserve"]),
                         Decimal(result["entry_gap_after_one_hl_fee"]) -
                         Decimal(quote["modeled_5bp_reserve_usd"]))


if __name__ == "__main__":
    unittest.main()
