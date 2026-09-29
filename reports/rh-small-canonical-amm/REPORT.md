# Canonical RH Chain stock-token AMM screen at $100–$1,000

**Read-only result, 29 September 2026, 22:40–22:46 UTC.** Five consecutive rounds sampled canonical Robinhood Chain **NVDA, AAPL, MSFT, and TSLA stock tokens** at $100, $250, $500, and $1,000. This is separate from the RH-domain Lighter perpetual maker pilot. The [method](../../research/rh-small-canonical-amm-method.md), [collector](../../scripts/rh_small_canonical_amm.py), [raw stopped capture](../../data/raw/rh_small_canonical_amm/20260929T224037Z/manifest.json), and [quality analysis](analysis.json) give the reproducible details. No wallet, order, transaction, bridge, or VPN was used.

## Result

The two preselected direct token/USDG Uniswap pools per asset (highest archived indexed-liquidity v3 and v4 candidates) were all verified against the current canonical registry and onchain pool identity before quoting. All **320 fixed-block quoter calls** and **20 HL L2 books** returned; the capture ended `complete` with no errors and used **542,478 of 8,000,000 allowed bytes**. Both direct pool candidates were available for every asset/side/size/round, yielding 160 best-direct-pool observations.

The offline validator found all 320 quote/books had finite positive, strictly sorted, uncrossed HL levels, source no later than local receipt, enough displayed depth, and at least $10 walked HL notional. **48/320** individual quote/book pairs exceeded the 2-second fixed-block-source or local-receipt timing screen; **136/160** best-direct-pool observations passed it. All **320/320** converted stock-token quantities were **off the HL lot grid**. The HL walk therefore gives an *optimistic continuous-size hedge bound*, not a valid exact-quantity HL order. A rounded HL hedge would leave residual stock-token exposure and requires a different amount/route simulation.

For each round and size, the best direct **buy** route is the pool yielding the most token from the same USDG input; the best direct **sell** route yields the most USDG from the same token input. Each table value is the median **entry-only** gap in USD across the timing-accepted rounds, after the AMM quoter's embedded pool fee, **one** HL taker entry fee on walked notional, and a separately labeled modeled 5 bp reserve. The buy direction is AMM token buy / HL short; the sell direction is AMM token sell / HL long. A negative value is a cost. The fee/reserve screen is **not** a completed round-trip profit calculation.

| Token | Direction | Timing-accepted rounds | $100 | $250 | $500 | $1,000 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| NVDA | Buy / short HL | 3/5 | −$0.060 | −$0.150 | −$0.300 | −$0.603 |
| NVDA | Sell / long HL | 3/5 | −$0.167 | −$0.418 | −$0.836 | −$1.676 |
| AAPL | Buy / short HL | 4/5 | −$0.119 | −$0.300 | −$0.612 | −$1.281 |
| AAPL | Sell / long HL | 4/5 | −$0.107 | −$0.271 | −$0.553 | −$1.152 |
| MSFT | Buy / short HL | 5/5 | −$0.442 | −$1.107 | −$2.221 | −$4.471 |
| MSFT | Sell / long HL | 5/5 | −$0.287 | −$0.720 | −$1.447 | −$2.924 |
| TSLA | Buy / short HL | 5/5 | −$0.135 | −$0.340 | −$0.691 | −$1.421 |
| TSLA | Sell / long HL | 5/5 | −$0.558 | −$1.400 | −$2.820 | −$5.727 |

The separate **fee-only** entry gap is also retained in [analysis.json](analysis.json): `gross entry gap − one HL entry fee`, before the modeled 5 bp reserve. Its timing-accepted median at each size was:

| Token | Direction | $100 | $250 | $500 | $1,000 |
| --- | --- | ---: | ---: | ---: | ---: |
| NVDA | Buy / short HL | −$0.010 | −$0.025 | −$0.050 | −$0.103 |
| NVDA | Sell / long HL | −$0.117 | −$0.293 | −$0.586 | −$1.175 |
| AAPL | Buy / short HL | −$0.069 | −$0.175 | −$0.362 | −$0.781 |
| AAPL | Sell / long HL | −$0.057 | −$0.146 | −$0.303 | −$0.652 |
| MSFT | Buy / short HL | −$0.392 | −$0.982 | −$1.971 | −$3.971 |
| MSFT | Sell / long HL | −$0.237 | −$0.595 | −$1.197 | −$2.424 |
| TSLA | Buy / short HL | −$0.085 | −$0.215 | −$0.441 | −$0.921 |
| TSLA | Sell / long HL | −$0.508 | −$1.275 | −$2.570 | −$5.227 |

**Four of 136** timing-accepted best-route rows had a positive fee-only entry gap. They were **one correlated NVDA-buy round** expressed at four sizes: **+$0.004155 at $100, +$0.010134 at $250, +$0.019424 at $500, and +$0.035473 at $1,000**. All are below the pilot's $0.10 net target *before* gas, exits, conversion, and any future market move; all are off the HL lot grid. After the separately modeled 5 bp reserve, those four became negative. **Zero of 136** timing-accepted best-route entry gaps were positive after that partial cost screen, and none of the 160 best-route quantities was an exact HL lot. No claim about executable arbitrage or future profitability follows from these quotes.

## What was measured and what remains unknown

The registry's `currentMultiplier` converts each stock-token amount **returned by an exact-input quote** into underlying share units; the HL book is walked for that *same continuous share quantity*. The quoter amount already includes the chosen pool's swap fee and price impact. A single recent block is fixed for both selected pool quotes for an asset, and one near-time HL book is used; the 2-second screen compares the block timestamp and local quote/book receipts. These clocks do not prove simultaneous executable prices or venue-wide source synchronization. USDG and HL's USDC are treated at parity **only** for the displayed numeric gap; no conversion route or transfer cost is priced.

This is a **single entry** screen. It omits AMM approval and transaction gas, slippage between quote and mined transaction, HL order grid and minimum at a valid rounded quantity, partial hedge residual, both future exits, funding, inventory/collateral on separate venues, and conversion. A canonical AMM swap and an HL perp trade are on separate execution domains and are not atomic. The current direct-pool candidate set comes from an earlier Dexscreener index and includes one verified v3 and one verified standard no-hook v4 pool per token; it does not claim every possible pool or split route was checked. The raw capture contains every direct-pool quote and error slot, fixed block and timing fields, registry snapshots, pool verification, and HL books. Route selection in [analysis.json](analysis.json) is a post hoc price screen among those two predeclared candidates, not a rule fitted to execute a trade.

The observed small-size canonical AMM quotes do not supply evidence to lower the RH-domain maker pilot's $100 floor or replace its $1,000 primary benchmark. They answer a different question, on different instruments and execution venues, and even the optimistic entry-only bound was negative after its stated partial costs in every timing-accepted best-direct observation.

## Reproduce

The collection already stopped; rerun only the offline analysis:

```bash
python scripts/analyze_rh_small_amm.py data/raw/rh_small_canonical_amm/20260929T224037Z
python -m unittest tests.test_rh_small_canonical_amm tests.test_analyze_rh_small_amm -q
```

The initial non-networked sandbox launch is retained as a [stopped DNS-error artifact](../../data/raw/rh_small_canonical_amm/20260929T224026Z/manifest.json), not included in the result.
