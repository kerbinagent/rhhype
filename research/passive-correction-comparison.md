# Strict and retirement-corrected replay comparison

The [offline comparison utility](../scripts/analyze_passive_correction_comparison.py) compares the original strict passive-exit v1 output with the separately frozen [retirement correction](passive-retirement-correction.md). It is prepared for use **after both replays finish**. Creating and testing this utility reads synthetic artifacts only; it does not inspect the running raw capture, holdout events, or empirical results.

The inputs are `data/derived/rh-passive-exit-v1-restart/analysis.json` and `data/derived/rh-passive-exit-v1-restart-corrected/analysis.json`. The command refuses missing, incomplete, errored, mislabeled, or injected-test-event results before opening stopped source artifacts. Each input is limited to 32,000,000 bytes. Both must claim complete `verified_capture` provenance and a verified, nontruncated end event.

After these gates, it verifies the original protocol, all 18 original frozen source hashes, stopped manifest/timeline/metadata, actual raw gzip SHA-256, and agreement between result and terminal hashes. It hashes compressed bytes without decoding public feed records. The corrected result must additionally identify its actual runtime class, variant, two extra source hashes, original schema, and correction freeze hash/time. The verifier checks all 20 frozen source files and the correction deadline against both its conservative bound and actual holdout cutoff. Assumptions, metadata, calibration models, capture identity, timeline, and original protocol must match between results. This utility changes none of those sources.

Every one of the 128 independent ledgers appears side by side in `comparison.json` and `REPORT.md`. For each branch, the JSON reports retained candidate cohort count, admitted cohort count, closed episodes, known/unknown episodes, actual execution-unknown and funding-unknown counts, admitted episodes without a closed result, attributed-entry-flow count, and engine counters. It shows known closed fee-only and stressed contributions alongside the nullable complete portfolio net. It also shows first unknown/halt time, unknown reason, effective quote opportunity time, final positions, delta/gross inventory, and accumulated exposure. These amounts and exposures refer to each replay's own admission history.

Admission denominators are recomputed from actual `cohorts` rows; each closed episode must identify an admitted cohort of its own branch. The utility recomputes the frozen cohort score and rejects summaries that disagree with the actual episodes or admissions. Known closed contribution includes only episodes for which funding and execution remain known. A closed zero-cash episode later marked `execution_unknown` contributes **no known episode value**; its contribution is undefined, and the corresponding total portfolio must remain unknown. The sum of other known closed episodes may still be zero or positive; that partial contribution is never used to replace the unknown total.

Shared cohort IDs identify decisions present in both replays. Each group reports these IDs, admission-map changes on shared decisions, and strict-only/corrected-only later cohorts with timestamps and admission maps. Each branch reports shared admitted IDs and admissions present in only one variant. Actual changes to an episode's `execution_unknown` classification are listed with the original/corrected episode number, reason, known contribution or null, recorded cash, and retired-flow evidence. Shared known episodes with identical full-entry signatures are counted separately. The utility reports no cross-variant profit gain even for that subset.

The primary Standard XAG $1,000 control10s versus passive_target10s comparison has a dedicated JSON view containing both branches. It preserves each replay's own same-entry primary contrast from the frozen cohort scoring, including its own sample denominator. It does not subtract those contrast summaries to claim that the correction improved profitability. A classification correction can halt one branch or its shared admission group sooner, changing later trades and observation time; net from unequal admission histories or observation time is not a causal profit comparison. The 128 correlated counterfactual branches are never summed into one portfolio.

After both stopped replays have published:

```bash
.venv/bin/python scripts/analyze_passive_correction_comparison.py
```

Defaults use the restarted protocol and its retirement-correction freeze and create a **new** `data/derived/rh-passive-exit-v1-restart-comparison` directory. Overrides are available through `--strict`, `--corrected`, `--protocol`, `--correction-freeze`, and `--out`. The complete JSON and report are assembled and checked against output caps before creating that directory. JSON output is limited to 32,000,000 bytes, report output to 1,000,000 bytes, cohort retention to 20,000, and episode retention to 2,000 per branch. An exceeded bound fails without publishing a partial comparison.

Offline fixture verification:

```bash
.venv/bin/python -m unittest tests.test_analyze_passive_correction_comparison -v
```

The tests cover a false known zero becoming an unknown episode and portfolio, changed later admission denominators, shared and unmatched cohort IDs, first halt/exposure changes, actual-episode score consistency, all 128 branch ledgers, original/corrected capture/protocol/assumption mismatches, missing or injected inputs, corrected variant/source/freeze provenance, raw-byte hash rejection, and output-cap refusal before publication. The fixtures do not establish any empirical strategy result.
