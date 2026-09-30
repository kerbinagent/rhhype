# RH passive inventory exit: prospective paper method

**Frozen when the source-hashed protocol is issued before capture.** This is a read-only public-flow
counterfactual, not an order or a private-fill record. Earlier data informed
these hypotheses; no new holdout outcome selects a parameter here. The experiment asks
whether an RH maker **sell** of an existing RH long can recover enough spread
to pay for the original RH maker buy, HL short hedge, and eventual HL buyback.

## Universe, branches, and time

Use BTC, ETH, NVDA, XAG and original RH order budgets $100, $250, $500,
$1,000, with $1,000 primary. RH Standard and asset-specific HL Standard fees
are primary. RH Premium is a separate 64-branch processing/fee sensitivity,
never combined with Standard. Each `(asset, budget, tier, branch)` has its own
prefunded RH USDG and HL USDC ledger; apparent combined dollars condition on
USDG/USDC parity and omit a conversion trade. The same frozen public market
metadata, tick/lot/minimum rules, source/receipt validity, four-leg fee
accounting, wallet reserves, and RH buy-flow queue attribution apply to all
branches. No private fill is assumed.

Exactly four exit branches share **fixed_best RH maker buy entry and HL taker
short hedge** logic:

| Branch ID | RH exit after first full matched hedge | Deadline from that hedge |
| --- | --- | ---: |
| `control10s` | Existing executable $0.10 early-take-profit mark **or** 10 s deadline requests RH taker sell plus HL taker buy | 10 s maximum request hold |
| `passive_best10s` | RH maker sell at current best ask; HL taker buy on attributed sell increments; taker flatten remainder | 10 s |
| `passive_target10s` | RH maker sell at the cost-aware target ask; same hedge/flatten | 10 s |
| `passive_target60s` | Same target rule; same hedge/flatten | 60 s |

The deadline initiates exit or cancellation; it does not assert flat inventory
or a fill by that time. One common, receipt-ordered fixed-best candidate
stream assigns a stable opportunity ID **before** branch wallet/busy checks.
For each `(asset, size, tier)` group, admit no new entry unless all four
branches are flat; record `group_busy` at every otherwise valid opportunity.
Each branch still records its own wallet, model, and venue-order admission
reason; a branch that abstains does not make another branch's cash known.
Independent ledgers can diverge after their exits. Compare cash
only on common opportunities with the **same actual modeled entry quantity,
maker price, HL hedge quantity, and hedge price**, and completed known exits
in all compared branches. Report all-opportunity admission, fill, hedge,
completion, censor, and funding-unknown denominators separately. Do not
turn no-flow, unknown, or unmatched branches into zero profit. Do not add
counterfactual ledgers as simultaneous executable returns.

Capture 30 minutes calibration and a 20-minute frozen holdout. The last
**80 seconds of that holdout admit no new entries** and process existing
obligations only: the entry-admission window is 1,120 seconds, followed by
an 80-second washout, within the existing 3,000-second capture limit. This
does not guarantee flat inventory. Block new entries from 80 seconds before
each UTC funding-hour boundary through two seconds after it, recording the
otherwise eligible candidates as `funding_window_blocked`. Any residual
funding crossing remains unknown unless sourced settlement cash is captured.
The source-hashed
protocol, market metadata digest, frozen parameters, parser, engine, analyzer,
and bounded output rules must be recorded **before** the new capture begins.
Reject a capture predating the protocol or violating duration/continuity,
market hash, raw byte cap, or event terminal status. Raw capture cap is 384 MB;
the derived audit cap is 96 MB and summary/report cap is 32 MB (128 MB combined).
A cap hit means truncation and unknown remaining
obligations, not a negative result.

## Target ask, with a causal adverse buyback allowance

For a matched original quantity `q`, entry RH maker buy price `R_in`, actual
HL short proceeds `H_in(q)`, current HL ask walk `H_ask(q)`, and RH candidate
maker exit ask `R_out`, the projected completed cash is

`q·(R_out − R_in) + H_in(q) − H_buy_hat(q) − four own-notional fees`.

Here `H_buy_hat(q) = H_ask(q) × (1 + A75/10,000)`, where `A75` is a
nonnegative 75th percentile of the **HL buyback ask adverse change** following
public RH buy-aggressor flow at or through the then-standing RH ask. During
the first 30 minutes, deduplicate flow anchors at most once per second per
asset/size. Require the standing RH ask book source time no later than the
trade source time, so a delayed print cannot be labeled by a future book.
Each anchor freezes the current HL ask walk at original valid
`q`, waits 150 ms from local trade receipt, and uses only the first eligible
same-generation HL book in the next second. Its source and receipt must both
be at or after due. First eligible shallow depth censors rather than seeking
a later better book. Missing, stale, invalid, generation-broken, or clock
ambiguous observations are censored. Include adverse observations beyond
the 10 bp execution limit in the fit. Require at least 20 matched flow
observations spanning 10 minutes and at least 50% resolution; otherwise the
target branches abstain as `model_unready` rather than borrowing holdout
outcomes. Freeze `A75` at the calibration cutoff for the entire holdout.
The existing maker-sell model's buy-aggressor flow estimator may supply this
statistic if its exact rules and source hash are frozen; it does **not** supply
a complete closing-basis forecast or a fill probability.

For `passive_target`, choose the **lowest valid noncrossing RH ask tick at
or above current RH best ask and no more than 5 bp above it** whose projected completed net, after the
actual entry fees, modeled RH maker-exit fee, HL taker buy fee on
`H_buy_hat`, five-basis-point reserve on larger entry notional, elapsed
capital plus the remaining horizon allowance, and $0.10 target is
nonnegative. Recalculate candidate fee/notional and lot validity at the
actual ask tick; never use an invalid order or assume an RH maker fill.
If no valid tick or adequate HL buy depth exists, record an abstention.
`passive_best` posts the current valid RH best ask without applying a net
threshold. The target ask is a **screen**, not promised exit profit: RH
maker flow may never reach it, and HL may move further before the buyback.

After the first full matched hedge, wait for confirmed entry-bid cancellation,
its `cancel_due + max_book_age` late-flow guard, no pending entry hedge, and
matched RH/HL inventory before requesting one RH maker sell for no more than
actual RH long inventory. If this wait consumes the deadline, request taker
flatten without a passive ask. Freeze that request's price for its lifetime; no
favorable subsequent repricing. RH Standard maker activation and cancel
effectiveness each take published 200 ms plus 100 ms network allowance;
Premium uses its separately frozen schedule. At activation, use a source-
and receipt-valid RH book at or after due. Freeze displayed same-price
queue ahead. Only subsequent RH **buy-aggressor** prints with source and
receipt at or after activation and price at/through our ask deplete this
queue. Trade-through and same-price touch are reported separately; no
credit for unseen cancellations ahead. Attributed sell quantity executes
at the **own ask price**, not the observed print price. An inside-spread
counterfactual quote can alter real prints, so attribution is conditional.

For each attributed RH maker sell increment, request an equal-quantity HL
taker buy after the frozen 150 ms local delay and apply the first eligible
HL book, same 10 bp directional limit, and three-second intent timeout.
The first time-eligible shallow HL buy book produces a **partial actual
modeled IOC** with its cash and fee, followed by bounded rescue for the
residual; it is not a no-fill censor. Missing/invalid first evidence stays
unknown rather than waiting for a favorable later book. Venue minimum and common lot apply
to the **increment**, not merely the original $1,000 quote. Unhedgeable
dust remains open/unknown and cannot be upsized or silently netted.
Within a branch, simultaneous pending hedge, passive buyback, and fallback
IOCs cannot each consume the same displayed book depth. Allocate fills in
one deterministic event order and count actual partial slices; never reuse
one level as if it replenished between orders without a new book event.
At 10 or 60 seconds, request cancellation of remaining RH maker sell and
taker flatten every actual residual RH and HL position using the frozen
latencies and first eligible books. Fills during cancel pending are still
obligations. A late sell fill racing with a taker exit must reconcile actual
inventory; unresolved or excess short inventory is unknown, never zero.
Invalid books, feed gaps, source regression, funding boundary crossings,
depth failure, order timeout, and capture end are separately labeled.

## Predeclared readout

Primary descriptive contrast: Standard XAG/$1,000 `passive_target10s` versus
`control10s` on
common **same-entry, known-complete** cohorts, reporting paired cash net
after actual modeled fees, five-basis-point reserve, and elapsed capital.
The control keeps its original **early** $0.10 take-profit request and may
exit before 10 seconds. Thus this compares whole exit policies, including
different hold times, not only maker versus taker execution price.
Secondary: passive best versus control at 10 s, and target 60 s versus target
10 s, on the same common-cohort rule. The 60 s branch has larger funding,
capital, no-fill, and residual inventory exposure; report those outcomes,
not just completed favorable fills. A branch's own all-opportunity coverage,
unknown/censored episodes, complete cash by currency, maker-exit fill
quantity, taker residual quantity, one-leg seconds, and p50/p90 completion
delay accompany every paired economic number. The comparator does not
inherit another branch's capital or admission decision. Five-minute blocks
and asset/size breakdowns are descriptive; overlapping candidate streams
and public flow cannot support independent-trade significance claims.
Report first unknown timestamp, time from first requested quote to first
unknown, and valid book-event quote checks per group. An early unknown
shortens effective active coverage; a quiet or stale feed makes this a
feasibility failure rather than evidence against the strategy.

This study can reject a particular ten- or sixty-second passive exit rule.
It cannot observe actual private queue priority, one-way network latency,
funding/borrow cash unless independently recorded, USDG conversion, or
real execution quality. A short favorable replay would justify a longer
new frozen study, not live deployment.
