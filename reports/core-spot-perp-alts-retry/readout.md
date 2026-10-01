# Five native spot/perpetual pairs — completed retry

Frozen6ec6582 before fresh capture. 2026-10-01 16:20:21.341–16:30:21.364 UTC,600.024seconds. Both independent $100-per-leg portfolios (1bp and10bp entry limits, $600 prefunded each) had **zero entries/fills/P&L**, and ended without inventory. The preceding interrupted98-second capture is separately preserved.

Each arm evaluated3979directions:152freshness/skew rejections and3827reference-warmup rejections. No forecast was evaluated. This is an inactive coverage result, not evidence that executable opportunities were unprofitable.

| Asset | Retained samples | Maximum past reference count | Eligible sampled callbacks at60 /90 |
|---|---:|---:|---:|
| UNI |348|78|215 /0|
| AAVE |320|76|142 /0|
| SKY |345|76|211 /0|
| LINK |346|84|217 /0|
| LDO |122|29|0 /0|

The count comparison retains the original2-second embargo,89-second minimum span and fresh synchronized samples; it evaluates only reference availability. No counterfactual P&L was calculated. This supports a prospective60-versus90reference-count comparison on these same five assets, with all execution checks unchanged.

One healthy Core connection,21933messages,10,306,031ingress bytes,112,462compressed retained bytes,1481samples and10shutdown invalidations. Independent audit passed hashes, selected native markets, reference timing, unchanged wallets and empty inventory. Fill checks are vacuous. All partial and complete outcomes retained.
