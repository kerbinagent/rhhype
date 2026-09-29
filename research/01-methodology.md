# Measurement and economic comparability

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
