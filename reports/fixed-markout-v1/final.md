# Fixed-quantity prospective quote study

Stopped snapshot: 2026-09-29T18:43:22+00:00. Horizon 12.0–16.0 seconds.

These are observed quotes at the original quantity, after four frozen Standard taker fees. They are not orders, fills, realized P&L, or an executable strategy claim.

## Full-run coverage and censoring

Anchors 2134; warmup 1128; v2-scored 1006; matched 1595; censored 539.

| Cohort | Role | Anchors | Matched | Censored | Pending | Matched % | Censored % |
|---|---|---:|---:|---:|---:|---:|---:|
| all_v2_scored | all scored | 1006 | 863 | 143 | 0 | 85.8% | 14.2% |
| conditional_linear_gt_0 | primary | 0 | 0 | 0 | 0 | ? | ? |
| conditional_linear_gt_0.25 | primary | 0 | 0 | 0 | 0 | ? | ? |
| persistence_gt_0 | reference | 0 | 0 | 0 | 0 | ? | ? |
| persistence_gt_0.25 | reference | 0 | 0 | 0 | 0 | ? | ? |
| historical_median_gt_0 | secondary | 5 | 4 | 1 | 0 | 80.0% | 20.0% |
| historical_median_gt_0.25 | secondary | 1 | 1 | 0 | 0 | 100.0% | 0.0% |
| horizon_delta_gt_0 | secondary | 0 | 0 | 0 | 0 | ? | ? |
| horizon_delta_gt_0.25 | secondary | 0 | 0 | 0 | 0 | ? | ? |

Censor reasons: future_exit_depth=493, outcome_missing=22, stopped_pending=24.

## Retained export and quote outcomes

Terminal rows retained 2134; export drops 0. Retained matched 1595 of 1595 full-run matched; retained censored 539 of 539 full-run censored. All dollar distributions below use retained matched rows only.

| Retained subset | n | Four-fee net mean / p10 / median / p90 USD | Four-fee positive | After-reserve net mean / p10 / median / p90 USD | After-reserve positive |
|---|---:|---|---:|---|---:|
| all matched | 1595 | -0.87 / -1.26 / -0.94 / -0.34 | 0.1% | -1.37 / -1.76 / -1.44 / -0.84 | 0.0% |
| v2-scored matched | 863 | -0.85 / -1.25 / -0.94 / -0.35 | 0.1% | -1.35 / -1.74 / -1.44 / -0.85 | 0.0% |
| conditional_linear_gt_0 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| conditional_linear_gt_0.25 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| persistence_gt_0 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| persistence_gt_0.25 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| historical_median_gt_0 | 4 | -0.30 / -0.44 / -0.31 / -0.16 | 0.0% | -0.80 / -0.94 / -0.81 / -0.66 | 0.0% |
| historical_median_gt_0.25 | 1 | -0.09 / -0.09 / -0.09 / -0.09 | 0.0% | -0.59 / -0.59 / -0.59 / -0.59 | 0.0% |
| horizon_delta_gt_0 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| horizon_delta_gt_0.25 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |

Retained all-matched gross quoted capture mean: $-0.24; four frozen-fee means buy entry $0.16, sell entry $0.16, buy exit $0.16, sell exit $0.16. All fee distributions are in JSON.

Selected thresholds were frozen at $0 and $0.25. The conditional-linear cohorts are primary; persistence is a reference; historical-median and horizon-delta are secondary. Cohorts overlap and censoring can bias matched-only quote summaries.

## Paired four-model forecast errors

Every model below is evaluated on the same retained matched v2-scored anchors. Error is actual four-fee quote net minus the frozen dollar screen.

| Model | Role | Same n | Mean error USD | Median absolute error USD | RMSE USD |
|---|---|---:|---:|---:|---:|
| conditional_linear | primary | 863 | -0.01 | 0.07 | 0.12 |
| persistence | reference | 863 | -0.01 | 0.08 | 0.15 |
| historical_median | secondary | 863 | -0.01 | 0.08 | 0.15 |
| horizon_delta | secondary | 863 | -0.01 | 0.08 | 0.15 |

## Retained breakdowns

Full distributions and selected-cohort results by asset, directed route, and five-minute UTC anchor block are in the JSON. These breakouts are retained-row views, not full-run rates.

Asset groups: 12; directed routes: 24; five-minute blocks: 5.

### Asset

| Group | Matched n | Censored n | Four-fee net median USD | Four-fee positive | After-reserve positive | V2-scored matched n | Primary selected >$0 n | Primary selected >$0.25 n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 154 | 32 | -0.99 | 0.0% | 0.0% | 85 | 0 | 0 |
| CASHCAT | 11 | 135 | -3.85 | 0.0% | 0.0% | 0 | 0 | 0 |
| COIN | 101 | 67 | -0.54 | 0.0% | 0.0% | 38 | 0 | 0 |
| ETH | 163 | 23 | -1.00 | 0.0% | 0.0% | 88 | 0 | 0 |
| HYPE | 142 | 44 | -1.05 | 0.0% | 0.0% | 84 | 0 | 0 |
| META | 163 | 23 | -0.40 | 0.0% | 0.0% | 87 | 0 | 0 |
| NVDA | 179 | 11 | -0.49 | 0.6% | 0.0% | 99 | 0 | 0 |
| SOL | 176 | 14 | -1.08 | 0.0% | 0.0% | 97 | 0 | 0 |
| XAG | 151 | 37 | -0.32 | 0.0% | 0.0% | 84 | 0 | 0 |
| XPL | 10 | 118 | -1.73 | 0.0% | 0.0% | 0 | 0 | 0 |
| XRP | 178 | 12 | -1.19 | 0.0% | 0.0% | 103 | 0 | 0 |
| ZEC | 167 | 23 | -1.12 | 0.0% | 0.0% | 98 | 0 | 0 |

### Directed route

| Group | Matched n | Censored n | Four-fee net median USD | Four-fee positive | After-reserve positive | V2-scored matched n | Primary selected >$0 n | Primary selected >$0.25 n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC&#124;hyperliquid:BTC&#124;lighter:1 | 80 | 13 | -1.00 | 0.0% | 0.0% | 45 | 0 | 0 |
| BTC&#124;lighter:1&#124;hyperliquid:BTC | 74 | 19 | -0.98 | 0.0% | 0.0% | 40 | 0 | 0 |
| CASHCAT&#124;hyperliquid:CASHCAT&#124;lighter:221 | 4 | 69 | -4.17 | 0.0% | 0.0% | 0 | 0 | 0 |
| CASHCAT&#124;lighter:221&#124;hyperliquid:CASHCAT | 7 | 66 | -3.80 | 0.0% | 0.0% | 0 | 0 | 0 |
| COIN&#124;hyperliquid:xyz:COIN&#124;lighter:109 | 50 | 34 | -0.57 | 0.0% | 0.0% | 22 | 0 | 0 |
| COIN&#124;lighter:109&#124;hyperliquid:xyz:COIN | 51 | 33 | -0.52 | 0.0% | 0.0% | 16 | 0 | 0 |
| ETH&#124;hyperliquid:ETH&#124;lighter:0 | 78 | 15 | -1.01 | 0.0% | 0.0% | 43 | 0 | 0 |
| ETH&#124;lighter:0&#124;hyperliquid:ETH | 85 | 8 | -1.00 | 0.0% | 0.0% | 45 | 0 | 0 |
| HYPE&#124;hyperliquid:HYPE&#124;lighter:24 | 69 | 24 | -1.06 | 0.0% | 0.0% | 42 | 0 | 0 |
| HYPE&#124;lighter:24&#124;hyperliquid:HYPE | 73 | 20 | -1.05 | 0.0% | 0.0% | 42 | 0 | 0 |
| META&#124;hyperliquid:xyz:META&#124;lighter:117 | 78 | 15 | -0.41 | 0.0% | 0.0% | 42 | 0 | 0 |
| META&#124;lighter:117&#124;hyperliquid:xyz:META | 85 | 8 | -0.40 | 0.0% | 0.0% | 45 | 0 | 0 |
| NVDA&#124;hyperliquid:xyz:NVDA&#124;rh_lighter:15 | 88 | 7 | -0.48 | 1.1% | 0.0% | 49 | 0 | 0 |
| NVDA&#124;rh_lighter:15&#124;hyperliquid:xyz:NVDA | 91 | 4 | -0.49 | 0.0% | 0.0% | 50 | 0 | 0 |
| SOL&#124;hyperliquid:SOL&#124;lighter:2 | 90 | 5 | -1.05 | 0.0% | 0.0% | 50 | 0 | 0 |
| SOL&#124;lighter:2&#124;hyperliquid:SOL | 86 | 9 | -1.09 | 0.0% | 0.0% | 47 | 0 | 0 |
| XAG&#124;hyperliquid:xyz:SILVER&#124;lighter:93 | 72 | 22 | -0.32 | 0.0% | 0.0% | 38 | 0 | 0 |
| XAG&#124;lighter:93&#124;hyperliquid:xyz:SILVER | 79 | 15 | -0.32 | 0.0% | 0.0% | 46 | 0 | 0 |
| XPL&#124;hyperliquid:XPL&#124;lighter:71 | 5 | 59 | -1.62 | 0.0% | 0.0% | 0 | 0 | 0 |
| XPL&#124;lighter:71&#124;hyperliquid:XPL | 5 | 59 | -1.80 | 0.0% | 0.0% | 0 | 0 | 0 |
| XRP&#124;hyperliquid:XRP&#124;lighter:7 | 90 | 5 | -1.19 | 0.0% | 0.0% | 52 | 0 | 0 |
| XRP&#124;lighter:7&#124;hyperliquid:XRP | 88 | 7 | -1.19 | 0.0% | 0.0% | 51 | 0 | 0 |
| ZEC&#124;hyperliquid:ZEC&#124;lighter:90 | 83 | 12 | -1.11 | 0.0% | 0.0% | 50 | 0 | 0 |
| ZEC&#124;lighter:90&#124;hyperliquid:ZEC | 84 | 11 | -1.12 | 0.0% | 0.0% | 48 | 0 | 0 |

### Five-minute UTC anchor block

| Group | Matched n | Censored n | Four-fee net median USD | Four-fee positive | After-reserve positive | V2-scored matched n | Primary selected >$0 n | Primary selected >$0.25 n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-29T18:20:00+00:00 | 139 | 43 | -0.95 | 0.0% | 0.0% | 0 | 0 | 0 |
| 2026-09-29T18:25:00+00:00 | 397 | 133 | -0.95 | 0.0% | 0.0% | 0 | 0 | 0 |
| 2026-09-29T18:30:00+00:00 | 388 | 134 | -0.92 | 0.0% | 0.0% | 213 | 0 | 0 |
| 2026-09-29T18:35:00+00:00 | 410 | 129 | -0.94 | 0.2% | 0.0% | 392 | 0 | 0 |
| 2026-09-29T18:40:00+00:00 | 261 | 100 | -0.93 | 0.0% | 0.0% | 258 | 0 | 0 |

Validation warnings: none.

## Interpretation

- These are prospective fixed-original-quantity quotes after four frozen Standard taker fees, not fills or cash P&L.
- The reserve-adjusted quote screen additionally subtracts fixed extra-cost and elapsed capital estimates.
- Censored anchors have no observed economic outcome; retained rows may omit older terminals.
- Opposite directions and fee-screen cohorts share books, so rows and cohorts are not independent returns.
- Frozen v2 bps forecasts converted to dollars are diagnostics, not calibrated fixed-quantity predictions.
