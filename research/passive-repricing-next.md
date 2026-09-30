# Hedge-cost-based quote refresh: next strategy hypothesis

**30 September 2026, 03:13 UTC.** Research preparation during the unscored
passive-exit capture. No current policy or frozen source is changed.

## Mechanism

[Hummingbot's cross-exchange market-making documentation](https://hummingbot.org/strategies/v1-strategies/cross-exchange-market-making/)
describes placing maker orders, hedging their fills on a second venue, and
checking active orders for profitability, balance and price changes. Its
quoted hedge economics drive cancellation and repricing. That documented
implementation targets spot; our two-perpetual adaptation must retain both
closing obligations and all four own-notional fees. This is an implementation
reference, not evidence of profit on Robinhood or Hyperliquid.

Our v1 intentionally holds one passive exit price fixed. It isolates whether
opposite flow can improve the unwind. An additional strategy question is
whether refreshing that price with the hedge venue preserves more of the
initial margin. This cannot be answered by inspecting only an opening spread
or by making a canceled order disappear immediately.

## Arithmetic example, not a market observation

Take ten hypothetical units near $100 each. RH quotes 99.98/100.02, HL quotes
99.995/100.005, RH maker fees are zero and HL charges 0.9 bp per taker fill.
Assuming both RH maker fills and unchanged books, the RH spread earns $0.40,
the HL round trip costs $0.10 in spread and $0.18 in fees: $0.12 before other
costs. This is only $0.02 above the $0.10 target.

If the fixed RH ask fills while HL's buyback price has risen by $0.04 per
unit, the hedge costs another $0.40 plus its small incremental fee. The same
cycle becomes approximately −$0.280036. The quote's original target price
does not lock a completed profit. With a 0.01 RH tick, a refreshed ask of
100.06 would cover that contemporaneous higher hedge cost and the $0.10
cycle target under these assumptions—but whether it fills, and at what later
HL buyback price, remains unknown. Its previous 100.02 quote can still fill
before cancellation takes effect.

## Candidate experiment after the v1 readout

1. **Admission:** for a fresh prospective asset/size cohort, reject an entry
   whose quoted complete cycle already misses the declared fee/target hurdle.
   Publish fee-only and separate 5 bp stress selection cases. Include original
   no-filter controls and every rejected-candidate denominator. An admission
   filter can avoid predicted losses; it cannot create a profitable trade.
2. **Exit price:** recompute the minimum acceptable RH ask from actual entry
   cash, current same-quantity HL buy depth, own-notional fees, prior-only
   adverse-flow allowance, remaining capital charge and the declared target.
   Compare it with immediate executable liquidation. The original entry
   costs remain in full-cycle accounting, while the incremental wait decision
   compares expected exit proceeds and fallback costs.
3. **Refresh:** compare fixed v1 with one prespecified refresh rule, for
   example cancel when hedge-cost movement consumes the quoted net margin.
   Require a meaningful tick change, a fixed minimum refresh interval, and a
   bounded number of replacement quotes. Choose those parameters before the
   fresh evaluation window; do not optimize them on its best outcomes.
4. **Cancellation:** keep the old quote, original quantity and interval of
   possible fills through cancellation and late reporting. Replacements must
   not create excess sale quantity or consume the same trade twice. Retain
   evidence for every canceled price, including multiple prices within one
   episode; one tombstone per completed episode is insufficient for repricing.
5. **Hedge and deadline:** hedge each attributed RH fill increment at the
   first eligible later hedge book with actual fees/depth. The original
   ten-second deadline remains anchored to the first complete hedge; refreshing
   does not reset it. A separately labeled longer hold remains an independent
   experiment, including its forced unwind and capital costs.

This is a larger state-machine change than the isolated retirement correction.
It needs explicit order identities, quantity reservations, old-source prints,
partial IOC/fallback accounting, and independent tests before a capture.
The [ACK scenario design](passive-ack-scenarios-design.md) explains why public
book timing and assumed private cancellation timing must be distinguished.
The [public queue discussion](public-queue-uncertainty-followup.md) explains
why any resulting filled-P&L claim remains conditional on the execution model.

## Decision criteria

Use the completed broad universe screen to nominate a liquid asset with
sufficient observed spread and opposing trade flow. A positive quoted margin
only nominates the next study. Compare all admitted outcomes, common-entry
cohorts, completed cash, forced-exit losses, unresolved exposure, cancellation
count and known active quote time. A refresh policy that improves conditional
winning fills while abandoning its losing or ambiguous inventory has failed.

No fresh v1 outcome has been used to select this hypothesis. If the completed
screen has no candidate even under unchanged-book arithmetic, prioritize the
fee/venue feasibility question before building the more complex refresher.
