# Next short-horizon arbitrage research

**Superseded research sketch.** The approved, narrower
[impulse observer draft](impulse-observer-plan.md) defines the actual
read-only pilot, including RH-domain quote screens, confirmation-based
entry delays, and no no-impulse control in version 1. This memo is retained
for history.

**For review, not adopted:** test a strictly hedged **impulse-dislocation
entry** as a separate read-only observer. Buy the cheaper same-asset perp and
short the more expensive perp only after an observed venue price impulse
leaves a basis outlier that persists through a fresh update from the other
venue. Measure a complete quoted unwind within ten seconds, at the original
quantity, after all four taker fees and the existing reserve. No live entry
rule, process launch, or fill claim follows from this memo.

## Evidence and economic mechanism

The completed [fixed-quantity pilot](../reports/fixed-markout-v1/final.md)
had 1,595 matched 12–16-second outcomes from 2,134 anchors. About 0.1% of
matched quoted round trips were positive after four fees, and none after
the reserve; its primary forecast screens selected zero entries. The
[BTC/ETH public capture](maker-capture-analysis.md) found zero positive
complete four-taker quote outcomes at 1, 2, 5, and 10 seconds. The
[24-hour funding holdout](../reports/funding-carry/REPORT.md) did not cover
four-taker fees on any screened two-leg route. These observations do not
support an unconditional short hold or a historical median closing-basis
gate. A rare **new relative-price shock** could have different forward
behavior, but that is an untested hypothesis; filtering cannot create a
profitable quote if the dislocation never exceeds the execution hurdle.

The proposed return remains **basis contraction** between simultaneous
long and short positions in the same asset, with no intended outright
price exposure. The feature is the *change* from a prior route-specific
basis following a distinct venue impulse, rather than a favorable-looking
opening spread alone. The four cash-flow signs are: short entry proceeds
minus long entry cost, plus later long liquidation proceeds minus short
buyback cost. Each execution incurs its own taker fee; quote depth, impact,
the 5 bp reserve, and any funding boundary also matter. [Hyperliquid's
fee formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
varies for native and HIP-3 perps; [Lighter Standard fees](https://docs.lighter.xyz/trading/trading-fees)
are currently stated as zero, subject to market floors and the pilot's
frozen account assumption. Neither rate is inferred from a maker fill.

## Candidate rule, frozen before observing outcomes

Start with liquid, contract-checked **BTC and ETH** native Hyperliquid versus
Lighter Core routes in both directions. Add **NVDA and XAG** only if the
sampled HIP-3 and Lighter contracts have equivalent units, oracle/reference
exposure, trading hours, collateral assumptions, fresh depth, and frozen
per-asset fee metadata. The fixed-quantity pilot had 179 NVDA and 151 XAG
matched observations, but ticker similarity alone does not validate a hedge.
Exclude RH-domain USDG routes until conversion and collateral are modeled.

Use a fixed approximately $1,000 lot-matched base quantity. Maintain at most
one prior observation per second per physical pair for a **60-second**
rolling mid-basis history. At an event time `t`, compute
`b = 10,000 × (mid_HL − mid_Lighter) / mid_Lighter`; the reference `b_ref`
is the median of **only** synchronized samples from `[t−60s, t−2s]`.
Require at least 30 such samples spanning 30 seconds, with no generation
change or feed gap. The two-second embargo stops the current impulse and
confirmation quote from altering their own reference. Keep both directed
entry quote walks at the frozen quantity separate from this mid-based
feature.

An impulse candidate needs a within-venue mid move over one second of at
least **half the route's round-trip cost hurdle**, while the other venue's
move over that interval is at most one quarter of the impulse magnitude.
Then wait for the other venue to publish a **new source token and receipt**
after the impulse was received. Recompute `b` from the newest paired books;
only this confirmed value may trigger an entry. Its deviation from `b_ref`
must exceed the **full hurdle** in the direction that makes one venue cheap
and the other expensive. Define the hurdle at the original quantity as the
four frozen Standard taker fees on current size-walked entry and immediate
exit notionals, plus the 5 bp pair reserve and **$0.25** target, converted
to bps of the long buy cost. This ties both fixed thresholds to actual
costs, while the 60-second history and $0.25 target are set before the
pilot. Record all failed triggers and reasons; never relax thresholds on
the pilot's outcome sample.

Both books must be uncrossed and executable at the same quantity, with
source and receipt ages at most two seconds and paired source/receipt skew
at most one second. Both source tokens must advance; invalidate on sequence
or generation breaks. The [earlier public feed capture](maker-capture-analysis.md)
observed Hyperliquid receipt-minus-source medians near **0.30 s** and
Lighter Core near **0.065 s**. Exchange clocks were not calibrated. Thus a
Hyperliquid message arriving first does **not** establish that Hyperliquid
led price discovery. The confirmation update and later post-delay quote
measure what the collector could have acted on; report source-clock offset
sensitivity and classify unalignable events as timing-unknown. Do not
overwrite an older Hyperliquid L2 book with a newer BBO top or combine
incompatible source times. Use local receipt order for causality and within-
venue source order for advancement, not an unverified cross-venue timestamp
ordering claim.

## Prospective quote measurement and falsification

For each confirmed candidate, freeze direction, quantity, trigger time,
reference basis, cost hurdle, both source identities, and all feature values.
At a predeclared **500 ms** post-trigger arrival, use the first fresh paired
books to size-walk both taker entry legs at the *original* quantity; use 1 s
as a stress case on the **same candidates**. A missing leg, changed
generation, or insufficient depth is a failed paired quote, not a filled
hedge. From the first complete paired entry quote, request a full exit quote
at five seconds and use the first synchronized advancing paired books
thereafter, with a **hard ten-second deadline from the trigger**. Walk the
long venue bids and short venue asks for the same quantity. Missing or
shallow exit depth is censored explicitly. An entry or exit crossing a
funding event is excluded unless that event's signed cash is observed and
assigned to both legs. Never use a quote available before the relevant
arrival or exit time. This is an optimistic quote screen; actual sequential
orders may incur one-leg failure and different fills.

Compute gross capture and all four fee dollars on their own notionals,
then subtract the fixed 5 bp reserve and elapsed capital estimate. Report
candidate, confirmation, paired-entry, full-exit, and censored counts;
net-quote median/p10/p90 and positive fraction; source ages/skews; and
one-leg-risk states. Compare with a **same-route, same-five-minute-block**
control of cost-hurdle-sized basis outliers that lacked the impulse feature.
If no such controls exist, say the impulse contribution is unidentified.
Opposite directions, adjacent anchors, and 500 ms/1 s scenarios share books
and are not independent trades.

The hypothesis fails this pilot if **no** cost-hurdle-confirmed candidate
survives fresh-book confirmation, or if at least 30 complete candidates
have median net quoted capture at or below zero after fees and reserve.
It remains unassessable if fewer than 30 complete outcomes or if paired
entry/exit coverage is below half of confirmed candidates. Even a positive
quote result would need a separate paired-fill and failed-hedge loss audit
before any trading-policy change. This pilot sends no orders.

## Deferred ideas

The previous **one-leg directional Hyperliquid-to-Lighter spillover** idea
is **not adopted** as a replacement for the user's arbitrage strategy:
it deliberately takes unhedged price exposure. A multi-hour funding carry
also has a different holding mandate and failed the existing 24-hour
all-fee screen. The separate maker post-flow/round-trip work remains with
its current owner; this proposed test assumes only taker quotes and never
counts a public trade as a hypothetical maker fill.
