# Historical carry and basis check

**Observation window:** 2026-08-30 03:00 to 2026-09-29 03:00 UTC, exactly 720 completed hourly slots. The first 480 hours (20 days) choose a funding direction **once per pair**. The next 240 hours (10 days) evaluate that frozen direction. Every candle used for entry, exit, or basis began before the 03:00 cutoff; the still-open 03:00 candle is excluded. This is a single historical holdout, not a live fill record or proof of repeatable profit.

Data and reproducibility: [`scripts/history_analyze.py`](../scripts/history_analyze.py), derived [pair results](../data/derived/history_20260929T035055Z/history_perp_pairs.csv), [cash carry results](../data/derived/history_20260929T035055Z/history_cash_carry.csv), and [daily funding rows](../data/derived/history_20260929T035055Z/history_daily_funding.csv). Raw sources are the timestamped [Hyperliquid](../data/raw/hyperliquid/20260929T034903Z) and [comparator](../data/raw/comparators/20260929T035055Z) API captures. The comparator inventory includes archived dYdX on-chain [fee parameters](../data/raw/comparators/20260929T035055Z/dydx/fee_tiers.json). No Robinhood Chain historical fills or books enter these calculations.

## Methods and checks

All funding rates use the sign **positive = long pays short**. Hyperliquid and dYdX rates are fractions per hourly settlement. Lighter's `rate` is a **percent per hour**, so `0.0012` becomes `0.000012` as a fraction; `direction=short` reverses the sign. The unit is independently supported by a raw Lighter BTC record: its `$0.93769920` payment on roughly `$78,000` notional agrees with `0.0012%`. Aster rates are signed fractions **per event**, with observed 8-hour, 4-hour, and variable intervals; the analysis sums settled events within each window without multiplying them by eight or filling unstated hours. Hyperliquid and [dYdX](https://help.dydx.trade/en/articles/166992-default-funding-rates-on-dydx) fund hourly; [Hyperliquid's formula and payment convention](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) use oracle notional. Aster funding is also paid between long and short traders according to its [official funding description](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/funding-rate).

For two perps, the training side is **short Hyperliquid and long comparator** if Hyperliquid's summed funding exceeds the comparator's; otherwise the reverse. Holdout funding edge is the difference of realized event-rate sums in that fixed direction, reported in basis points of notional. For the same crypto unit, a diagnostic dollar P&L also holds one unit on each venue from the prior completed hourly close at the split through the last completed hourly close. It adds the **change in the two candle-close prices** to funding cash approximated from the preceding closed candle price, and divides by starting Hyperliquid price. Actual funding uses exchange oracle/mark prices, and closing trade prices do not show executable bid/ask depth. Funding-only bps and approximate funding-cash bps therefore differ slightly.

Taker fees apply separately to both legs at entry and exit, each on its own **entry or exit price** rather than on a fixed starting notional. Rates assumed: Hyperliquid tier-0 native 4.5 bp per side and HIP-3 per-asset multiplier from the [official fee formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees); Lighter Standard 0 bp; Aster USDT 4 bp from its [fee page](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees); dYdX tier-0 5 bp from the archived on-chain parameters, with user tiers subject to [30-day volume](https://help.dydx.trade/en/articles/166995-trading-fees-on-dydx). Spread, impact, slippage, gas, token/bridge cost, collateral conversions, account-specific discounts, liquidation risk, and funding changes after the sample are excluded. A second *illustrative* cost applies a simple 5% annual financing rate for 10/365 year to 40% of initial notional (20% margin on each perp leg), or to 120% for spot plus perp (100% spot plus 20% margin). These are sensitivity assumptions, not quotes.

The script checks the identity that the ten daily funding rows sum to each holdout funding result and that each reported fixed-unit gross equals basis change plus price-weighted funding. All paired **holdout** crypto candles cover 240/240 closed hours. Lighter has 719/720 paired candles over the entire 30 days because its first price hour is absent; that hour is before the holdout. dYdX has 720/720 for the major crypto pairs. A price-based result is withheld if more than 10% of the comparator's holdout candles show zero trade volume. This excludes dYdX HYPE (38%), dYdX ZEC (48%), and dYdX silver (94%). Aster NVDA (27%) and Aster SPY (28%) also fail the price-quality screen. dYdX EUR-USD is in final settlement and is not compared. Funding-only numbers for these markets remain descriptive, not trade recommendations.

## Held-out results: matched crypto perps

All figures below are **basis points per initial underlying notional over the final 10 days**, rounded to 0.1 bp. `Direction` is the Hyperliquid leg selected using only the first 20 days. `Funding` sums the event-rate differential; `Basis` is the fixed-unit change of two closed-candle prices; `Gross` includes a price-weighted estimate of funding cash. `After fees` deducts the four modeled taker trades. `After capital` also deducts the illustrative 5.5 bp financing cost. Neither of the last two columns includes execution spread or impact.

| Pair: HL vs comparator | Direction | Funding | Funding-positive days | Basis | Gross | After fees | After capital |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC vs Lighter | Long | −2.1 | 5/10 | −6.6 | −8.7 | −17.8 | −23.3 |
| BTC vs Aster | Short | +14.8 | 9/10 | +10.2 | +25.6 | +8.5 | +3.0 |
| BTC vs dYdX | Short | +28.5 | 10/10 | +11.7 | +41.1 | +22.0 | +16.5 |
| ETH vs Lighter | Short | +4.2 | 10/10 | +0.4 | +4.8 | −4.3 | −9.8 |
| ETH vs Aster | Short | +9.3 | 10/10 | +5.5 | +15.1 | −2.0 | −7.5 |
| ETH vs dYdX | Short | +9.5 | 5/10 | +5.3 | +15.3 | −3.8 | −9.2 |
| SOL vs Lighter | Short | +5.1 | 10/10 | +0.6 | +6.0 | −3.1 | −8.6 |
| SOL vs Aster | Short | +16.1 | 8/10 | +1.8 | +18.7 | +1.4 | −4.1 |
| SOL vs dYdX | Short | +22.8 | 8/10 | −0.9 | +23.8 | +4.5 | −1.0 |
| HYPE vs Lighter | Short | +9.8 | 9/10 | −0.3 | +9.4 | +0.8 | −4.7 |
| HYPE vs Aster | Short | +32.7 | 10/10 | +7.5 | +39.9 | +23.6 | +18.1 |
| ZEC vs Lighter | Long | +10.9 | 7/10 | −5.1 | +5.2 | −3.3 | −8.7 |
| ZEC vs Aster | Short | +18.1 | 10/10 | +15.7 | +33.6 | +17.5 | +12.0 |

**Counterexample to extrapolating training carry:** BTC/Lighter's first 20 days favored long Hyperliquid/short Lighter by +1.9 bp of funding. That direction lost −2.1 bp of funding in the holdout and −8.7 bp including closing-price basis change. Gold/Lighter, SP500/SPY on Lighter, and Brent/Lighter also reversed their training funding advantage. The final seven training days had already disagreed with the full 20-day sign for some of these proxy pairs, visible in the derived CSV. Choosing the best pair after seeing the holdout would destroy the out-of-sample interpretation.

Aster ZEC's settlement cadence changed within this sample: **250 funding events in the 20-day training window and 30 in the 10-day holdout**, with the latter settling roughly every eight hours. The table sums the actual event rates in each window; it does not assume that its earlier hourly funding continued.

## Hyperliquid spot plus native perp

The long-spot/short-perp side is fixed by the feasible cash-and-carry structure; it is **not selected** using training. Spot API pair identifiers and actual token names matter: `@142=UBTC/USDC`, `@151=UETH/USDC`, `@156=USOL/USDC`, `@107=HYPE/USDC`, `@272=UZEC/USDC`. The tokens may have custody, redemption, and bridge risks distinct from the native crypto reference asset. Each pair has 240/240 paired holdout candles. Positive perp funding paid the short on all ten holdout days for every listed asset. These are indicative same-venue carry estimates, not Robinhood Chain arbitrage observations.

| Spot / short perp | Funding-rate sum | Worst funding day | Spot-perp basis change | Gross fixed-unit estimate | After four taker fees | After illustrative capital cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| UBTC / BTC | +28.2 | +1.2 | +11.6 | +40.8 | +17.5 | +1.1 |
| UETH / ETH | +32.8 | +3.0 | +1.5 | +35.2 | +12.0 | −4.4 |
| USOL / SOL | +30.3 | +2.5 | +0.0 | +31.2 | +7.9 | −8.6 |
| HYPE / HYPE | +33.1 | +2.1 | +12.5 | +45.2 | +23.1 | +6.7 |
| UZEC / ZEC | +42.7 | +2.8 | −14.8 | +27.4 | +5.7 | −10.7 |

The HYPE example requires roughly **22.0 bp** in modeled entry/exit taker fees and **16.4 bp** in the illustrative 120%-capital financing scenario. Its remaining **6.7 bp over ten days** is before spot/perp bid-ask spreads, price impact, and any token-related costs. This is a sensitivity result, not an investment return projection.

## Other asset classes and contract mismatch

The following are funding-only comparisons unless otherwise noted. The pair labels are **reference-price oracles**, not interchangeable deliverable claims. Official [trade\[XYZ\] stock hours](https://docs.trade.xyz/perpetuals/markets/stocks/us), [FX quote conventions](https://docs.trade.xyz/perpetuals/markets/fx), [commodity roll method](https://docs.trade.xyz/perpetuals/markets/commodities), and [index method](https://docs.trade.xyz/perpetuals/markets/equity-indices/us) differ by product. Lighter's [RWA specifications](https://docs.lighter.xyz/trading/real-world-assets-rwas/market-specifications) give one-share, one-troy-ounce, and FX reference units. Its [futures roll schedule](https://docs.lighter.xyz/trading/real-world-assets-rwas/futures-contract-price-rolling-mechanism) specifies Brent roll transitions; even when both Brent markets use a barrel, their oracle and roll timing can diverge.

| Comparison | 10d selected-side funding edge | Positive days | Worst day | Descriptive basis change | Key limitation |
| --- | ---: | ---: | ---: | ---: | --- |
| `xyz:NVDA` / Lighter NVDA | +8.9 bp | 5/10 | −0.5 bp | −0.5 bp | Same share-sized reference, different synthetic contract/oracle; no stock delivery. |
| `xyz:NVDA` / Aster NVDA | −0.9 bp | 4/10 | −1.5 bp | withheld | 27% of holdout candles had no trades. |
| `xyz:GOLD` / Lighter XAU | −5.2 bp | 3/10 | −2.7 bp | +0.3 bp | One-troy-ounce gold reference; no physical delivery. |
| `xyz:GOLD` / Aster XAU | +14.2 bp | 6/10 | −1.5 bp | +3.2 bp | Gold reference; contract/oracle basis persists. |
| `xyz:SILVER` / Lighter XAG | +6.7 bp | 6/10 | −0.6 bp | −4.9 bp | One-troy-ounce silver reference. |
| `xyz:SILVER` / Aster XAG | +5.4 bp | 6/10 | −1.7 bp | −2.4 bp | 2.5% zero-volume candle hours. |
| `xyz:SILVER` / dYdX XAG | +24.7 bp | 10/10 | +0.0 bp | withheld | 94% zero-volume hours; 24h market volume zero in captured metadata. |
| `xyz:SP500` / Lighter US500 | +22.4 bp | 4/10 | −2.1 bp | +6.3 bp | Both large-cap index references, but different construction and oracle; Lighter's is not the licensed S&P contract. |
| `xyz:XYZ100` / Lighter US100 | +24.8 bp | 6/10 | −1.5 bp | −3.4 bp | Both top-100 non-financial references; trade[XYZ]'s modified weighting differs from Lighter's feed. |
| `xyz:SP500` / Lighter SPY | −14.8 bp | 2/10 | −4.4 bp | withheld | S&P index vs ETF share; price level scaled about 10:1 but dividend/expense basis is real. |
| `xyz:SP500` / Aster SPY | +2.8 bp | 4/10 | −1.5 bp | withheld | Index vs ETF plus 28% no-trade candles. |
| `xyz:BRENTOIL` / Lighter BRENTOIL | −7.8 bp | 2/10 | −2.9 bp | +0.9 bp | Separate deployer roll schedules/oracles; training advantage of +79.4 bp reversed. |
| `xyz:EUR` / Lighter EURUSD | +18.4 bp | 8/10 | −0.1 bp | +2.3 bp | Both EUR/USD-style quote; weekend internal pricing and 6.7% no-trade candles. |

Hyperliquid also has JPY, GBP, single-name shares, 10-year-rate-style contracts, and other categories in the venue census. There was no aligned 30-day comparator history for those here. In particular, a yield-like `para:10Y` value around 5.25 is not a bond price and should not be paired with a bond token without duration and payout modeling. Native Hyperliquid `SPX` is a Solana token exposure, not the S&P 500 index. No historical executable Robinhood Chain order-book spread is inferred for any of these instruments.

## RH-domain Lighter history and same-domain stock-token carry

The separate `api.rh.lighter.xyz` venue has its own [timestamped 30-day hourly captures](../data/raw/comparators/rh_lighter/20260929T040726Z/history), with 720 funding events and candles for 11 sampled perps, including BTC, ETH, SOL, HYPE, AAPL, NVDA, META, MSFT, gold, silver, and SPY. Its funding has the same Lighter **percent-per-hour** rate/direction unit as Lighter Core; the raw BTC payment independently validates the conversion. These are **separate order books and collateral domains**. Its API reported zero Standard taker fees for the sampled markets, but wallet/account terms and funding access still need verification. The cross-domain pair results below use the same 20-day training/10-day holdout and the same 240 completed holdout candles as above. RH-domain perps are USDG-quoted; Hyperliquid perps are USDC-margined, so actual conversion cost is absent.

| HL vs RH-domain perp | HL direction | 10d funding edge | Fixed-unit basis change | Gross | After modeled taker fees | After illustrative perp capital cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BTC | Long | −6.6 bp | −5.5 bp | −12.3 bp | −21.4 bp | −26.9 bp |
| ETH | Long | −4.4 bp | +0.6 bp | −3.9 bp | −12.9 bp | −18.4 bp |
| SOL | Short | +22.2 bp | −2.9 bp | +20.5 bp | +11.3 bp | +5.9 bp |
| HYPE | Short | +4.2 bp | +4.9 bp | +9.1 bp | +0.4 bp | −5.0 bp |

For four RH-domain share-price-reference pairs, the training-selected holdout funding edges were NVDA **+7.4 bp**, AAPL **−4.4 bp**, META **+20.3 bp**, and MSFT **−1.0 bp**. Within the **51 hourly settlements** classified as New York overnight (Sunday–Thursday 8 PM–4 AM ET), their corresponding edges were **+3.6, −1.3, +9.9, +0.6 bp**. The overnight subset is part of the full 240 hours, not an additional return; price basis, weekend/internal-oracle mechanics, and execution remain relevant. The full [pair CSV](../data/derived/history_20260929T035055Z/history_perp_pairs.csv) also includes RH-domain gold/silver/SPY reference-pair diagnostics.

RH-domain Lighter spot markets `NVDA/USDG` and `SPY/USDG` identify the same issuer token addresses as Robinhood Chain's canonical stock-token registry, and their API `multiplier` values match the issuer's current shares-per-token ratios. The [asset and unit evidence](../data/raw/comparators/rh_lighter/20260929T040726Z/spot_unit_validation.json) establishes token identity; practical deposit/withdrawal fungibility has not been tested. To model a fixed **one-token** spot position, the history analysis shorts its effective shares-per-token multiplier in the same-domain share-reference perp, with no multiplier update during this holdout. The spot candles are inferred to quote USDG per token from market metadata and contemporaneous prices; the API documentation does not expressly state price scaling. Both spot and perp API fee fields were zero for the sampled Standard markets.

| RH-domain long stock token / short perp | 10d funding-rate sum | Token-perp basis change | Gross one-token estimate | 5% annual cost on 120% capital | After illustrative capital cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVDA/USDG + NVDA perp | +21.2 bp | withheld | withheld | 16.4 bp | withheld |
| SPY/USDG + SPY perp | +11.7 bp | −3.0 bp | +8.7 bp | 16.4 bp | −7.7 bp |

**NVDA's spot candle series fails the price-quality screen:** 108 of 240 holdout hours (45%) recorded zero spot volume, and the entry/exit spot hours recorded only **$299.75/$49.98** of quote volume. A stale endpoint close can drive the apparent one-token P&L. The unfiltered formula would be +36.6 bp gross (+20.2 bp after illustrative financing), retained in the CSV **for audit only**, not as an opportunity estimate. The market's captured trailing 24-hour volume was about **$61.6k** versus **$20.6m** for SPY. SPY had zero zero-volume holdout hours, and its entry/exit spot hours recorded about **$324k/$1.11m** of quote volume. Neither spot history includes order-book depth or actual fills at entry/exit. Token settlement, bridge and withdrawal terms, funding collateral segregation, and real wallet fees can change the result.

## Robinhood Chain stock-token price diagnostic

The Robinhood Chain [hourly pool candles](../data/raw/robinhood_history_complete_20260929T040036Z.json) originally used GeckoTerminal `currency=usd`, an indexer-converted USD price per stock token. We independently archived the **actual AMZN/USDG pool quote** via [`currency=token`](../data/derived/history_20260929T035055Z/amzn_gecko_crosscheck_raw.json), then all seven canonical pools' [quote-denominated candles](../data/derived/history_20260929T035055Z/rh_quote_candles_raw.json). The USDG quote is the primary historical comparison unit. We divide its close per token by the **shares-per-token multiplier effective at that hour**, using [public on-chain ERC-8056 update logs](../data/raw/robinhood_multipliers_20260929T040952Z.json) scanned from before this 30-day window. The scan contains no cancellation events, and every latest effective multiplier matches Robinhood's registry. The hour containing an update is dropped because its candle may mix two share ratios. We pair the same **completed UTC hour** against Hyperliquid's USD/share `xyz` perp close. A USDG quote is compared to a USD reference as an approximate near-par value, not as an executable currency conversion.

The need for this quote-unit check is concrete. The AMZN primary-pool **USD-indexed** close diverged sharply while its **USDG quote** stayed near Hyperliquid and a second AMZN/USDG pool. All prices below are per token or share as labeled; the multiplier for AMZN was 1 throughout.

| UTC hour | HL AMZN close, USD/share | Primary pool, USDG/token | Primary indexer USD/token | Alternate pool, USDG/token | Primary implied USDG→USD factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sep 21 17:00 | 258.06 | 257.515 | 267.366 | 257.509 | 1.0383 |
| Sep 23 13:00 | 250.53 | 250.610 | 264.679 | 250.814 | 1.0561 |
| Sep 25 13:00 | 248.68 | 249.566 | 250.567 | 248.355 | 1.0040 |

An independent [CoinGecko Global Dollar USD series](../data/raw/robinhood_usdg_coingecko_20260929T041551Z.json) at Sep 21 17:00 and Sep 23 13:00 was **$1.000090** and **$0.999946**, respectively; its 121 hourly observations over Sep 21–26 ranged **$0.999787–$1.000091**. [Paxos describes USDG as redeemable 1:1](https://docs.sandbox.paxos.com/guides/stablecoin/usdg/index). Thus Gecko's implied 1.038–1.056 factors at these hours do not reflect the independent market indication. The alternate pool independently shows a similar USDG quote near the share reference. Its Sep 25 13:00 USD-indexed/quote-price factor was **1.0462**, while the primary pool's was **1.0040**, making the indexer artifact partly pool-specific. These are **indexer USD-conversion artifacts**, not measured AMZN tradeable premiums. CoinGecko's global price is corroboration only; it is not a Robinhood Chain executable USDG conversion quote.

Signed basis below is `10,000 × (Robinhood USDG/share close ÷ Hyperliquid USD/share close − 1)`. The table covers the same 720 closed hours. The 90th percentile absolute basis is a historical dispersion measure, **not an arbitrage opportunity count**. Sessions use America/New_York; regular hours are classified by hourly-bar midpoint 9:30 AM–4 PM weekdays, without a separate holiday calendar. Full per-hour USD-indexed and USDG-quoted prices, multipliers, inferred indexer factors, volumes, and sessions are in the [derived hourly file](../data/derived/history_20260929T035055Z/history_robinhood_hl_hourly.csv).

| Stock | Paired hours / 720 | Median signed quote basis | Median absolute quote basis | 90th percentile absolute | Regular median absolute | Weekend median absolute |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 720 | +2.5 bp | 6.9 bp | 19.2 bp | 6.9 bp | 7.8 bp |
| NVDA | 719 | +1.6 bp | 5.9 bp | 14.6 bp | 6.1 bp | 6.8 bp |
| GOOGL | 719 | +1.2 bp | 6.7 bp | 17.7 bp | 7.0 bp | 6.9 bp |
| MSFT | 719 | −8.3 bp | 27.6 bp | 50.6 bp | 25.6 bp | 28.0 bp |
| TSLA | 718 | −4.6 bp | 26.2 bp | 47.8 bp | 21.7 bp | 29.1 bp |
| AMZN | 718 | −4.1 bp | 25.3 bp | 46.5 bp | 26.5 bp | 25.2 bp |
| META | 710 | −6.7 bp | 23.1 bp | 48.2 bp | 22.8 bp | 24.5 bp |

NVDA, AAPL, and GOOGL have the narrowest **historical last-trade reference basis** in this sample; that ranking depends on candles and does not show two simultaneous executable quotes. The USD-indexed AMZN 90th-percentile absolute basis of 411.9 bp falls to **46.5 bp** in actual USDG pool quotes after fixing the conversion artifact. Even the lower quote-basis percentiles can be consumed by two venues' entry/exit spreads, fees, impact, financing, collateral conversions, and token custody/redemption risks. A stock token's dividends and other holder rights are not delivered by a perp. This is a live-screen candidate map, not a historical profit backtest.

## Interpretation

The ten-day holdout shows a few **fee-and-capital-sensitivity survivors**, especially HYPE/Aster, ZEC/Aster, and BTC/dYdX among matched crypto perps. Their positive numbers are only a research screen. Every remaining edge must exceed both venues' contemporaneous executable spread and depth impact at the intended size, actual wallet fees, transfer/collateral costs, and the risk of future funding and basis moving against the hedge. The 20/10-day split is one non-independent observation period; it does not establish a stable expected return. The negative or near-zero outcomes across several other pairs show why a positive funding spread alone is an insufficient arbitrage test.
