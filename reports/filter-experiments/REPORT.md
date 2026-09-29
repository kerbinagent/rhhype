# Retrospective entry-filter experiments

Frozen checkpoint: 2026-09-29T17:48:16.015646+00:00. Evidence SHA-256: `b2412d250f8ee2bf3b5e335032b046d8e3d4e9eaace309f939cd8562722f06bc`.

The primary sample is the Standard-fee `shadow_baseline` portfolio. Each filter keeps or abstains from an observed attempt; fills and exits are unchanged.

After 5-second route deduplication: 1758 settled attempts (3 removed). Chronological 70/30 split at 2026-09-29T17:08:49.735478+00:00; 2 training outcomes unavailable by the boundary were purged (settlement for closes, close time for aborts).

Unfiltered holdout: 528 attempts, 527 closes, 517 paired closes, 10 failed hedges, 0 wins, net -$624.27 (-$1.182 per attempt).

Across the full retained baseline, net -$2020.84 = price P&L -$706.01 less fees $438.42, modeled other costs $876.37, and small capital costs, plus funding. Paired closes: 1727 and -$1969.12; failed hedges: 29 and -$51.72.

## Train-selected filters on untouched holdout

| Family | Train choice | Holdout attempts | Coverage | Holdout net | Net/attempt | Wins | Failed hedges |
|---|---:|---:|---:|---:|---:|---:|---:|
| net_edge_min_usd | 0.1 | 377 | 71.4% | -$452.21 | -$1.199 | 0 | 7 |
| gross_to_cost_min | 1.25 | 245 | 46.4% | -$280.31 | -$1.144 | 0 | 5 |
| receipt_skew_max_ms | 500 | 326 | 61.7% | -$380.81 | -$1.168 | 0 | 5 |
| source_skew_max_ms | 750 | 233 | 44.1% | -$266.84 | -$1.145 | 0 | 4 |
| asset_class | rwa_xyz | 506 | 95.8% | -$540.62 | -$1.068 | 0 | 6 |

Selection maximizes training net P&L per observed attempt among the listed fixed thresholds, subject to at least 10% training coverage and 30 attempts. Only outcomes known before the holdout began train the selection. No threshold was chosen from holdout outcomes. All filter outcomes are observed subsets, not simulated trades.

## Loss components and venue mix

| Group | Attempts | Paired | Failed hedge | Price P&L | Fees | Other costs | Net P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| rwa_xyz | 1674 | 1659 | 13 | -$565.29 | $371.80 | $834.45 | -$1771.59 |
| crypto | 83 | 68 | 15 | -$134.11 | $65.82 | $41.42 | -$241.35 |
| rh_lighter | 1152 | 1141 | 10 | -$417.94 | $205.11 | $574.30 | -$1197.38 |
| lighter | 309 | 292 | 16 | -$201.97 | $105.26 | $153.77 | -$461.00 |
| aster | 297 | 294 | 3 | -$86.10 | $128.05 | $148.31 | -$362.46 |

Largest route cohorts (at least 20 attempts):

| Route | Attempts | Failed hedge | Price P&L | Fees | Other costs | Net P&L |
|---|---:|---:|---:|---:|---:|---:|
| XAG|hyperliquid:xyz:SILVER|rh_lighter:41 | 309 | 1 | -$111.21 | $55.12 | $153.80 | -$320.15 |
| XAG|hyperliquid:xyz:SILVER|aster:XAGUSDT | 293 | 1 | -$77.97 | $125.60 | $146.31 | -$349.90 |
| NVDA|hyperliquid:xyz:NVDA|rh_lighter:15 | 249 | 0 | -$81.72 | $44.73 | $124.36 | -$250.81 |
| GOOGL|hyperliquid:xyz:GOOGL|rh_lighter:12 | 233 | 1 | -$72.35 | $41.67 | $116.36 | -$230.39 |
| META|hyperliquid:xyz:META|rh_lighter:13 | 218 | 8 | -$103.24 | $37.90 | $108.36 | -$249.51 |
| XAG|hyperliquid:xyz:SILVER|lighter:93 | 100 | 0 | -$13.19 | $17.96 | $49.93 | -$81.09 |
| SAMSUNGUSD|hyperliquid:xyz:SMSN|lighter:162 | 75 | 0 | -$31.96 | $13.29 | $36.96 | -$82.22 |
| AAPL|hyperliquid:xyz:AAPL|rh_lighter:10 | 59 | 0 | -$18.66 | $10.60 | $29.46 | -$58.72 |
| CASHCAT|lighter:221|hyperliquid:CASHCAT | 45 | 7 | -$111.89 | $38.06 | $22.46 | -$172.40 |
| MSFT|hyperliquid:xyz:MSFT|rh_lighter:14 | 42 | 0 | -$13.99 | $7.54 | $20.97 | -$42.51 |

## Forecast-policy diagnostic

Forecasts exist only on policies that entered. Their outcomes are shown separately from the primary baseline; calendar-window baseline rows are not matched counterpart trades.

| Policy | Settled attempts | Paired | Failed hedge | Forecasted closes | Mean forecast | Mean realized on forecasted | Net P&L | Calendar baseline |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| convergence | 27 | 4 | 22 | 26 | $0.599 | -$1.139 | -$29.61 | 1715 / -$1971.07 |
| conservative | 1 | 1 | 0 | 1 | $0.604 | -$2.704 | -$2.70 | 0 / $0.00 |
| confirmed | 0 | 0 | 0 | 0 | — | — | $0.00 | — |

Forecast cohorts among selected closes (retrospective, no baseline forecast imputation):

| Policy | Forecast USD | Closes | Wins | Failed hedges | Realized net |
|---|---|---:|---:|---:|---:|
| convergence | 0_to_0.5 | 14 | 0 | 11 | -$15.74 |
| convergence | 0.5_to_1 | 9 | 0 | 9 | -$10.42 |
| convergence | 1_or_more | 3 | 0 | 2 | -$3.45 |
| conservative | 0.5_to_1 | 1 | 0 | 0 | -$2.70 |

## Interpretation

This study can identify filters that avoided losses in this sample. It cannot establish that abstention improves future executions or that any selected filter is profitable. The recorded single-leg failures remain a separate risk from spread convergence.

## Limits

- Filters only retain or abstain from recorded fills and exits; a changed entry policy could receive different fills.
- The holdout is retrospective and all candidate families are exploratory; it is not prospective profit evidence.
- Using only shadow_baseline removes duplicate fee-variant rows, but routes and assets can remain correlated in time.
- Historical forecasts are present only for selected forecaster entries and cannot be imputed onto baseline attempts.
- Current market metadata supplies asset categories; unmapped historical pairs remain unmapped.
- The SQLite trade ring omits earlier history; ledger lifetime totals are not substituted for this retained sample.
