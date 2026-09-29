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
