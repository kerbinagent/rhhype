# What the 5 bp buffer does to the RH passive-cycle test

**Read-only cost sensitivity, 2026-09-30 UTC, using stopped September 29 books.** The [offline analyzer](../scripts/analyze_passive_cost_buffer.py) applies hypothetical batch costs to the same [4,336 matched four-leg quote rows](../reports/passive-hedge-venues/matched-rows.csv). It makes no new market request and observes no RH maker fill, transfer, conversion, or account balance. The full [scenario table](../reports/passive-cost-buffer/scenario-groups.csv) covers both RH directions, both hedge venues, $100/$250/$500/$1,000, static same-book arithmetic and +10–16 s delayed quotes. These are candidate quote scores, **not realized cash P&L**.

## Separate paid costs from the stress allowance

The prior replay already includes displayed four-leg price movement, hedge depth, published public-tier fill fees on each leg's own notional, and a 5% annual capital charge for the delayed seconds. An adverse later book is therefore already in price P&L; adding it again as a guessed “slippage fee” would double-count it. The extra **5 bp of the larger entry leg** is a stress allowance, not a paid or published charge. Its approximate per-turn dollars are $0.05, $0.125, $0.25 and $0.50 at the four quote sizes. It equals about 1.25 bp of four-fill turnover when the leg notionals are similar.

The operating case worth pricing is prefunded, separate USDG collateral at RH and USDC at HL or Core, with closed-trade proceeds reused at each venue. [Robinhood Wallet documents that closing an RH perp returns remaining margin to the trading contract balance and requires a **separate** withdrawal to move it to the wallet](https://robinhood.com/us/en/support/articles/robinhood-wallet-perpetual-futures/). It also says available USDG excludes position and pending-order margin. [RH and Core are distinct Lighter domains](https://docs.robinhood.com/chain/lighter-domains/) with separate liquidity; a Core hedge does not make RH collateral portable. [HL says trading is gas-free but external USDC deposit needs source-chain gas](https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/how-to-start-trading); its [`withdraw3` API describes a $1 withdrawal fee and roughly five-minute finality at the time of writing](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). That $1 applies **when that withdrawal actually occurs**, not on each closed trade. The RH withdrawal, swap/bridge, network gas, USDG/USDC conversion and depeg cost have no universal dollar quote in these sources. [Core's documented USDG-from-RH routing option](https://apidocs.lighter.xyz/docs/deposits-transfers-and-withdrawals) exposes an estimated fee/minimum-received quote, not a guaranteed free conversion. Do not infer actual account access or a zero cost from that option.

Define a transfer only when the relevant venue's **available collateral** falls below a predeclared next-order margin plus safety floor, or when a predeclared scheduled rebalance/terminal withdrawal occurs. Record `venue balance + realized venue P&L − actual venue fees/funding ± transfers`, pending orders, maintenance margin and available margin separately. Net paired P&L can be positive while losses accumulate on one venue, so the number of turns before rebalance is a **hitting-time outcome**, not reliably one per trade or automatically 100. Prefunding can amortize a fixed movement over many completed turns, but ties up collateral and creates a terminal exit obligation. A quoted cost for the actual transfer direction/size should replace the example below once available. Do not add its embedded swap and bridge fees twice; use actual input minus received output plus separately invoiced charges after settlement.

## Bounded illustrative batch costs

Let **C** be the *entire external cost of one eventual rebalance* and **M** be the number of *completed* paired cycles it supports. For homogeneous sizes, the illustration allocates `C/M` per completed cycle; with unequal fills, allocate by observed four-fill turnover instead. **$1/$2/$5 and 10/50/100 cycles are explicitly hypothetical**, not quoted RH↔HL or RH↔Core routes. Applying the same C to both hedge venues isolates the captured book and trading-fee difference; it does not assert their real transfer routes cost the same. Even the documented $1 HL withdrawal is only one component of a possible route. None of the archives can establish M because no actual maker cycles completed.

| Hypothetical batch | Per completed cycle | Approx. four-fill turnover cost at $100 / $1,000 | Compared with 5 bp one-leg buffer |
|---|---:|---:|---|
| $1 / 100 cycles | $0.01 | 0.25 / 0.025 bp | Smaller at all four sizes |
| $2 / 50 cycles | $0.04 | 1.0 / 0.10 bp | Smaller at all four sizes |
| $5 / 10 cycles | $0.50 | 12.5 / 1.25 bp | Larger at $100–$500; about equal at $1,000 |

For one-leg notional approximately equal to the displayed quote size, the five bp buffer equals $1 shared over **20, 8, 4, 2** turns at $100/$250/$500/$1,000; $2 shared over **40, 16, 8, 4** turns; and $5 shared over **100, 40, 20, 10** turns. Exact row buffers differ slightly because quantity is floored to the common lot.

The table below counts **positive static RH-long quote scores** at the captured same-time bid/ask, first with explicit modeled fees/capital only, then after C/M. Each cell is `HL / Core Standard`; RH-short static scores mirror these counts and are not independent evidence. The existing 5 bp stress leaves **zero positive** in every group. This table is an arithmetic sensitivity conditional on both RH maker fills at an unchanged book, not a tradable return.

| Asset | Size | Common quotes | Fee-only | $1/100 | $2/50 | $5/10 |
|---|---:|---:|---:|---:|---:|---:|
| BTC | $100 | 75 | 0 / 61 | 0 / 6 | 0 / 0 | 0 / 0 |
| BTC | $250 | 75 | 0 / 59 | 0 / 33 | 0 / 0 | 0 / 0 |
| BTC | $500 | 75 | 0 / 59 | 0 / 47 | 0 / 8 | 0 / 0 |
| BTC | $1,000 | 75 | 0 / 58 | 0 / 53 | 0 / 30 | 0 / 0 |
| ETH | $100 | 75 | 0 / 72 | 0 / 39 | 0 / 0 | 0 / 0 |
| ETH | $250 | 75 | 0 / 72 | 0 / 67 | 0 / 2 | 0 / 0 |
| ETH | $500 | 75 | 0 / 72 | 0 / 72 | 0 / 51 | 0 / 0 |
| ETH | $1,000 | 75 | 0 / 72 | 0 / 72 | 0 / 67 | 0 / 0 |
| NVDA | $100 | 56 | 4 / 51 | 0 / 29 | 0 / 0 | 0 / 0 |
| NVDA | $250 | 56 | 4 / 51 | 0 / 48 | 0 / 20 | 0 / 0 |
| NVDA | $500 | 56 | 4 / 51 | 4 / 50 | 0 / 35 | 0 / 0 |
| NVDA | $1,000 | 56 | 4 / 50 | 4 / 50 | 0 / 46 | 0 / 0 |
| XAG | $100 | 68 | 68 / 68 | 39 / 68 | 0 / 1 | 0 / 0 |
| XAG | $250 | 68 | 68 / 68 | 61 / 68 | 17 / 65 | 0 / 0 |
| XAG | $500 | 68 | 68 / 68 | 65 / 68 | 53 / 68 | 0 / 0 |
| XAG | $1,000 | 68 | 68 / 68 | 67 / 68 | 61 / 68 | 0 / 0 |

The existing **+$0.10 per-cycle target** is materially harder than merely positive. For $1,000 Core static quotes, the fee-only target counts are **5/75 BTC, 36/75 ETH, 25/56 NVDA, 68/68 XAG**. Under even the hypothetical $1/100 allocation they fall to **2, 31, 24, 68**; at $2/50 they are **0, 17, 20, 67**. The delayed +10–16 s Core sensitivity at $1,000 gives target counts **6/75, 35/75, 24/50, 68/68** under $1/100 and **1, 16, 16, 65** under $2/50. Delayed book movement is already in those scores. Every delayed group also remains zero positive with the existing 5 bp stress. All rows and the other seven batch cases are in the [CSV](../reports/passive-cost-buffer/scenario-groups.csv).

## Test implication

The 5 bp allowance can suppress a **fee-only economic signal** if rebalancing is infrequent and cheap enough; it is therefore not an adequate stand-in for a known paid fee. But the zero-buffer branch is still a two-maker *quote* fantasy until fill probability, queue selection, delayed hedging, capital drift and terminal inventory are measured. It also does not rescue most BTC outcomes at the +$0.10 target. For a **future separate paper protocol**, retain the present 5 bp stress as the primary conservative gate and add a paired fee-only target branch, explicitly labeled “pre-unpriced-cost quoted economics.” Log venue-specific balances, actual closed fills, rebalance triggers, all paid route receipts, and any quoted terminal transfer liability. Replace the buffer with a quote-backed amortized cost only when the route and completion denominator exist. This does not change the current v1 monitor or its decision policy.
