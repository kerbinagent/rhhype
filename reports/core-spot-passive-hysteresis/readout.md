# LIT inside-bid entry with cash-based active retention

Protocol frozen at `70f94e2`. Fresh capture **2026-10-01 18:04:31.139687–18:14:31.961323 UTC**: 600.822 seconds, one connection, no errors, 15,478 records and 1,733,015 compressed raw bytes. One $600 USDC portfolio; $100 target per leg. No orders sent.

## Result

**Three quotes, zero attributed fills, zero P&L, flat inventory and $600 final cash.** No rescues, unknown obligations, capital charges or funding payments.

All independent audits passed: three admissions, 14,977 reference rows, 133 active checks, three queue episodes, three first-eligible activations and cancellations, and a conservative request-count peak of three per66seconds. Actual entry values were zero; fill/exit checks are vacuous.

## What changed in observed behavior

The active-cash rule retained quotes below the5bp entry excursion on117checks. The unchanged clock gate or cash floor then canceled them:

| Quote | Rest before cancel | Cancellation | Source skew at cancel | Spot source age |
|---|---:|---|---:|---:|
| 1 | 1.096s | Pair skew | 259.311ms | 335.477ms |
| 2 | 0.049s | Forecast fell to+$0.009498 | 0.723ms | 98.820ms |
| 3 | 2.992s | Pair skew | 277.782ms | 346.072ms |

None received eligible public sell flow during its original active interval, including the cancellation delay. Quote1 activated behind100LIT of better-priced bids, quote2 inside with no displayed queue, quote3 behind580LIT of better bids and755.78LIT at its price. There were396ordinary live prints totaling$11,819.04; subscription backlog IDs were excluded and duplicates removed.

## Next sensitivity test

A separate prospective protocol can use a500ms source-and-receipt pair-skew gate while retaining the2second absolute age bound. This changes freshness eligibility, reference sampling, admission, active checks and hedge-anchor availability together; it is a different timing assumption and does not amend this250ms result.

The [official WebSocket reference](https://apidocs.lighter.xyz/docs/websocket-reference) describes50ms batching and state-change updates after an initial snapshot. Different last-change times on the two markets can therefore contribute to skew. This supports investigating the assumption; it is not proof that relaxing it produces executable profits.

Raw data, metadata, source pins, all results, audits and quote diagnostics are retained. Public-flow fills remain conditional on queue, clock and acknowledgment assumptions. Replay and independent audits ran at nice+10.
