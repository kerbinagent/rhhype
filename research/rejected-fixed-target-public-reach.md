# Rejected fixed targets: observed public buy-price reach

**Post-capture offline diagnostic; no wider-ceiling strategy implemented or replayed.** The stopped strict replay rejected 150 fixed passive exit targets because the rounded target exceeded 5 bp above the as-of RH ask. All 150 attempts were reconstructed and retained. **None had a genuinely new valid RH buy print reaching the fixed target during its causal source window**, including prints received after the hold deadline. This is observed public-flow nonreach under the stated feed and clock assumptions, not an absolute no-fill bound.

The [final artifact](../reports/rejected-target-public-reach/final-analysis.json) retains every attempt, 32 tier/asset/size/policy groups, exact audit-row provenance, as-of RH book provenance, target/deadline reconstruction and input/source hashes. The [diagnostic](../scripts/analyze_rejected_target_reach.py) invokes the frozen canonical public-event decoder; it does not invoke a strategy engine or replay coordinator. [Synthetic tests](../tests/test_analyze_rejected_target_reach.py) cover rounding, original tier latencies, missing/ambiguous as-of evidence, source/receipt boundaries, later receipts, duplicate suppression, feed uncertainty and strict provenance rejection.

## Observations

| Tier | Asset | Rejected 10s targets | Rejected 60s targets | Reaching targets, either policy |
| --- | --- | ---: | ---: | ---: |
| Standard | BTC | 27 | 27 | 0 |
| Standard | ETH | 36 | 36 | 0 |
| Premium | BTC | 8 | 8 | 0 |
| Premium | ETH | 4 | 4 | 0 |

There were no rejected fixed-target attempts for NVDA or XAG. This supplies no comparable target-reach result for those assets. Every BTC/ETH size ($100, $250, $500 and $1,000) remains in the artifact. Attempts in different portfolios overlap public events and are not independent samples; neither their print counts nor economic ledgers are summed into profit.

For Standard $1,000, each BTC/ETH policy had nine rejected targets. The closest eligible BTC buy price remained **13.58 bp below its fixed target** in the 10s case and **12.73 bp below** in the 60s case, measured as `target / maximum eligible print price - 1`. ETH's corresponding nearest shortfall was **11.90 bp** for both policies. Three BTC and four ETH $1,000 10s attempts had no eligible buy print at all; every corresponding 60s attempt had at least one. No target reached in a later-received print either.

No explicit canonical feed invalidation, 2s book freshness gap or conflicting raw native trade ID overlapped any target window. All hold deadlines were covered by the stopped capture. This does not establish a complete public trade feed, calibrated source clocks, private ACKs or execution. The manifest's terminal disconnects occur outside these windows.

## Reconstruction and causal window

The diagnostic preserves all `passive_target_abstain` audit rows. The fixed requirement is the original logged `required_price`; it is not recalibrated using subsequent prices, fees or favorable target choices. It associates the preceding `first_full_hedge` event in that branch/admission, uses its `hold_due_ns`, and cross-checks the policy's 10s or 60s hold duration.

The original log records `capped_price = asof_ask * 1.0005`. Dividing that exact decimal by `1.0005` gives a candidate as-of ask, which must equal the actual preceding or current raw RH book's best ask at the request callback. Book source, receipt, generation, sequence, canonical index and hash are retained. A missing book, mismatched ask, stale clock or ambiguous same-receipt book callback is unreconstructable; none occurred here. The fixed hypothetical target is rounded **up** on the original RH tick from `max(required_price, asof_ask)`.

No ask was actually issued in these frozen branches. The diagnostic defines a labelled hypothetical activation at the rejected request receipt plus the original configured maker delay (Standard 300 ms, Premium 100 ms). It tests buys whose source is at/after activation and at/before the original hold deadline, with receipt at/after activation and source no later than receipt. Activation and deadline equality are included. Prints received by the deadline and prints received later are counted separately. No quantity, queue-ahead assumption or fill probability is assigned.

The frozen adapter excludes malformed batches, source-ahead prints, subscribed backlogs and liquidations, and suppresses repeated native IDs within a generation. A separate bounded raw review detects conflicting economic content that the adapter's ID suppression could otherwise hide. Additional cross-generation exact duplicates are suppressed under the explicit assumption that native IDs are unique/stable per RH asset across generations. Conflicts create uncertainty. Freshness is checked using both receipt and source age of RH/HL book events, alongside explicit book/trade invalidations; quiet trade intervals alone are not labelled feed gaps.

## What this supports

Widening the 5 bp quote ceiling alone supplies no observed reaching-print evidence for these 150 frozen cost targets in this stopped sample. The result does not show what a different dynamic target, longer horizon or later market would do, and does not authorize choosing a favorable ceiling after seeing this capture.

Even a future reaching print would not establish maker fill: queue priority, acceptance and completeness remain unknown. A common market rise can lift both RH buy prints and the cost of buying back the HL short, erasing an apparent higher-ask gain. Before using a touch as margin evidence, the next gate must reconstruct the actual same quantity and the first eligible fresh HL buy book after that print's receipt plus the frozen IOC latency, walk its depth, and include the original own-notional fees/reserve/capital assumptions. This first reach diagnostic does not guess missing quantities or compute a fill-contingent margin.

## Provenance and run versions

The final analysis independently requires the strict replay schema and `verified_capture` event source, the exact stopped-capture path, complete result status, unchanged original protocol sources, correct result/audit/raw/manifest/metadata hashes, and a verified nontruncated terminal. Its canonical terminal must exactly match the strict replay terminal. All 20 frozen correction source hashes and every input file are checked before and after; the diagnostic source's physical hash is likewise stable across the final scan. The final output is below the 2 MB cap.

Two preliminary JSON files are preserved separately. `analysis.json` was produced during initial development; a pure validation improvement was made while its scan was active, so its reported physical diagnostic hash does not provide a clean runtime-source freeze. It is provisional. `verified-analysis.json` used a stable diagnostic self-hash and agrees on all 150 outcomes, but predates the stronger independent strict-summary schema/terminal gates. `final-analysis.json` is the publication artifact. Neither preliminary file amends the frozen strategy or contributes profit evidence.

Reproduce to a new output path:

```sh
python -m scripts.analyze_rejected_target_reach --out /tmp/rejected-target-reach.json
python -m unittest tests.test_analyze_rejected_target_reach
```
