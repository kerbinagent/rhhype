> Archived signal-only collector. For the streaming position monitor, use [the current guide](monitor.md).

# Long-running asyncio monitor

## Run it

From the repository root, install the updated dependencies once:

```bash
.venv/bin/pip install -r requirements-lock.txt
```

Run with the simple TUI (automatic when launched in a terminal):

```bash
.venv/bin/python scripts/monitor.py --legacy
```

The display adapts to terminal resizes within half a second, independently of data/report intervals. Narrow terminals use fewer columns; very short terminals show the rows that fit and prompt you to enlarge the window. Both the collecting TUI and viewer restore the cursor and original screen on exit.

It starts collecting immediately; discovery usually takes a few seconds. The default is **$1,000 per leg**, both directions, across every qualifying matched perpetual on Hyperliquid native/xyz versus Robinhood Lighter, Lighter Core, and Aster. Each market must have at least $1 million trailing 24-hour quote volume. Real book depth must also support the requested quantity. Live discovery, rather than the September research snapshot, determines coverage.

For background collection and a detachable viewer:

```bash
nohup .venv/bin/python scripts/monitor.py --legacy --no-tui > /tmp/rhhype-monitor-launch.log 2>&1 &
.venv/bin/python scripts/monitor.py --legacy --watch
```

Ctrl-C in `--watch` closes only the viewer. Ctrl-C in the collecting TUI stops collection and saves state. Stop a background collector gracefully with:

```bash
kill -TERM "$(cat data/monitor/monitor.lock)"
```

The lock file contains the owning PID. Check that the process is still this monitor before using an old PID file after a crash. The OS releases the actual advisory lock on process exit; there is no stale-lock deletion step. Only one collector can own an output directory; any number of viewers can read it.

To keep it alive across host restarts, use your existing service manager to run the same command. `nohup` survives terminal disconnects, but not a machine reboot.

## TUI and the $1,000 tally

The terminal always shows the **ten best recorded directed pairs**, selecting the best size/moment for each pair. Rankings default to dollars **after opening fees and configured cost reserves**. Best-ever records survive both rolling-window eviction and restarts. These are historical peaks, not current quotes.

The paper tally models a fresh $1,000 notional allocation at the **first positive observation of each episode**:

1. Walk both books at exactly the same base quantity, rounded down to the intersection of both lot grids. The buy leg spends at most $1,000 before fees; minimum order constraints must pass.
2. Subtract each leg's taker fee on that leg's own quote notional.
3. By default also reserve an equal amount for two future closing fees, plus 5 bp of buy notional for other costs.
4. If the remaining edge is positive, count one episode and add its after-opening-fee and after-reserve values to separate persistent sums.
5. Further positive polls of that same directed pair do not increase the episode tally. An observed nonpositive value re-arms it. A gap of over 600 seconds without a valid $1,000 observation also starts a new episode; change with `--episode-gap`.

No quote is treated as a completed trade. The tally is a hypothetical **entry-edge sum**, not realized or portfolio profit. It does not enforce a finite total capital pool, model subsequent exits, assign funding, or prove fills. Simultaneous routes may compete for the same liquidity. A signal can turn negative and positive between polls without being observed. The underlying post-fee value can be positive while the configured reserve makes it ineligible for the tally.

For completeness, JSON also contains `paper_1000_positive_samples` and `paper_1000_positive_sample_sum_usd`: the naive sum over every positive $1,000 poll, including repeated observations of a continuing spread. The TUI uses the episode sum to avoid counting repeated polls as separate trades.

The top-10 peak can occur later than an episode's first observation, so summing the leaderboard is **not** how the paper tally is calculated. There is no hindsight allocation at the episode peak.

## Retention and restart behavior

- Default rolling window: 24 hours, with a **hard cap of 100,000 observations**. The row cap can shorten the effective window; JSON reports the actual oldest retained timestamp and cumulative cap evictions.
- Each observation is one direction at one size. Negative observations are retained within the window so positive-frequency tallies have a denominator.
- Persistent all-time storage: ten best records, aggregate counters, and bounded recent episode state. No unbounded raw orderbook history is written.
- SQLite deletes old rows and reuses pages. Its file can remain at its high-water size rather than shrink after deletion. WAL is checkpointed every report and on shutdown. Disk use depends on the row cap, not elapsed runtime.
- Logs rotate at 2 MB with three backups. JSON/Markdown outputs and market metadata are replaced atomically, not appended.
- Default output directory: `data/monitor/`, ignored by Git. It contains `window.sqlite3`, `leaderboard.json`, `leaderboard.md`, `markets.json`, `config.json`, and rotated logs.
- Restart with the same command to resume. Rankings, tally sums and active episode state persist. At most the last report interval's uncommitted samples can be lost in an abrupt crash. Normal SIGINT/SIGTERM flushes state.
- Changing fee/ranking/asset-selection/model settings requires a new `--out` directory to avoid mixing incomparable records. Window length, row cap, reporting interval and polling cadence can change in place.

## Useful options

```bash
# Larger sizes too; $1k is always included for the paper tally.
.venv/bin/python scripts/monitor.py --legacy --notionals 1000 10000 100000 --out data/monitor-sizes

# Premium fee schedule, $1k allocations, 12-hour window.
.venv/bin/python scripts/monitor.py --legacy --lighter-tier premium --window-hours 12 --out data/monitor-premium

# Crypto subset on Robinhood Lighter and Core.
.venv/bin/python scripts/monitor.py --legacy --assets BTC ETH SOL HYPE XRP ZEC --venues rh_lighter lighter --out data/monitor-crypto

# Pure after-opening-fee screen, explicitly excluding other reserves.
.venv/bin/python scripts/monitor.py --legacy --no-reserve-exit-fees --extra-cost-bps 0 --out data/monitor-entry-only

# Rank by basis points, rather than absolute dollars.
.venv/bin/python scripts/monitor.py --legacy --rank-by bps --out data/monitor-bps
```

Use `--out` on `--watch` too when viewing a nondefault directory. `--duration 120` provides a finite two-minute check. All options are listed by `--help`.

## Fees, mappings, freshness and concurrency

- The collector uses asyncio/aiohttp with persistent connections and three pair workers per comparator venue. A comparator book is followed immediately by its Hyperliquid hedge book.
- Host pacing: Robinhood Lighter 45 requests/minute, Core 45, Aster 60, Hyperliquid 180. These include discovery requests and leave headroom under the documented endpoint budgets. Higher worker counts do not bypass the gates. Avoid running another public collector at full quota against the same host/IP.
- Each venue cycles independently. The minimum cycle is 60 seconds, but broad coverage or cooldowns can extend it. No backlog of missed polling cycles is accumulated.
- HTTP errors, timeouts and rate-limit responses trigger shared host cooldowns. No IP rotation or host VPN configuration is performed.
- Every hour, refresh market status, volume, quantity constraints, and Hyperliquid per-market deployer/growth fee modifiers. Discovery retries failed comparator venues. If essential metadata is older than two hours, stop sampling until refreshed. A delisting within a cycle can still produce a rejected request before the next refresh.
- Base account fees remain explicit configured assumptions: HL native 4.5 bp, Aster general crypto 4 bp, RWA 1.25 bp, listed Group B crypto 10 bp; Lighter Standard 0, Plus 0.5 bp, Premium RH 3.5 bp/Core 2.8 bp. Positive per-market Lighter published fee metadata is a fee floor. Public base schedules can change; monitor and update the configuration when they do. No private account fee query is made.
- The default closing-fee reserve uses current opening notionals and rates. Actual closing fees, prices and spreads can differ. The 5 bp buffer is an assumption, not a measured conversion/financing cost.
- Reject empty/crossed/nonfinite books, insufficient depth, invalid minimum sizes, more than five seconds receipt skew or quote age, and large midpoint mismatches (>5%). Lighter's REST book lacks an engine timestamp; nearby receipt times cannot prove engine freshness.
- USDG, USDC and USDT are assumed at parity in the price comparison. Stablecoin conversion and oracle/settlement differences remain economic risks even when prices line up.
- Only perpetuals with one-for-one base-unit mappings are monitored here. Native crypto tickers and xyz exact tickers are matched; explicit aliases cover gold/silver, selected indices/FX and verified Korean common-share USD contracts. New same-ticker listings still warrant contract review. Scaled Lighter contracts are skipped. Other HIP-3 domains, AMM stock tokens, wrapped spot and spot borrowing routes are not silently substituted; their unit, custody and redemption models differ.

Primary references: [Hyperliquid info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [aiohttp client documentation](https://docs.aiohttp.org/en/stable/client_quickstart.html), [fee sources](fees.md), and [verified comparator mappings](comparators.md).

## Verification

The tests cover both-leg fees and reserves, the $1,000 spending ceiling, exact intersection of different quantity grids, insufficient depth, nonfinite/crossed/stale rejection, rolling expiry, hard row cap, distinct top-10 records, restart/config consistency, episode deduplication, concurrent request pacing, and real pseudo-terminal resize/Ctrl-C/SIGTERM behavior.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

A finite live check on September 29 found 123 venue comparisons across 66 assets; the observed universe varies with live volume and listings. Detailed final check results are recorded in the journal.

## Overnight audit and fee-model correction

See [the September 29 overnight audit](../reports/monitor-audit/REPORT.md) for exact tally reconciliation, fee-tier sensitivity, sampled signal durations, and subsequent-exit diagnostics. The approximately $330 display was an opening-edge sum, not simulated closed-trade profit. Model version 3 corrects Aster fee classes and makes that distinction explicit in the TUI. Use a fresh `--out data/monitor-v3` when restarting; stop the previous collector first. Existing running processes keep their original code and fees.

Aster overrides are `--aster-fee-bps` for general crypto, `--aster-rwa-fee-bps`, and `--aster-group-b-fee-bps`. The Group B list is verified as of September 29; revisit it as fee schedules change.
