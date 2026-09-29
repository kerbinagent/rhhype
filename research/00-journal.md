# Research journal

## 2026-09-29 UTC — initialization

User scope: thoroughly investigate arbitrage between Robinhood Chain and Hyperliquid, with other popular DEX comparators; cover all asset classes with sufficient liquidity; use simple Python and historical / consecutive recent observations; organize memory in Markdown and commit incrementally. Research only, no trading.

- Initialized Git with `main`; existing workspace VPN skill and credentials are preserved. `.env` and raw data are excluded from commits.
- Delegated source verification / Robinhood pools, Hyperliquid census and history, and comparator census/history to three explicitly authorized `gpt-6-sol` agents at high effort. Root owns integration, methodology, consecutive sampling, and conclusions.
- Default sandbox cannot resolve public endpoints. Approved elevated public requests succeed: Hyperliquid `/info`, Lighter `orderBooks`, Coinbase server time.
- System clock and Coinbase server clock agree on Sep 29 2026 UTC. Do not confuse older testnet support pages with current mainnet. Official Robinhood July 1 announcement and chain ID verification show mainnet is live.
- Keep evidence of data failures and avoid treating absent observations as zero liquidity.

## 03:59 UTC — live collection and data validation

- Full Hyperliquid census: 529 perp listings (328 active) and 330 spot pairs. Fixed a concrete spot identity join bug: context array has 885 entries versus 330 market definitions; joining by `coin` restores HYPE, UBTC and other token identities. Perp arrays align by definition.
- Archived 31d history for 37 representative Hyperliquid perp instruments and comparator history. Backfilling silent Lighter 500-candle response cap.
- Robinhood official registry has 195 token deployments. Full canonical pool scan: 143 have indexed pairs, 139 USDG pairs, 33 with >=$100k top-pool liquidity and >=$100k h24 volume. Indexer figures are a screen only.
- Verified Uniswap v3/v4 read-only Quoter simulations on Robinhood mainnet. Larger v4 pools commonly charge 30bp while v3 alternatives charge 5bp; TVL is not a sufficient route selector.
- Crucial economic correction: stock-token quantity times `currentMultiplier` equals hedged shares. Cash dividends are reinvested. Raw token vs stock price would manufacture basis. Current multiplier cannot be applied silently to 30d history.
- Initial 265-market live sample exceeded Lighter's 60 public requests/min allowance, producing HTTP405 after two successful rounds. Stopped collector, retained raw failed run, resumed 186-market plan at 60s with just 30 Lighter calls/min. No VPN or IP rotation used.
- Robinhood seven direct stock hedges are sampled at 30s, fixed block and adjacent HL books; QQQ/SPY have no exact xyz equity hedge. First run SPY selected a different v3 factory; contract validation rejected it, and it is counted as unavailable instead of assigning a false quote.
- Economic calculation tests cover book walking, insufficient liquidity, fee tiers/growth strings, crossed-book rejection, both-leg fees, and share multipliers. All six pass.

## 04:16 UTC — separate Robinhood Lighter domain and historical QA

- Discovered and verified separate Lighter domain on Robinhood Chain: `https://api.rh.lighter.xyz`, app-chain ID 466324 anchored to L2 4663. Official docs explicitly separate its sequencer, contracts, liquidity and API from Lighter Core. Full census: 57 active perps / 27 active spot markets. Started 20 rounds ×60s paired books (30 RH markets plus adjacent HL books).
- RH Lighter Standard taker fee zero; Plus 0.5bp; Premium base3.5bp vs Core2.8bp. RH perps collateral is USDG per official deposit documentation, not USDC. Archived asset metadata ties spot base asset IDs to canonical RH contracts and published multipliers. Price-unit interpretation is documented separately and checked under both raw-token and share-unit hypotheses.
- Expanded AMM collection to all19 eligible canonical token/direct-HL equity overlaps, including SPCX (verified June2026 IPO via SEC); additional samples select best tested Uniswap routes at $10k. Found COIN v4 pool100bp fee and reject unsupported pool hooks/keys. Collectors remain read-only.
- Historical multiplier logs, including effective timestamps, are available even when historical eth_call is unavailable. Reconstructed9 token multiplier histories from event logs and verified current anchors. Dropped hours in which multipliers change from hourly close comparisons.
- Material historical indexer error: GeckoTerminal `currency=usd` used an anomalous USDG/USD conversion factor up to1.0561, while independent CoinGecko USDG/USD at the same hour was0.999946. Switched RH pool history to `currency=token` (USDG per token), then normalized exact historical multipliers. Apparent5% historical arbitrage was a data-conversion artifact.
- A separate synchronized21-market supplemental run covers Aster, Korean common-share contracts and UZEC spot. Korean common-share SKHX/SMSN units verified in XYZ docs; SKHY is an ADS and must remain distinct.
- Independent audit found lot-size residuals can exceed small modeled profits. Added conservative lot-rounding reserves and explicit on-grid flags; continuous-size estimates remain labeled. No partial-fill or execution success is assumed.

## Finalization checks

- Offline `rebuild.py` initially omitted the historical multiplier input, which left historical RH results stale. Fixed it to pass the frozen multiplier-event file explicitly; required counts are39 perp pairs,5 HL cash pairs,2 RH-domain cash pairs and7 RH/HL stock basis series.
- Excluded apparent NVDA RH-domain spot cash-carry performance after finding45% zero-volume holdout hours and negligible entry/exit candle turnover. A liquid perp does not validate a thin spot price history.
- Verified RH-domain spot asset addresses and multiplier values against issuer registry and assetDetails. Token-price convention is supported by API base-token quantity definitions and empirical index prices; retain share-unit sensitivity as a qualification.
- Fixed future `robinhood_live.py` discovery to select verified Uniswap DEX candidates before factory checks, avoiding the known SPY third-party factory mismatch. Frozen failed observations remain intact. Changed default Core live cadence to60s to leave public API headroom.

## 04:30 UTC — frozen result and delivery

- Completed 35 Core rounds (6,510 requests) and 70 primary AMM rounds; RH Lighter completed 20 paired rounds with 600 RH and 520 HL book responses and zero errors. Supplemental paired Aster/Korean coverage completed 24 rounds. All collectors are stopped.
- At $10k, RH Lighter NVDA entry median is 10.80bp after Standard opening fees, or 7.30bp under Premium. None of 287 eligible RH-domain 5/10-minute unwind scenarios was positive after all four fees. Core had zero positives among 452 eligible $10k 5/15-minute scenarios. These overlapping samples are not independent trials or portfolio returns.
- Historical rebuild confirms 39 perp pairs, 5 HL cash pairs, 2 RH cash pairs and 7 multiplier-corrected stock basis series. Final report distinguishes funding-rate sums from price-weighted cash estimates and executable observations from candle scenarios.
- Offline rebuild completed successfully. Seven economic calculation tests pass; scripts compile; Git whitespace checks pass. Standard PNG/SVG figures and Markdown report are complete.
- Frozen public evidence contains 441 files (183,939,433 uncompressed bytes) in a 22,127,964-byte archive, with archive and per-file SHA-256 hashes. No credentials or host VPN changes were used.

- Added Git whitespace attributes for standard CSV CRLF and Matplotlib-generated SVG path formatting after the staged artifact check flagged their machine-generated whitespace. Source-code whitespace checks remain enabled.

## Continuous monitor and TUI — 2026-09-29

- Added `scripts/monitor.py`: asyncio/aiohttp public book sampling across native/xyz Hyperliquid versus Robinhood Lighter, Lighter Core and Aster. Live discovery refreshes metadata and quantity constraints. Per-host pacing and cooldowns allow long unattended sessions.
- Added bounded SQLite rolling history (24 hours / 100,000 observations by default), persistent top ten distinct directed pairs, and a persistent $1,000-per-positive-episode paper tally. Both legs use exactly equal quantities on intersected order grids; buy notional never exceeds its target. Fees and explicit closing/conversion reserves remain distinct.
- User requested an extremely simple TUI and explicit resize/Ctrl-C checks. Display redraws within 0.5 seconds, adapts to narrow/short windows, and restores the original screen and cursor. Separate `--watch` mode detaches UI from a background collector.
- Seventeen tests pass, including real pseudo-terminal resize sequences (120×30 → 35×10 → 80×24), actual terminal Ctrl-C for viewer and collector, and collector SIGTERM. All exit code 0; collector flushes state and releases its lock.
- Final finite live validation: 123 matched comparisons across 66 assets, 112 paired samples / 224 directional $1,000 observations, one quarantined price mismatch, zero transport/API errors, and zero observations above the allocation ceiling. SQLite integrity check passes. Example paper total was $8.22 after opening fees / $2.32 after configured reserves across ten episodes; these are not realized trading profits. See `reports/monitor-validation.json`.
- All validation collectors are stopped. The user can launch the default monitor with a fresh `data/monitor` state directory.

## 12:00 UTC — overnight audit

- User reported roughly $300 paper profit and asked for signal duration/latency and fee-tier interpretation. Froze a consistent read-only snapshot without stopping the active monitor: 84,240 observations over 6.78 hours. The 432 episode counters reconcile exactly: $330.85 opening-edge sum, less $70.23 closing-fee reserve and $215.92 other reserve = $44.70. The code counts signals, not position/exit P&L.
- 421 episode triggers were repeated crossings back above zero. Median after-reserve episode value is $0.0593; 291 values are below $0.10. Renamed the TUI display to entry-edge sum and explicitly state closed-trade profit is not simulated.
- 189 episodes were single samples. RH cadence ~60s, Core ~83s. NVDA RH had long observed spans up to 343min, but samples cannot establish continuous executable lifetime. Added per-route persistence, censored endpoint brackets, and fee-tier-specific counts.
- Subsequent opposite-direction VWAP diagnostic: 395 five-minute same-hour scenarios, 8 positive after four fees, median −$0.521/$1k; only 1 survives the additional 5bp buffer. Nearby-size VWAP scaling is explicitly approximate, and scenario sums overlap rather than form a portfolio.
- Baseline used Lighter Standard 0bp versus HL Tier0 and Aster flat4bp. Premium Lighter repricing leaves 35 eligible episodes, all Core; none RH. Found Aster RWA fee is1.25bp, GroupB10bp, not universal4bp. Corrected monitor fee model3 with new-output-directory guard. Existing live process remains untouched.
- Added reproducible audit, charts, compact public compressed evidence, economic and persistence tests. Full findings: `reports/monitor-audit/REPORT.md`.

- Validation completed: 21 tests pass, including fee classes, persistence censoring, fee-scenario algebra, and prior terminal tests. The frozen public evidence hash verifies; the audit report links and figure were checked.

## Streaming paper execution upgrade — 2026-09-29

- Replaced the default monitor entry point with model 4; retained the original signal collector under `--legacy`. New output is `data/paper-monitor`, so the overnight signal tally and its running process are not mutated or imported as trading income.
- Added independent Standard/Plus/Premium portfolios with finite prefunded cash, equal lot quantities, delayed IOC-style entries, partial/unhedged exposure, timed exits, all fill fees, financing/friction reserves, settled funding and separate estimated/incomplete outcomes. Realized paper losses remain in net P&L; winning and losing sums are separately retained.
- Added public WebSockets for all four venues, checked sequence/generation resynchronization, dirty-pair coalescing, bounded in-memory book history, and SQLite atomic checkpoints with bounded rows/evidence/main file/WAL/logs. Blocking persistence runs off the feed loop.
- Live QA found Hyperliquid L2 WebSockets delivered at ~5.2s cadence even while REST source timestamps advanced more often. A three-second timeout with WS-only books produced systematic one-leg failures. Added quota-limited targeted HL REST refresh for due orders, held marks and probes, sharing the existing 180/min request gate; no full-universe REST burst. Live paired fills then succeeded. Exits and held risk marks receive priority over probe volume.
- Delayed fills require both receipt and available exchange timestamps after the intent's due time. Stale/regressing source snapshots, disconnects, missing funding and unmarkable collateral cannot improve portfolio capacity. Known unposted funding debits reduce spendable cash; unposted credits do not.
- Latency probes retain original quantities, unique episode identities, actual observed delays, missing reasons and fee-scenario counters. Sampled episode bounds are censored on missing depth, stale/gapped data, shutdown and restart. The TUI shows target delay alongside actual mean delay and missing count; a 100ms target must not be mistaken for a 100ms observation.
- Runtime tests exposed an idle Python 3.13 executor shutdown wakeup problem. A short shutdown timer remains scheduled while durable checkpoint work and executor shutdown finish. Real PTY tests exercise resizing, actual Ctrl-C, SIGTERM, terminal restoration, released locks and stopped snapshots.
- Aster funding's documented `fapi3` host returned 403 in this environment; the working public `fapi` V3 funding history and premiumIndex endpoints were validated and adopted. Pending closed trades were preserved until successful history lookup after restart.
- The all-market experiment and restart audit are recorded in `reports/paper-monitor-validation.md` and its JSON evidence. Current resident memory is measured separately from the inherited process high-water statistic. The monitor remains a displayed-depth paper model: no actual orders, credentials, venue transfers or host VPN changes.

- Final validation: 85 tests pass; 116 comparisons / 67 symbols; 554,556 book events across 420s plus 240s restart. All 11 prior positions recovered and closed, two Aster funding lookups resolved, all wallet reconciliations within 1e-7, SQLite integrity `ok`. Closed net results: Standard −$9.18 (8), Plus −$11.38 (8), Premium −$13.56 (5), with 12 positions still durably open. Evidence archive and explicit missing/censored latency diagnostics are committed with the validation report. All validation processes exited cleanly.
- Final failure-path regression: a failed checkpoint restores drained trade/signal/evidence queues before retry, keeping financial state and its audit records together. The fault test avoids host-specific idle thread-executor teardown; actual threaded checkpoint shutdown remains covered by the collector PTY tests.

## Viewer waiting at launch — 2026-09-29

- Diagnosed a viewer-only launch: host process list contained `scripts/monitor.py --watch`, with no collector or default output directory. Started the authorized paper collector in the background and verified fresh snapshots, 115 comparisons and advancing book counters. Left that collector running for the user.
- The waiting screen now checks the writer lock and distinguishes an absent collector from startup in progress, showing the collector command and watched path. The check creates no files and ignores stale PID contents.
