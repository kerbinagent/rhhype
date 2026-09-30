# RH passive-exit replay performance, before method freeze

This is an engineering benchmark, not a result of the passive-exit study.
It uses the first 1,000 normalized events of the **stopped prior** RH maker
capture. All events precede that capture's 30-minute calibration cutoff.
No new public data was collected, and no entry, exit, profit, or holdout
outcome was evaluated. The complete machine-readable provenance, archive
and source hashes, event counts, and timings are in
[`performance-prefix-benchmark.json`](../reports/rh-passive-exit-v1/performance-prefix-benchmark.json).

## Measured work

The benchmark verified the prior capture's 41,368,405-byte gzip archive
SHA-256 through `iter_events`, decoded a bounded prefix, constructed one
`RhMakerSellModel` and all 128 prospective `PassiveExitBranch` objects,
then called `model.consume(event)` and every matching branch's
`process(event)` for each event. It used the event-scoped immutable parse
cache and reset it before every event. It wrote no audit rows or strategy
results. The process ran at `nice=10` alongside other workspace processes.

| Step | Time for 1,000 events |
|---|---:|
| Verify archive and normalize prefix | 0.622 s |
| One sell-model calibration consume | 2.016 s |
| 128 cached branch processing | 7.731 s |
| Measured total | 10.370 s |

There were 965 valid book parse misses and 29,915 cache hits from 30,880
branch parse calls. The single calibration model parsed 965 books. These
counts show that branches still process the full event stream while sharing
only the validated parsed representation. The actual analyzer uses four
calibration models and creates branches only at the holdout cutoff; this
benchmark intentionally combines one model with all branches to measure the
branch path. The prior capture has 104,790 raw frames; a simple constant-cost
projection from this prefix is about 18 minutes for a capture of similar
event count. **This is not a runtime upper bound or a measurement of the
analyzer's actual schedule.** Later RH book depth, market activity, holdout
quote decisions, passive-exit state, washout, audit compression, and host
contention can all change cost. The prospective method has an 80-second
no-new-entry washout within the 20-minute holdout.

The prior RH BTC book sampled for the earlier replay had roughly 7,875
levels across both sides. Without sharing, parsing it into Decimal levels
once per same-asset branch is the known dominant cost. The cache shares an
immutable Decimal book among branches and an independent immutable float
book among model consumers. It never shares portfolio or model state.

## Correctness and integration limits

Five focused cache tests pass. They check immutable economic book behavior,
source parser restoration, invalid-book validation, reuse of a mutable
event dictionary across yields, independent Standard/Premium model state,
fee-independent frozen adverse calibration on a small synthetic sample,
and matching summaries for the four passive-exit branches with and without
the cache. The analyzer calls `next_event()` before **every** yielded event
and includes the helper's source hash in its pre-capture method freeze.

One additional synthetic end-to-end analyzer injection used a test manifest
dated after its synthetic protocol freeze, four receipt-ordered BTC books,
a terminal event, and the
prospective 128-branch runner. With the cache enabled and disabled, the
analysis objects matched exactly after excluding cache counters, runtime,
and gzip hash; all 48 ordered decompressed audit records matched byte for
byte. This verifies the current integration path on a tiny sample. It does
not establish full-capture equivalence or exercise active passive exits.

Current frozen market metadata differs between Standard and Premium only in
RH maker and taker fees; the HL fields are identical. The adverse-flow
calibration path uses size, grid, book, and public flow, so one calibration
model can serve both fee tiers when the runner reads only its frozen adverse
estimate. `RhMakerSellModel.quote()` uses fees and must not be shared across
tiers. Entry diagnostics should be computed once per asset, budget, and
fee tier per event, then passed to the four exit branches with that shared
entry rule. This avoids redundant holdout quote calculations while keeping
independent ledgers and decisions.

No full prospective replay has been run. Exact output equivalence and full
runtime still require the runner's own tests and its first stopped capture.
