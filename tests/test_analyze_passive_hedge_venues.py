import unittest
from decimal import Decimal

from scripts.analyze_passive_hedge_venues import (
    cycle, delayed_observation, valid_quantity, analyze_dataset, NS,
)


def book(bid, ask, qty=100, ts=0):
    return {"bids": [[bid, qty]], "asks": [[ask, qty]],
            "source_utc_ns": ts, "receipt_utc_ns": ts}


def specs():
    return {venue: {"size_step": "1", "min_qty": "1", "min_notional": "5",
                    "max_qty": None, "taker_fee_bps": "4.5" if venue == "hyperliquid" else "0"}
            for venue in ("rh_lighter", "hyperliquid", "lighter")}


class PassiveHedgeVenueTests(unittest.TestCase):
    def test_static_two_maker_spread_and_own_notional_fees_both_sides(self):
        rh = {"rh_lighter": book(100, 101)}
        hl = book(100, 101)
        core = book(Decimal("100.5"), Decimal("100.6"))
        for side in ("buy_rh", "sell_rh"):
            h = cycle(1, side, rh, rh, hl, hl, "4.5")
            c = cycle(1, side, rh, rh, core, core, 0)
            self.assertEqual(h["gross"], 0)
            self.assertEqual(h["fee"], Decimal("201") * Decimal("4.5") / 10_000)
            self.assertEqual(c["gross"], Decimal("0.9"))
            self.assertEqual(c["fee"], 0)
            self.assertEqual(c["fee_only"], Decimal("0.9"))
            self.assertEqual(c["stress"], c["fee_only"] - c["reserve"])

    def test_delayed_price_change_and_depth_are_not_silently_zero(self):
        rh0 = {"rh_lighter": book(100, 101)}
        rh1 = {"rh_lighter": book(98, 99)}
        hedge0 = book(100, 101)
        hedge1 = book(99, 100)
        result = cycle(1, "buy_rh", rh0, rh1, hedge0, hedge1, 0, 10)
        self.assertEqual(result["gross"], Decimal("-1"))
        self.assertGreater(result["capital"], 0)
        self.assertLess(result["fee_only"], -1)
        self.assertIsNone(cycle(2, "buy_rh", rh0, rh1, book(100, 101, 1), hedge1, 0))

    def test_common_quantity_checks_minimums_and_same_matched_observation(self):
        b = {v: book(10, 11) for v in ("rh_lighter", "hyperliquid", "lighter")}
        m = specs()
        self.assertTrue(valid_quantity(1, b, m))
        m["lighter"]["min_qty"] = "2"
        self.assertFalse(valid_quantity(1, b, m))
        m["lighter"]["min_qty"] = "1"
        b["lighter"] = book(11, 10)
        self.assertFalse(valid_quantity(1, b, m))
        b["lighter"] = book(10, 11)
        anchor = 100 * NS
        after = anchor + 10 * NS
        for value in b.values():
            value["source_utc_ns"] = value["receipt_utc_ns"] = anchor
        later = {v: book(10, 11, ts=after) for v in b}
        rows, coverage = analyze_dataset(("BTC",), {"BTC": [anchor]},
                                         {"BTC": [(anchor, b), (after, later)]},
                                         {v: {"BTC": spec} for v, spec in m.items()})
        self.assertEqual(len(rows), 16)  # 4 sizes × 2 sides × static/delayed
        self.assertEqual({r["q"] for r in rows if r["budget_usd"] == 100}, {"9"})
        self.assertTrue(all(Decimal(r["hl_fee_only"]) <= Decimal(r["core_fee_only"])
                            for r in rows))
        self.assertEqual(coverage[("delayed", "BTC", 100, "buy_rh"), "complete_common"], 1)

    def test_unmatched_delayed_books_are_censored_from_quote_rows(self):
        b = {v: book(10, 11) for v in ("rh_lighter", "hyperliquid", "lighter")}
        m = {v: {"BTC": spec} for v, spec in specs().items()}
        anchor = 100 * NS
        rows, coverage = analyze_dataset(("BTC",), {"BTC": [anchor]},
                                         {"BTC": [(anchor, b)]}, m)
        self.assertEqual(len(rows), 8)  # static only
        self.assertEqual(coverage[("delayed", "BTC", 100, "buy_rh"), "exit_unmatched"], 1)

    def test_delayed_quote_requires_every_source_after_due(self):
        anchor = 100 * NS
        due = anchor + 10 * NS
        stale = {v: book(10, 11, ts=due) for v in specs()}
        stale["lighter"]["source_utc_ns"] = due - 1
        valid = {v: book(10, 11, ts=due + NS) for v in specs()}
        observations = [(due, stale), (due + NS, valid)]
        self.assertEqual(delayed_observation(observations, [t for t, _ in observations], anchor),
                         observations[1])


if __name__ == "__main__":
    unittest.main()
