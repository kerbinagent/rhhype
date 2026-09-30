# Separate retirement correction for passive-exit v1

This is a separately labeled implementation amendment for the restarted passive-exit capture. It preserves the original frozen v1 replay as its own result. The amendment was prepared after capture launch, during calibration, and must be frozen before holdout begins. It is a correction to execution classification and the resulting admission halt; it does not change economic assumptions or introduce an ACK scenario.

## The defect and correction

The frozen entry guard checks retired quotes before the base engine's callback invokes `tick(receipt_ns)`. An activated, canceled entry quote with remaining quantity can retire inside that tick. The incoming delayed trade then sees no live quote, while the guard has not seen the newly created tombstone. The frozen predicate also requires `receipt > retired_ns`, so merely rechecking the same receipt does not catch the event. The result can be a falsely known no-flow episode with zero cash contribution.

The separately reviewed [RetirementGuardPassiveExitBranch](../scripts/rh_passive_retirement_guard.py) accepts qualifying entry flow at `receipt == retired_ns`, then checks again after inherited processing. If a tombstone matches, it reenters the inherited guard's evidence path. That path marks the affected finalized episode `execution_unknown` and returns before another tick, trade attribution or diagnostic. It fabricates no inventory, fee, fill or cashflow. It also flags the episode when an unrelated audit limit already made the branch unknown during retirement; marking only the branch would be insufficient because cohort scoring inspects each closed episode.

Execution unknown halts future branch activity and can block later shared group admissions. Consequently the corrected variant can have different later admissions and realized counterfactual economic paths even though price selection, quantity, queue assumptions, public activation/cancel confirmation, hedge mechanics, fees, capital and reserve definitions are unchanged. Neither known-zero results from frozen v1 nor unknown results from the corrected variant should be overwritten to force agreement. Under frozen timing, entry quote source intervals do not overlap: a later entry activates after the prior quote's retirement, which is at least two seconds after its cancel due time. A single source timestamp therefore cannot qualify for multiple retired entry quotes in this study.

## Freeze during calibration, with an earlier conservative deadline

The restarted [original protocol](../reports/rh-passive-exit-v1-restart/protocol.json) was frozen at **2026-09-30 02:52:37.908796 UTC**. Its verifier requires actual capture start to be at or after that time. Adding the fixed 1,800-second calibration gives **03:22:37.908796 UTC** as a conservative lower bound on the actual holdout cutoff. This is not a claimed capture start or the actual cutoff. The [launcher record](../reports/rh-passive-exit-v1-restart/launch.json) says launch was 02:52:57.775724 UTC; the stopped manifest will supply actual capture start and cutoff.

The [wrapper](../scripts/replay_passive_retirement_corrected.py) provides a `freeze` command that stamps the current UTC time itself, verifies every original source hash, and refuses to freeze at or after that conservative bound. No CLI timestamp can backdate it. Its amendment records the original protocol hash and all 18 original source hashes, plus the new guard and wrapper hashes. It explicitly discloses that this is an amendment to an already launched capture. It does not represent an unchanged before-capture protocol.

```bash
.venv/bin/python scripts/replay_passive_retirement_corrected.py freeze
```

Defaults identify capture `data/raw/rh-passive-exit-v1/20260930T0252Z`, original protocol `reports/rh-passive-exit-v1-restart/protocol.json`, and amendment destination `reports/rh-passive-exit-v1-restart/retirement-correction-freeze.json`. The amendment destination must not already exist. Freeze the reviewed code once, then preserve those source bytes. The timestamp and hashes in that JSON, once created, are the evidence of the correction freeze; this note does not substitute for it.

## Replay after capture stops

```bash
.venv/bin/python scripts/analyze_rh_passive_exit.py replay \
  --capture data/raw/rh-passive-exit-v1/20260930T0252Z \
  --protocol reports/rh-passive-exit-v1-restart/protocol.json \
  --out data/derived/rh-passive-exit-v1-restart

.venv/bin/python scripts/replay_passive_retirement_corrected.py replay
```

The original strict result and corrected result use distinct new output directories. The wrapper defaults to **`data/derived/rh-passive-exit-v1-restart-corrected`**. It verifies the original stopped-capture protocol, metadata and source inventory, amendment identity, both new source hashes, original protocol hash, and the amendment timestamp against both the conservative bound and actual manifest holdout cutoff. A mismatch fails before applying the runtime override. It rechecks sources and the unchanged amendment after replay.

In a single isolated replay process, a context manager temporarily binds `scripts.rh_passive_exit_engine.PassiveExitBranch` to `RetirementGuardPassiveExitBranch`. The frozen coordinator imports that binding inside `replay`, so this selects the reviewed correction without changing any of the 18 frozen files. The original class binding is restored in `finally`, including replay exceptions. The binding is process-global; run this wrapper as its own CLI process rather than concurrently with another replay in the same Python interpreter.

Final artifacts publish only after the result has been annotated in temporary storage. The corrected JSON uses schema `rh-passive-exit-replay-retirement-corrected-v1`, carries `implementation_variant`, the actual runtime class override, `source_sha256_extra`, correction freeze hash/time, original protocol hash, and actual capture start/holdout cutoff. Original source hashes remain available as `source_sha256`. `original_frozen_v1_result` is false. The regenerated report begins **RH passive-exit retirement corrected replay** and states the calibration-time amendment. A temporary original-format coordinator result is never published as the final corrected artifact.

## Verification and limits

[Five wrapper tests](../tests/test_replay_passive_retirement_corrected.py) run combined original and corrected synthetic replays on the same declared event stream. They verify the known-zero versus execution-unknown boundary, identical cash/fees/positions, equivalent results when the qualifying case is absent, explicit corrected provenance on disk, restoration on an injected replay exception, new-source/original-protocol hash mismatches, and both freeze deadlines. Synthetic models only establish replay plumbing and behavior; they make no market request and are not empirical strategy evidence. [Retirement review tests](../tests/test_passive_retirement_review.py) additionally cover the normal-config audit-limit case, cancellation endpoint, reconnect generation, repeated evidence and nonqualifying flow. The original frozen safety test remains an intentional expected failure documenting the defect.

This amendment provides a classified corrected diagnostic alongside the unchanged frozen result. Public queue attribution remains conditional, private executions remain unobserved, and an unknown episode remains unknown. No full market-capture replay was launched while implementing or testing this wrapper.
