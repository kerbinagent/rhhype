#!/usr/bin/env python3
"""Separately frozen retirement correction; never relabel frozen v1 results."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import analyze_rh_passive_exit as original
from scripts import rh_passive_exit_engine as engine
from scripts.rh_passive_retirement_guard import RetirementGuardPassiveExitBranch

VARIANT = "entry-same-receipt-retirement-corrected-v1"
FREEZE_SCHEMA = "rh-passive-retirement-correction-freeze-v1"
RESULT_SCHEMA = "rh-passive-exit-replay-retirement-corrected-v1"
EXTRA_SOURCES = ("scripts/rh_passive_retirement_guard.py",
                 "scripts/replay_passive_retirement_corrected.py")
ORIGINAL_CLASS = engine.PassiveExitBranch
DEFAULT_PROTOCOL = ROOT / "reports/rh-passive-exit-v1-restart/protocol.json"
DEFAULT_CAPTURE = ROOT / "data/raw/rh-passive-exit-v1/20260930T0252Z"
DEFAULT_FREEZE = ROOT / "reports/rh-passive-exit-v1-restart/retirement-correction-freeze.json"
DEFAULT_OUT = ROOT / "data/derived/rh-passive-exit-v1-restart-corrected"
RUNTIME_OVERRIDE = {
    "module_binding": "scripts.rh_passive_exit_engine.PassiveExitBranch",
    "original_class": "scripts.rh_passive_exit_engine.PassiveExitBranch",
    "actual_class": "scripts.rh_passive_retirement_guard.RetirementGuardPassiveExitBranch",
    "mechanism": "temporary module binding during original replay; restored in finally",
}


def verified_sources(protocol_path: Path) -> dict:
    protocol = original._bounded_json(protocol_path)
    expected = protocol.get("source_sha256")
    if protocol.get("schema") != original.SCHEMA or not isinstance(expected, dict):
        raise ValueError("original frozen protocol required")
    if set(expected) != set(original.REQUIRED_SOURCES):
        raise ValueError("incomplete original source inventory")
    for name, claimed in expected.items():
        if original.digest(original._source_path(name)) != claimed:
            raise ValueError(f"source hash mismatch: {name}")
    return protocol


def build_correction_freeze(protocol_path: Path, capture: Path, *, now: datetime | None = None) -> dict:
    """CLI supplies actual UTC now; explicit clock injection is for tests only."""
    protocol_path, capture = Path(protocol_path), Path(capture)
    protocol = verified_sources(protocol_path)
    frozen_at = (datetime.now(timezone.utc) if now is None else now).isoformat()
    frozen_ns = original._utc_ns(frozen_at)
    # The original verifier guarantees capture start >= original freeze. This
    # deadline is earlier than the eventual actual holdout cutoff, never later.
    deadline = original._utc_ns(protocol["frozen_at"]) + 1800 * original.NS
    if not original._utc_ns(protocol["frozen_at"]) <= frozen_ns < deadline:
        raise ValueError("correction must freeze before conservative holdout lower bound")
    return {
        "schema": FREEZE_SCHEMA, "implementation_variant": VARIANT,
        "frozen_at": frozen_at,
        "protocol_sha256": original.digest(protocol_path),
        "protocol_frozen_at": protocol["frozen_at"],
        "source_sha256": protocol["source_sha256"],
        "source_sha256_extra": {name: original.digest(original._source_path(name)) for name in EXTRA_SOURCES},
        "expected_capture": str(capture.resolve()),
        "conservative_holdout_lower_bound_ns": deadline,
        "deadline_definition": "original protocol freeze + 1800s; conservative lower bound, not actual capture start/cutoff",
        "runtime_class_override": RUNTIME_OVERRIDE,
        "scope": "retired entry episode execution classification and resulting admission halt only; economic assumptions unchanged",
        "timing_disclosure": "correction is a calibration-time amendment to an already launched capture, not the original before-capture freeze",
    }


def verify_correction(freeze_path: Path, protocol_path: Path, capture: Path, *, cutoff_ns: int | None = None) -> dict:
    protocol = verified_sources(protocol_path)
    freeze = original._bounded_json(freeze_path)
    if (freeze.get("schema") != FREEZE_SCHEMA
            or freeze.get("implementation_variant") != VARIANT
            or freeze.get("runtime_class_override") != RUNTIME_OVERRIDE):
        raise ValueError("unexpected correction implementation")
    if (freeze.get("protocol_sha256") != original.digest(protocol_path)
            or freeze.get("source_sha256") != protocol["source_sha256"]
            or freeze.get("protocol_frozen_at") != protocol["frozen_at"]):
        raise ValueError("correction original protocol/hash mismatch")
    if freeze.get("expected_capture") != str(Path(capture).resolve()):
        raise ValueError("correction capture identity mismatch")
    expected = freeze.get("source_sha256_extra")
    if not isinstance(expected, dict) or set(expected) != set(EXTRA_SOURCES):
        raise ValueError("incomplete correction source inventory")
    for name, claimed in expected.items():
        if original.digest(original._source_path(name)) != claimed:
            raise ValueError(f"correction source hash mismatch: {name}")
    lower = original._utc_ns(protocol["frozen_at"])
    deadline = lower + 1800 * original.NS
    frozen_ns = original._utc_ns(freeze.get("frozen_at"))
    if freeze.get("conservative_holdout_lower_bound_ns") != deadline or not lower <= frozen_ns < deadline:
        raise ValueError("correction freeze misses conservative holdout bound")
    if cutoff_ns is not None and frozen_ns >= cutoff_ns:
        raise ValueError("correction freeze must precede actual holdout cutoff")
    return freeze


@contextmanager
def corrected_branch_binding():
    """Use only in one isolated replay process; module bindings are global."""
    if engine.PassiveExitBranch is not ORIGINAL_CLASS:
        raise RuntimeError("passive branch binding already overridden")
    engine.PassiveExitBranch = RetirementGuardPassiveExitBranch
    try:
        yield
    finally:
        engine.PassiveExitBranch = ORIGINAL_CLASS


def corrected_report(result: dict) -> str:
    body = original._report(result)
    heading = "# RH passive-exit retirement corrected replay"
    body = heading + body[body.index("\n"):]
    disclosure = (
        f"\n\n**Separate corrected implementation: `{VARIANT}`.** Original v1 remains a separate result. "
        "The runtime branch binding uses `RetirementGuardPassiveExitBranch`; this amendment was frozen "
        "during the already launched capture, before its holdout cutoff. Qualifying retired-entry flow "
        "makes execution unknown without inventing fills or zero outcomes. Admission can stop earlier "
        "after unknown; price, queue, ACK, fees, quantity and economic assumptions retain original v1 definitions.\n\n"
    )
    return body.replace("\n", disclosure, 1)


def replay_corrected(capture: Path, out: Path, protocol_path: Path, freeze_path: Path, *, events=None) -> dict:
    capture, out = Path(capture), Path(out)
    # Preserve every original source, metadata and stopped-capture check.
    _, _, start, cutoff, _ = original.verify_protocol(protocol_path, capture)
    freeze = verify_correction(freeze_path, protocol_path, capture, cutoff_ns=cutoff)
    freeze_hash = original.digest(Path(freeze_path))
    if out.exists():
        raise ValueError("corrected output must be a new directory")
    if out.resolve() == capture.resolve():
        raise ValueError("corrected output cannot replace capture")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after annotation. The original implementation's intermediate
    # result stays in temporary storage and never appears as a final variant.
    with tempfile.TemporaryDirectory(prefix=".retirement-corrected-", dir=out.parent) as scratch:
        staged = Path(scratch) / "result"
        with corrected_branch_binding():
            result = original.replay(capture, staged, protocol_path, events=events)
        verify_correction(freeze_path, protocol_path, capture, cutoff_ns=cutoff)
        if original.digest(Path(freeze_path)) != freeze_hash:
            raise ValueError("correction freeze changed during replay")
        result.update({
            "schema": RESULT_SCHEMA, "original_result_schema": original.RESULT_SCHEMA,
            "implementation_variant": VARIANT,
            "runtime_class_override": RUNTIME_OVERRIDE,
            "source_sha256_extra": freeze["source_sha256_extra"],
            "correction_freeze": {
                "path": str(Path(freeze_path)), "sha256": freeze_hash,
                "frozen_at": freeze["frozen_at"],
                "conservative_holdout_lower_bound_ns": freeze["conservative_holdout_lower_bound_ns"],
                "actual_capture_started_ns": start, "actual_holdout_cutoff_ns": cutoff,
                "frozen_after_capture_started": original._utc_ns(freeze["frozen_at"]) >= start,
                "disclosure": freeze["timing_disclosure"],
            },
            "original_frozen_v1_result": False,
        })
        report = corrected_report(result).encode()
        if len(report) > 1_000_000:
            raise ValueError("corrected report byte cap")
        original._write_json(staged / "analysis.json", result, original.SUMMARY_CAP - len(report))
        (staged / "REPORT.md").write_bytes(report)
        if out.exists():
            raise ValueError("corrected output appeared during replay")
        staged.rename(out)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="freeze correction sources now, before conservative holdout bound")
    run = sub.add_parser("replay", help="replay stopped capture as explicitly corrected variant")
    for command in (freeze, run):
        command.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
        command.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
        command.add_argument("--correction-freeze", type=Path, default=DEFAULT_FREEZE)
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        data = build_correction_freeze(args.protocol, args.capture)
        args.correction_freeze.parent.mkdir(parents=True, exist_ok=True)
        with args.correction_freeze.open("x") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"correction_freeze": str(args.correction_freeze), "frozen_at": data["frozen_at"]}))
        return 0
    result = replay_corrected(args.capture, args.out, args.protocol, args.correction_freeze)
    print(json.dumps({"out": str(args.out), "status": result["status"], "variant": VARIANT, "errors": result["errors"]}))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
