# Preregistered follow-up: RH maker sell, HL taker buy

**Design note, 2026-09-29.** The running RH maker-bid / HL short pilot is
buy-side only and remains frozen. This note specifies a separate future
paper experiment, before using that pilot's outcomes to select a direction.
No current capture, orders, or private fills were inspected.

## Economic hypothesis

For one original common-lot quantity `q`, the sell path posts an RH maker
**ask** at `p`, buys the same base quantity on HL by taker after an
attributed RH maker fill, then exits within the same ten-second rule by RH
taker **buy** and HL taker **sell**. Its completed gross cash is

`G_sell = q·p − HL_entry_ask_walk(q) − RH_exit_ask_walk(q) + HL_exit_bid_walk(q)`.

Four actual fill fees, reserve, capital held, signed funding if a settlement
boundary is crossed, collateral conversion, and any residual inventory are
separate. The matching closing liability is
`C_sell(t,q) = [RH buyback ask walk(q) − HL sell bid walk(q)] / q`.
A quote based only on `p − HL_entry_ask/q` ignores that liability. If books
and basis do not change, an RH ask at the current best ask loses the HL
round-trip spread and any RH buyback depth impact before costs; the sell
quote therefore needs a sufficiently higher ask or a defensible, causal
closing-basis forecast. It can have different opportunities from a maker
bid if RH's relative premium rises or falls, but that is a hypothesis, not
an arbitrage certificate.

The sign of **adverse selection reverses**: RH buyer-aggressor flow that
could fill our ask can precede an upward HL buy price. Calibrate
`10,000·(HL_first_postdue_buy_VWAP − HL_at_flow_buy_VWAP) /
HL_at_flow_buy_VWAP` on original `q`; the positive tail hurts this side.
The RH-short / HL-long pair also reverses signed funding exposures and
margin risks. A short squeeze, oracle/session moves in NVDA or XAG, and
unmatched RH shorts are not interchangeable with the current RH-long / HL-
short inventory. Perp shorts do not require assuming a spot borrow fee, but
funding and liquidation capacity at each prefunded wallet still matter.
USDG/USDC parity is a conditional reporting assumption, never an executable
conversion quote.

## What existing evidence says

The earlier stopped NVDA/XAG replay had **10 and 17** RH→HL maker-sell
quote-supported one-second decisions, respectively, and **zero** strict
full-flow signals on both sides ([archived report](maker-equity-results.md)).
Its RH→HL maker-buy cohorts had 11 and 14 supported decisions and also zero
full-flow signals. The BTC/ETH exploratory replay had only two primary
RH→HL full-flow signals across both directions and one complete conditional
path, with no positive completed result ([exploratory report](maker-roundtrip-exploratory.md)).
These small, correlated public-flow counts cannot rank buy against sell or
estimate an actual maker fill probability. The separate stopped-book
[spread hurdle](rh-maker-inventory-exits.md) shows why RH displayed width
alone does not pay HL spread, fees, reserve, and a ten-second taker unwind.

## Frozen future test

Use the same **BTC, ETH, NVDA, XAG** perp contracts, independent wallets,
RH Standard primary fees/delays, asset-specific frozen HL taker fees,
**$100/$250/$500/$1,000** maximum order budgets, and $1,000 primary size.
Keep the current pilot's 30-minute calibration / 20-minute holdout split,
source≤receipt, age≤2 seconds, paired skew≤1 second, generation continuity,
valid lot/tick/minimums, 5 bp risk reserve, 5% annual capital charge,
$0.10 completed target, and the 10 bp hedge execution cap. At each proposed
ask price, floor quantity to a common valid lot under the **actual**
`q·ask ≤ budget`; freeze that `q` for queue, HL hedge, and both exit legs.
If no price and quantity clear all venue minima and budget, record an
abstention; do not upsize a small order or silently resize a partial fill.

For closing-basis calibration, use past-only anchors spaced at least ten
seconds and the first advancing, source/receipt-valid paired books at
10–16 seconds, walking the original quantity. The first eligible shallow
pair censors the anchor. Freeze the median matured change in `C_sell` only
when at least 30 matched anchors span ten minutes and at least half of all
admitted anchors resolve. For flow-conditioned hedge calibration, sample
at most once per second per asset/size on deduplicated **RH
buyer-aggressor** trades at/through the then-current ask; reject a trade
whose source predates the RH book used to label it. Use the first HL ask
book whose source and receipt are both at least local flow receipt+150 ms,
within one second of that receipt, with full original-quantity depth. Keep
moves beyond the 10 bp execution cap in the 75th-percentile adverse
estimate; first-eligible shallow, invalid, late, or generation-broken
outcomes are censors, never replaced by later favorable depth. Require at
least 20 resolved flow anchors spanning ten minutes and 50% resolution.
Calibration pending at cutoff is censored, and the fit is immutable in
holdout. Unready routes abstain rather than borrow the buy-side fit.

The sell quote screen is the sign-reversed completed forecast:
`forecast_net(p) = q·[p − expected_HL_buy − forecast_C_sell] − four
expected fee notionals − 5 bp reserve − ten-second capital − $0.10`.
Use the **lowest valid noncrossing RH ask tick** that clears it, subject to
actual quote notional and HL depth. The adverse-flow 75th percentile raises
expected HL buy cost; plain persistence sets the adverse adjustment to
zero; fixed-best joins the current RH best ask without a model-net gate.
The same event IDs feed three independent counterfactual ledgers. No
prediction may use its own future book. Keep all rejected candidates,
quote activation/cancellation races, possible partial fills, no-flow,
hedge failures, funding boundaries, and unresolved inventory in the
denominator.

For public-flow attribution, freeze visible same-price RH ask quantity
ahead at activation; only deduplicated RH **buy-aggressor** trades at or
through that ask with source and receipt after activation may deplete it.
A trade at/above our ask implies lower ask levels were traversed, so do not
double-subtract their initial displayed volume. Price an attributed maker
fill at **our ask**, not at a higher printed trade. Cancel the unfilled
remainder immediately after the first attributed partial, but count
possible late fills before cancellation becomes effective as obligations.
Buy HL only for an attributed valid increment, and flatten or retain
below-minimum dust explicitly. Reverse the RH and HL exit sides; preserve
venue-specific delays, first eligible depth, normal timeouts, and the
full-pair ten-second exit request rule. A public print is possible flow,
not a private fill.

A mirrored buy paper ledger on the **same new prospective window** can use
its already frozen rule as a direction control. Separate RH/HL wallet
balances, gross inventory, and funding keep the two branches independent;
their outcomes are correlated because they share market data, and summing
or netting them would require a new combined execution policy. Predeclare
per-direction all-candidate coverage, complete net after costs, missed
flow, one-leg exposure, and terminal unknowns. Compare directions only on
that future window, including abstentions and failed exits; do not choose
whichever direction looks favorable in the current buy holdout. If either
side is unready or lacks complete paths, report that limit and require a
newly frozen, longer prospective run before any strategy recommendation.
This remains paper research, with no automatic production promotion.

The operational maker-then-hedge rule is consistent with the existing
[primary-source research review](sota-maker-hedging.md), including
[Hummingbot's documented cross-exchange maker workflow](https://hummingbot.org/strategies/v1-strategies/cross-exchange-market-making/).
That spot workflow does not establish RH/HL perp queue position, private
fills, or short-inventory economics.
