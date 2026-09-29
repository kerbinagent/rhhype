# Depth versus BBO paper pilot

Generated: 2026-09-29T18:03:11+00:00 · status: **early_stop_due_quantity_bug**

Common retained-trade cutoff: 2026-09-29T18:01:20+00:00 (checkpoint skew 0.00 s).

Config equal: **True**. Pair counts: depth 21, BBO 21. Flags: aged_one_lot_exit_residual_censoring, early_stop_due_quantity_bug.

## Lifetime ledger totals

Each row is an independent paper portfolio. The totals are at each run's own checkpoint.

| Portfolio | Feed | Attempts | Closed | Exact P&L | Est. P&L | Total P&L | Wins | Losses | Aborted | Mean/trade |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| confirmed | depth | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| confirmed | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| conservative | depth | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| conservative | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| convergence | depth | 2 | 1 | -0.81 | +0.00 | -0.81 | 0 | 1 | 1 | -0.81 |
| convergence | bbo | 0 | 0 | +0.00 | +0.00 | +0.00 | 0 | 0 | 0 | ? |
| cooldown | depth | 15 | 15 | -17.58 | +0.00 | -17.58 | 0 | 15 | 0 | -1.17 |
| cooldown | bbo | 39 | 38 | -51.12 | +0.00 | -51.12 | 0 | 38 | 0 | -1.35 |
| plus | depth | 473 | 471 | -501.58 | -0.93 | -502.51 | 1 | 470 | 1 | -1.07 |
| plus | bbo | 186 | 182 | -249.31 | -1.68 | -250.99 | 0 | 182 | 0 | -1.38 |
| premium | depth | 26 | 25 | -50.82 | +0.00 | -50.82 | 1 | 24 | 1 | -2.03 |
| premium | bbo | 30 | 29 | -62.31 | +0.00 | -62.31 | 0 | 29 | 0 | -2.15 |
| shadow_baseline | depth | 566 | 562 | -532.07 | -0.83 | -532.90 | 1 | 561 | 1 | -0.95 |
| shadow_baseline | bbo | 84 | 80 | -92.27 | +0.00 | -92.27 | 0 | 80 | 0 | -1.15 |
| standard | depth | 566 | 562 | -532.07 | -0.83 | -532.90 | 1 | 561 | 1 | -0.95 |
| standard | bbo | 84 | 80 | -92.27 | +0.00 | -92.27 | 0 | 80 | 0 | -1.15 |

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
| cooldown | bbo | 1 | 0 | 1 | 0 | 259 | 249 | 1 |
| plus | depth | 1 | 0 | 1 | 0 | 3 | ? | 0 |
| plus | bbo | 4 | 0 | 3 | 0 | 819 | 808 | 2 |
| premium | depth | 0 | 0 | 0 | 0 | ? | ? | 0 |
| premium | bbo | 1 | 0 | 0 | 0 | 7 | ? | 0 |
| shadow_baseline | depth | 3 | 0 | 3 | 0 | 3 | ? | 0 |
| shadow_baseline | bbo | 4 | 0 | 4 | 0 | 856 | 845 | 4 |
| standard | depth | 3 | 0 | 3 | 0 | 3 | ? | 0 |
| standard | bbo | 4 | 0 | 4 | 0 | 856 | 845 | 4 |

## Retained closed-trade diagnostics

These rows use only trades retained in SQLite at the earlier checkpoint cutoff.

| Portfolio | Feed | Common retained / lifetime | Common fraction | Paired | Failed hedge | Entry ms median | Exit ms median | Full-size entry gap $ median |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| confirmed | depth | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| confirmed | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| conservative | depth | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| conservative | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| convergence | depth | 1 / 1 | 100.0% | 0 | 1 | ? | ? | ? |
| convergence | bbo | 0 / 0 | ? | 0 | 0 | ? | ? | ? |
| cooldown | depth | 15 / 15 | 100.0% | 0 | 15 | ? | ? | ? |
| cooldown | bbo | 38 / 38 | 100.0% | 23 | 15 | 692 (n=23) | 657 (n=23) | -0.08 |
| plus | depth | 471 / 471 | 100.0% | 2 | 469 | 1837 (n=2) | 797 (n=2) | -0.01 |
| plus | bbo | 182 / 182 | 100.0% | 118 | 64 | 626 (n=118) | 702 (n=118) | +0.00 |
| premium | depth | 25 / 25 | 100.0% | 0 | 25 | ? | ? | ? |
| premium | bbo | 29 / 29 | 100.0% | 9 | 20 | 537 (n=9) | 2663 (n=9) | -0.27 |
| shadow_baseline | depth | 562 / 562 | 100.0% | 2 | 560 | 1837 (n=2) | 797 (n=2) | -0.01 |
| shadow_baseline | bbo | 80 / 80 | 100.0% | 54 | 26 | 694 (n=54) | 788 (n=54) | +0.00 |
| standard | depth | 562 / 562 | 100.0% | 2 | 560 | 1837 (n=2) | 797 (n=2) | -0.01 |
| standard | bbo | 80 / 80 | 100.0% | 54 | 26 | 694 (n=54) | 788 (n=54) | +0.00 |

## Performance snapshots

Performance figures are from separate JSON snapshot timestamps.

| Feed | Snapshot UTC | CPU % of one core | p95 loop lag ms | Book events/s |
|---|---|---:|---:|---:|
| depth | 2026-09-29T18:01:20+00:00 | 24.8 | 2.3 | 324 |
| bbo | 2026-09-29T18:01:20+00:00 | 34.7 | 3.3 | 401 |

## Hyperliquid entry provenance

Counts are retained closed-trade legs at the common cutoff. Missing observations limit source comparisons.

| Portfolio | Feed | Observed / filled legs | HL filled | HL BBO | HL l2book | HL missing |
|---|---|---:|---:|---:|---:|---:|
| convergence | depth | 1 / 1 | 0 | 0 | 0 | 0 |
| cooldown | depth | 15 / 15 | 0 | 0 | 0 | 0 |
| cooldown | bbo | 75 / 75 | 38 | 38 | 0 | 0 |
| plus | depth | 474 / 474 | 3 | 0 | 3 | 0 |
| plus | bbo | 360 / 360 | 180 | 174 | 6 | 0 |
| premium | depth | 25 / 25 | 0 | 0 | 0 | 0 |
| premium | bbo | 56 / 56 | 28 | 28 | 0 | 0 |
| shadow_baseline | depth | 565 / 565 | 3 | 0 | 3 | 0 |
| shadow_baseline | bbo | 159 / 159 | 79 | 77 | 2 | 0 |
| standard | depth | 565 / 565 | 3 | 0 | 3 | 0 |
| standard | bbo | 159 / 159 | 79 | 77 | 2 | 0 |

## Retained route examples

Top rows by retained closed count. Category and P&L are for one portfolio and route at a time.

| Portfolio | Route | Category | Depth closed / P&L | BBO closed / P&L |
|---|---|---|---:|---:|
| plus | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 144 / -142.80 | 82 / -100.94 |
| plus | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 176 / -162.48 | 23 / -25.22 |
| shadow_baseline | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 163 / -145.69 | 26 / -28.70 |
| standard | META\|hyperliquid:xyz:META\|rh_lighter:13 | RWA/xyz | 163 / -145.69 | 26 / -28.70 |
| shadow_baseline | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 176 / -145.42 | 11 / -11.01 |
| standard | XAG\|hyperliquid:xyz:SILVER\|rh_lighter:41 | RWA/xyz | 176 / -145.42 | 11 / -11.01 |
| shadow_baseline | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 108 / -80.51 | 13 / -12.71 |
| standard | NVDA\|hyperliquid:xyz:NVDA\|rh_lighter:15 | RWA/xyz | 108 / -80.51 | 13 / -12.71 |
| plus | CASHCAT\|lighter:221\|hyperliquid:CASHCAT | crypto | 72 / -126.20 | 47 / -92.32 |
| shadow_baseline | CASHCAT\|lighter:221\|hyperliquid:CASHCAT | crypto | 81 / -134.63 | 16 / -29.26 |

## Reading this result

Do not rank feeds from this pilot: aged one-lot exit residuals censor closed-trade outcomes. Repeat both feeds after the execution fix.

Full source counts and crypto/RWA groups are in the JSON under each portfolio's retained diagnostics.

### Limits

- Cumulative ledger totals are each run's latest checkpoint and cannot be rewound to the common cutoff.
- Retained trade diagnostics use the common earlier checkpoint cutoff and may omit pruned trades.
- Depth and BBO portfolios share opportunities; portfolio P&L must not be summed as independent returns.
- The feed cohorts may have different numbers and mixes of attempted trades; net P&L alone cannot rank feeds.
- Public displayed quotes and paper fills do not prove executable orders.
- CPU and p95 lag are separate snapshot observations, not one synchronized measurement.
- Entry-edge deterioration is measured only for paired, full planned size; exit delay requires exit_requested_at.
- Only trades settled by the common earlier checkpoint enter retained comparisons; open and unsettled positions stay separate.
