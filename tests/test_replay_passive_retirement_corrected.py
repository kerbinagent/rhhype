from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_rh_passive_exit as original
from scripts import rh_passive_exit_engine as engine
from scripts import replay_passive_retirement_corrected as corrected
from tests.test_rh_maker_late_flow_guard import book, trade

NS = original.NS
START = 1_796_083_200 * NS  # December 1, 2026 UTC, synthetic only.
DECISION = START + 1803 * NS


class FixedBuyModel:
    def __init__(self, *args):
        pass

    def consume(self, event):
        pass

    def quote(self, asset, size, policy, *, now_ns):
        if asset == "BTC" and size == 1000 and now_ns == DECISION:
            return {"reason": "quote", "price": 100, "quantity": 1}
        return None

    def snapshot(self):
        return {"synthetic_test_model": True}


class FixedSellModel(FixedBuyModel):
    def __init__(self, *args):
        self.fit = {"routes": {
            f"{asset}|{size}": {"flow_ready": False, "adverse_p75_bps": None}
            for asset in original.ASSETS for size in original.SIZES}}


class CorrectedReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        shutil.copytree(original.ROOT / "reports/rh-small-maker-v1/metadata",
                        self.capture / "metadata")
        self.protocol = self.root / "protocol.json"
        data = original.build_protocol("2026-11-30T23:59:00+00:00", self.capture / "metadata")
        self.protocol.write_text(json.dumps(data))
        manifest = {
            "schema": "rh-maker-public-capture-v1", "read_only": True,
            "configured_seconds": 3000, "calibration_seconds": 1800,
            "holdout_seconds": 1200, "configured_total_bytes": 384_000_000,
            "started_utc": "2026-12-01T00:00:00+00:00",
            "ended_utc": "2026-12-01T00:50:00+00:00",
            "end_reason": "duration_limit", "frames_sha256": "0" * 64,
            "metadata_normalized_sha256": data["metadata_normalized_sha256"],
        }
        (self.capture / "manifest.json").write_text(json.dumps(manifest))
        self.freeze = self.root / "correction.json"
        amendment = corrected.build_correction_freeze(
            self.protocol, self.capture,
            now=datetime(2026, 12, 1, 0, 10, tzinfo=timezone.utc))
        self.freeze.write_text(json.dumps(amendment))
        self.addCleanup(setattr, engine, "PassiveExitBranch", corrected.ORIGINAL_CLASS)

    def events(self, qualifying=True):
        events = [book("rh_lighter", START + 1800 * NS),
                  book("hyperliquid", START + 1800 * NS),
                  book("rh_lighter", DECISION - 100_000_000),
                  book("hyperliquid", DECISION - 100_000_000),
                  book("hyperliquid", DECISION),
                  book("rh_lighter", DECISION + 400_000_000),
                  book("rh_lighter", DECISION + 5_300_000_000),
                  book("rh_lighter", DECISION + 5_700_000_000),
                  trade(DECISION + 7_700_000_000, DECISION + 5_500_000_000,
                        "sell" if qualifying else "buy", 100),
                  {"type": "end", "received_ns": START + 3000 * NS, "truncated": False}]
        return events

    def combined_replay(self, qualifying):
        with patch.object(original, "RhMakerModel", FixedBuyModel), \
             patch.object(original, "RhMakerSellModel", FixedSellModel):
            strict = original.replay(self.capture, self.root / "strict", self.protocol,
                                     events=deepcopy(self.events(qualifying)))
            variant = corrected.replay_corrected(self.capture, self.root / "corrected",
                        self.protocol, self.freeze, events=deepcopy(self.events(qualifying)))
        self.assertIs(engine.PassiveExitBranch, corrected.ORIGINAL_CLASS)
        self.assertEqual(strict["status"], "complete", strict["errors"])
        self.assertEqual(variant["status"], "complete", variant["errors"])
        return strict, variant

    def test_combined_original_and_corrected_boundary_and_explicit_provenance(self):
        strict, variant = self.combined_replay(True)
        def selected(result):
            return next(b for b in result["branches"] if
                        (b["tier"], b["asset"], b["budget_usd"], b["exit_policy"])
                        == ("standard", "BTC", "1000", "control10s"))
        old, new = selected(strict), selected(variant)
        self.assertEqual(old["complete_net"], "0")
        self.assertFalse(old["episodes"][0].get("execution_unknown", False))
        self.assertIsNone(new["complete_net"])
        self.assertTrue(new["episodes"][0]["execution_unknown"])
        for key in ("cash_rh_usdg", "cash_hl_usdc", "fees_rh", "fees_hl",
                    "reserve_cost", "capital_cost", "rh_position", "hl_position"):
            self.assertEqual(old[key], new[key])
        self.assertEqual(strict["schema"], original.RESULT_SCHEMA)
        self.assertEqual(variant["schema"], corrected.RESULT_SCHEMA)
        self.assertEqual(variant["implementation_variant"], corrected.VARIANT)
        self.assertEqual(len(variant["source_sha256"]), 18)
        self.assertEqual(len(variant["source_sha256_extra"]), 2)
        self.assertEqual(variant["runtime_class_override"], corrected.RUNTIME_OVERRIDE)
        self.assertTrue(variant["correction_freeze"]["frozen_after_capture_started"])
        self.assertFalse(variant["original_frozen_v1_result"])
        disk = json.loads((self.root / "corrected/analysis.json").read_text())
        self.assertEqual(disk["schema"], corrected.RESULT_SCHEMA)
        self.assertTrue((self.root / "corrected/REPORT.md").read_text().startswith(
            "# RH passive-exit retirement corrected replay"))
        self.assertEqual(json.loads((self.root / "strict/analysis.json").read_text())["schema"],
                         original.RESULT_SCHEMA)

    def test_no_qualifying_retirement_flow_preserves_original_results(self):
        strict, variant = self.combined_replay(False)
        branches = deepcopy(variant["branches"])
        for b in branches:
            b.pop("retirement_guard_revision")
            b.pop("frozen_v1_result")
        self.assertEqual(branches, strict["branches"])
        for key in ("cohort_score", "cohorts", "counts", "models", "assumptions"):
            self.assertEqual(variant[key], strict[key])

    def test_binding_restores_when_underlying_replay_raises(self):
        def failure(*args, **kwargs):
            self.assertIs(engine.PassiveExitBranch, corrected.RetirementGuardPassiveExitBranch)
            raise RuntimeError("synthetic replay failure")
        with patch.object(original, "replay", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "synthetic replay failure"):
                corrected.replay_corrected(self.capture, self.root / "failed", self.protocol, self.freeze)
        self.assertIs(engine.PassiveExitBranch, corrected.ORIGINAL_CLASS)
        self.assertFalse((self.root / "failed").exists())
        self.assertFalse(list(self.root.glob(".retirement-corrected-*")))

    def test_correction_hash_mismatch_rejects_before_override(self):
        data = json.loads(self.freeze.read_text())
        data["source_sha256_extra"][corrected.EXTRA_SOURCES[0]] = "0" * 64
        self.freeze.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "correction source hash mismatch"):
            corrected.replay_corrected(self.capture, self.root / "invalid", self.protocol, self.freeze)
        self.assertIs(engine.PassiveExitBranch, corrected.ORIGINAL_CLASS)
        self.assertFalse((self.root / "invalid").exists())

    def test_original_protocol_hash_and_both_freeze_deadlines_are_enforced(self):
        data = json.loads(self.freeze.read_text())
        data["protocol_sha256"] = "0" * 64
        self.freeze.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "original protocol/hash mismatch"):
            corrected.verify_correction(self.freeze, self.protocol, self.capture)
        data["protocol_sha256"] = original.digest(self.protocol)
        self.freeze.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "actual holdout"):
            corrected.verify_correction(self.freeze, self.protocol, self.capture,
                cutoff_ns=original._utc_ns(data["frozen_at"]))
        with self.assertRaisesRegex(ValueError, "conservative holdout"):
            corrected.build_correction_freeze(self.protocol, self.capture,
                now=datetime(2026, 12, 1, 0, 29, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
