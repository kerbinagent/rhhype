# Completed exploratory ACK sensitivity

**No positive complete portfolio and no promotion.** These are post-capture
execution-model sensitivities on one stopped archive. ACK times are assumed;
no private acknowledgment or actual fill was observed. Different models and
branches are correlated and their P&L is not summed.

## Complete-portfolio coverage

| Model | Complete portfolios | Negative | Positive | Unknown |
|---|---:|---:|---:|---:|
| Frozen strict | 29 | 29 | 0 | 99 |
| Frozen entry-retirement correction | 29 | 29 | 0 | 99 |
| Exploratory ACK base | 12 conditional | 12 | 0 | 116 |
| Exploratory ACK plus200 | 0 | 0 | 0 | 128 |

The twelve complete base branches are Premium BTC, all four sizes, with
control10s, passive_target10s and passive_target60s exits. Their individual
net results after fees, stress and capital range from −$0.454706 to
−$0.771059. They do not constitute twelve independent profit samples.
Unknown portfolio totals remain null even where closed episodes have a
conditional contribution. All runs retained their complete output inventories.

The [full comparison](../../data/derived/rh-passive-exit-v1-restart-ack-readout/readout.json)
contains 128 branch rows and 768 pairwise alignment rows; the
[generated table](../../data/derived/rh-passive-exit-v1-restart-ack-readout/REPORT.md)
shows every branch/model. The eleven strict/corrected branches with the
post-halt historical-guard caveat retain provisional contributions and have
their validated comparison counts withheld. The ACK models run the outer
historical checks; their known values remain conditional on assumed execution.

## Primary Standard XAG, $1,000

All four exit policies within each model have the same coverage below.

| Model | Admitted attempts | Closed without flow | Completed trading cycles | Time before first uncertainty | First uncertainty |
|---|---:|---:|---:|---:|---|
| Strict / corrected | 57 each | 56 each | 0 | 449.73s | Cancellation ordering ambiguity |
| ACK base | 29 | 28 | 0 | 228.61s | Coverage gap with an open obligation |
| ACK plus200 | 7 | 6 | 0 | 50.06s | Late revision to the assumed activation anchor |

The time column starts at each model's first requested quote and is an
observation interval, not filled inventory exposure. The unfinished attempt
in each case prevents a known whole-portfolio result. Zero contribution from
closed no-flow attempts is not a break-even portfolio or demonstrated trading
performance.

Strict/base share 29 primary target10s admission IDs, with 28 strict-only and
zero base-only IDs. Strict/plus200 share one, with 56 strict-only and six
plus200-only IDs. None of these primary comparisons has a matched completed
full entry. Across all branches, strict/base have 64 branches with at least
one identical full-entry signature; strict/plus200 and base/plus200 have none.
Common decision IDs alone do not establish equal entries or causal effects.
Aggregate inventory exposure is recorded, but attribution to common versus
unmatched cohorts is unavailable and remains null.

## First halt and target attrition

| First recorded halt | Base branches | Plus200 branches |
|---|---:|---:|
| Late revision to assumed ACK anchor | 48 | 64 |
| Coverage gap with an open obligation | 48 | 48 |
| Assumed post-only rejection left unresolved | 16 | 16 |
| Exit lot/minimum unresolved | 4 | 0 |
| No recorded halt | 12 | 0 |

These are first recorded halts, not independent causal decompositions.
The timing sensitivities also add coverage, native-ID and historical-evidence
guards; the change from strict cannot be attributed solely to ACK latency.
Smaller partial losses in earlier-halted runs do not show economic improvement.

The immutable audits contain 64 base and 32 plus200
`passive_target_abstain` events, all with reason `target_above_5bp_ask_cap`.
These counts include correlated sizes and exit policies. Neither clock model
removes that price constraint. The separate strict-run
[reach diagnostic](../rejected-target-public-reach/REPORT.md) found no eligible
observed buy print reaching any of its 150 reconstructed rejected targets
within the fixed window. This is observed nonreach, conditional on the public
tape; it does not prove an absolute no-fill bound or evaluate every ACK target.

## Provenance and next decision

Both runs started at 04:10:54 UTC on 30 September 2026. Plus200 finished at
04:23:27 UTC (751.725 replay seconds), base at 04:26:25 UTC (930.107 replay
seconds), both exit 0 and within their one-hour limit. The complete output
directories occupy 9,077,663 bytes for plus200 and 11,887,402 for base, each
below 128 MB. Logs stayed below their 1 MB limits.

The readout helper was reviewed, committed as `a314eda` and passed seven
synthetic tests before reading the completed artifacts. It verified stopped
manifest/raw hashes, all 21 actual runtime dependencies, unchanged before/after
source snapshots, the exact scenario assumptions and strict/corrected reference
hashes. It recorded its own source, tests and method hashes and checked them
again before publication. Raw SHA-256 remains
`c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6`.

Next, inspect the dominant halt mechanisms for evidence limits or concrete
bookkeeping defects, and inventory existing matched books for a stricter
pre-entry economic gate. These findings do not justify relaxing freshness,
queue evidence, fees, stress or unknown treatment to obtain a positive result.
No new raw capture or strategy promotion follows from this sensitivity.
