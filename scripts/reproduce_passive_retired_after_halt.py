"""Post-capture synthetic diagnosis only; does not replay or modify frozen sources.

Run with: python -m scripts.reproduce_passive_retired_after_halt
The JSON printed on stdout retains every synthetic callback and the frozen
source inventory. A direct guard call is an isolated diagnostic probe, not a
proposed replay patch or changed result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from scripts.analyze_rh_passive_exit import _complete_net
from scripts.rh_maker_engine import Config, NS
from scripts.rh_passive_exit_engine import PassiveExitBranch
from scripts.rh_passive_retirement_guard import RetirementGuardPassiveExitBranch
from tests.test_rh_maker_engine import DIAG, META, T, book, trade


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "reports/rh-passive-exit-v1-restart/retirement-correction-freeze.json"


def frozen_sources() -> dict[str, str]:
    freeze = json.loads(FREEZE.read_text())
    expected = {**freeze["source_sha256"], **freeze["source_sha256_extra"]}
    actual = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
              for path in expected}
    if actual != expected:
        raise ValueError("frozen source inventory mismatch")
    return actual


def snapshot(branch) -> dict:
    episode = branch.episodes[0]
    return {
        "branch_unknown_reason": branch.unknown_reason,
        "portfolio_complete_net": branch.summary()["complete_net"],
        "closed_episodes": len(branch.episodes),
        "retired_passive_asks": len(branch._retired_passive),
        "episode_execution_unknown": bool(episode.get("execution_unknown")),
        "episode_execution_unknown_reason": episode.get("execution_unknown_reason"),
        "cohort_complete_net": (None if _complete_net(episode) is None
                                else str(_complete_net(episode))),
        "rh_position": str(branch.rh_pos), "hl_position": str(branch.hl_pos),
        "cash_rh": str(branch.cash_rh), "cash_hl": str(branch.cash_hl),
        "fees_rh": str(branch.fees_rh), "fees_hl": str(branch.fees_hl),
    }


def reproduce(cls, prior_halt: bool) -> dict:
    branch = cls(Config("BTC", Decimal("1000"), "fixed_best"), META,
                 exit_policy="passive_best10s")
    callbacks = []

    def process(event, diag=None):
        callbacks.append({"event": event, "quote_diag": diag})
        branch.process(event, diag)

    def refresh(offset):
        process(book("rh_lighter", T + offset))
        process(book("hyperliquid", T + offset))

    process(book("rh_lighter", T))
    process(book("hyperliquid", T), DIAG)
    process(book("rh_lighter", T + 400_000_000))
    process(trade(T + 500_000_000, qty=1.5, tid="entry"))
    process(book("hyperliquid", T + 700_000_000))
    process(book("rh_lighter", T + 900_000_000))
    refresh(2_800_000_000)
    refresh(3_200_000_000)
    process(trade(T + 3_300_000_000, side="buy", price=100.4,
                  qty=10.5, tid="partial-exit"))
    process(book("hyperliquid", T + 3_500_000_000))
    for offset in (4_500_000_000, 6 * NS, 7_500_000_000, 9 * NS,
                   10_500_000_000, 12 * NS):
        refresh(offset)
    assert branch.unknown_reason is None
    assert len(branch.episodes) == len(branch._retired_passive) == 1
    assert branch.rh_pos == branch.hl_pos == 0
    before = snapshot(branch)
    old = branch._retired_passive[0]
    tombstone = {
        "episode_number": old.episode_number, "price": str(old.price),
        "remaining": str(old.remaining), "activation_due_ns": old.activation_due_ns,
        "cancel_due_ns": old.cancel_due_ns, "retired_ns": old.retired_ns,
        "seen_ids": sorted(old.seen_ids),
    }
    if prior_halt:
        process(book("hyperliquid", T + 12_010_000_000), DIAG)
        assert branch.quote is not None
        process({**book("rh_lighter", T + 12_200_000_000), "generation": "changed"})
        assert branch.unknown_reason == "book_generation_changed_during_obligation"
    late = trade(T + 12_300_000_000, source=T + 3_500_000_000,
                 side="buy", price=100.4, qty=0.01, tid="genuine-late-passive")
    process(late)
    after = snapshot(branch)
    assert after["portfolio_complete_net"] is None
    assert after["episode_execution_unknown"] is (not prior_halt)
    economic_fields = ("rh_position", "hl_position", "cash_rh", "cash_hl", "fees_rh", "fees_hl")
    assert all(after[key] == before[key] for key in economic_fields)
    # Diagnose reachability of the already existing guard on a disposable
    # branch. This is deliberately outside process and outside any replay.
    assert branch._retired_flow_check(late)
    probe = snapshot(branch)
    assert probe["episode_execution_unknown"] and probe["cohort_complete_net"] is None
    assert all(probe[key] == after[key] for key in economic_fields)
    return {"runtime_class": f"{cls.__module__}.{cls.__name__}",
            "prior_halt": prior_halt, "callbacks": callbacks,
            "retired_passive_ask": tombstone, "before": before,
            "after_process": after, "isolated_existing_guard_probe": probe}


def main() -> None:
    before = frozen_sources()
    cases = [reproduce(cls, halt) for cls in
             (PassiveExitBranch, RetirementGuardPassiveExitBranch) for halt in (False, True)]
    assert frozen_sources() == before
    report = {
        "schema": "rh-passive-retired-after-halt-synthetic-diagnosis-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "post_capture_diagnosis": True, "historical_replay_run": False,
        "frozen_sources_unchanged": True, "source_sha256": before,
        "reproducer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "test_helper_sha256": hashlib.sha256((ROOT / "tests/test_rh_maker_engine.py").read_bytes()).hexdigest(),
        "synthetic_metadata": META, "cases": cases,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
