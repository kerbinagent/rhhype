# Settled-funding carry screen — 29 September 2026

**Decision for the next review:** the 24-hour holdout did not support a two-leg, taker-funded carry trade in any of the 16 Hyperliquid–Lighter pairs screened. The largest holdout funding advantage was **4.52 bp** for short Hyperliquid SOL / long Robinhood Chain Lighter SOL, versus **9 bp** for four base-tier taker fees before any spread, impact, bridge, or collateral cost. This is a separate historical strategy screen; it does not change the current 10-second paper policy.

## Evidence and method

The script [`scripts/funding_carry_probe.py`](../../scripts/funding_carry_probe.py) fetched **48 settled hourly funding events** for BTC, ETH, SOL, HYPE, ZEC, COIN, XAG, and NVDA from Hyperliquid, Lighter Core, and the separate Robinhood Chain Lighter domain. The API responses, inventory, request URLs/bodies, and documentation copies are in [`raw/`](raw/). The initial 26 public requests succeeded. Sixteen additional bounded Lighter requests corrected its `count_back` boundary and yielded exactly 48 matched event hours for every asset and venue; all succeeded. No credentials or orders were used. Run `python scripts/funding_carry_probe.py --offline` to regenerate [`comparison.csv`](comparison.csv), [`comparison_stress_10bp.csv`](comparison_stress_10bp.csv), and [`holdout_hourly.csv`](holdout_hourly.csv) from the archived responses; run without `--offline` to collect a fresh rolling window. Five focused checks for rate conversion, unknown/nonfinite data and duplicate conflicts, train-only direction selection, monitor-equivalent costs, and exact raw-data reproducibility pass with `python -m unittest discover -s tests -p test_funding_carry_probe.py -v`.

The fixed event window is **27 Sep 17:00 through 29 Sep 16:00 UTC**. The first 24 hours chose the funding direction; the following 24 hours measured it without choosing the direction again. Positive rates mean longs pay shorts. [Hyperliquid settles hourly](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) and its historical `fundingRate` is a decimal fraction. [Lighter's hourly settled history](https://apidocs.lighter.xyz/reference/fundings) reports `rate` in **percent**, plus `direction` naming the payer; the sign and 1/100 scale are checked against its payment `value` and mark-price magnitude. Thus a Lighter `rate` of `0.0012` with `direction=long` is **0.0012% = 0.12 bp**, paid by longs. The [RH-domain funding endpoint](https://apidocs.rh.lighter.xyz/reference/fundings) has the same schema. We align exact hourly settlements and sum `(venue long-pays rate − HL long-pays rate)` for long HL / short venue, or its negative for the reverse.

The primary threshold assumes both legs are taken at market on entry and exit: `2 × (HL taker fee + Lighter taker fee)` plus a **5 bp pair-level extra cost**, matching the current [monitor setting](../../scripts/monitor.py), for spreads, impact, collateral conversion, and other frictions. A separate 10 bp stress case is in [`comparison_stress_10bp.csv`](comparison_stress_10bp.csv). [Hyperliquid's base taker fee](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) is 4.5 bp for the sampled crypto perps. The archived [HL fee metadata](raw/hl_fee_metadata.json) shows COIN, XAG (`xyz:SILVER`), and NVDA on the `xyz` HIP-3 dex with 1× deployer scale and growth mode enabled, giving 0.9 bp per taker fill under the published fee formula. [Lighter Core Standard](https://apidocs.lighter.xyz/docs/account-types) and [RH Lighter Standard](https://apidocs.rh.lighter.xyz/docs/account-types) are 0 bp; the base Premium taker scenarios are 2.8 and 3.5 bp respectively. The Standard/Premium labels apply **only to the Lighter account scheme**; the Hyperliquid fee is held fixed at its base rate in both columns, without VIP or staking discounts. **All fee figures are fixed scenarios calibrated to public information on 29 September 2026, not verified historical fees or an account-specific schedule.** A future refresh must recheck fees and HIP-3 growth settings. Actual account fees, maker fills, and stablecoin prices can differ.

| Asset | Alternative venue | Chosen HL leg | Holdout funding (bp) | Four taker fees, Standard / Lighter Premium (bp) | +5 bp cost threshold, Standard / Lighter Premium (bp) |
| --- | --- | --- | ---: | ---: | ---: |
| BTC | Core Lighter | short | +0.47 | 9.0 / 14.6 | 14.0 / 19.6 |
| BTC | RH Lighter | short | +1.43 | 9.0 / 16.0 | 14.0 / 21.0 |
| ETH | Core Lighter | short | +0.12 | 9.0 / 14.6 | 14.0 / 19.6 |
| ETH | RH Lighter | short | +0.12 | 9.0 / 16.0 | 14.0 / 21.0 |
| SOL | Core Lighter | short | +1.31 | 9.0 / 14.6 | 14.0 / 19.6 |
| SOL | RH Lighter | short | +4.52 | 9.0 / 16.0 | 14.0 / 21.0 |
| HYPE | Core Lighter | short | +0.76 | 9.0 / 14.6 | 14.0 / 19.6 |
| HYPE | RH Lighter | long | +0.17 | 9.0 / 16.0 | 14.0 / 21.0 |
| ZEC | Core Lighter | long | +0.14 | 9.0 / 14.6 | 14.0 / 19.6 |
| ZEC | RH Lighter | short | −0.06 | 9.0 / 16.0 | 14.0 / 21.0 |
| COIN | Core Lighter | long | −0.66 | 1.8 / 7.4 | 6.8 / 12.4 |
| COIN | RH Lighter | short | +0.74 | 1.8 / 8.8 | 6.8 / 13.8 |
| XAG | Core Lighter | long | +1.51 | 1.8 / 7.4 | 6.8 / 12.4 |
| XAG | RH Lighter | short | −0.09 | 1.8 / 8.8 | 6.8 / 13.8 |
| NVDA | Core Lighter | long | −0.53 | 1.8 / 7.4 | 6.8 / 12.4 |
| NVDA | RH Lighter | long | +0.87 | 1.8 / 8.8 | 6.8 / 13.8 |

No selected pair reached its fee-plus-cost threshold during the 24 holdout events. **None even covered the four Standard taker fees from funding alone.** At the holdout's average rate, the most favorable SOL/RH Lighter pair would need roughly **74 hours** to cover Standard fees plus the 5 bp cost, or **112 hours** with RH Lighter base Premium fees. This is a **descriptive extrapolation of the holdout average**, far beyond the observed 24 hours, not a tradable forecast. The CSV includes the threshold, first observed crossing, and illustrative break-even hours for every scenario.

## Limits on interpreting the screen

- Funding receipts use each venue's own oracle/index notional; this screen compares rate basis points, **not exact dollars**. Different marks, contract specifications, and token/share multipliers require separate dollar reconciliation. COIN, NVDA, and XAG are tagged `RWA_reference_review` because ticker similarity alone does not establish identical exposure.
- A fixed-notional hedge would have entry and exit basis changes, different collateral units, possible liquidations, and rebalancing costs. Lighter Core and Hyperliquid use USDC exposure while the [RH Lighter perps account accepts only USDG deposits](https://apidocs.rh.lighter.xyz/docs/deposits-transfers-and-withdrawals). The 5 bp extra cost is applied once per pair on the reference notional, as in the monitor; it is a scenario, not a validated all-in cost bound. The 10 bp stress case adds another 5 bp to every threshold and also shows no crossing.
- The direction was selected from one day and measured on one day. Funding rates can reverse; a positive settled differential cannot be presumed to persist to the next payment. The 24-hour result is a small historical sample, not a backtested profit or fill claim.
- Maker execution or a longer holding period could alter economics, but those approaches require size-specific synchronized entry/exit quotes, observed fills, basis and collateral accounting, and a fee tier tied to an actual account before they merit a separate paper test.
