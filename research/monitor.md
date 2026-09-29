# Streaming paper monitor — model 4

## Run it

```bash
.venv/bin/python scripts/monitor.py
```

Default output: `data/paper-monitor`. No API keys, wallet, or trading permissions are used. All order fills are simulations against public depth.

For a background collector with a detachable TUI:

```bash
nohup .venv/bin/python -u scripts/monitor.py --no-tui \
  --out data/paper-monitor </dev/null >/dev/null 2>&1 &

.venv/bin/python scripts/monitor.py --watch --out data/paper-monitor
```

The collector writes its PID in `data/paper-monitor/paper.lock`. Stop the collector gracefully with:

```bash
kill -TERM "$(cat data/paper-monitor/paper.lock)"
```

Ctrl-C stops a foreground collector and checkpoints its state. Ctrl-C in `--watch` exits only the viewer. Resizing is supported; 80×24 shows ten ranked signals, while smaller windows show what fits and indicate omitted rows. Logs rotate inside the output directory; the background command does not create an unbounded `nohup.out`.

Restart with the **same command and output path** to resume the portfolios and cumulative counters. The lock prevents two writers. Changes to capital, fees, universe filters, delay or holding assumptions require a fresh `--out`; unrelated experiments must not share a P&L history. Shutdown preserves outstanding exposure. On restart it resumes exits using fresh feeds; it does not invent fills during downtime. SIGKILL/power loss can lose work since the last successful checkpoint, normally about two seconds.

The former monitor remains `scripts/monitor.py --legacy`. Its `data/monitor` entry-edge sums are not imported as new profits. An already-running old process keeps using its loaded code; starting the new version does not upgrade that process in place.

## Current exit policy

The default now requests an exit when estimated net liquidation P&L reaches **$0.10**, or **10 seconds after both entry legs fill**, whichever occurs first. Both exit fees, the other-cost reserve, capital charge and available settled funding are included in the profit trigger. The trigger requires fresh, sufficiently synchronized books. Actual exit fills happen later against fresh depth and can produce a loss even after a positive trigger.

Ten seconds is the **exit-request deadline**, not a promise to be flat by ten seconds: missing depth or a disconnected venue leaves tracked exposure that must be retried. Partial/failed entry hedges still trigger immediate flattening.

```bash
.venv/bin/python scripts/monitor.py --holding-seconds 10 --take-profit-usd 0.10
```

For the historical fixed-hold benchmark, use `--holding-seconds 300 --no-take-profit` with its own output directory. The five-minute validation report remains a record of that earlier policy.

On the user's requested switch, the earlier run was saved under `data/paper-monitor-5min-20260929T143302Z`, including its 12 open paper positions. A fresh ledger is running in `data/paper-monitor-10s`. `data/paper-monitor` is a symlink to the new run so an existing viewer follows it automatically; results were not merged. The old positions remain archived, not synthetically closed.

## What the numbers mean

| Display | Meaning |
|---|---|
| Closed exact | Net P&L of flat paper positions with complete modeled funding/costs |
| Closed est | Separate net P&L using estimated funding cashflows |
| Open exit | Current depth-based liquidation P&L after entry fees, projected exit fees, other reserve, capital cost and covered funding; `?` when incomplete |
| Winning/loss sums | Cumulative positive and negative closed results, retained separately per fee scenario in the snapshot/report |
| Pending funding | Flat positions whose funding cannot yet be established; excluded from closed totals and keep capital reserved |
| Top 10 | Best recorded after-reserve entry signals, distinct by directed route and fee scenario; these are not profits |

The **net closed result includes losses**. Do not add Standard, Plus and Premium totals: they are mutually exclusive counterfactual accounts, each starting with $20,000. `exact` describes complete paper accounting, not certainty of real execution. The `paper_report.py` audit prints the cumulative ledger, winning/loss sums, per-route retained results and wallet reconciliation error:

```bash
.venv/bin/python scripts/paper_report.py data/paper-monitor
```

The report briefly opens SQLite read-only and prints JSON. Detailed trades are a bounded window; their sum need not equal lifetime ledger totals after pruning.

## Execution and capital

- Discover all eligible same-unit perpetual comparisons across native/XYZ Hyperliquid and Robinhood Lighter, Lighter Core and Aster. Default minimum reported 24h turnover is $1m **on both legs**; a trade also requires sufficient current executable depth. This covers crypto and eligible equity/index/commodity/FX contracts that overlap, without an NVDA-only selection. Robinhood AMMs and spot-token hedges remain separate research workflows because inventory, token multipliers, gas and transfers need different execution models.
- A position buys one venue and shorts the other in equal base quantity, rounded onto their common lot grid. Each leg is capped at $1,000, with entry slippage headroom. Both venue minimums and maximums apply.
- Each scenario has $20,000 prefunded across four venue wallets, $5,000 per venue. Default margin reserves are 100% of each leg's notional plus fees and buffer. Max ten positions / $10,000 matched notional, further constrained by wallet cash. At most one position per undirected asset/venue comparison and fee scenario. Existing unmarkable exposure or uncovered funding after a settlement boundary blocks additional entries using that venue. Known funding debits reduce spendable cash before they are posted at closure; unposted credits are not spent.
- An entry is eligible only when the displayed opening edge exceeds opening fees, a closing-fee reserve, the other-cost reserve, and the planned capital charge. This filter does not predict that the basis will converge.
- Fills use the **first valid new book after the configured delay**, not the triggering book. Where an exchange timestamp exists, it must also be after the due time; a newly received but older source snapshot cannot fill the order. Default 100ms network assumption plus venue processing: HL/Aster 50ms assumptions; Lighter Standard/Plus 300ms; Premium Core 140ms / RH 200ms. These are modeling inputs, not a measured latency promise.
- Entry IOC price tolerance defaults to 10bp. Partial fills, rejected legs and timeouts produce tracked hedge failures and emergency exits. Disconnect/generation changes invalidate pending entry assumptions. Exit retries continue until actual displayed depth flattens the exposure; the engine never declares an unfilled leg closed.
- Exits are requested at the net profit target or the ten-second deadline. Exits use opposite-side future books, with their own delays and fees. Multiple orders in one scenario share a given book's available liquidity. Venue replenishment between separate public updates is not independently observable.
- Fully collateralized defaults avoid using assumed leverage to inflate the tally. `--margin-fraction` can change the reserve experiment, but the engine does not reproduce each exchange's maintenance-margin/liquidation engine. Prefunded balances do not automatically move between venues.

## Fees and funding

Three scenarios run simultaneously:

| Venue | Standard | Plus | Premium |
|---|---:|---:|---:|
| Lighter Core taker | 0bp | 0.5bp | 2.8bp |
| Robinhood Lighter taker | 0bp | 0.5bp | 3.5bp |
| Hyperliquid | Tier 0 baseline 4.5bp; metadata-derived XYZ deployer/growth adjustment in all scenarios |
| Aster | Crypto 4bp / RWA 1.25bp / specified Group B 10bp in all scenarios |

Published Lighter market fee floors override a lower assumed fee. There are no assumed staking/referral/maker discounts. HL and Aster rates can be overridden via CLI for an explicitly documented account; this does not infer your private VIP status. Fee inputs and metadata are saved in `paper_config.json` and `markets.json`. See [fee sources](fees.md), [overnight fee audit](../reports/monitor-audit/REPORT.md), and [funding mechanics](funding-monitor.md).

Fees are charged on each actual fill, including both exit legs and failed hedges. Additional cost reserve: 5bp of maximum entry leg notional per position. Capital charge: 5% annualized on reserved notional for actual elapsed holding time. The extra reserve represents conversion/rebalancing/friction; it is not a measured transfer quote. USDG, USDC and USDT are assumed at USD parity. Funding signs and settlement crossings are calculated per filled leg and partial exit quantity. Missing history/reference prices remain unknown, never silently zero. Public near-settlement reference prices and inferred Lighter per-unit cash values are explicitly marked estimated.

Open positions refresh funding after settlement boundaries. Closed positions get priority for settlement lookup. Bounded caches reuse hourly history across fee scenarios and partial exits. Public REST requests have separate pacing and retry backoff; an outage can leave a position pending funding for an extended period.

## Frequency, opportunity duration and latency

The TUI shows CPU usage as a percentage of **one core** and recent p95 event-loop lag. `BUSY` flags a sample at ≥85% CPU or p95 lag ≥50ms; it is a diagnostic threshold, not a proven capacity limit. Snapshot JSON also records these measurements.

Default transport is WebSocket, using one shared `aiohttp` session and concurrent venue subscriptions. HL uses L2 snapshots; Lighter uses checked nonce-linked books; Aster uses diff streams requested at 100ms, bridged to REST depth snapshots. Sequence gaps discard the book and trigger resynchronization. The observed HL WebSocket cadence in validation was about **5.2 seconds** per book. A targeted REST refresher therefore requests fresher HL books for due orders/probes and held positions. It uses the shared 180-request/minute HL gate, at most three workers, a 0.5s minimum per-key interval, and exit priority. It does not poll the whole universe at that rate. Actual delay and missing coverage remain measured. Streams and targeted REST continuously update books; fills process every valid book event. Signal evaluation coalesces updates per comparison at 100ms by default (`--signal-interval`, minimum 20ms). More updates cannot be manufactured for a quiet venue.

Episode spans report **observed positive time**, not proof of continuous executability. Invalid/stale data, insufficient depth and shutdown/restart censor intervals. One-sample spans are zero observed duration, not zero real lifetime. Signals shorter than the evaluation interval can be missed.

At episode onset, 100/300/500/1,000ms probes retain the original quantity and independently observe each leg's first fresh update after the delay. Survival means the recalculated edge still clears the same reserves. Actual observation delay and missing results are recorded; do not interpret `100ms` as precisely sampled at 100ms or as an exchange fill guarantee. Per-strategy statistics and bounded episode detail are in the state/report. These diagnostics measure feed-observable persistence; public feeds cannot establish queue priority, adverse selection or real acceptance latency.

Freshness defaults: max book age 2s; max receipt skew 1s; engine timestamps are checked when available. Missing exchange timestamps are not fabricated. Price divergence above 500bp is quarantined. Metadata refreshes hourly; new entries stop once metadata is older than two hours. Existing exits continue.

`--transport poll --poll-interval 1` is an explicit REST fallback. Per-host quota gates still apply, so large universes do not receive one request per pair per second. Streaming is the high-frequency path. Do not run many independent collectors at full REST quotas on the same IP.

## Long-run storage bounds

- Rolling details: 24h, at most 20,000 signal improvements, 5,000 trade rows, 2,000 evidence records.
- Compressed evidence: 16MiB total, with an individual-record cap. Full books are not appended to disk on every update. Best-signal books and fill/trade evidence are retained within the ring limits.
- In-memory sampled book ring: 30 seconds and a 16MiB estimated-object budget; whichever binds first. Other feed/position/counter caches have their own limits; 16MiB is not a whole-process RAM cap.
- SQLite budget: 128MiB by default, with main-file page cap and WAL reserve. Each write batch is capped, old detail is pruned, and a pinned-reader WAL causes writes to stop rather than grow indefinitely. SQLite can transiently exceed the WAL reserve during a single bounded transaction; this setting is not a strict cap on every byte in the directory.
- Logs: 2,000,000 bytes × four files. Atomic JSON files are replaced rather than appended. Small fixed state, top records and cumulative counters survive detail expiry. An interrupted atomic write can leave one bounded temporary file.
- Disk errors stop the monitor with the last durable checkpoint. Inspect `paper.log` and the snapshot age after a stopped collector; a viewer continues showing the most recent saved snapshot.

Example smaller study:

```bash
.venv/bin/python scripts/monitor.py --assets BTC ETH SOL NVDA XAU \
  --max-db-mb 64 --evidence-mb 8 --book-memory-mb 8 \
  --out data/paper-monitor-small
```

Use `--duration 120 --no-tui --out data/paper-monitor-test` for a finite check. See `--help` for all limits and assumptions.

## Experimental entry policies

Enable with `--shadow-strategies`. This adds four independent Standard-fee paper portfolios to the current collector; existing ledgers and positions are retained. Saved experiments resume automatically on subsequent launches. The new `shadow_baseline` starts alongside the experiments, so its P&L is the relevant comparison rather than the original Standard portfolio's older cumulative losses.

| Label | Entry rule |
|---|---|
| S.Base | Original positive opening-edge rule, fresh capital and start time |
| Cooldown | At least $0.25 opening edge after estimated round-trip costs, receipt/source skew no more than 250 ms, 60-second cooldown per directed route |
| Converge | Same controls, plus opening edge minus historical median executable closing spread must be at least $0.25 |
| Conserv. | Same controls, using the 75th percentile closing spread and a $0.50 minimum forecast |

All use the original $1,000 target per leg, $20,000 initial portfolio, actual simulated fill fees, 5 bp additional cost allowance, delayed fills, $0.10 net profit exit trigger and ten-second maximum hold. Each portfolio has independent capital and displayed-depth allocation; their P&Ls must not be added.

Forecasts use only preceding observations from a rolling 15-minute window. At least 40 distinct paired samples spanning 120 seconds are required. Both books must advance, source timestamps must advance where available, and paired receipt/source skew must be at most 250 ms. Sampling is capped at once per second per direction and 900 observations per route, with an absolute 2,000-route cap. Thirty-second observation gaps and stream generation changes reset the affected model. Models warm up again after restart; entry cooldowns and accounting persist. Nothing grows with runtime without a bound.

These are exploratory historical closing-spread forecasts, not validated ten-second convergence probabilities. Zero trades indicate no qualifying observations; they are not evidence of profitable execution. Results are evaluated on subsequent live fills without retroactively selecting winning parameters. The same feed and Hyperliquid REST quota serve all portfolios; extra simulated orders can affect observation scheduling.

Restart a currently open viewer to load the new table:

```bash
.venv/bin/python scripts/monitor.py --watch
```

The compact table shows net closed P&L, open liquidation P&L, wins/trades, and entry/warmup/rejection diagnostics. On small terminals, enlarge the window to see all ten opening signals. An open mark of `?` means a fresh complete liquidation estimate is unavailable.
