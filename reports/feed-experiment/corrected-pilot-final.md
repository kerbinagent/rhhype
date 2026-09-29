# Depth versus BBO paper pilot

Generated: 2026-09-29T18:46:21+00:00 · status: **duration_reached**

Common retained-trade cutoff: 2026-09-29T18:45:52+00:00 (checkpoint skew 0.00 s).

Config equal: **True**. Pair counts: depth 21, BBO 21. Flags: retained_trades_pruned_or_query_limited.

## Lifetime ledger totals

Each row is an independent paper portfolio. The totals are at each run's own checkpoint.

| Portfolio | Feed | Attempts | Closed | Exact P&L | Est. P&L | Total P&L | Wins | Losses | Aborted | Mean/trade |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| confirmed | depth | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| confirmed | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| conservative | depth | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| conservative | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| convergence | depth | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| convergence | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| cooldown | depth | 12 | 12 | -12.36 | +0.00 | -12.36 | 0 | 12 | 0 | -1.03 |
| cooldown | bbo | 114 | 113 | -123.07 | +0.00 | -123.07 | 0 | 113 | 1 | -1.09 |
| plus | depth | 1303 | 1299 | -1,195.41 | +0.00 | -1,195.41 | 6 | 1293 | 2 | -0.92 |
| plus | bbo | 761 | 757 | -846.56 | +0.00 | -846.56 | 1 | 756 | 1 | -1.12 |
| premium | depth | 51 | 50 | -78.42 | +0.00 | -78.42 | 1 | 49 | 1 | -1.57 |
| premium | bbo | 76 | 76 | -137.72 | +0.00 | -137.72 | 0 | 76 | 0 | -1.81 |
| shadow_baseline | depth | 1604 | 1599 | -1,274.90 | +0.00 | -1,274.90 | 9 | 1590 | 2 | -0.80 |
| shadow_baseline | bbo | 855 | 852 | -840.79 | +0.00 | -840.79 | 0 | 852 | 0 | -0.99 |
| standard | depth | 1604 | 1599 | -1,274.90 | +0.00 | -1,274.90 | 9 | 1590 | 2 | -0.80 |
| standard | bbo | 855 | 852 | -840.79 | +0.00 | -840.79 | 0 | 852 | 0 | -0.99 |

## Outstanding at each checkpoint

Aged one-lot residuals are a known execution censoring risk for this pilot.

| Portfolio | Feed | Filled exposure | Entry pending | Exit pending | Funding pending | Oldest age s | Oldest exit wait s | Aged one-lot residuals |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| confirmed | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| confirmed | bbo | 0 | 0 | 0 | 0 | ? | ? | 0 |
| conservative | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| conservative | bbo | 0 | 0 | 0 | 0 | ? | ? | 0 |
| convergence | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| convergence | bbo | 0 | 0 | 0 | 0 | ? | ? | 0 |
| cooldown | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| cooldown | bbo | 0 | 0 | 0 | 0 | ? | ? | 0 |
| plus | depth | 0 | 0 | 0 | 2 | 5 | ? | 0 |
| plus | bbo | 3 | 0 | 0 | 0 | 12 | ? | 0 |
| premium | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| premium | bbo | 0 | 0 | 0 | 0 | ? | ? | 0 |
| shadow_baseline | depth | 1 | 0 | 1 | 2 | 5 | ? | 0 |
| shadow_baseline | bbo | 3 | 0 | 0 | 0 | 10 | ? | 0 |
| standard | depth | 1 | 0 | 1 | 2 | 5 | ? | 0 |
| standard | bbo | 3 | 0 | 0 | 0 | 10 | ? | 0 |

## Retained closed-trade diagnostics

These rows use only trades retained in SQLite at the earlier checkpoint cutoff.

| Portfolio | Feed | Common retained / lifetime | Common fraction | Paired | Failed hedge | Entry ms median | Exit ms median | Full-size entry gap $ median |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| confirmed | depth | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| confirmed | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| conservative | depth | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| conservative | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| convergence | depth | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| convergence | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| cooldown | depth | 4 / 12 | 33.3% | 0 | 4 | ? | ? | ? |
| cooldown | bbo | 85 / 113 | 75.2% | 73 | 12 | 666 (n=73) | 724 (n=73) | -0.00 |
| plus | depth | 552 / 1299 | 42.5% | 0 | 552 | ? | ? | ? |
| plus | bbo | 563 / 757 | 74.4% | 442 | 121 | 666 (n=442) | 739 (n=442) | +0.00 |
| premium | depth | 14 / 50 | 28.0% | 0 | 14 | ? | ? | ? |
| premium | bbo | 58 / 76 | 76.3% | 31 | 27 | 582 (n=31) | 702 (n=31) | -0.16 |
| shadow_baseline | depth | 711 / 1599 | 44.5% | 0 | 711 | ? | ? | ? |
| shadow_baseline | bbo | 641 / 852 | 75.2% | 525 | 116 | 661 (n=525) | 727 (n=525) | +0.00 |
| standard | depth | 711 / 1599 | 44.5% | 0 | 711 | ? | ? | ? |
| standard | bbo | 642 / 852 | 75.4% | 526 | 116 | 661 (n=526) | 727 (n=526) | +0.00 |

## Performance snapshots

Performance figures are from separate JSON snapshot timestamps.

| Feed | Snapshot UTC | CPU % of one core | p95 loop lag ms | Book events/s |
|---|---|---:|---:|---:|
| depth | 2026-09-29T18:45:52+00:00 | 26.6 | 3.0 | 202 |
| bbo | 2026-09-29T18:45:52+00:00 | 28.0 | 4.5 | 245 |

## 100 ms latency probe

Cumulative counts at each JSON snapshot time. The aggregate repeats correlated market observations across fee scenarios; it is not a count of independent opportunities. Survived means the delayed opening edge stayed positive, not that a completed trade profited.

| Feed | Snapshot UTC | Triggered | Observed | Survived | Missing | Pending | Observed coverage | Actual delay mean ms | Min / max ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| depth | 2026-09-29T18:45:52+00:00 | 3135 | 0 | 0 | 3135 | 0 | 0.0% | ? | ? / ? |
| bbo | 2026-09-29T18:45:52+00:00 | 6297 | 6090 | 4116 | 207 | 0 | 96.7% | 573.7 | 323.1 / 1892.3 |

## Hyperliquid entry provenance

Counts are retained closed-trade legs at the common cutoff. Missing observations limit source comparisons.

| Portfolio | Feed | Observed / filled legs | HL filled | HL BBO | HL l2book | HL missing |
|---|---|---:|---:|---:|---:|---:|
| cooldown | depth | 4 / 4 | 0 | 0 | 0 | 0 |
| cooldown | bbo | 170 / 170 | 85 | 85 | 0 | 0 |
| plus | depth | 552 / 552 | 0 | 0 | 0 | 0 |
| plus | bbo | 1114 / 1114 | 551 | 534 | 17 | 0 |
| premium | depth | 14 / 14 | 0 | 0 | 0 | 0 |
| premium | bbo | 115 / 115 | 57 | 57 | 0 | 0 |
| shadow_baseline | depth | 711 / 711 | 0 | 0 | 0 | 0 |
| shadow_baseline | bbo | 1270 / 1270 | 629 | 615 | 14 | 0 |
| standard | depth | 711 / 711 | 0 | 0 | 0 | 0 |
| standard | bbo | 1272 / 1272 | 630 | 616 | 14 | 0 |

## Retained route examples

Top rows by retained closed count. Category and P&L are for one portfolio and route at a time.

| Portfolio | Route | Category | Depth closed / P&L | BBO closed / P&L |
|---|---|---|---:|---:|
| standard | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 206 / -170.20 | 177 / -179.84 |
| shadow_baseline | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 206 / -170.20 | 176 / -178.75 |
| plus | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 206 / -190.78 | 167 / -188.27 |
| shadow_baseline | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 195 / -167.44 | 151 / -168.65 |
| standard | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 195 / -167.44 | 151 / -168.65 |
| shadow_baseline | XAG\|hyperliquid:xyz:SILVER\|lighter:93 | RWA/xyz | 143 / -90.46 | 172 / -134.22 |
| standard | XAG\|hyperliquid:xyz:SILVER\|lighter:93 | RWA/xyz | 143 / -90.46 | 172 / -134.22 |
| plus | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 152 / -146.15 | 144 / -177.42 |
| shadow_baseline | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 155 / -116.46 | 126 / -121.35 |
| standard | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 155 / -116.46 | 126 / -121.35 |

## Reading this result

No automatic feed promotion; evaluate after a matched, sufficiently populated run.

Full source counts and crypto/RWA groups are in the JSON under each portfolio's retained diagnostics.

### Limits

- Cumulative ledger totals are each run's latest checkpoint and cannot be rewound to the common cutoff.
- Retained trade diagnostics use the common earlier checkpoint cutoff and may omit pruned trades.
- Depth and BBO portfolios share opportunities; portfolio P&L must not be summed as independent returns.
- The feed cohorts may have different numbers and mixes of attempted trades; net P&L alone cannot rank feeds.
- Public displayed quotes and paper fills do not prove executable orders.
- CPU and p95 lag are separate snapshot observations, not one synchronized measurement.
- Latency probes are cumulative at each JSON snapshot time, separate from ledger checkpoint times. Fee-scenario observations share market signals and are correlated.
- Probe survival means the delayed opening edge remained positive; it is not completed-trade profitability. Only count, sum, minimum, and maximum delay are recorded, so no delay p95 is available.
- Entry-edge deterioration is measured only for paired, full planned size; exit delay requires exit_requested_at.
- Only trades settled by the common earlier checkpoint enter retained comparisons; open and unsettled positions stay separate.
