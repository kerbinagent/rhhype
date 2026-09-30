"""Selection-only reserve variant; frozen v1 engine is not modified."""

import copy
import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config
from scripts.rh_passive_exit_cost_policy import (
    CostPolicyPassiveExitBranch, required_target_ask,
)
from scripts.rh_passive_exit_engine import PassiveExitBranch
from tests.test_rh_maker_engine import META, T, book, trade
from tests.test_rh_passive_exit_engine import activate_exit, matched_entry


def config():
    return Config("BTC", Decimal("1000"), "fixed_best")


class PassiveExitCostPolicyTests(unittest.TestCase):
    def test_pure_formula_only_adds_selected_reserve_to_required_price(self):
        inputs = dict(qty=Decimal("2"), target_usd=Decimal("0.10"),
                      existing_cash=Decimal("0.12"), hl_buy_value=Decimal("200"),
                      adverse_bps=Decimal("1"), hl_taker_fee_bps=Decimal("0.9"),
                      rh_maker_fee_bps=Decimal("1.2"), capital_usd=Decimal("0.01"))
        no_reserve = required_target_ask(**inputs, quote_reserve_usd=Decimal("0"))
        stress = required_target_ask(**inputs, quote_reserve_usd=Decimal("0.10"))
        expected_delta = Decimal("0.10") / (Decimal("2") * (1 - Decimal("1.2") / 10_000))
        self.assertLess(abs((stress - no_reserve) - expected_delta), Decimal("1e-24"))
        self.assertEqual(inputs["hl_buy_value"], Decimal("200"))
        with self.assertRaises(ValueError):
            required_target_ask(**inputs, quote_reserve_usd=Decimal("-1"))

    def test_quote_zero_and_five_differ_only_in_selection_allowance(self):
        meta = copy.deepcopy(META)
        meta["rh"]["price_tick"] = "0.01"
        zero = CostPolicyPassiveExitBranch(config(), meta,
                                           exit_policy="passive_target10s",
                                           exit_adverse_bps=Decimal("0"),
                                           quote_reserve_bps=0)
        five = CostPolicyPassiveExitBranch(config(), meta,
                                           exit_policy="passive_target10s",
                                           exit_adverse_bps=Decimal("0"),
                                           quote_reserve_bps=5)
        asks = [[100.31, 10], [100.32, 10]]
        for branch in (zero, five):
            matched_entry(branch)
            activate_exit(branch, rh_asks=asks)
        self.assertEqual(zero.passive_ask.price, Decimal("100.31"))
        self.assertEqual(five.passive_ask.price, Decimal("100.35"))
        self.assertEqual(zero.reserve_cost, five.reserve_cost)
        self.assertEqual(zero.cash_rh + zero.cash_hl, five.cash_rh + five.cash_hl)
        self.assertEqual(zero.fees_hl, five.fees_hl)
        self.assertEqual(zero.summary()["reported_stress_reserve_bps"], "5")
        self.assertEqual(five.summary()["reported_stress_reserve_bps"], "5")

        zero.process(trade(T + 3_300_000_000, side="buy", price=100.31,
                           qty=11, tid="exit"))
        zero.process(book("hyperliquid", T + 3_500_000_000))
        zero.process(book("rh_lighter", T + 3_700_000_000, asks=asks))
        zero.tick(T + 5_700_000_000)
        summary = zero.summary()
        self.assertEqual(Decimal(summary["stressed_complete_net"]),
                         Decimal(summary["fee_only_complete_net"])
                         - Decimal(summary["reserve_cost"])
                         - Decimal(summary["capital_cost"]))
        self.assertLess(Decimal(summary["stressed_complete_net"]),
                        Decimal(summary["fee_only_complete_net"]))

    def test_five_bp_quote_and_economics_match_original_v1(self):
        original = PassiveExitBranch(config(), META,
                                     exit_policy="passive_target10s",
                                     exit_adverse_bps=Decimal("0"))
        variant = CostPolicyPassiveExitBranch(config(), META,
                                              exit_policy="passive_target10s",
                                              exit_adverse_bps=Decimal("0"),
                                              quote_reserve_bps=5)
        for branch in (original, variant):
            matched_entry(branch)
            activate_exit(branch)
            self.assertEqual(branch.passive_ask.price, Decimal("100.4"))
            branch.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                                 qty=11, tid="exit"))
            branch.process(book("hyperliquid", T + 3_500_000_000))
            branch.process(book("rh_lighter", T + 3_700_000_000))
            branch.tick(T + 5_700_000_000)
        base, trial = original.summary(), variant.summary()
        for key in ("episodes", "counts", "audit", "cash_known", "fees_rh", "fees_hl",
                    "reserve_cost", "capital_cost", "complete_net",
                    "fee_only_complete_net", "stressed_complete_net"):
            self.assertEqual(base[key], trial[key], key)

    def test_variant_rejects_unfrozen_ledger_reserve(self):
        bad = Config("BTC", Decimal("1000"), "fixed_best",
                     reserve_bps=Decimal("0"))
        with self.assertRaises(ValueError):
            CostPolicyPassiveExitBranch(bad, META,
                                        exit_policy="passive_target10s",
                                        quote_reserve_bps=0)


if __name__ == "__main__":
    unittest.main()
