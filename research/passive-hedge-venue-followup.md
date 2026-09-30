# RH two-maker cycle: Core or HL hedge?

**Read-only follow-up, 2026-09-29 UTC.** The [replay script](../scripts/analyze_passive_hedge_venues.py), [matched rows](../reports/passive-hedge-venues/matched-rows.csv), and [machine summary](../reports/passive-hedge-venues/summary.json) compare the *same RH maker entry and maker exit quotes* hedged with two taker trades on either Hyperliquid (HL) or Lighter Core. The inputs are the stopped BTC/ETH and NVDA/XAG archives. No order, fill, new capture, or change to the live HL-focused pilot occurred.

## Why hedge venue matters

[RH Lighter is a separate domain with its own liquidity](https://docs.robinhood.com/chain/lighter-domains/), so the RH bid/ask cannot be treated as a Core order book. RH's [archived official account table](../reports/funding-carry/raw/sources/rh_accounts.md), sourced from [RH's API documentation](https://apidocs.rh.lighter.xyz/docs/account-types) on September 26, lists Standard at **0 bp maker / 0 bp taker**, with 300 ms taker and 200 ms maker/cancel processing. [Core's current public Standard schedule](https://docs.lighter.xyz/trading/trading-fees) also lists **0/0 bp** and 300 ms taker processing. Its trading-fees page says 200 ms maker processing, while its [API account table](https://apidocs.lighter.xyz/docs/account-types) says 0 ms; this conflict does not affect the taker-only Core hedge arithmetic, but prospective execution must confirm current behavior. [HL's tier-0 table](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) lists 4.5 bp taker for native perps. The frozen market metadata for this capture lists 0.9 bp for `xyz:NVDA` and `xyz:SILVER`; HL's documentation explains that HIP-3 growth and deployer settings alter fees. These are public Standard/tier-0 scenarios, not an authenticated fee quote or an assumed private discount.

At one snapshot, let `q` be the same base quantity on all four hypothetical fills. A long RH cycle buys passively at RH bid and sells passively at RH ask, while the hedge sells into a venue bid and buys back through its ask. A short RH cycle reverses every sign. The static gross is therefore the **RH quoted spread minus the hedge venue's executable roundtrip spread and depth cost**, with basis at that instant cancelling across the two hedge trades. We subtract two hedge taker fees on their own fill notionals. This is a decomposition of the displayed books **conditional on both RH maker fills and unchanged books**. It is not an achievable instantaneous trade or an expected return: two passive fills cannot be compelled at one unchanged snapshot, and queue position, fill selection, and adverse movement are unknown.

## Matched method and result

HL L2 receipt anchors are spaced at least five seconds apart without choosing the cheaper hedge route. At each anchor, all three books must pass receipt age ≤1 s, source age ≤2 s, and cross-venue receipt/source skew ≤1 s. We set `q = floor($budget / RH ask, common lot step)` for **$100, $250, $500, $1,000**, then check the captured lot and minimum notional constraints on all three venues. Every HL/Core comparison uses the same RH quotes, exact `q`, and timestamp; both hedge books must contain enough displayed quantity for both taker legs. Unknown maximum-order limits are not assumed away for live execution. Static cases use the same matched entry and exit snapshot. The secondary delayed sensitivity uses the first fresh, matched observation at **+10–16 seconds**, with every venue's source and receipt timestamp after +10 seconds. It does **not** require the original RH posted price to survive until then; doing so would select surviving quotes and hide adverse moves. Missing future/depth cases retain an explicit denominator.

The fee-only score is four-leg quoted cash flow minus explicit public-tier fill fees and 5% annual carrying cost on both entry notionals over the modeled delay. The separate stress score subtracts **5 bp of the larger entry leg notional** as an allowance for unpriced costs. This 5 bp is not a documented exchange charge; USDG/USDC conversion, real collateral transfers, funding, and liquidation remain unpriced. In the static same-book case, capital cost is zero by construction.

The table reports **static** results for the RH-long direction; the RH-short direction has the same static spread arithmetic and counts, so it is not an independent observation. `N` is common, depth-complete anchors per asset and size. Positive and ≥$0.10 counts are **fee-only**. Every group in both directions had **zero positive after the 5 bp stress allowance**.

| Asset | RH quote size | N | HL positive | Core positive | HL ≥$0.10 | Core ≥$0.10 | Median Core−HL, USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | $100 | 75 | 0 | 61 | 0 | 0 | +0.086 |
| BTC | $250 | 75 | 0 | 59 | 0 | 0 | +0.216 |
| BTC | $500 | 75 | 0 | 59 | 0 | 0 | +0.430 |
| BTC | $1,000 | 75 | 0 | 58 | 0 | 5 | +0.859 |
| ETH | $100 | 75 | 0 | 72 | 0 | 0 | +0.090 |
| ETH | $250 | 75 | 0 | 72 | 0 | 0 | +0.226 |
| ETH | $500 | 75 | 0 | 72 | 0 | 0 | +0.452 |
| ETH | $1,000 | 75 | 0 | 72 | 0 | 36 | +0.901 |
| NVDA | $100 | 56 | 4 | 51 | 0 | 0 | +0.019 |
| NVDA | $250 | 56 | 4 | 51 | 0 | 0 | +0.047 |
| NVDA | $500 | 56 | 4 | 51 | 0 | 3 | +0.091 |
| NVDA | $1,000 | 56 | 4 | 50 | 0 | 25 | +0.165 |
| XAG | $100 | 68 | 68 | 68 | 0 | 0 | +0.013 |
| XAG | $250 | 68 | 68 | 68 | 0 | 1 | +0.032 |
| XAG | $500 | 68 | 68 | 68 | 11 | 53 | +0.065 |
| XAG | $1,000 | 68 | 68 | 68 | 38 | 68 | +0.130 |

For the separate delayed +10–16 s sensitivity, common RH-long observations were **75 BTC, 75 ETH, 50 NVDA, 68 XAG** per size. At $1,000, Core fee-only scored ≥$0.10 in **8, 42, 26, 68** observations respectively; HL did so in **0, 0, 1, 34**. Both venues again had **zero** observations positive after the 5 bp allowance, at every size and in both RH directions. The [summary](../reports/passive-hedge-venues/summary.json) gives all directions, sizes, censored counts, medians, and input hashes. These delayed paths remain quote sensitivities: neither RH maker fill nor executable hedge prices after venue processing were observed.

**Decision:** Core Standard materially lowers the explicit hedge fee hurdle for BTC/ETH and often improves the static quote arithmetic for NVDA/XAG. Yet the current stopped books do not show a robust complete-cycle surplus after the stated stress allowance. This warrants a separately predeclared, prospective *paper* comparison of Core against the existing HL control only if the aim is to test real RH passive fill selection and true nontrading costs. Keep the current HL-primary pilot unchanged. Freeze account tier and processing delays, observe RH order queue and post-fill hedge books, require complete maker exit or terminal inventory valuation, and track venue-specific funding, collateral, and conversion before attributing profit. The seven-minute archives and overlapping anchors are too short and correlated to establish expected returns.
