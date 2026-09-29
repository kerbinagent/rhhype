"""Focused checks for the read-only, settled-funding carry screen."""

import datetime as dt
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import funding_carry_probe as carry


class FundingCarryTests(unittest.TestCase):
    def test_lighter_percent_and_payer_direction_convert_to_fraction(self):
        self.assertAlmostEqual(carry.lighter_signed_fraction({"rate":"0.0012","direction":"long"}), 0.000012)
        self.assertAlmostEqual(carry.lighter_signed_fraction({"rate":"0.0012","direction":"short"}), -0.000012)
        with self.assertRaises(ValueError):
            carry.lighter_signed_fraction({"rate":"0.0012","direction":"unknown"})
        with self.assertRaises(ValueError):
            carry.lighter_signed_fraction({"rate":"nan","direction":"long"})
        with self.assertRaises(ValueError):
            carry.finite_rate("inf")

    def test_conflicting_duplicate_settlement_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            timestamp=1_800_000_000
            carry.save_json(out/"raw/lighter_core/BTC.json", {"fundings":[
                {"timestamp":timestamp,"rate":"0.0012","direction":"long"},
                {"timestamp":timestamp,"rate":"0.0013","direction":"long"}]})
            with self.assertRaisesRegex(ValueError,"conflicting lighter_core BTC"):
                carry.rate_series(out,"lighter_core","BTC",timestamp*1000,timestamp*1000)
            carry.save_json(out/"raw/hl/BTC.json", [
                {"time":timestamp*1000,"fundingRate":"0.000012"},
                {"time":timestamp*1000+15,"fundingRate":"0.000013"}])
            with self.assertRaisesRegex(ValueError,"conflicting hl BTC"):
                carry.rate_series(out,"hl","BTC",timestamp*1000,timestamp*1000)

    def test_four_fees_and_one_extra_cost_match_monitor_convention(self):
        # monitor.py: opening fees + equal closing-fee reserve + one
        # extra_cost_bps charge on the reference buy notional.
        fees, threshold = carry.roundtrip_cost_bps(4.5, 0.0, 5.0)
        self.assertEqual((fees, threshold), (9.0, 14.0))
        fees, threshold = carry.roundtrip_cost_bps(0.9, 3.5, 5.0)
        self.assertAlmostEqual(fees, 8.8)
        self.assertAlmostEqual(threshold, 13.8)
        self.assertEqual(carry.roundtrip_cost_bps(4.5, 0.0, 10.0)[1] - 14.0, 5.0)

    def test_holdout_cannot_choose_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            start = dt.datetime(2026, 9, 27, 17, tzinfo=dt.timezone.utc)
            first = int(start.timestamp()*1000)
            last = first + 47*carry.HOUR_MS
            carry.save_json(out / "raw/manifest.json", {
                "window_first_event_utc":start.isoformat(),
                "window_last_event_utc":dt.datetime.fromtimestamp(last/1000,dt.timezone.utc).isoformat()})
            carry.save_json(out / "raw/hl/BTC.json", [
                {"time":first+i*carry.HOUR_MS+15,"fundingRate":"0"} for i in range(48)])
            # Core's train rates favor long HL / short Core. Its holdout
            # rates reverse sign; choosing from holdout would flip the side.
            carry.save_json(out / "raw/lighter_core/BTC.json", {"fundings":[
                {"timestamp":(first+i*carry.HOUR_MS)//1000,"rate":"0.01",
                 "direction":"long" if i<24 else "short"} for i in range(48)]})
            # RH's train rates favor short HL / long RH, then reverse.
            carry.save_json(out / "raw/rh_lighter/BTC.json", {"fundings":[
                {"timestamp":(first+i*carry.HOUR_MS)//1000,"rate":"0.01",
                 "direction":"short" if i<24 else "long"} for i in range(48)]})
            rows = carry.analyze(out,5.0)
            core = next(r for r in rows if r["asset"]=="BTC" and r["venue"]=="lighter_core")
            rh = next(r for r in rows if r["asset"]=="BTC" and r["venue"]=="rh_lighter")
            self.assertEqual(core["direction"], "long_HL_short_venue")
            self.assertEqual(rh["direction"], "short_HL_long_venue")
            self.assertEqual(core["train_events"], 24)
            self.assertEqual(core["holdout_events"], 24)
            self.assertAlmostEqual(core["holdout_funding_edge_bps"], -24.0)
            self.assertAlmostEqual(rh["holdout_funding_edge_bps"], -24.0)

    def test_archived_raw_rebuild_is_identical(self):
        source = carry.BASE
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            shutil.copytree(source / "raw", out / "raw")
            carry.analyze(out,5.0)
            carry.analyze(out,10.0,"comparison_stress_10bp.csv",False)
            for name in ("comparison.csv","comparison_stress_10bp.csv","holdout_hourly.csv"):
                self.assertEqual((out/name).read_bytes(),(source/name).read_bytes(),name)


if __name__ == "__main__":
    unittest.main()
