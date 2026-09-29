# Horizon model v2: stopped snapshot analysis

Snapshot updated: `1790707522.2188182`. Metric: 12–16 second forward executable closing-spread quote error, bps.

## Scored coverage and censoring

All-run anchors: 4325; matched: 3744; scored: 2797; warmup: 1438; censored: 581; pending at stop: 0.

Censor reasons: `{"other": 22, "outcome_missing": 559}`.

## All-run model errors

Primary descriptive ranking: all-run MAE on equal scored counts; tie-break RMSE, then fixed model order.

| Model | Scored | MAE bps | RMSE bps | MAE gain vs persistence bps |
|---|---:|---:|---:|---:|
| historical_median | 2797 | 1.057 | 1.477 | 0.037 |
| persistence | 2797 | 1.094 | 1.538 | 0.000 |
| horizon_delta | 2797 | 1.101 | 1.545 | -0.007 |
| conditional_linear | 2797 | 0.927 | 1.286 | 0.167 |

Ranking: `['conditional_linear', 'historical_median', 'persistence', 'horizon_delta']`. Equal model scored counts: `True`.

## Retained-row analysis

Retained mature rows: 3744 of 3744; retained scored: 2797 of 2797. Export truncated: `False`; reported dropped: 0.

Percentiles and route/block results use retained scored rows only. Each model is scored on the same anchors; positive MAE gain means lower absolute error than persistence.

| Model | p50 abs bps | p90 abs bps | Retained MAE bps | Paired MAE gain bps |
|---|---:|---:|---:|---:|
| historical_median | 0.779 | 2.362 | 1.057 | 0.037 |
| persistence | 0.792 | 2.461 | 1.094 | 0.000 |
| horizon_delta | 0.796 | 2.471 | 1.101 | -0.007 |
| conditional_linear | 0.687 | 2.045 | 0.927 | 0.167 |

## Directed routes

| Group | Scored | Persistence MAE | Conditional linear MAE | Conditional gain |
|---|---:|---:|---:|---:|
| BTC\|hyperliquid:BTC\|lighter:1 | 145 | 0.890 | 0.658 | 0.232 |
| BTC\|lighter:1\|hyperliquid:BTC | 145 | 0.807 | 0.618 | 0.189 |
| COIN\|hyperliquid:xyz:COIN\|lighter:109 | 84 | 1.108 | 1.040 | 0.068 |
| COIN\|lighter:109\|hyperliquid:xyz:COIN | 85 | 1.126 | 0.884 | 0.242 |
| ETH\|hyperliquid:ETH\|lighter:0 | 145 | 1.181 | 0.988 | 0.193 |
| ETH\|lighter:0\|hyperliquid:ETH | 145 | 1.283 | 1.032 | 0.251 |
| HYPE\|hyperliquid:HYPE\|lighter:24 | 142 | 1.322 | 1.283 | 0.039 |
| HYPE\|lighter:24\|hyperliquid:HYPE | 142 | 1.237 | 1.154 | 0.083 |
| META\|hyperliquid:xyz:META\|lighter:117 | 143 | 1.108 | 1.031 | 0.077 |
| META\|lighter:117\|hyperliquid:xyz:META | 145 | 0.982 | 0.839 | 0.143 |
| NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | 145 | 0.854 | 0.849 | 0.005 |
| NVDA\|rh_lighter:15\|hyperliquid:xyz:NVDA | 145 | 0.850 | 0.821 | 0.029 |
| SOL\|hyperliquid:SOL\|lighter:2 | 147 | 1.103 | 0.817 | 0.287 |
| SOL\|lighter:2\|hyperliquid:SOL | 147 | 1.198 | 0.896 | 0.302 |
| XAG\|hyperliquid:xyz:SILVER\|lighter:93 | 148 | 0.650 | 0.597 | 0.054 |
| XAG\|lighter:93\|hyperliquid:xyz:SILVER | 148 | 0.638 | 0.583 | 0.055 |
| XRP\|hyperliquid:XRP\|lighter:7 | 148 | 1.093 | 0.964 | 0.129 |
| XRP\|lighter:7\|hyperliquid:XRP | 148 | 1.200 | 0.969 | 0.231 |
| ZEC\|hyperliquid:ZEC\|lighter:90 | 150 | 1.633 | 1.274 | 0.360 |
| ZEC\|lighter:90\|hyperliquid:ZEC | 150 | 1.619 | 1.278 | 0.340 |

## Five-minute anchor-time blocks (UTC)

| Group | Scored | Persistence MAE | Conditional linear MAE | Conditional gain |
|---|---:|---:|---:|---:|
| 1790705400 | 92 | 0.934 | 0.833 | 0.101 |
| 1790705700 | 430 | 1.105 | 0.966 | 0.139 |
| 1790706000 | 455 | 1.108 | 0.954 | 0.154 |
| 1790706300 | 445 | 0.869 | 0.791 | 0.077 |
| 1790706600 | 446 | 1.176 | 0.944 | 0.232 |
| 1790706900 | 460 | 1.162 | 0.935 | 0.227 |
| 1790707200 | 451 | 1.181 | 0.993 | 0.189 |
| 1790707500 | 18 | 0.900 | 0.902 | -0.001 |

Opposite directions and adjacent 12–16 second outcomes can be correlated. No independent significance or cash-profit inference is made. Per-block censor coverage is unavailable from this snapshot.
