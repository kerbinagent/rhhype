# Follow-up: can funding carry replace a losing opening-spread unwind?

**29 September 2026; read-only strategy assessment. No policy change or new capture.** The current short-hold monitor often enters on a favorable *opening* cross-venue spread and loses it at exit. A genuinely different source of return would be **funding carry over several settlements**, with a neutral-sized perp long on one venue and short on another. It must pay for both entry and eventual exit. This is a separate strategy mandate from the user's live ten-second/$0.10 rule and from the small RH-maker test; it should not silently change either.

## The contract is not a fixed-rate bond

Let $B_t=P^S_t-P^L_t$ be the executable price basis for short venue S and long venue L at entry; at exit use the opposite executable sides. For matched base quantity $q$, full paired dollars are

\[
q(B_{entry}-B_{exit})
+\sum_{\tau\in(entry,exit]}q(P^S_{index,\tau}f^S_\tau-P^L_{index,\tau}f^L_\tau)
-F_{fills}-C_{capital}-C_{conversion/rebalance}.
\]

Positive signed $f$ means longs pay shorts. Funding is received or paid **only while the leg exists at actual settlement times**, at a rate and reference notional determined later; a current rate is an input to a forecast, not a purchased stream of fixed coupons. [Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) and [Lighter](https://docs.lighter.xyz/trading/funding) pay hourly but use different premium samples and settlement index/oracle methods. Their rate difference can persist or reverse. Perps have no maturity date forcing the exit basis to converge; [He et al., *Fundamentals of Perpetual Futures*](https://arxiv.org/abs/2212.06888) derive trading-cost bounds and describe margin/liquidation risk during apparent arbitrage. Therefore a positive opening basis or funding payment alone cannot be booked as profit.

## What the stopped settlement sample permits

The reproducible [48-hour funding screen](../reports/funding-carry/REPORT.md) fixed eight assets and both HL–Core and HL–RH routes. The first 24 hourly settlements selected each route's direction; the next 24 measured it without flipping direction. Raw public histories and exact rate-unit conversion are retained there. This table adds a *descriptive* holding-horizon calculation from its stopped CSVs; it uses no later capture, exit quotes or trades. The “positive hours” count is within the 24-hour holdout, **not** 24 independent days.

| Route, selected direction | Holdout funding / 24 h | Positive holdout hours | Four Standard taker fees; with 5 bp stress | Constant-rate hours to cover fees; with stress |
| --- | ---: | ---: | ---: | ---: |
| SOL: short HL, long RH | +4.52 bp | 24/24 | 9; 14 bp | 47.8; 74.3 h |
| BTC: short HL, long RH | +1.43 bp | 22/24 | 9; 14 bp | 151.2; 235.2 h |
| SOL: short HL, long Core | +1.31 bp | 24/24 | 9; 14 bp | 164.9; 256.5 h |
| XAG: long HL, short Core | +1.51 bp | 22/24 | 1.8; 6.8 bp | 28.6; 108.1 h |

The fee hurdle is on **one leg's notional**: for standard HL native crypto, two 4.5 bp HL taker fills cost 9 bp, while the two Lighter Standard fills are modeled at zero. The added 5 bp is the monitor's *stress allowance*, not a published exchange fee. For the sampled `xyz` RWA contracts, the 1.8 bp four-fill scenario relies on the archived HIP-3 growth/deployer metadata and [HL's current fee formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees); it is not universal or verified for an actual account. At $1,000 per leg, SOL/RH's 4.52 bp of one-day funding is about $0.452 before basis, fees, capital, conversion and margin risk; the 14 bp fee-plus-stress hurdle is $1.40. Fee tiers and token/share multipliers must be rechecked before another study.

The “constant-rate hours” divide the threshold by the **observed average from only one day**. They are break-even arithmetic, not expected holding periods. SOL/RH was +9.54 bp on its training day, then +4.52 bp on holdout; its first and last 12 holdout hours earned 2.70 and 1.82 bp respectively. This deceleration illustrates why annualizing a favorable hour is misleading. Direction failures also exist: selected ZEC/RH, COIN/Core, XAG/RH and NVDA/Core had *negative* holdout funding totals. The stopped sample does not contain synchronized size-specific entry and exit depth, so none of these rows establishes executable liquidity or a profitable hedge. XAG, NVDA and COIN add oracle/reference and session mismatch concerns; ticker matching is insufficient proof of identical underlying exposure.

The monitor's separate capital assumption is 5% annualized on **each** fully reserved leg. With two $1,000 reserved legs, that is about **2.74 bp of one-leg notional per day**. Holding this model constant and assuming zero basis change, SOL/RH's holdout daily advantage net of that charge would be only **1.78 bp/day**: about **121 hours** to cover 9 bp fees, or **189 hours** to cover fees plus the 5 bp stress. Every other positive route in the table earned less than 2.74 bp/day during this holdout, so no finite break-even exists under *those same frozen daily rates and capital assumptions*. Actual opportunity cost, margin allocation and future funding differ. An adverse exit basis or forced rebalance raises the hurdle further; a favorable basis change can help but must be measured at an executable exit. No result in the 24-hour holdout covers even the four Standard taker fees from funding alone.

## Decision and a limited next test

This evidence **deprioritizes immediate production carry**. SOL/RH is the only clean-crypto route here with an all-positive hourly holdout and any positive net rate after the current full-capital charge, yet the projected fee-plus-stress payback is about eight days while only 24 held-out hours were observed. Its future rate, exit basis, margin path and RH USDG versus HL USDC conversion are unproven. The recent RH chain also limits historical coverage. The literature and venue mechanics justify studying carry as a different hypothesis, not presenting it as an available edge.

If pursued, first assemble a longer *public-data feasibility* record for BTC/ETH/SOL and matched HL–Core/RH perps, with prior-only rate forecasts, simultaneous size-specific entry/exit depth, settlement history, wallet-specific collateral and observed quote gaps. Freeze a maximum holding period, dynamic stop for deteriorating predicted funding or basis/margin loss, and full exit/terminal inventory accounting **before** a prospective holdout. Compare the selected policy with an unselected all-routes control and with the existing ten-second strategy separately. Treat no quote, missing settlement, one-leg hedge and open-at-end inventory as exposed/censored, not zero returns. The criterion is positive completed net after four fills, actual funding, conversion/rebalance and time-varying capital, with a risk bound robust to selection across routes. The present sample is insufficient to authorize that strategy or infer an optimal holding horizon.
