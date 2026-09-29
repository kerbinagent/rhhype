# Python performance and quote cadence, 29 September 2026

This note compares the 14 scheduled production reviews from 16:06–20:26 UTC with two read-only production and contingent snapshots at 20:43:47 and 20:44:02 UTC. The compact inputs and exact timestamps are in [evidence.json](../reports/python-performance/evidence.json). This is an operational sample, not a load test or a before/after experiment.

## What the collector measured

| Observation | CPU, percent of one core | Recent p95 event-loop lag | Book events/s |
| --- | ---: | ---: | ---: |
| 14 production reviews, median (range) | 61.38% (51.56–81.87%) | 13.45 ms (6.79–65.50 ms) | 910 (819–1,109) |
| Production, 20:43:47 UTC | 45.04% | 6.57 ms | 556 |
| Production, 20:44:02 UTC | 50.99% | 7.39 ms | 709 |
| Contingent trial, same two reads | CPU not instrumented | 1.87 / 1.87 ms | 114 over the 15.09 s between snapshots |

All four production feeds were connected in every scheduled review. The 16:46 review had 65.50 ms p95 lag at 59.83% of one core; the 18:06 review had 47.49 ms at 81.87% of one core. Those are two distinct high-lag windows, so CPU load alone does not explain every tail event. The review cadence is about 20 minutes and misses intervening spikes. CPU is process time over each report interval, book rate is a report-interval rate, and lag p95 uses up to 1,200 heartbeat samples at a nominal 20 Hz (roughly one recent minute). Their windows differ. A periodic checkpoint can affect the maximum while leaving p95 low.

At the two read times, production SQLite was 53.22 and 53.21 MB, WAL 0, against a 128 MiB combined budget; the main file shrank 16 KiB over 15 seconds, which does not establish a growth rate. Its retained caps were 20,000 events, 5,000 trades and 2,000 evidence rows. The younger contingent database was 475 and 512 KiB, WAL 0, under its own 128 MiB budget. Its previous completed checkpoint pauses were 42.78 and 25.72 ms. Its 114 books/s interval comes from a different selected market set, so it is not a throughput comparison with production. Contingent CPU is absent from its snapshot.

## What the simulated delay measures

The [20:26 review](../data/strategy-reviews/review-20260929T202630.918654Z.json) reports 91 retained paired Standard completions with 1.261 s median and 1.885 s p95 signal-to-paired-entry time. This is paper intent and eligible-quote observation time, not actual order latency or network RTT. The model includes venue/network delay assumptions (150 ms for HL and 400 ms for Standard Lighter/RH before waiting for a book), then waits for valid observations. The p95 loop lag in that review was 15.82 ms. These differently sampled quantities cannot be subtracted to assign a precise cause, but the measured scheduling lag is much smaller than the observed paper entry time. Faster Python alone has no measured path to remove the full second.

The [feed cadence study](hyperliquid-feed-cadence.md) found median Hyperliquid BBO receipt intervals of 119–120 ms for BTC/ETH, versus 5,400 ms for L2; Core and RH book intervals were about 50–51 ms. BBO is one level and only supports the actual quantity when displayed size covers it. Receipt minus source time was about 296–298 ms for HL BBO in that capture; it mixes clock relation and publication delay and is not measured RTT. The production monitor already uses WebSocket feeds and bounded targeted REST refresh. Its current quote mode in these snapshots is depth, so the measured BBO cadence is a candidate observation improvement, not an achieved production improvement.

The current [Hyperliquid subscription documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) also specifies an optional `l2Book` `fast` flag with five levels versus twenty for slow. A controlled same-market fast/slow capture is pending; no cadence or economic benefit has been measured for that option yet. A shallower book must still pass the actual quantity and depth gate. [Official rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) include 1,200 REST weight/minute per IP, weight 2 for `l2Book` info calls, and WebSocket connection/subscription/message caps. These constrain any blanket polling increase.

## Smallest next steps

1. Use existing position and book evidence to split paper entry time by venue into configured intent delay, time to the first eligible source/receipt update, and time spent waiting for sufficient displayed depth. Keep failed hedges and missing observations in the denominator. This identifies whether the next change should target feed cadence, depth coverage or the paper execution rule.
2. Finish the same-market `fast:true`/slow L2 probe, then compare source timestamps, receipt intervals, five-level size coverage for the real trade quantity, and event-loop load. Test one isolated pilot before considering production. Keep BBO as a complete one-level quote only when it covers the quantity; never attach stale deeper levels.
3. Preserve priority-gated REST refresh for due intents and held exposure. Increase request cadence only for a measured freshness bottleneck within the published limits; record requests, successful fresh books, and still-missing fills. More calls by themselves do not prove better exits or P&L.
4. If repeated windows approach the monitor's 85% one-core or 50 ms p95 diagnostic thresholds, profile that exact workload. The prior [offline probe profile](../reports/strategy-experiments/probe-profile.md) measured a 1.51× improvement in one book-capture component and about 19.7 ms for a 1.08 MB checkpoint deepcopy; it did not measure a whole-process speedup. Treat checkpoint copy as a candidate only if pause/lag telemetry links it to current tails and preserve snapshot consistency.

Additional Python threads are already useful for blocking production storage and I/O. They have no measured benefit for the seconds-scale paper fill interval shown here. Move CPU-heavy analysis to a separate process only after profiling shows sustained collector contention; retain bounded queues and timestamped evidence so any improvement is measurable.
