# RH maker pilot: interpretation rules before the holdout

Recorded 29 September 2026 before the 21:51:32 UTC holdout start. These
rules guide the human report; they change no frozen quote or execution
policy. The implementation freeze is commit 38950ef. No calibration fits
or holdout outcomes have been inspected.

## Primary and diagnostic results

The primary panel is RH **Standard**, **$1,000**, **adaptive** pricing for
BTC, ETH, NVDA and XAG, reported separately. The fixed-best and persistence
policies are controls on the same public events. $100/$250/$500 and RH
Premium are declared sensitivities, with independent simulated inventories.
Do not select the highest of 96 branch returns and present it as a tested
strategy. Branches share events and their P&L cannot be added as income.

Every branch needs five distinct fields:

1. Model readiness and calibration coverage; an unready model's abstention
   says nothing about the profitability of the intended trained rule.
2. Quote decisions, competitiveness and observed flow coverage. Resting
   far behind the book with no flow is an economically relevant result,
   but absence of a private fill remains unknowable from public events.
3. Completed filled episodes: price cash flow, explicit fees, separate
   reserve and capital; positive cash before the reserve is different
   from positive modeled net. Funding-unknown episodes stay separate.
4. Failed hedges, partial quantities, cancellation ambiguity and actual
   residual inventory. Unresolved obligations prevent a total-return claim;
   completed contributions alone can be selected by which paths resolve.
5. Observed timing, missing endpoints, and censoring. Quote residence is
   not a continuously available profitable execution window. Requested
   150 ms hedges and ten-second closes are not observed fill latencies.

## Decisions supported by each outcome

| Observation | Defensible next action |
|---|---|
| Calibration unready | Report which count/span/coverage gate failed; freeze a new longer collection before trying a different gate |
| Valid quotes but no attributed flow | Measure distance and queue/flow coverage; consider a separately frozen price/fill trade-off study, preserving the negative/no-flow control |
| Tiny partials or dust dominate unresolved outcomes | Investigate a separately capped inventory-netting policy; retain all unhedged exposure and below-minimum residuals |
| Complete results negative even before explicit fees | Change the economic mechanism or predictor; fee tier arithmetic alone cannot rescue those paths |
| Fee-only positive, reserve-negative | Report both; establish measured nontrading/rebalancing costs before changing a conservative allowance |
| Some positive closes but unresolved inventory/funding | Report partial contributions and unresolved risk, without a portfolio-return or profitability claim |
| Complete primary branch positive after modeled costs | Preserve the result and specify a new multi-day prospective replication; this short public-flow counterfactual does not establish private queue execution or a durable edge |

The bid-side study does not test RH maker sells, passive inventory exits,
Core hedges, or canonical Robinhood Chain AMM routes. Separate methods for
[sell quotes](rh-maker-sell-followup.md),
[passive exits and bounded partial netting](rh-maker-inventory-exits.md),
and [hedge venue choice](rh-hedge-venue-choice.md) already exist independently
of this pilot's outcomes. These are future hypotheses, not retroactive
repairs of its result. The existing production monitor keeps its own
ledger, controls and ten-second exit-request policy throughout.
