import csv
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.analyze_passive_fee_thresholds import (
    CAPITAL_ANNUAL, FEE_INPUTS, ROOT, SOURCE, TARGET, dec, published_rates,
    run, threshold_row,
)


def quoted_row(gross="0.5", side="buy_rh", stage="static"):
    """Unequal hedge notionals deliberately differ from the $100 size label."""
    rh_in, hedge_in, hedge_out = map(Decimal, ("100", "101", "103"))
    elapsed = 12 if stage == "delayed" else 0
    gross = Decimal(gross)
    rh_out = rh_in - hedge_in + hedge_out + (gross if side == "buy_rh" else -gross)
    capital = (rh_in + hedge_in) * CAPITAL_ANNUAL * elapsed / (365 * 86400)
    reserve = Decimal("0.0505")
    fee = (hedge_in + hedge_out) * Decimal("4.5") / 10_000
    return {
        "stage": stage, "asset": "BTC", "budget_usd": "100", "side": side,
        "anchor_ns": "100000000000", "exit_ns": str(100000000000 + elapsed * 10**9),
        "q": "1", "hl_hedge_entry": str(hedge_in), "hl_hedge_exit": str(hedge_out),
        "hl_rh_entry": str(rh_in), "hl_rh_exit": str(rh_out),
        "hl_gross": str(gross), "hl_capital": str(capital), "hl_reserve": str(reserve),
        "hl_fee": str(fee), "hl_fee_bps_per_taker": "4.5",
        "hl_fee_only": str(gross - fee - capital),
        "hl_stress": str(gross - fee - capital - reserve),
    }


class FeeThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = json.loads(FEE_INPUTS.read_text())
        cls.rates = published_rates("BTC", cls.frozen)

    def test_actual_two_hedge_notionals_and_both_cashflow_directions(self):
        for side in ("buy_rh", "sell_rh"):
            for stage in ("static", "delayed"):
                with self.subTest(side=side, stage=stage):
                    source = quoted_row(side=side, stage=stage)
                    result = threshold_row(source, self.rates)
                    denominator = Decimal("204")
                    self.assertEqual(dec(result["hl_two_leg_notional_usd"]), denominator)
                    max_fee = dec(result["fee_only_max_taker_bps"])
                    net = dec(source["hl_gross"]) - dec(source["hl_capital"]) - max_fee * denominator / 10_000
                    self.assertAlmostEqual(net, TARGET, places=24)
                    stress_max = dec(result["stress_max_taker_bps"])
                    self.assertAlmostEqual(
                        max_fee - stress_max,
                        dec(source["hl_reserve"]) * 10_000 / denominator, places=24)

    def test_negative_threshold_and_exact_target_boundary(self):
        result = threshold_row(quoted_row("0.05"), self.rates)
        self.assertLess(dec(result["fee_only_max_taker_bps"]), 0)
        self.assertEqual(result["zero_fee_meets_fee_only"], "False")
        # $0.10 + the actual two-leg 4.5 bp fee, with zero static capital.
        result = threshold_row(quoted_row("0.1918"), self.rates)
        self.assertEqual(dec(result["fee_only_max_taker_bps"]), Decimal("4.5"))
        self.assertEqual(result["fee_only_meets_at_base"], "True")
        self.assertEqual(result["stress_meets_at_base"], "False")

    def test_published_native_and_frozen_hip3_fee_formula(self):
        self.assertEqual(self.rates["tier6_volume_only"], Decimal("2.4"))
        self.assertEqual(self.rates["tier6_diamond"], Decimal("1.44"))
        for asset in ("NVDA", "XAG"):
            rates = published_rates(asset, self.frozen)
            self.assertEqual(rates["base"], Decimal("0.9"))
            self.assertEqual(rates["tier6_volume_only"], Decimal("0.48"))
            self.assertEqual(rates["tier6_diamond"], Decimal("0.288"))
            changed = json.loads(json.dumps(self.frozen))
            changed["markets"][asset]["growthMode"] = "disabled"
            with self.assertRaisesRegex(ValueError, "HIP-3 fee inputs"):
                published_rates(asset, changed)

    def test_inconsistent_fee_gross_capital_and_stress_inputs_rejected(self):
        for key in ("hl_fee", "hl_gross", "hl_capital", "hl_reserve"):
            with self.subTest(key=key):
                row = quoted_row(stage="delayed")
                row[key] = str(dec(row[key]) + Decimal("0.01"))
                # Preserve the score identities so each underlying amount is audited.
                row["hl_fee_only"] = str(dec(row["hl_gross"]) - dec(row["hl_fee"]) - dec(row["hl_capital"]))
                row["hl_stress"] = str(dec(row["hl_fee_only"]) - dec(row["hl_reserve"]))
                with self.assertRaises(ValueError):
                    threshold_row(row, self.rates)
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                dec(value)
        row = quoted_row(stage="delayed")
        row["exit_ns"] = row["anchor_ns"]
        with self.assertRaisesRegex(ValueError, "timing"):
            threshold_row(row, self.rates)

    def test_stopped_archive_complete_cohorts_and_reference_counts(self):
        protected = ROOT / "reports/rh-passive-exit-v1/protocol.json"
        protocol = json.loads(protected.read_text())
        before = {name: (ROOT / name).read_bytes() for name in protocol["source_sha256"]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            summary = run(SOURCE, out)
            self.assertEqual((summary["source_rows"], summary["groups"]), (4336, 64))
            overall = summary["overall"]
            self.assertEqual(overall["fee_only_base_clear_count"], 193)
            self.assertEqual(overall["fee_only_tier6_volume_only_clear_count"], 402)
            self.assertEqual(overall["fee_only_tier6_diamond_clear_count"], 574)
            self.assertEqual(overall["fee_only_zero_fee_clear_count"], 923)
            self.assertEqual(overall["stress_zero_fee_clear_count"], 1)
            for rate in ("base", "tier6_volume_only", "tier6_diamond"):
                self.assertEqual(overall[f"stress_{rate}_clear_count"], 0)
            with (out / "groups.csv").open(newline="") as stream:
                groups = list(csv.DictReader(stream))
            cohorts = {(g["stage"], g["asset"], g["budget_usd"], g["side"]) for g in groups}
            self.assertEqual(len(cohorts), 64)
            # Higher discounts cannot decrease quote target counts.
            for g in groups:
                for gate in ("fee_only", "stress"):
                    counts = [int(g[f"{gate}_{rate}_clear_count"]) for rate in
                              ("base", "tier6_volume_only", "tier6_diamond", "zero_fee")]
                    self.assertEqual(counts, sorted(counts))
        self.assertEqual(before, {name: (ROOT / name).read_bytes() for name in before})


if __name__ == "__main__":
    unittest.main()
