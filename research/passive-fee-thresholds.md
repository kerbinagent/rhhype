# HL taker fee thresholds for RH passive cycles

**Offline quote sensitivity, 2026-09-30 UTC.** Using the stopped September 29 books, the +$0.10 fee-only target clears on **193/4,336 quote rows at public base rates, 402/4,336 at volume tier 6, and 574/4,336 at tier 6 plus Diamond staking**. These pooled counts describe overlapping quote observations, not trades, independent trials, or total profit. With the separate 5 bp reserve, **no row clears at any of these published rates**. Fee discounts therefore improve some quoted economics, chiefly XAG, but do not establish executable RH maker cycles.

The [offline analyzer](../scripts/analyze_passive_fee_thresholds.py) reads the same [matched rows](../reports/passive-hedge-venues/matched-rows.csv) as the [cost buffer followup](passive-cost-buffer-followup.md). It makes no market request and changes no monitor or policy. It covers BTC, ETH, NVDA and XAG, $100/$250/$500/$1,000, RH maker buy and maker sell, static same-book arithmetic and the first matched +10–16 s delayed quotes: **64 groups and 4,336 rows**. Static BTC/ETH groups contain 75 anchors each, NVDA 56, and XAG 68; delayed NVDA falls to 50 while the other group denominators stay the same. These are common tri-venue rows selected by the earlier venue comparison, including Core coverage, rather than every possible RH/HL observation.

## Maximum fee on each HL taker fill

For a matched quantity, let `H_in` and `H_out` be the actual dollar notionals of the HL hedge entry and exit, including the archived depth walk. Let `R_in` and `R_out` be the RH maker entry and exit notionals. The Standard RH maker fee is modeled as 0 bp in the source. Four-leg gross is:

- RH maker buy, HL sell hedge: `G = −R_in + H_in + R_out − H_out`.
- RH maker sell, HL buy hedge: `G = R_in − H_in − R_out + H_out`.

A uniform HL taker fee of `f` bp costs `f × (H_in + H_out) / 10,000`. The row denominator is **the sum of the two actual HL fill notionals**. It is not the nominal size label, one entry notional, or total four-leg turnover. The capital charge from the earlier replay is `K = (R_in + H_in) × 0.05 × elapsed_seconds / (365 × 86,400)`, zero for static rows. This is an explicit full-entry-notional opportunity-cost convention; it does not claim actual account leverage, margin, balances, or staking capital.

The greatest fee preserving +$0.10 is:

```text
fee-only f_max = 10,000 × (G − K − 0.10) / (H_in + H_out)
stress   f_max = 10,000 × (G − K − S − 0.10) / (H_in + H_out)
S = 0.0005 × max(R_in, H_in)
```

The reserve `S` is the separate **5 bp stress allowance on the larger entry leg**, not a published fee or a measured transfer cost. The threshold subtracts capital in both branches. Delayed movement and depth are already represented in the archived execution notionals; another guessed price-movement charge would double-count them. If a maximum is negative, **even zero HL taker fee fails the $0.10 target**. Zero exactly meets the target at zero fee; any higher fee fails. A median below a published rate says the median quote fails, while a fraction counts each row separately. Rounding the displayed median to three decimals is for presentation only; row comparisons use unrounded Decimal values.

## Public rate comparison, with eligibility conditions

The current [official HL fee schedule and developer formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), checked September 30 UTC, publishes the following native perp taker rates. Volume means rolling 14-day weighted volume; spot counts twice. No user tier is known here.

| Volume tier | Required volume | Native taker bp | With Diamond bp |
|---|---:|---:|---:|
| 0 | Base | 4.5 | 2.7 |
| 1 | >$5M | 4.0 | 2.4 |
| 2 | >$25M | 3.5 | 2.1 |
| 3 | >$100M | 3.0 | 1.8 |
| 4 | >$500M | 2.8 | 1.68 |
| 5 | >$2B | 2.6 | 1.56 |
| 6 | >$7B | 2.4 | 1.44 |

| Staking tier | Required HYPE stake | Fee reduction |
|---|---:|---:|
| Wood | >10 | 5% |
| Bronze | >100 | 10% |
| Silver | >1,000 | 15% |
| Gold | >10,000 | 20% |
| Platinum | >100,000 | 30% |
| Diamond | >500,000 | 40% |

For the **frozen** [xyz metadata](../reports/maker-equity-v2/fee-inputs.json), `xyz:NVDA` and `xyz:SILVER` have deployer scale `d=1`, growth enabled and unaligned USDC collateral. The official formula gives `2d × 0.1 = 0.2` times the native rate: **0.9 bp base, 0.48 bp volume tier 6, 0.288 bp tier 6 + Diamond**. BTC/ETH use **4.5 / 2.4 / 1.44 bp**. [Deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-3-deployer-actions) document configurable fee scale. Market configuration was not re-queried. Referral and aligned-collateral discounts are excluded; growth reduces volume contribution, so HIP-3 turnover is not credited dollar-for-dollar toward tier acquisition. The rate cases are eligibility sensitivities, not assumed user entitlements.

## Every asset and size

Each cell below is the **median maximum bp per HL taker fill**, shown as **RH buy / RH sell**. It includes both directions in each of the 16 asset/size combinations and both static and delayed stages. A negative value means zero fee is insufficient for that median quote. See the [full 64-group table](../reports/passive-fee-thresholds/REPORT.md) and [CSV](../reports/passive-fee-thresholds/groups.csv) for row-level target fractions at zero fee, base, volume tier 6 and tier 6 + Diamond.

| Asset | Size | Static fee-only buy/sell | Delayed fee-only buy/sell | Static stress buy/sell | Delayed stress buy/sell |
|---|---:|---:|---:|---:|---:|
| BTC | $100 | -4.675 / -4.675 | -4.734 / -4.681 | -7.175 / -7.175 | -7.234 / -7.181 |
| BTC | $250 | -1.656 / -1.656 | -1.709 / -1.662 | -4.156 / -4.156 | -4.209 / -4.162 |
| BTC | $500 | -0.653 / -0.653 | -0.707 / -0.659 | -3.153 / -3.153 | -3.207 / -3.159 |
| BTC | $1,000 | -0.153 / -0.153 | -0.207 / -0.158 | -2.653 / -2.653 | -2.707 / -2.659 |
| ETH | $100 | -4.500 / -4.500 | -4.539 / -4.612 | -7.000 / -7.000 | -7.039 / -7.112 |
| ETH | $250 | -1.517 / -1.517 | -1.536 / -1.610 | -4.017 / -4.017 | -4.036 / -4.110 |
| ETH | $500 | -0.516 / -0.516 | -0.554 / -0.610 | -3.016 / -3.016 | -3.054 / -3.110 |
| ETH | $1,000 | -0.017 / -0.017 | -0.054 / -0.113 | -2.516 / -2.517 | -2.554 / -2.613 |
| NVDA | $100 | -4.355 / -4.355 | -4.355 / -4.573 | -6.857 / -6.857 | -6.857 / -7.075 |
| NVDA | $250 | -1.345 / -1.345 | -1.345 / -1.564 | -3.847 / -3.847 | -3.847 / -4.066 |
| NVDA | $500 | -0.343 / -0.343 | -0.343 / -0.562 | -2.845 / -2.845 | -2.845 / -3.064 |
| NVDA | $1,000 | 0.158 / 0.158 | 0.158 / -0.062 | -2.344 / -2.344 | -2.344 / -2.564 |
| XAG | $100 | -3.577 / -3.577 | -3.623 / -3.573 | -6.079 / -6.080 | -6.125 / -6.076 |
| XAG | $250 | -0.560 / -0.560 | -0.601 / -0.552 | -3.062 / -3.063 | -3.103 / -3.055 |
| XAG | $500 | 0.444 / 0.444 | 0.402 / 0.452 | -2.058 / -2.059 | -2.101 / -2.051 |
| XAG | $1,000 | 0.945 / 0.945 | 0.899 / 0.953 | -1.558 / -1.558 | -1.603 / -1.550 |

At $1,000, the fee-only quote fractions make the value of discounting clearer. Rates are the asset-specific cases above, not one common rate across all four assets.

| Stage | Asset | RH side | Zero fee | Base | Tier 6 volume | Tier 6 + Diamond |
|---|---|---|---:|---:|---:|---:|
| static | BTC | buy | 14/75 | 0/75 | 0/75 | 0/75 |
| static | BTC | sell | 14/75 | 0/75 | 0/75 | 0/75 |
| static | ETH | buy | 37/75 | 0/75 | 0/75 | 0/75 |
| static | ETH | sell | 37/75 | 0/75 | 0/75 | 0/75 |
| static | NVDA | buy | 30/56 | 0/56 | 4/56 | 23/56 |
| static | NVDA | sell | 30/56 | 0/56 | 4/56 | 23/56 |
| static | XAG | buy | 68/68 | 38/68 | 65/68 | 68/68 |
| static | XAG | sell | 68/68 | 38/68 | 65/68 | 68/68 |
| delayed | BTC | buy | 24/75 | 0/75 | 0/75 | 0/75 |
| delayed | BTC | sell | 24/75 | 0/75 | 0/75 | 0/75 |
| delayed | ETH | buy | 34/75 | 0/75 | 0/75 | 1/75 |
| delayed | ETH | sell | 30/75 | 0/75 | 1/75 | 1/75 |
| delayed | NVDA | buy | 26/50 | 1/50 | 6/50 | 18/50 |
| delayed | NVDA | sell | 23/50 | 1/50 | 8/50 | 15/50 |
| delayed | XAG | buy | 68/68 | 34/68 | 63/68 | 68/68 |
| delayed | XAG | sell | 68/68 | 40/68 | 64/68 | 67/68 |

BTC clears **zero** rows at all three published cases, across every size, stage and direction. ETH clears zero at base, one delayed $1,000 RH-sell row at volume tier 6, and four delayed rows at tier 6 + Diamond: one each at $500 and $1,000 in both directions. These rare quotes coexist with negative ETH median thresholds. NVDA clears two base rows, both delayed at $1,000, then 24 volume-tier and 84 Diamond rows overall. XAG accounts for **191 of the 193 base-rate clears**, 377 of 402 volume-tier clears, and 486 of 574 Diamond clears. This concentration is conditional on the captured xyz growth setting.

For the stress branch, **4,335/4,336 rows have negative thresholds**. The sole nonnegative exception is a delayed ETH $1,000 RH-sell quote, anchor `1790710841939457157`, whose maximum is only **0.059879 bp** per HL fill. Its gross $0.612315, capital $0.000034279 and reserve $0.500298465 leave $0.111982256 before HL fees; its two HL notionals sum to $2,001.08253. Zero fee clears, but even the 1.44 bp native tier 6 + Diamond rate fails. Static stress thresholds are negative for every row. With fee-only costs, zero fee clears 923 rows and fails 3,413.

## Interpretation and verification

These thresholds are **conditional on two RH maker fills**, whose queue priority, execution probability and adverse selection are unobserved. Static opposite-side maker fills at one unchanged book cannot be simultaneous; buy and sell static quote cycles largely mirror one another. The delayed observations are later books, not confirmed fill-time executions. Anchors overlap, both directions reuse books, and static/delayed scores reuse entries, so summing scores or treating the pooled count as an independent success probability is invalid.

The fee-only target precedes unpriced funding, USDG/USDC conversion, actual rebalances, gas and terminal withdrawal liabilities. Staking capital/opportunity cost and the cost of obtaining a volume tier are also excluded. The [cost buffer followup](passive-cost-buffer-followup.md) explains why a batch rebalance allocation requires actual route costs and completed cycles. These quote rows provide neither. The result supports a separate fee-only branch in a future paper design while retaining the separate stress branch; it provides no evidence to relax the frozen v1 study.

[Threshold rows](../reports/passive-fee-thresholds/threshold-rows.csv) preserve every signed maximum and eligibility flag; [summary.json](../reports/passive-fee-thresholds/summary.json) records input hashes, documentation check date, formula definitions and caveats. The analyzer verifies the frozen raw metadata hash, four-leg gross, fee/notional identity, capital/timing identity, reserve identity, and base-rate agreement with the earlier replay. [Five tests](../tests/test_analyze_passive_fee_thresholds.py) verify both cashflow directions, unequal actual notionals, exact boundaries, negative thresholds, corrupted-input rejection, native/HIP-3 rates, all 64 archive groups and the reference counts. The archive test checks that all 18 sources named by [the frozen v1 protocol](../reports/rh-passive-exit-v1/protocol.json) remain byte-for-byte unchanged by analysis. No source code, protocol file, policy, market data or study input in that manifest was edited.
