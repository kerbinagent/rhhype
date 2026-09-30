import unittest
from decimal import Decimal

from scripts.analyze_passive_cost_buffer import scenario


def quoted_row(score="0.08", reserve="0.05"):
    row = {"stage": "static", "asset": "BTC", "budget_usd": "100",
           "side": "buy_rh"}
    for venue in ("hl", "core"):
        row.update({f"{venue}_fee_only": score, f"{venue}_reserve": reserve})
        row.update({f"{venue}_{leg}": "100" for leg in
                    ("rh_entry", "rh_exit", "hedge_entry", "hedge_exit")})
    return row


class CostBufferTests(unittest.TestCase):
    def test_equal_batch_allocation_and_target(self):
        rows = scenario([quoted_row("0.12")], Decimal(1), 50)
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["allocated_usd_per_turn"], "0.02")
            self.assertEqual(Decimal(r["median_quote_net_after_allocated_usd"]), Decimal("0.10"))
            self.assertEqual(r["positive_quote_count"], 1)
            self.assertEqual(r["at_least_10c_quote_count"], 1)
            self.assertEqual(r["allocated_less_than_5bp_stress"], 1)
            self.assertEqual(Decimal(r["median_allocated_bp_of_four_fill_turnover"]), Decimal("0.5"))

    def test_cost_can_exceed_stress_without_being_claimed_paid(self):
        rows = scenario([quoted_row()], Decimal(1), 10)
        self.assertTrue(all(r["positive_quote_count"] == 0 for r in rows))
        self.assertTrue(all(r["allocated_less_than_5bp_stress"] == 0 for r in rows))
        with self.assertRaises(ValueError):
            scenario([quoted_row()], Decimal(-1), 10)


if __name__ == "__main__":
    unittest.main()
