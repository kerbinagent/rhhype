"""Focused checks for frozen-holdout fee and turnover counterfactuals."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fee_sensitivity as fees


class FeeSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample, cls.reference, cls.train, cls.holdout, cls.boundary, cls.purged, cls.digest = fees.load_frozen_holdout()
        cls.result, cls.attempts, cls.failed = fees.analyze()

    def test_split_uses_only_outcomes_settled_before_boundary(self):
        self.assertEqual(self.digest, fees.EXPECTED_SHA256)
        self.assertEqual(self.boundary, self.reference["train_test"]["cut_at"])
        self.assertEqual((len(self.holdout),self.purged),(528,2))
        for trade in self.train:
            known_at=trade.get("closed_at") if trade["status"]=="ABORTED" else trade.get("settled_at")
            self.assertLess(known_at,self.boundary)

    def test_scenario_algebra_and_failed_hedges_stay_separate(self):
        hold=self.result["primary_holdout"]
        self.assertEqual((hold["paired"],hold["failed_hedges"],hold["aborted"]),(517,10,1))
        base=hold["scenarios"]["recorded"]
        zero_fee=hold["scenarios"]["zero_fees"]
        zero_reserve=hold["scenarios"]["zero_reserve"]
        zero_both=hold["scenarios"]["zero_both"]
        self.assertAlmostEqual(zero_fee["all_closed_net_usd"]-base["all_closed_net_usd"],hold["recorded_fees_usd"])
        self.assertAlmostEqual(zero_reserve["all_closed_net_usd"]-base["all_closed_net_usd"],hold["modeled_5bp_reserve_usd"])
        self.assertAlmostEqual(zero_both["all_closed_net_usd"]-base["all_closed_net_usd"],hold["recorded_fees_usd"]+hold["modeled_5bp_reserve_usd"])
        self.assertLess(zero_both["all_closed_net_usd"],0)
        self.assertAlmostEqual(zero_both["paired_net_usd"]+zero_both["failed_hedge_net_usd"],zero_both["all_closed_net_usd"])

    def test_improvement_uses_recorded_four_leg_turnover(self):
        hold=self.result["primary_holdout"]
        self.assertEqual(len(self.attempts),517)
        turnover=sum(row["four_leg_turnover_usd"] for row in self.attempts)
        self.assertAlmostEqual(turnover,2_064_381.40152,places=4)
        self.assertAlmostEqual(hold["paired_four_leg_turnover_usd"],turnover)
        first=self.attempts[0]
        self.assertAlmostEqual(first["four_leg_turnover_usd"],first["hl_turnover_usd"]+first["other_venue_turnover_usd"])
        self.assertAlmostEqual(first["additional_improvement_recorded_bps_of_four_leg_turnover"],
                               max(0,-first["net_recorded_usd"])/first["four_leg_turnover_usd"]*10_000)
        paired_shortfall=-hold["scenarios"]["recorded"]["paired_net_usd"]
        self.assertAlmostEqual(hold["scenarios"]["recorded"]["paired_aggregate_extra_bps_to_zero"],paired_shortfall/turnover*10_000)
        with self.assertRaises(ValueError):
            fees.four_leg_turnover(self.failed[0])

    def test_original_filters_unreselected_and_outputs_rebuild(self):
        fixed=self.result["fixed_train_selected_filters_on_same_holdout"]
        for family,item in fixed.items():
            self.assertEqual(item["threshold"],self.reference["experiments"][family]["chosen_threshold"])
            self.assertLess(item["result"]["scenarios"]["zero_both"]["all_closed_net_usd"],0)
        with tempfile.TemporaryDirectory() as directory:
            fees.write(Path(directory))
            for filename in ("summary.json","paired_attempts.csv","failed_hedges.csv"):
                self.assertEqual((Path(directory)/filename).read_bytes(),(fees.OUT/filename).read_bytes(),filename)


if __name__ == "__main__":
    unittest.main()
