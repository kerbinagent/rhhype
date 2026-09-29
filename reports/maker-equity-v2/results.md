# NVDA/XAG post-market capture result

The frozen public capture ran 2026-09-29 **20:22:56.780–20:29:56.818 UTC** and stopped at its 420-second duration limit. It has 10,619 records and 3,755,149 gzip bytes, with no recorded feed errors or invalidations. Integrity, market-plan hash, one-generation-per-venue, malformed-trade, and source-ahead-trade checks pass. The [full result and coverage audit](../../research/maker-equity-results.md) documents every primary cohort; the [derived summary](../../data/derived/maker-equity-20260929T2022Z/summary.json) and [case file](../../data/derived/maker-equity-20260929T2022Z/cases.json) are machine-readable.

| Frozen maker arrival | Cohort anchors | Stale decisions | Quote-supported | Same-price arrivals | Strict full-flow signals | Hedge quotes | Complete exits |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 s primary | 1,328 | 904 | 248 | 50 | 1 | 1 | 0 |
| 0.5 s control | 1,328 | 904 | 248 | 65 | 0 | 0 | 0 |
| 3 s control | 1,328 | 904 | 248 | 34 | 0 | 0 | 0 |

The sole primary flow signal was HL maker-buy silver → Core hedge at 20:28:20 UTC, `q=16.28 oz`, with displayed queue ahead `6.01 oz`. Qualifying public trade flow exceeded `ahead + q`; the first eligible hedge quote was found. The specified exit search lacked a due-time quote side (`missing_due_exit_side`). Its hard deadline was before capture end, and no funding boundary fell inside the case. The **+2.139 bp decision-time opening allowance is not a result**: there is no completed unwind, actual maker order, fill, after-fee net, or observed P&L.

In a **post hoc diagnostic only**, HL's first source-valid exit BBO arrived at 20:28:29.934, after its 20:28:29.039 frozen search cutoff; Core's paired exit ask then showed 3.45 oz against `q=16.28`. A later full-depth matched pair before the 20:28:32.314 hard deadline cannot replace that first shallow pair or the expired one-second stage window. The frozen missing-exit classification stands.

Post hoc coverage explains much of the sparse primary screen without changing it. HL NVDA BBO was fresh at 19/83 unique anchors, Core NVDA ticker at 42/83, and RH NVDA ticker at 38/83. HL–Core NVDA was jointly fresh at only 13/83 anchors; HL–RH NVDA at 14/83. For XAG, the six corresponding feed/pair figures were HL 59/83, Core 71/83, RH 32/83, HL–Core pair 52/83, and HL–RH pair 27/83. [HL documents that BBO updates are change-triggered](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions); a quiet timestamp is a lack of a new observation under the frozen 1-second receipt-age rule, not proof of a broken connection or proof that old displayed size remained executable. No threshold was altered after capture.

This single post-market window yields **zero complete conditional round trips**, not a zero-return trade. It cannot establish maker fill probability, executable arbitrage, or a regular-hours/overnight comparison. No additional capture is implied by this report.
