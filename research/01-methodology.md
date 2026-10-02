# Measurement and economic comparability

## Current research decisions — 2 October 2026

The active question is whether a public-data paper strategy can earn convincing
closed cash returns over seconds to minutes. On 2 October the user clarified
that $100 was an example; larger sizes are in scope. Evaluate size against
depth, delayed execution, costs and required capital. Keep each frozen test's
declared size and preregister new size comparisons. Directional one-venue
trades are allowed; earlier carry questions remain historical. Current decisions
and the evidence needed to reopen a parked idea live in the
[decision register](research-decision-register.md).

Use this sequence for new work:

1. **State the mechanism and its falsifier.** Describe whose activity should
   move the price, why the effect should persist until our delayed entry, and
   what observable result would contradict it. A stable cross-venue premium
   is not itself a forecast of convergence.
2. **Check observability and the cost budget first.** Establish native units,
   executable size, spread/depth, ordinary live trade coverage, both clocks,
   and missing-data rates. Calculate how much movement is needed for a closed
   cycle. Reject a test whose intended signal or fills cannot be measured.
3. **Run a small descriptive screen before building execution variants.**
   Reuse retained captures where possible. Include the relevant non-event,
   same-time or direction control; specify matching using information available
   at the decision. Report local movement, reference-market movement and
   delayed executable quote return separately. Explain what each control can
   and cannot identify. Screen results from already inspected data are exploratory.
4. **Freeze the next decision, not just code.** Name the primary hypothesis,
   comparator, economic criterion, request/byte/time limit, and advance/park/
   inconclusive outcomes before inspecting new results. A changed threshold,
   horizon or selected asset is another research choice. Keep the full selection
   history and require untouched time blocks before claiming validation.
5. **Spend execution effort on surviving questions.** Use existing capture,
   replay and accounting components with configuration where feasible. Keep
   pinned historical and armed sources fixed. Add machinery only for a named
   missing capability or a demonstrated measurement defect.

Count distinct market episodes and time blocks alongside quotes, variants and
trades. Multiple horizons, venues and rules can reuse the same price move;
their returns and sample counts are not independent evidence. Ten minutes
with hundreds of callbacks remains one short session. When independent blocks
are too few to estimate precision credibly, report that limitation rather than
substituting an arbitrary minimum quote count.

Every experiment needs a gate funnel: eligible observations, events, admissions,
orders requested, attributed fills, closed episodes, unresolved outcomes and
missing measurements. State which gates were actually exercised. A passing
audit with zero fills verifies no fill arithmetic. A parameter change that
would not alter any decision does not warrant a full strategy rerun.

Separate measured cash costs (spread, depth, actual modeled delay, fees and
applicable funding/financing) from capital assumptions and additional stress.
Show baseline cash and relevant 1/2/5 bp sensitivities; do not treat the 5 bp
allowance as an observed fee or double-count slippage already in delayed fills.
Public maker attribution and hypothetical taker fills remain conditional.
Technical health, forecast skill and economic performance are separate results.

After a result, update one current decision row and link its retained evidence.
Continue research when an idea is parked; repeating a negative baseline or a
healthy collector check is not a new research result. Operational monitoring
and untouched frozen studies keep their existing authorized endpoints.

## Questions

1. Which canonical Robinhood Chain assets have sufficient public pool liquidity and equivalent Hyperliquid hedges?
2. Do actual bids/asks or size-aware pool quotes leave positive entry spread after fees and slippage?
3. Can a spread be locked, or does the trade depend on convergence, funding, redemption, borrow, or future market reopening?
4. Are funding differences persistent in historical observations, after entry/exit costs and collateral requirements?
5. Are apparent opportunities robust across consecutive observations rather than isolated or stale quotes?

## Required distinctions

- Chain is not exchange. Canonical token address, pool deployment, quote asset, and redemption rights matter.
- Same ticker is insufficient. Compare underlying, unit/multiplier, FX denomination, index composition, dividends/splits, futures roll, hours, oracle and settlement.
- Long fully funded spot / short perp is basis plus funding exposure, with liquidation and issuer risks. There is no guaranteed convergence date for a perpetual.
- Two perps require separate margin balances and carry funding differences. A price spread is not realized cash profit while both positions remain open.
- Reverse cash and carry requires accessible spot borrowing and its cost. Do not assume borrow exists for Stock Tokens.
- Fully prepositioned inventory avoids a bridge on each trade but requires capital and rebalancing. Funding return on notional differs from return on committed capital.

## Measurements

- Save local request start/end UTC and venue timestamps if available. Report observed skew, age, rate failures, and sample windows.
- For equal base quantity q: buy cost is sum of consumed asks; sell proceeds sum of consumed bids. Gross entry bps = 10,000 × (sell VWAP / buy VWAP − 1). Subtract both trading fees and explicit nontrading costs. Never extrapolate beyond returned book depth.
- Evaluate target notionals $1,000 / $10,000 / $100,000 where depth permits, reporting fill capacity and actual buy cost. Fees apply to each leg's own notional.
- A matched dollar notional is not necessarily a delta hedge for dissimilar units. Use equal economic quantities only after unit checks.
- Short receives positive funding; long pays positive funding. Sum realized timestamped payments over matched windows with actual venue interval. Do not annualize one current rate as a forecast.
- Funding history and hourly candle basis establish persistence, not executable historical fills. Candles are unsynchronized trade aggregates, not an orderbook backtest.
- Screening thresholds should be explicit; broad census first, then prioritize meaningful turnover and available two-sided depth. Failure to fetch a market does not establish illiquidity.
- No look-ahead claims: same-period best direction and average funding are descriptive, selected ex post. Forward results require separate holdout samples.

## Inference limits

A short consecutive live window cannot establish durable profitability, capacity under stress, or execution success. Report its exact duration and the number of independent funding intervals. Cross-chain finality, transaction gas, MEV, slippage limits, issuer controls, collateral depegs, oracle behavior and liquidation are material where applicable. Accessible public data does not establish user trading eligibility.
