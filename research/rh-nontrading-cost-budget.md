# RH–Hyperliquid nontrading cost budget

**29 September 2026; public documentation review only.** Scope: a prefunded RH Lighter USDG perp leg and Hyperliquid USDC perp hedge, at $100/$250/$500/$1,000 per leg. This separates costs outside the four modeled fills and the monitor's separate capital charge. Published terms can change; no account, transfer, swap, order or live quote was used.

## What is documented

| Item | Supported treatment | Source |
| --- | --- | --- |
| Perp trading fees | Keep the four actual modeled fill fees by venue, tier, side and size. Lighter **Core** publishes Standard 0 maker/0 taker, Plus 0.5 bp and paid Premium. **RH Lighter's separate schedule** also showed Standard 0/0 and Plus 0.5 bp in its 26 September archived official page; base Premium was 1.2 bp maker/3.5 bp taker below $1 million trailing volume. Its separate instance has separate liquidity. None is a reason to add 5 bp as a published exchange fee. | [Lighter Core fee schedule](https://docs.lighter.xyz/trading/trading-fees); [RH account types](https://apidocs.rh.lighter.xyz/docs/account-types) ([dated local copy](../reports/funding-carry/raw/sources/rh_accounts.md)); [RH domain separation](https://docs.robinhood.com/chain/lighter-domains/) |
| Hyperliquid trading and funding | HL trading fees depend on account tier and possibly HIP-3 deployer/growth settings. Trading on HL does not cost separate gas according to its onboarding guide. Funding is a separate actual signed cashflow, not part of this reserve. | [HL fee schedule](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees); [HL onboarding](https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/how-to-start-trading) |
| HL wallet movement | Depositing USDC through its Arbitrum bridge requires ETH gas on Arbitrum. HL's own withdrawal to Arbitrum is **$1**, with no user gas for that HL action; its API describes about five minutes to finalize. A new HyperCore destination account can incur a one-time 1 quote-token activation charge, not a routine trade charge. | [HL onboarding](https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/how-to-start-trading); [HL exchange API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint); [activation rule](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/activation-gas-fee) |
| RH collateral movement | Robinhood Wallet says RH Lighter margin is USDG locked in the Lighter relayer contract; a close leaves it in the **trading contract balance** until a separate withdrawal. RH Chain's direct deposit invokes an on-chain contract; Robinhood Chain gas is ETH and varies with L2 execution and L1 data fees. Lighter's RH instance has separate sequencing and liquidity from Core. Fast and secure RH withdrawals exist, but the public pages reviewed do not establish a fixed dollar fee for either mode. | [Robinhood Wallet perps](https://robinhood.com/us/en/support/articles/robinhood-wallet-perpetual-futures/); [RH Lighter domain](https://docs.robinhood.com/chain/lighter-domains/); [RH gas](https://docs.robinhood.com/chain/gas-and-fees/) |
| Core Lighter as a possible destination | Core perps accept USDC. Its deposit guide lists USDG from RH Chain among supported inputs to a routing service, and exposes an **estimated** fee/minimum-received quote endpoint; the builder route requires an API key. Core documents secure/fast withdrawals and minimums, but no universal fixed withdrawal charge on this page. This is a route to investigate, **not** a free RH↔HL conversion. | [Core deposits/transfers/withdrawals](https://apidocs.lighter.xyz/docs/deposits-transfers-and-withdrawals) |

**Per-trade chain gas:** RH Chain charges gas for transactions on *that chain*. The cited Lighter/RH documents do not identify a separate RH Chain ETH gas debit on every matched perp order inside the Lighter domain. We therefore have **no verified extra per-fill gas amount** to add to the paper fills, and also cannot assert it is guaranteed zero for every account path. Direct contract deposits, withdrawals or swaps are distinct on-chain actions that need transaction-specific gas estimates/receipts. A wallet signature is not itself proof that each matched order incurs an RH Chain transaction fee. Do not borrow Robinhood's unrelated broker futures or EU-perp schedules for this RH Lighter account.

## A priceable rebalance path, without inventing its price

The least assumption-heavy operating model is **prefund and reuse two separate wallets**: keep RH USDG and HL USDC at each venue, and allow local closed-trade proceeds to fund later trades there. No USDG↔USDC conversion is required for every paired trade. Rebalance only after an inventory threshold or planned withdrawal; track opportunity cost of idle USDG/USDC separately from an actual transfer charge.

For RH→HL, the operational path is: release USDG from RH Lighter to an RH Chain wallet; obtain a **current exact-size, time-stamped** USDG-on-RH to USDC-on-Arbitrum swap/bridge quote (or separately quote swap and bridge); check minimum received, provider fee, network gas, price impact and expiry; then deposit USDC to HL from Arbitrum. Robinhood Chain [documents bridge and swap-route classes](https://docs.robinhood.com/chain/bridging/), including canonical bridging and third-party swap/bridge aggregators, but does **not** quote a USDG→USDC exchange rate for this route. [Robinhood Wallet's swap guide](https://robinhood.com/us/en/support/articles/send-receive-and-swap-crypto/) says displayed output can differ due to liquidity, slippage, swap fees and network fees. A reverse HL→RH route starts with HL's documented $1 USDC withdrawal to Arbitrum, then a quoted USDC→USDG bridge/swap and RH deposit. The canonical RH↔Ethereum bridge can impose a seven-day withdrawal challenge and Ethereum claim gas; a faster provider may price its own risk. Neither route implies instant cash availability.

The current monitor treats USDG, USDC and dollars at parity. That is a **scenario assumption**, not a guaranteed executable conversion. Without an actual supported quote for the chosen amount and direction, leave conversion cost and turnaround as *unknown* or run explicitly labeled stresses; do not assign them zero, one bp, or the monitor's five bp by fiat. Keep quote execution quality and a possible stablecoin basis/depeg shock separate. A hypothetical loss from a stablecoin shock should be a scenario tail, not an exchange fee.

## How to use the 5 bp allowance

The monitor's extra **5 bp of one $N$ leg** is $0.05/$0.125/$0.25/$0.50 at $100/$250/$500/$1,000 respectively. For equal-sized four-fill round trips, that is **1.25 bp of gross completed fill turnover**. It is a *stress allowance*, neither a published RH/HL fee nor a measured transfer quote. With no rebalance during a trade, assigning a full bridge/withdrawal charge to every round trip would overstate a route cost that might be shared across many turns. Conversely, a $1 HL withdrawal alone exceeds the $0.05 allowance for one $100 trade if that trade alone causes the withdrawal.

For a planned rebalance cycle, estimate its all-in external cash cost
`C_route` from input value minus the quoted minimum output value in a common
numeraire, plus only fixed charges and network gas **not already included**
in that quote. After execution, replace the quoted component with input
value minus actual received value and actual external receipts. Do not add
a separate realized conversion loss on top of an input/output difference
that already includes that loss, or charge embedded bridge/swap fees twice.
If that cycle supports (M) completed paired turns with observed four-fill
dollar turnover (T_{\rm completed}=\sum_{j=1}^M\sum_{k=1}^4 |V_{jk}|), its allocated nontrading cost is

\[
r_{\rm route,bp}=10{,}000\,C_{\rm route}/T_{\rm completed},\qquad
C_{{\rm route},j}=C_{\rm route}\,T_j/T_{\rm completed}.
\]

Show both the cash amount and turnover bp; do not assume four fills when maker inventory is recycled or partially filled. Account for any unfinished inventory and terminal rebalance liability before counting (M). Capital carrying cost, funding, explicit trading fees and realized basis/price P&L stay in their **existing separate ledger fields**. In particular, the fill model already records adverse entry/exit price movement, displayed spread and depth impact in price P&L. Recharging the same movement as an invented “slippage fee” would double-count it. Compare (a) recorded fills with no unquoted extra cost, (b) the current 5 bp stress allowance, and (c) a quote-backed rebalance budget when available; never add overlapping allowances as if each were a distinct paid charge.
