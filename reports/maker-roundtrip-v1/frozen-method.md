# Frozen public-feed maker round-trip diagnostic

Status: **prospective method frozen by root at 2026-09-29T19:38:48.812544+00:00**.

Capture: 420 seconds maximum, 25,000,000 compressed bytes maximum, frozen `market-plan.json` in this directory. All rules below apply before inspecting this future capture.

 This plan fixes the policy before inspecting round-trip outcomes. The existing 18:23 UTC archive is exploratory. A later capture, if authorized and collected, should carry a frozen market-plan file and its SHA-256 inside the capture directory so a mutable production plan cannot break provenance.

## Universe and timing

- BTC and ETH, each maker side, for four routes: HL maker → Core hedge, Core maker → HL hedge, HL maker → RH Lighter hedge, RH Lighter maker → HL hedge.
- Non-overlapping UTC 5-second anchors, starting after the archive's first three seconds. Every eligible anchor is counted. Hypothetical maker arrival delay is **1 second primary**; 0.5 and 3 seconds are controls. A trade-flow window ends at the next 5-second anchor. No route, side, or horizon is selected based on its outcome.
- Fixed base quantity is the $1,000 maker-leg notional divided by the displayed maker price, floored to BTC 0.00001 or ETH 0.0001. Same base quantity is required for the hedge and both exits. Quotes are one-level displayed size only.

## Decision and hypothetical full-flow gates

1. At the anchor, both quotes must have receipt age ≤1 s, source age ≤2 s, and source-time difference ≤0.5 s. Opposite-venue displayed best size must cover the full quantity. Compute opening quote allowance after maker entry fee, taker hedge entry fee, and an approximate two-taker exit-fee hurdle. **Predeclared entry-positive subset** means this decision-time allowance >0; the full set is always reported alongside it.
2. At hypothetical maker arrival, the original maker-side best price must still be displayed, uncrossed, and fresh under the same age limits. Displayed size at that price becomes modeled queue ahead. This is not an actual queue measurement or order acknowledgement.
3. Starting at arrival, use uniquely identified, prospective public trades with valid aggressor, price, size, source time, and receipt time. Count opposite aggressor volume at or through the maker price, without reuse inside the window. A **hypothetical full-quantity flow event** occurs at the *first* trade for which cumulative qualifying volume **strictly exceeds** initial displayed queue ahead plus the fixed quantity. Record its source and receipt time. No flow event is classified as no hypothetical full fill; it is never assigned zero P&L.

## Post-flow hedge and ten-second paired exit

4. Only conditional on that full-flow event, select the **first** quote on the opposite venue after `flow receipt + 0.1 s`, within one additional second, that passes **time/source/freshness** checks. Its source time must be at least the flow source time; receipt minus source must be 0–2 s. Test its opposite-side displayed depth **after selection**. If it is shallow, censor as insufficient hedge depth; do not wait for a later, fuller quote. Maker-buy hedges by selling at bid; maker-sell hedges by buying at ask. A full-flow signal without an eligible hedge quote is an **unresolved, unhedged hypothetical outcome**, never a zero return or discarded denominator.
5. Set exit target to `hedge receipt + 10 s`. Until target +1 s, select the **first observed pair** of opposite-side best quotes, one on each venue, that passes **time/source/freshness and ≤0.5 s source/receipt skew**; each source time must be ≥ target. Test both displayed depths **after pair selection**. If either is shallow, censor as insufficient exit depth; do not wait for a later, fuller pair. Missing or unsynchronized exits receive separate counts. Report actual target-to-observation delay.
6. Conditional displayed cashflow uses the fixed base quantity: maker entry at its original price, opposite taker hedge at the selected quote, both taker exits at the selected paired quotes. Charge **all four fees on each leg's own entry or exit notional**: maker entry rate, hedge taker entry rate, maker-venue taker exit rate, hedge-venue taker exit rate. Rates are native HL tier-0 1.5 bp maker / 4.5 bp taker and Lighter Core/RH Standard 0/0 bp, subject to wallet-tier verification. Normalize bps by maker entry notional. Alongside primary four-fee net, report a sensitivity column that subtracts a further **5 bp of the larger maker or hedge entry notional** as an execution reserve. This reserve is a scenario, not a measured fee. No conversion, funding, financing, gas, slippage, collateral transfer, or queue opportunity cost is otherwise included.

## Integrity and interpretation

The script must reject archives with more or fewer than one feed generation per venue, any feed/trade invalidation or error, malformed trade identities, or unknown-market trades. Startup trade snapshots and trades before the first quote are excluded. Report **every** quote-supported anchor, same-price arrival, full-flow event, hedge status, and exit status by route, side, and delay; output each full-flow case in bounded CSV/JSON. Missing outcomes remain in denominator summaries and are never coded as zero return. Both the complete full-flow cohort and the decision-time entry-positive subset are reported. Arrival-delay controls share frames, and 10-second hypothetical holds overlap the 5-second anchors; no cohort returns are summed into a portfolio P&L.

Even if all gates pass, the resulting value is a **conditional hypothetical displayed-book round trip**, not realized P&L, an upper bound, or fill probability. Public trade flow does not reveal our queue position, hidden liquidity, cancels, ALO acceptance, or whether the resting order would exist. Cross-venue clocks are not calibrated; receipt minus source is not measured network latency. Zero or few qualified cases should be reported as an evidence limit, without promotion to live orders.

A full-flow event with a missing hedge is an unresolved hypothetical unhedged exposure, not a zero return or an unentered trade. Five-second anchor windows can produce overlapping ten-second holds; no independent-trial or summed portfolio P&L claim is permitted.
