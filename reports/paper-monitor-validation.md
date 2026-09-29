# Streaming paper monitor validation

2026-09-29. Implementation and restart validation, not an estimate of expected trading returns.

## Result

**85 tests pass.** Live validation ran for seven minutes, then resumed the same saved portfolios for four more minutes. All validation collectors are stopped. The user's earlier collector and `data/monitor` results were left untouched.

| Measurement | Observed |
|---|---:|
| Matched venue comparisons | 116 |
| Distinct underlying symbols | 67 |
| Native-Hyperliquid / XYZ symbols | 39 / 28 |
| Book events over 660 configured seconds | 554,556 (~840/s) |
| Final session event-loop lag, recent p95 | 12.75ms |
| Final resident memory | 117.95MiB |
| SQLite main file / WAL at stop | 3.96MiB / 0 |
| Retained evidence | 2,000 records, within configured cap |
| Completed paper trades across scenarios | 21 |
| Still-open paper positions | 12, durably saved |
| Pre-restart positions recovered and subsequently closed | All 11 |
| Pending Aster funding lookups resolved after restart | 2 |

The universe included BTC, ETH, SOL and 36 other native-HL symbols; equities including NVDA, MSFT, AMD and Korean stocks; US100/US500/SOXL index or ETF exposure; and gold, silver and oil contracts. No FX pair passed the current overlap/turnover filters. `markets.json` records every exact comparison and its lot, collateral, volume and fee metadata. Symbol overlap does not remove index, corporate-action or contract-basis risk.

## The old entry tally does not survive position accounting

These are **separate portfolios**, each with $20,000 prefunded capital and $1,000 maximum per leg. Never add their P&L together.

| Account scenario | Closed trades | Net closed paper P&L | Winning sum | Losing sum |
|---|---:|---:|---:|---:|
| Standard | 8 | −$9.18 | $0.00 | −$9.18 |
| Plus | 8 | −$11.38 | $0.00 | −$11.38 |
| Premium | 5 | −$13.56 | $0.00 | −$13.56 |

All reported closed outcomes have complete modeled costs. This live window did not cross a UTC funding boundary, so it does not validate live hourly funding estimation; 14 funding tests cover signs, missing rates, boundaries, partial-close quantities through runtime tests, sampled references and cache behavior. Twelve positions were still open at shutdown, so the table is not the final return of every trade initiated. Open marks become unknown after feed shutdown; the engine does not fabricate liquidation prices.

Two Premium entries (USELESS and PUMP against Aster) filled only the Aster leg after Hyperliquid rejected the post-delay book's price/depth. The filled legs were flattened, their fees and losses retained, and funding stayed pending until a successful history lookup. The other completed trades exercised five-minute holdings and delayed opposite-side exits. Cumulative wallet cash reconciles with closed and still-active cashflows to less than $0.0000001 per scenario.

## Feed and latency findings

An initial WebSocket-only test found Hyperliquid book pushes around every **5.2 seconds** for BTC, XPL, NVDA, SILVER and SMSN. That caused systematic HL entry timeouts under the three-second timeout, despite fast updates from other venues. Direct REST checks returned advancing books with approximately 0.35–0.83s source age. The final design keeps broad streaming and adds targeted HL REST requests for due orders, held marks and probes, with a shared 180/minute gate and at most three workers.

The final experiment issued 1,957 targeted HL requests, published 1,947 usable responses, rejected older/generation-mismatched responses, and had no systematic intent timeouts. Both legs opened in 31 paper positions. Exchange timestamps predating an order's due time are rejected in the final implementation; nine such books were rejected during the restart validation.

**A probe target is not its actual observation delay.** Across the three correlated fee scenarios:

| Target | Observed / triggered | Missing | Mean actual delay | Still positive among observed |
|---|---:|---:|---:|---:|
| 100ms | 1,237 / 3,182 | 1,945 | 1,010ms | 91.7% |
| 300ms | 1,436 / 3,182 | 1,746 | 1,199ms | 90.5% |
| 500ms | 1,617 / 3,182 | 1,565 | 1,389ms | 89.4% |
| 1,000ms | 2,010 / 3,182 | 1,172 | 1,767ms | 89.5% |

These survival fractions are conditional on successful fresh paired observations. Missing results are substantial and cannot be counted as survivors. The requests also prioritize actual simulated exposure, so observations are not a uniform random sample of all opportunities. The 100ms row does **not** establish 100ms executability.

Among the last 2,000 retained episodes, 1,856 were right-censored and 221 had just one positive sample. Median observed span was 0.832s; maximum 7.639s. Those are sampled lower bounds, not continuous lifetimes. The retained simulated HL entry delays had median 1,214ms and p95 2,065ms. Public feeds, quota allocation and source age dominate these numbers; they are not Python execution time or a proven latency target for a trading system.

## Checks and fixes

- Economic tests: persistent entry premium is not income; equal lots; entry/exit fees; partial hedge failure; delayed source timestamps; venue capital limits; stale marks; settlement signs; missing/estimated funding; no double credit after restart.
- Streaming tests: sequence gaps, bootstrap bridges, bounded buffers, distinct manager generations, fresh targeted REST, reconnect during a request, failed request preserving stream state, unexpected worker exception reaching the supervisor.
- Storage tests: atomic checkpoint rollback, config mismatch, pruning without resetting totals, evidence budgets, SQLite-full handling and a pinned WAL reader. Main-file/WAL budgets are explicit; one bounded SQLite transaction can transiently exceed the WAL reserve, after which writes stop. Logs and JSON files have separate bounded overhead.
- Terminal tests: real PTY resize, actual Ctrl-C, SIGTERM, duration exit, restored screen/cursor, final stopped snapshot and released writer lock.
- Live restart: every prior position recovered; both Aster pending lookups resolved; all 11 prior positions subsequently closed; integrity check `ok`; every latency trigger reconciles to an observed or missing outcome at shutdown.

The initial seven-minute segment preceded the final source-time/funding-reserve safeguards and Aster host correction. The four-minute restart exercised those changes. The final tests include the later reporting and worker-supervision fixes. This is an incremental integration validation, not a single immutable binary benchmark or an overnight reliability claim.

## Reproduce the audit

- [Machine-readable validation](paper-monitor-validation.json)
- [Frozen public evidence](../data/evidence/paper-monitor-validation.tar.gz): SQLite checkpoint, configuration, market plan, before/after restart state, audit and per-file SHA-256 manifest.
- Archive SHA-256: `a876a2f08c3b5ba1d0f25e135a4be6b21b844a9760626a0ea712ccf5aa4b266e`.

```bash
mkdir -p /tmp/rhhype-paper-evidence
tar -xzf data/evidence/paper-monitor-validation.tar.gz -C /tmp/rhhype-paper-evidence
.venv/bin/python scripts/paper_report.py /tmp/rhhype-paper-evidence
.venv/bin/python -m unittest discover -s tests -q
```

Use [the monitor guide](../research/monitor.md) to start a fresh long-running experiment. Public displayed depth remains a paper fill model; it cannot establish real fills, queue priority, liquidation behavior, stablecoin conversion costs or transferable arbitrage profit.
