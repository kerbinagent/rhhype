# Partial-exit lot accounting audit — 2026-09-29

## Observed problem

During the separate BBO-versus-depth paper experiment started 17:44:49 UTC,
the BBO baseline stopped at 80 completed trades with four positions still
exiting. Inspection at about 18:01 UTC found 11 affected positions across fee
and shadow scenarios, including these Standard-fee baseline remainders:

| Asset | Entered quantity | Remaining float | Venue lot |
|---|---:|---:|---:|
| XAG | 16.42 | 0.009999999999999787 | 0.01 |
| NVDA | 4.364 | 0.0009999999999996678 | 0.001 |
| XAG (failed hedge) | 8.29 | 0.009999999999999565 | 0.01 |
| META | 1.371 | 0.0009999999999999454 | 0.001 |

Subtracting successive partial fills as binary floats produced these numbers.
The next execution attempt converts the already rounded-down float to Decimal,
then floors it to the lot size: the last lot becomes zero executable quantity.
This is an accounting defect, not evidence that those markets lacked the last
lot for ten minutes. We must preserve and execute that real remaining lot;
rounding the position flat without an observed exit would fabricate a fill.

Frozen four-position evidence: `data/evidence/bbo-partial-exit-remainders.json`,
30,826 bytes, SHA-256
`1029b140242c7ea2e54f61193d9b552415fe43a80fb91661f7588aafb4e2f6ba`.
The original live-data directories remain preserved. Both paper pilots were
stopped together early, at 18:01:20 UTC, pending a tested accounting fix.
They are not completed forty-minute experiments. Production had no corresponding
open dust positions at inspection; its two old Aster records were flat and
awaiting funding coverage, a different issue.

## Consequences for interpreting the experiment

- Open positions retain capital and block new entries, so lower BBO turnover
  and total closed losses cannot be interpreted as a superior strategy.
- Closed-only return and exit-time statistics omit the stuck positions. A
  comparison must show all attempts, outstanding positions and their ages.
- Missing entry observations on an unfilled leg are expected. Compare quote
  provenance among filled legs; do not label every absent fill an instrumentation
  discrepancy.
- The depth-only pilot disabled targeted REST. Many HL entry intents expired
  before a usable new depth snapshot; its losses are largely failed hedge
  unwinds. It does not represent the production collector, which keeps REST.
- A corrected experiment needs separate output directories and matched settings.
  Old results must not be rewritten as if the new arithmetic had run originally.

## Existing execution assumption, separate from this arithmetic fix

The simulator applies minimum quantity/notional checks to entries and permits
reduce-only exits below entry minimums, while requiring actual displayed depth
and venue lot size. Hyperliquid's official
[error list](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
lists a $10 minimum and its
[order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
define reduce-only, but these pages do not explicitly document a small-position
minimum exception. Sub-minimum closure acceptance therefore remains an execution
assumption to validate independently before live use. This fix changes quantity
arithmetic, not that policy. Repeated displayed quotes also do not prove how real
liquidity would replenish after our own hypothetical orders.
