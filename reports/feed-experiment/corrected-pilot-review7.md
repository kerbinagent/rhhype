# Depth versus BBO paper pilot

Generated: 2026-09-29T18:26:42+00:00 · status: **interim**

Common retained-trade cutoff: 2026-09-29T18:26:41+00:00 (checkpoint skew 0.45 s).

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
| cooldown | depth | 8 | 8 | -9.24 | +0.00 | -9.24 | 0 | 8 | 0 | -1.15 |
| cooldown | bbo | 63 | 63 | -73.00 | +0.00 | -73.00 | 0 | 63 | 0 | -1.16 |
| plus | depth | 733 | 728 | -672.97 | +0.00 | -672.97 | 6 | 722 | 2 | -0.92 |
| plus | bbo | 431 | 428 | -482.74 | +0.00 | -482.74 | 1 | 427 | 0 | -1.13 |
| premium | depth | 37 | 36 | -55.10 | +0.00 | -55.10 | 1 | 35 | 1 | -1.53 |
| premium | bbo | 45 | 44 | -83.64 | +0.00 | -83.64 | 0 | 44 | 0 | -1.90 |
| shadow_baseline | depth | 871 | 865 | -695.54 | +0.00 | -695.54 | 8 | 857 | 2 | -0.80 |
| shadow_baseline | bbo | 470 | 466 | -465.47 | +0.00 | -465.47 | 0 | 466 | 0 | -1.00 |
| standard | depth | 871 | 865 | -695.54 | +0.00 | -695.54 | 8 | 857 | 2 | -0.80 |
| standard | bbo | 470 | 466 | -465.47 | +0.00 | -465.47 | 0 | 466 | 0 | -1.00 |

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
| plus | depth | 3 | 3 | 0 | 0 | 1 | ? | 0 |
| plus | bbo | 3 | 0 | 0 | 0 | 6 | ? | 0 |
| premium | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| premium | bbo | 1 | 0 | 0 | 0 | 3 | ? | 0 |
| shadow_baseline | depth | 4 | 4 | 0 | 0 | 1 | ? | 0 |
| shadow_baseline | bbo | 4 | 0 | 0 | 0 | 10 | ? | 0 |
| standard | depth | 4 | 4 | 0 | 0 | 1 | ? | 0 |
| standard | bbo | 4 | 0 | 0 | 0 | 10 | ? | 0 |

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
| cooldown | depth | 7 / 8 | 87.5% | 0 | 7 | ? | ? | ? |
| cooldown | bbo | 63 / 63 | 100.0% | 52 | 11 | 591 (n=52) | 694 (n=52) | -0.00 |
| plus | depth | 583 / 728 | 80.1% | 0 | 583 | ? | ? | ? |
| plus | bbo | 428 / 428 | 100.0% | 322 | 106 | 665 (n=322) | 683 (n=322) | +0.00 |
| premium | depth | 16 / 36 | 44.4% | 0 | 16 | ? | ? | ? |
| premium | bbo | 44 / 44 | 100.0% | 21 | 23 | 553 (n=21) | 710 (n=21) | -0.04 |
| shadow_baseline | depth | 691 / 865 | 79.9% | 0 | 691 | ? | ? | ? |
| shadow_baseline | bbo | 466 / 466 | 100.0% | 367 | 99 | 641 (n=367) | 690 (n=367) | +0.00 |
| standard | depth | 691 / 865 | 79.9% | 0 | 691 | ? | ? | ? |
| standard | bbo | 466 / 466 | 100.0% | 367 | 99 | 641 (n=367) | 690 (n=367) | +0.00 |

## Performance snapshots

Performance figures are from separate JSON snapshot timestamps.

| Feed | Snapshot UTC | CPU % of one core | p95 loop lag ms | Book events/s |
|---|---|---:|---:|---:|
| depth | 2026-09-29T18:26:41+00:00 | 20.5 | 2.0 | 215 |
| bbo | 2026-09-29T18:26:41+00:00 | 25.4 | 2.4 | 308 |

## 100 ms latency probe

Cumulative counts at each JSON snapshot time. The aggregate repeats correlated market observations across fee scenarios; it is not a count of independent opportunities. Survived means the delayed opening edge stayed positive, not that a completed trade profited.

| Feed | Snapshot UTC | Triggered | Observed | Survived | Missing | Pending | Observed coverage | Actual delay mean ms | Min / max ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| depth | 2026-09-29T18:26:41+00:00 | 1772 | 0 | 0 | 1764 | 8 | 0.0% | ? | ? / ? |
| bbo | 2026-09-29T18:26:41+00:00 | 3537 | 3448 | 2318 | 89 | 0 | 97.5% | 566.8 | 323.1 / 1742.0 |

## Hyperliquid entry provenance

Counts are retained closed-trade legs at the common cutoff. Missing observations limit source comparisons.

| Portfolio | Feed | Observed / filled legs | HL filled | HL BBO | HL l2book | HL missing |
|---|---|---:|---:|---:|---:|---:|
| cooldown | depth | 7 / 7 | 0 | 0 | 0 | 0 |
| cooldown | bbo | 124 / 124 | 62 | 62 | 0 | 0 |
| plus | depth | 583 / 583 | 0 | 0 | 0 | 0 |
| plus | bbo | 846 / 846 | 419 | 407 | 12 | 0 |
| premium | depth | 16 / 16 | 0 | 0 | 0 | 0 |
| premium | bbo | 87 / 87 | 43 | 42 | 1 | 0 |
| shadow_baseline | depth | 691 / 691 | 0 | 0 | 0 | 0 |
| shadow_baseline | bbo | 919 / 919 | 453 | 448 | 5 | 0 |
| standard | depth | 691 / 691 | 0 | 0 | 0 | 0 |
| standard | bbo | 919 / 919 | 453 | 448 | 5 | 0 |

## Retained route examples

Top rows by retained closed count. Category and P&L are for one portfolio and route at a time.

| Portfolio | Route | Category | Depth closed / P&L | BBO closed / P&L |
|---|---|---|---:|---:|
| plus | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 183 / -170.14 | 122 / -137.19 |
| shadow_baseline | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 178 / -147.06 | 124 / -125.75 |
| standard | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 178 / -147.06 | 124 / -125.75 |
| plus | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 169 / -160.48 | 100 / -120.54 |
| shadow_baseline | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 170 / -144.31 | 99 / -111.15 |
| standard | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 170 / -144.31 | 99 / -111.15 |
| shadow_baseline | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 166 / -124.45 | 98 / -96.34 |
| standard | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 166 / -124.45 | 98 / -96.34 |
| shadow_baseline | XAG\|hyperliquid:xyz:SILVER\|lighter:93 | RWA/xyz | 142 / -85.40 | 118 / -90.34 |
| standard | XAG\|hyperliquid:xyz:SILVER\|lighter:93 | RWA/xyz | 142 / -85.40 | 118 / -90.34 |

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
