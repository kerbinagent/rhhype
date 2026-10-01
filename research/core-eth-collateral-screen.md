# ETH collateral candle screen — 1 October 2026

Historical exploratory diagnostic, selected after seeing September funding.
Three public daily-candle requests; no retries. ETH spot/perp/mark, September
1–30. Four fixed weeks, two-day remainder, and overlapping full month.
$1,000 spot target rounded down to a shared 0.0001 ETH lot; same short size;
10% cash buffer; zero Standard fees; 5% opportunity cost; 5 bp allowance.
Opening-hour funding excluded. Funding `value` units remain inferred.

Trade candles are asynchronous, potentially stale and non-executable. Margin
proxy combines daily spot low and mark high under current LTV .70/LT .85,
IMR .05/MMR .012. Spot trade price is not the collateral oracle; funding,
fees and debit financing are omitted from health. Positive headroom cannot
prove no liquidation. Negative results and missing observations are retained.
No parameter tuning, trade or prospective holdout claim. Source/request plan
are committed before collection. Frozen BTC carry is unaffected.
