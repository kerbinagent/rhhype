# Frozen impulse-dislocation observer pilot specification

This is a separate read-only, public-WebSocket pilot. It neither places orders
nor changes the running paper portfolios. Scope is up to eight Hyperliquid
versus Lighter Core/RH-domain pairs for BTC, ETH, NVDA, and XAG; each physical
pair is evaluated in both hedge directions. RH-domain USDG and HL USDC are
treated at **parity solely for this quote screen**. No conversion route or
convertibility is claimed. Require fresh discovery metadata, equivalent
base units/reference exposure, and lot/min-notional compatibility. Fee rates
are frozen Standard taker assumptions from that metadata, including market
floors; negative/nonfinite rates reject the pilot.

## Event order and candidate gate

Process each market update in collector receipt order. Validate noncrossed
books, positive depth, source and receipt age ≤2 s, pair source and receipt
skew ≤1 s, known sequence/generation, and within-venue source advancement.
Feed invalidation, generation change, or >30 s route gap clears history and
censors pending candidates. Keep at most one synchronized basis sample per
second per physical pair, requiring both source tokens to advance. Store
≤60 samples in the last 60 s, including mids and **both directed executable
closing-spread bps**; source data are never revised by a later packet.

At an event `t`, calculate the reference median only from samples in
`[t−60,t−2]`, with ≥30 samples spanning ≥30 s. A one-venue mid change over
≤1 s must reach **half** the current direction's hurdle, and the other
venue's absolute move must be ≤25% of that impulse. The hurdle in bps is
`(four current taker fees + 5 bp pair reserve + $0.25 target) / long buy
value × 10,000`, using same-quantity size-walked buy ask, sell bid, long
bid, and short ask. Arm for ≤1 s and require the **other** venue to publish
a new source token and receipt after the impulse receipt. At confirmation,
freeze direction (buy the venue below its prior relative basis, short the
other), equal lot-matched quantity, the arm-time prior reference, and fees.
Require (1) the confirmed mid-basis deviation
from its prior 60 s median ≥the full hurdle, aligned with the impulse sign,
and (2) `(short entry − long entry) − prior median executable closing
spread × long entry / 10,000 − four estimated fees − reserve ≥$0.25`.
This second test prevents a mid-only outlier from passing an uneconomic
closing-spread quote. Count each failed feature gate and each arm expiry.
Only **prior** samples train either median; the current and confirming
quotes are excluded by the two-second embargo.

Receipt ordering establishes what this collector knew. The old archive's
HL receipt-minus-source median was about 0.30 s versus Core about 0.065 s;
exchange clocks were not calibrated. No message-order claim that a venue
caused or led the other is made. Report both source ages, pair skew, and
unknown cross-clock alignment. Never merge an older HL L2 packet over a
newer BBO source time.

## First eligible paired quote outcomes

Create **two scenarios from the same frozen candidate**: primary entry due
at confirmation+0.5 s, and stress entry due at confirmation+1 s. These budgets include
Lighter Standard's published 300 ms taker delay plus a small network
allowance; they are optimistic quote observation delays, not measured fills.
For each scenario, use the **first** fresh paired book after due with both
source/receipt tokens advanced since confirmation **and both venue source and
receipt timestamps at or after the UTC due time**, no later than trigger+2 s.
Walk both entry legs at the frozen quantity. If that first eligible pair
lacks depth/lot/min-notional eligibility, censor `entry_depth` immediately;
do not retry a better quote. If absent, censor `entry_missing`.

For a complete paired entry quote, request exit at entry quote+5 s, allow
0.5 s exit observation delay, then use the **first** fresh paired book with
both source/receipt tokens advanced since entry **and both venue source and
receipt timestamps at or after exit due**. Record source and receipt delays; exchange
clock uncertainty limits their interpretation. The final outcome must be
received by trigger+10 s. Walk long bids and short asks at the **same**
quantity. Insufficient first eligible exit depth or venue minimum censors
`exit_depth` or `exit_minimum`, respectively;
absence censors `exit_missing`. Compute gross four-cash-flow capture,
each of four taker fees at its own observed notional, 5 bp reserve, and
capital estimate for actual entry-to-exit elapsed time separately. An
unresolved funding boundary is `funding_unknown`, never zero funding.
These are prospective quotes, never assumed fills or cash P&L. The prior
closing-spread median is an economic forecast heuristic, not a guaranteed
exit. Direction follows the **deviation from prior basis**, even if the
chronically higher-priced venue remains higher in absolute price.

## Bounds, outputs, and tests

At most eight physical pairs, 16 directions, one arm/active candidate per
pair, two scenarios/candidate, 60 history rows/pair, and 5,000 recent
terminal scenario rows. Counters are cumulative; export drops are explicit.
Default duration 1,200 s, hard cap 2,400 s. Atomic JSON snapshots and
rotating logs, no live book archive. Stop labels pending scenarios before
StreamManager shutdown invalidations. Report gate rejection counts,
candidate→entry→exit coverage and censor reasons by pair/direction/scenario,
plus all-run mean quoted economics. Later offline distributions must label
retained rows if the export truncates. Version 1 compares only the same
frozen candidates under 0.5 s and 1 s arrival; it has **no no-impulse
control**, so it cannot isolate the impulse feature's incremental effect.
Because late confirmation shortens the 1 s scenario's eligibility before
the fixed trigger+2 s cutoff, report coverage and censoring for all
candidates, but compare delay economics only when both scenarios complete
for the same candidate.

Meaningful regressions: current quote cannot enter its own median; first
shallow entry/exit censors rather than waits; 0.5/1 s scenarios share one
frozen candidate; source/generation/gap/clock checks; exact four-fee signs
and original quantity; no exit after trigger+10; arm requires opposing update;
bounded state/export; Ctrl-C/stop conservation. No pilot launch until code
and tests are reviewed.

Each side's short impulse history is timestamped by that book's actual
collector receipt, pruned against the current decision time, and requires two
observations spanning at least 0.5 s on both sides. The 128-row side history
cap can shorten the effective one-second window under very fast updates.
Pair validation tolerates source timestamps up to 0.25 s and receipt
timestamps up to 0.1 s ahead of local UTC `now`; exchange clocks are not
calibrated against each other. The hard trigger+2 s entry deadline can censor
the 1 s scenario if confirmation comes late. Source or receipt regressions
are rejected before feature and outcome evaluation.
