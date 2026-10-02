# HIP-4 continuation source notes v1 (2 October 2026, about 12:55 UTC)

These notes supplement the frozen [source review](../hip4-outcome-v1/source-review.md). No exchange request was made. Third-party items are leads only.

## Quote-asset identity: unresolved, and plausibly ambiguous

**What the sources say**
- **Live snapshot.** Every one of the 260 outcomes is labelled `quoteToken: "USDC"` (frozen raw `5a84b598…`).
- **Nautilus (third party).** Its [integration doc](https://github.com/nautechsystems/nautilus_trader/blob/224f599df710ecca2b9f4757ce07a06a86b3db70/docs/integrations/hyperliquid.md) denominates every outcome instrument in USDH (token index 360, pair `@230`). ccxt also defaults the outcome quote to USDH. Both conflict with the live label.
- **Official AQA page.** The [aligned quote assets page](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets) makes AQAv2 a requirement for HIP-4 quote assets "on a future network upgrade". It names no current token.
- **FalconX (third party, 2026-05-21).** [FalconX](https://www.falconx.io/newsroom/the-drivers-behind-hyperliquids-next-phase-hype-etfs-hip-4-outcome-markets-priority-fees-and-its-usdc-agreement) reports that on May 14 Coinbase announced USDC support as an aligned quote asset, with Circle as technical deployer.
- **HIP-1.** Token names have no uniqueness constraint.

**Consequences**
- A `USDC` label could denote legacy spot USDC or an aligned USDC token. Labels cannot settle this.
- Within one question, every conversion is collateral-to-collateral in that question's own quote token, so a certificate stated in that token is unaffected.
- USD-denominated P&L, and any route that mixes questions or venues with different quote tokens, needs an authoritative token identity.
- A cheap ambiguity falsifier, not a join: count the `spotMeta` tokens named `USDC`. More than one confirms the label is ambiguous. Exactly one does not prove the outcome quote is that token.

## Fees: time-varying and undocumented for outcomes

- **Official fee page.** It has the closing/settling-only rule and six volume cases, with no outcome base rate. The [fee page](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees#outcome-tokens) is byte-identical to the 29 September snapshot.
- **FalconX (2026-05-21).** Growth-mode reductions are "currently set to 0 bps for both opening and closing positions on mainnet".
- **Third-party September fills.** These show fees on merge rows (Aarymanv research `775e4aa`). Fees therefore changed after May; current values are unknown.
- **Live snapshot.** `deployerFeeScale` is `"1.0"` on `out` and `skew` (161 outcomes). It is absent on `txyz` (91) and on the 8 protocol-recurring outcomes. A top-level `feeScale` of `"1.0"` is undocumented.
- The [Block (2026-07-20)](https://theblock.co/post/408875/hyperliquid-hip-4-permissionless-deployment) describes permissionless deployment as testnet-first, with a 500k HYPE stake and deployer fees up to 50%. It is preliminary. The mainnet snapshot nonetheless lists three venues with sub-deployers.
- **Implication.** Zero-fee results are valid only as one-sided negative certificates. Any candidate needs measured or authoritative per-leg fees, including fees on `mergeQuestion`/`negate` and at settlement.

## Recurring BTC pair (H2) premises

- **P6, bucket order.** The contract spec lists the buckets `<P1`, `[P1,P2)`, `≥P2`.
  - Nautilus documents `index:N` as the "position in parent `named_outcomes` array". For Q371 that is 7551, 7552, 7553 → 0, 1, 2.
  - ccxt maps index 0 to below P1 and the last index to at or above the last threshold.
  - Both corroborate, but neither defines it. It is falsifiable after settlement from the `settledOutcome` `settleFraction` values and price details of 7551–7553.
- **Settlement timing.** Interpolation needs the first mark update after 06:00 UTC, so settlement cannot precede it. The delay and the time tokens convert are undocumented. The `settledOutcome` example carries `details: "price:…"`.
- **Settlement fee.** "Fees only when closing or settling" implies a fee at settlement on the payout. The rate is unknown, and the recurring outcomes carry no `deployerFeeScale`.
- **Cadence.** At most one recurring series exists per (seriesType, underlying, period), so there is about one binary–bucket pair per day for BTC, the only underlying with both classes. Repeatability accrues roughly one event per day.

## Deferred candidate H3: near-expiry digital mispricing versus the perp mark

Minutes before expiry, a recurring binary's payoff is nearly determined by the current interpolated mark relative to the target. Stale resting quotes far from the implied near-certain value would be an edge held to settlement, with inventory ending at zero. The risk is a model-dependent tail, so this is not static arbitrage.

The cheapest falsifier would compare the book tops of the four recurring binaries (BTC, ETH, SOL, HYPE) with the perp mark at fixed offsets before expiry over several days. It needs a volatility model frozen before outcomes, and a separate grant and plan. It is deferred until H1 and H2 resolve.
