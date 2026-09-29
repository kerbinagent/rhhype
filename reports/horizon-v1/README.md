# Legacy horizon v1 observations

Both finite observers ran for forty minutes on 29 September 2026. Exact selected plans and stopped snapshots are preserved alongside this report. They sampled 12 physical pairs / 24 directed routes. Start times differ; these are not synchronized model-performance trials.

| Source | UTC interval | Anchors | Matched | Censored | Match fraction | Scored |
|---|---|---:|---:|---:|---:|---:|
| depth | 17:34:19–18:14:19 | 3568 | 792 | 2776 | 22.2% | 0 |
| bbo | 17:43:39–18:23:39 | 4309 | 3756 | 553 | 87.2% | 2748 |

No depth-route forecast met the fixed warmup requirement. BBO had 2,748 forward scored anchors. Stream shutdown invalidates routes, so pending anchors at the boundary enter censor counters; final warm-route counts are therefore not an estimate of how many routes warmed earlier.

## BBO forecast errors

| Frozen model | MAE bp | RMSE bp | Mean signed error bp |
|---|---:|---:|---:|
| historical_median | 1.1025 | 1.5415 | 0.0606 |
| persistence | 1.2477 | 1.7594 | -0.0020 |
| horizon_delta | 1.2532 | 1.7654 | -0.0085 |

Historical median had the lowest aggregate quote error in this pilot. This does not establish profitable selection of large basis deviations, correct original-size exits, or profitable delayed fills. Opposite directions share books, and neighboring outcome intervals overlap; the count is not a number of independent trials.

## Version limitation

Version 1 applied a 1 Hz historical-sampling gate before resolving pending anchors. It could discard a valid intervening future quote and then censor the anchor. Version 2 fixes this in a separate prospective run and adds a fourth forecast, per-route diagnostics, and frozen-row exports. Do not merge the two versions or present the old coverage deficit as proof an opportunity did not exist.

The coarse depth cadence is also poorly matched to a 12–16-second future window. Faster BBO supports better observation coverage, but provides only its displayed top-level size. Fees, original-quantity closing depth, fills and cash returns are outside this variable-quantity basis-level study.
