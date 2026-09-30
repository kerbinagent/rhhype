# Exploratory post-capture ACK replay wrapper

The [separate ACK wrapper](../scripts/replay_passive_ack_exploratory.py) prepares and, only with an explicit replay flag, runs **one exploratory post-capture model** on the completed restarted RH passive-exit capture. It is separate from the original strict and retirement-corrected results. The model was prepared after capture launch while frozen readouts were being produced; no prospective or pre-holdout freeze is claimed. A source snapshot describes the implementation used for a diagnostic and is not ACK execution evidence or authorization.

Default invocation prints a plan for `base` and `plus200` without reading the capture, opening sockets, replaying events, creating output, or changing an engine binding:

```bash
.venv/bin/python scripts/replay_passive_ack_exploratory.py
```

`base` uses the already normalized frozen configuration's maker/cancel delays: Standard 300 ms and Premium 100 ms. `plus200` adds 200 ms to **both** maker and cancel delays: Standard 500 ms and Premium 300 ms. The ACK class clones the normalized configuration without invoking tier normalization a second time. RH taker and HL IOC timing, price/target selection, lot/quantity rules, FIFO accounting, fills, fees, reserve, capital, funding, and exit obligations remain delegated to inherited economic methods.

The changed execution model combines deterministic activation/cancel clocks, ordered timers and obligation coverage checks, preceding raw RH depth anchors and late revisions, an explicit native-trade-ID stability assumption and bounded identity evidence, and outer historical guards that continue checking old execution evidence after an unrelated halt. It is therefore a **combined execution-model sensitivity**. Differences from strict or corrected replay do not identify an isolated latency effect or causal profit improvement. See the [ACK model design](passive-ack-scenarios-design.md) and [passive retired-evidence followup](passive-retired-evidence-followup.md).

Acceptance and cancellation are assumed at their due clocks; they are not observed private acknowledgments. Queue ahead uses the last previously received raw RH same-price depth, with no cancellation credit. The book received on a later processing callback cannot supply the preceding timer anchor. Source-time activation ties win under the model, while cancellation ties remain unknown. Timer effective time and processing receipt are recorded separately. The public trade receipt starts the inherited hedge/contingent-buy latency, which declares a private-notification approximation. Native trade IDs are assumed unique and stable across transport generations, so identical economic signatures retransmitted on another connection are duplicates. Conflicting identity, exhausted evidence capacity, coverage gaps, and qualifying historical contradictions preserve unknown execution.

A due-time post-only proxy rejection conservatively ends execution unknown and preserves any existing passive-exit inventory; it cannot become a completed no-flow zero.

An authorized diagnostic uses an explicit single scenario and an explicit new output directory. Run each scenario in its own process and ledger:

```bash
.venv/bin/python scripts/replay_passive_ack_exploratory.py --replay \
  --scenario base \
  --out data/derived/rh-passive-exit-v1-restart-ack-exploratory-base

.venv/bin/python scripts/replay_passive_ack_exploratory.py --replay \
  --scenario plus200 \
  --out data/derived/rh-passive-exit-v1-restart-ack-exploratory-plus200
```

The root operator decides whether the empirical diagnostic is warranted after inspecting the frozen readouts. Preparing this wrapper and its synthetic tests does not launch either command. The defaults reference capture `data/raw/rh-passive-exit-v1/20260930T0252Z`, restarted `reports/rh-passive-exit-v1-restart/protocol.json`, and the completed strict/corrected `analysis.json` files. Those readouts are required provenance references, not permission or a reused correction freeze for the ACK model. Overrides are available for `--capture`, `--protocol`, `--strict-analysis`, and `--corrected-analysis`.

Before calling the frozen coordinator, the wrapper requires completed, error-free, `verified_capture` strict and corrected readout references for that same capture, raw/manifest/metadata/protocol hashes, and timeline. Original source hashes and economic/calibration metadata must agree; the corrected reference's two extra hashes still match its frozen code. It verifies the original 18-file protocol and complete duration-limit capture, hashes the actual bounded raw gzip, and snapshots **21 actual implementation dependencies**: original 18, retirement guard, ACK class, and this wrapper. Source files are capped at 2,000,000 bytes each and 16,000,000 bytes combined; protocol/reference JSON and raw replay use inherited bounds. The raw archive is limited to 384,000,000 bytes, each readout to 32,000,000 bytes. The original decoder enforces decoded payload and line/record limits during actual replay. No private endpoint is available.

The isolated context temporarily replaces only `scripts.rh_passive_exit_engine.PassiveExitBranch` with a factory that constructs `AssumedAckPassiveExitBranch(..., scenario=...)`. The original coordinator still constructs the same 128 tier/asset/budget/exit-policy branches. Nested bindings are refused, and the original class binding is restored in `finally`, including exceptions. Economic methods are not monkeypatched. Each branch remains an independent correlated counterfactual; nets from different branches or scenarios must not be summed.

The coordinator writes into a private temporary directory. The wrapper requires a complete result, the actual 128 ACK scenario branch labels, a verified nontruncated terminal event, and capture/protocol/timeline agreement. Injected event streams cannot publish a capture result. It rechecks sources, stopped input hashes, and readout references before publishing. The final result has schema **`rh-passive-exit-replay-ack-exploratory-postcapture-v1`**, selected scenario and effective delays, actual runtime factory, private-ACK/native-ID assumptions, active timing assumptions, inherited original coordinator assumptions, before/after dependency hashes, and an explicit **EXPLORATORY POST-CAPTURE MODEL** disclosure. Original strict/corrected schemas remain references. No original-format intermediate result is published as the final artifact.

The final report and JSON are validated before an atomic directory rename. Outputs are capped by the original 32,000,000-byte summary budget, with a 1,000,000-byte report maximum; the inherited streamed audit is capped at 96,000,000 bytes. Existing directories, dangling symlinks, and outputs overlapping the capture, protocol directory, or strict/corrected reference directories are refused. These protected artifacts are not edited. A failed, capped, mismatched, or incomplete replay publishes no final exploratory directory.

Completed scenario net remains conditional on unobserved execution assumptions. Unknown execution, funding, or open obligations retain null complete net. The inherited primary same-entry contrast is descriptive within that scenario's own admissions; scenario timing and guard changes can alter later admissions and exposure. The wrapper reports `causal_profit_improvement` and `summed_branch_portfolio_net` as null. It does not promote a scenario's outcome into a prospective v1 finding, validated private fill, guaranteed profit bound, or current strategy recommendation.

Synthetic wrapper verification:

```bash
.venv/bin/python -m unittest tests.test_replay_passive_ack_exploratory -v
```

Nine fixtures test dry-default behavior, both final tier delay profiles, the actual reviewed ACK class factory for all 128 configurations, exploratory staged schema/labels, original binding restoration and nested-binding refusal, source/reference changes, raw/readout provenance rejection, injected/terminal/scenario-label publication refusal, source/report caps, protected path overlaps, and dangling symlinks. The coordinator is mocked for those publication tests; no market-feed capture replay is performed. The ACK class's separate focused tests exercise its causal clock/queue/history behavior. Original frozen 18/20 source bytes remain unchanged.
