# Separate exploratory ACK readout

[analyze_passive_ack_readout.py](../scripts/analyze_passive_ack_readout.py) reads **four completed artifacts**: frozen strict, frozen retirement-corrected, exploratory ACK `base`, and exploratory ACK `plus200`. Preparing this helper and its fixtures does not inspect partial scenario outcomes, decode market-feed records, replay a strategy, start a capture, or change any of the 21 active ACK replay dependencies.

After both scenario outputs finish, the root operator can run:

```bash
.venv/bin/python scripts/analyze_passive_ack_readout.py
```

Defaults read the strict/corrected restarted `analysis.json` files and `data/derived/rh-passive-exit-v1-restart-ack-exploratory-base/analysis.json` and `...-plus200/analysis.json`. They create a new `data/derived/rh-passive-exit-v1-restart-ack-readout` directory. `--strict`, `--corrected`, `--base`, `--plus200`, `--protocol`, `--correction-freeze`, and `--out` allow explicit overrides. An absent, incomplete, errored, or injected-event artifact fails before stopped source inputs are read. Existing outputs, dangling symlinks, and output paths overlapping input directories are refused.

The original strict/corrected comparison keeps its schemas and trust checks. This helper independently requires the distinct exploratory ACK schema, exact `base`/`plus200` scenario IDs and tier delays, actual runtime factory, native-ID/ACK assumptions, active and inherited timing/economic assumptions, original 18-source and ACK 21-source inventories, identical before/after source snapshots, verified terminal hashes, same capture/protocol/metadata/calibration/timeline, and exact completed strict/corrected reference paths and hashes. It verifies the stopped manifest/raw gzip hash and original/corrected source provenance through the existing comparison helpers without decoding the public feed. The output records hashes for this helper, its tests and method document, and the shared comparison code. Source and input hashes are checked again before publication.

`readout.json` contains all 128 independent branch rows with four run snapshots. Each snapshot has candidate and admission denominators, closed/known/unknown episodes, known no-flow versus attributed-flow counts, execution/funding unknown counts, nullable complete portfolio net, partial closed-episode contribution, first halt and its reason, quote opportunity time, aggregate delta/gross inventory exposure, final positions, and raw engine counters. Target-abstain, fallback, cap, ACK, activation, cancellation, retirement, and hedge counters are retained alongside coverage and execution unknown reasons. This makes unchanged target ceilings and abstention visible alongside execution-model attrition.

First-halt reasons are grouped into explicit activation-window, cancel-window, retirement-evidence, coverage/generation/clock, anchor/post-only, native-ID, cap, execution-rule/depth/obligation, and other categories. These categories describe a branch's recorded first halt; they are not mutually causal decompositions of differences between runs. Episode execution-unknown reasons are counted separately because later evidence can affect old episodes after an earlier first halt. Known no-flow and attributed-flow counts come from actual episode flags and maker-attributed quantity, not aggregate cash sign.

ACK contribution and completed totals are labeled **conditional_known**. They depend on deterministic private ACK clocks, carried-forward queue assumptions, native-ID stability, public information delay, coverage checks, and outer historical evidence guards. They are not validated private executions. The frozen strict/corrected guard caveat remains visible: retained passive asks after a halt or incomplete retention make raw closed-episode contribution provisional and validated contribution undefined. The reviewed ACK class runs outer historical checks after an unrelated halt, so that precise frozen-parent bypass flag is not automatically applied to an intact ACK artifact; incomplete ACK retention still withholds conditional contributions.

Six pairwise alignments are provided for every branch: strict/corrected, strict/base, strict/plus200, corrected/base, corrected/plus200, and base/plus200. They record common admitted cohort IDs, actual full-entry signature matches, reported known full-entry matches, and admissions present in only one run. A match count is withheld if either model has incomplete retention or a required frozen-parent historical adjudication. Unmatched cohort rows record decision, known episode decision/flat, and first-full-hedge times, plus execution-unknown classification. The primary Standard XAG $1,000 control10s and passive_target10s branches have a dedicated view.

Episode decision-to-flat intervals are observation intervals, not filled inventory exposure. These summaries contain aggregate branch delta/gross exposure but cannot allocate it to common or unmatched cohorts. The helper therefore leaves common/unmatched inventory exposure null and explicitly records that allocation is unavailable. It does not invent exposure from an episode count or allocate aggregate exposure in proportion to admissions.

Changes across ACK runs combine assumed clocks with coverage checks, raw anchor revisions, native-ID evidence, and outer historical guards. Different fills, halts, or later admissions can change economic paths. Shared decision IDs alone do not prove equal entries; identical full-entry signatures alone do not establish a causal ACK latency effect. The helper supplies no causal profit-improvement statistic and never sums correlated branches or scenarios into a portfolio.

Each of the four input JSON files is capped at 32,000,000 bytes. Output JSON is capped at 32,000,000 bytes and report at 1,000,000 bytes. Cohorts remain capped at 20,000 per run, branches at exactly 128, alignments at exactly 768 rows, and cumulative retained alignment cohort memberships at 480,000. All output is assembled and checked before creating a final directory; exceeding a bound publishes no partial readout.

Synthetic checks:

```bash
.venv/bin/python -m unittest tests.test_analyze_passive_ack_readout -v
```

The tests use generated completed artifact fixtures only. They check exact schemas/scenario IDs/native-ID and timing assumptions, source/reference hash mismatch, refusal of incomplete/injected/unknown-total claims, six cohort alignments, common full-entry matches and unmatched admissions, target/cap counters and coverage categories, frozen-parent withholding versus conditional ACK semantics, exposure allocation limits, and bounded output/no overwrite behavior.
