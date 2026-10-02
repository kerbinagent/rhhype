# HIP-4 continuation: recurring-expiry settlement window v1 (proposal, no code yet)

This proposal authorizes nothing. It asks root for a go/no-go before code is written. It is distinct from expiry-v1, whose REST snapshots end at 05:57 and which reads settlement at about 06:01 and 06:10: this proposal watches the minutes around and after 06:00 continuously.

## Why it fits the closed-cash criterion

Protocol recurring outcomes have a formal resolution rule with a fixed event time ([contract specifications, recurring outcomes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications#recurring-outcomes)):

> the contract settles to YES if and only if `markPrice0 + (settlementTime - t0) / (t1 - t0) * (markPrice1 - markPrice0) ≥ targetPrice`

Here the two marks are "the mark price updates immediately before and immediately after the settlement timestamp". These outcomes are "automatically deployed and settled by the protocol", so no third-party deployer judgement is involved. [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) says the first market "settles daily at 06:00 UTC to the BTC mark price".

Once the first mark update after 06:00:00 is published, the outcome is arithmetically determined, but settlement may come later. If books still trade in that gap, any resting quote on the losing side is closed cash at settlement, minutes later:
- **Buy the winner.** Buy the winning YES at ask a; settlement pays 1, so closed cash = 1 − a.
- **Sell the loser.** Split one unit at par (basis 1), sell the losing YES at bid b, hold the winning NO; settlement pays 1, so closed cash = b.

Fees are charged when closing or settling ([fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)) and the HIP-4 page says they are "currently zero … for initial testing"; zero fees are treated as optimistic only.

## Instruments (frozen snapshot `5a84b598…`)

| Outcome | Description |
| --- | --- |
| 7544 | BTC `priceBinary`, target 85971 |
| 7545 | ETH `priceBinary`, target 2721.3 |
| 7546 | SOL `priceBinary`, target 121.91 |
| 7549 | HYPE `priceBinary`, target 90.017 |
| Q371 (7550–7553) | BTC `priceBucket`, thresholds 84251 and 87690 |

All expire at 06:00 UTC on 3 October 2026. The series recurs daily. A later day needs a fresh frozen `outcomeMeta`, because each day's instance has new ids. Instance identity is taken only from the frozen spec, never from a name.

## Smallest decisive design (one expiry)

- **Websocket.** One public connection from 05:58:00 to 06:08:00 UTC, with:
  - `bbo` for the 8 YES coins;
  - `activeAssetCtx` for BTC, ETH, SOL and HYPE, to observe mark changes around 06:00 (a snapshot feed pushed at most every 0.5 s);
  - `outcomeMetaUpdates`, to observe `outcomeSettled` and `questionSettled` receipt times.
- **REST.**
  - `settledOutcome` for each of the 8 ids at about 06:08:30, bound to the requested id and the frozen spec, as in revised expiry-v1. It gives X, the fractions and each settlement shape.
  - One `outcomeMeta` read before the window (weight 20), for membership and spec binding.
- **Retention.** Every frame raw, in progressive fsynced members, under a hard cap with a censoring reserve, as in live-v1. Expected volume is a few MB raw at most before compression. The cap is to be sized with root; no compression ratio is assumed.

## Measured quantities

1. **Trading after expiry.** Whether `bbo` updates carry server times after 06:00:00, and until when, relative to each `outcomeSettled` receipt.
2. **Determination time.** For each underlying, the receipt time of the first `activeAssetCtx` mark change after 06:00:00. This is an observable lower bound on when the outcome became determined. Unchanged-value updates are invisible, which is stated as a premise.
3. **Ex-post closed cash per unit.** For each state at or after the determination bound and before that outcome's settlement receipt, compute exact closed cash. The winning side comes from the bound settlement fractions. The routes are winner ask below 1, and loser bid above 0 sold from a par-split unit. Report runs of at least 1,000 ms with displayed units, full basis and no residual (settlement retires every token).
4. **Settlement latency.** From 06:00:00 to each `outcomeSettled` receipt, cross-checked by the REST shapes.
5. **Consistency of X.** Whether the interpolation rule is consistent with the observed marks around 06:00, within receipt-time uncertainty. This is reported, not assumed.

## Decision sketch

- **`candidate_recorded_vector`.** Any qualifying post-determination run on a validly settled instrument. It is a recorded-vector bound for a separate fee, depth and execution review.
- **`park`.** An uncensored window in which books stop updating at or before determination, or carry no losing-side quote for at least 1,000 ms before settlement.
- **`inconclusive`.** Otherwise.

One expiry is one sample per instrument, which is four binaries and one question. Repetition would need separate daily freezes.

## Open premises

- Whether outcome books halt at expiry: the docs are silent; this design answers it.
- Whether `activeAssetCtx` exposes every mark update.
- The format of the initial snapshot on subscription.
- The `outcomeMetaUpdates` channel name and shape: unobserved, as in live-v1.
