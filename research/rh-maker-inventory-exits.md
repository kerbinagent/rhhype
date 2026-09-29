# RH maker entry with taker versus maker inventory exit

**Research note, 2026-09-29.** This is a separate hypothesis for a later
prospective paper study. It uses only the stopped NVDA/XAG full-book archive
recorded before **21:21:32 UTC**, the pre-pilot market plan, and the current
frozen pilot's published method. It does not inspect the new capture or change
its quote, fill, hedge, or exit policy. A displayed book is not a fill or an
executable order acknowledgement.

## Two completed paths

Let `q` be one original matched lot, `p_in` the RH maker buy, `H_in` the HL
taker short VWAP, `R_bid(q)` the RH taker sell proceeds at exit, and
`H_ask(q)` the HL taker buyback cost. The current frozen path **A** is

`A_gross = H_in(q) − q·p_in + R_bid(q) − H_ask(q)`.

It exits both legs by taker no later than ten seconds after the first full
hedge, subject to the declared processing delays. Four fill fees, reserve,
capital, funding, residual inventory, and USDG/USDC parity uncertainty still
matter. When the books and cross-venue basis do not change, joining the
current RH best bid makes `q·p_in ≥ R_bid(q)`, while
`H_ask(q) ≥ H_in(q)`. Thus gross is nonpositive even before positive HL
fees, the five-basis-point reserve, and the $0.10 target. The largest bid
that clears the *static* screen necessarily lies **below** RH best bid by at
least the HL round-trip spread plus RH exit depth impact and the fee/risk
hurdle. Shrinking `q` helps depth and potential full-flow, but makes the
fixed $0.10 target more basis points: 10 bp at $100 versus 1 bp at $1,000.
Small size alone does not create an edge.

A distinct path **B** would enter RH maker buy and HL taker short, then post
an **RH maker sell that reduces only the actual RH long inventory**. On an
attributed RH sell fill, buy back the corresponding HL short by taker. Its
completed gross for that matched increment is

`B_gross = H_in(q) − q·p_in + q·p_out − H_out_buy(q)`.

At unchanged books, RH best-bid entry and best-ask maker exit can capture
RH's bid–ask spread, while HL still pays its buy–sell spread. This is a
possible change in economics, not a free spread: the second RH maker sell
may not fill, may fill partially, or may fill just as the cancellation
request is in flight. The HL buyback can worsen after RH sell-flow
confirmation. B must taker-flatten both residual legs at the ten-second
request deadline and keep later fills/unresolved inventory as obligations.
It cannot label an unfilled exit as completed profit.

## Stopped-archive quote hurdle

The reproducible [static-book calculation](../scripts/analyze_maker_spread_hurdle.py)
uses [5-second anchor diagnostics](../reports/maker-book-archive-v1/derived/rh-anchor-diagnostics.json),
the [stopped reconstructed full-book archive](../reports/maker-book-archive-v1/derived/book-events.jsonl.gz),
and the [pre-pilot venue plan](../reports/maker-equity-v2/market-plan.json).
It floors quantity from the RH best ask and historical common lot, then
walks full RH sell and HL sell/buy depth at that same quantity. Books must
be ≤1 second old by receipt, ≤2 seconds by source, and paired within one
second. RH Standard fees are 0/0 bp; the pre-pilot plan records 0.9 bp
HL xyz taker per leg. The calculation holds the displayed books fixed,
charges the current pilot's five-basis-point reserve, 5% annual capital for
10 seconds, and the $0.10 target. It solves for a *continuous-grid* RH bid;
it does not assert that a historical RH tick or a maker fill was available.

| Asset | RH-only fresh / 83 | Paired full-depth / 83 | RH spread median, RH-only | HL walk spread median, paired $1,000 | Required discount below RH best, paired $1,000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVDA | 78 | 15 | 1.75 bp | 0.44 bp | 8.23 bp |
| XAG | 80 | 16 | 3.06 bp | 0.16 bp | 7.96 bp |

The paired sample is small because the old HL full-book feed rarely met
the one-second paired receipt/source rule at those fixed anchors. The RH
spread column uses 78/80 RH-fresh observations; the HL and hurdle columns
use only 15/16 paired observations. At $100/$250/$500/$1,000, the median
static A discount below RH best was **17.25/11.24/9.23/8.23 bp** for NVDA
and **17.00/10.97/8.96/7.96 bp** for XAG. Every retained paired row
required a positive discount. These are displayed-book quote thresholds,
**not** observed executions, predicted fills, a B-policy backtest, or
profit estimates. The complete bounded [JSON evidence](../reports/rh-maker-inventory-exits/stopped-spread-hurdle.json)
contains all 124 asset-size paired rows, coverage counts, source hashes,
and p10/median/p90. A hypothetical RH maker sell at the **current** best ask, with unchanged
books and both maker fills simply assumed, still has a median static screen
of **−$0.65 NVDA / −$0.49 XAG** at $1,000 after the same fees, reserve,
capital, and target. These negative screens are not observed cash losses:
they assume an exit maker fill without proving one and hold future prices
fixed. A second quote would need better entry/exit prices, a favorable
basis move, lower costs, or some combination; its fill hazard must be
measured jointly with those prices.

## Next prospective policy to falsify

The current frozen pilot tests RH **buy** quotes only. The user's phrase
“bid size” is treated as an order-budget constraint, not evidence that RH
sell quotes should be excluded from the broader survey. A later symmetric
RH maker-sell/HL-buy study is also needed: the initial survey often observed
RH equity premiums in that direction. Neither a negative bid-side pilot nor
this static screen rejects all RH liquidity-provision strategies. The
current pilot is left intact so its result remains interpretable.

Freeze a **separate future run**, after the current pilot, with a shared
original RH maker-buy candidate stream and independent ledgers for A and B.
Use the same four assets and $100/$250/$500/$1,000 budgets, Standard RH
fees and verified asset-specific HL fees, lot/tick/minimum checks, prefunded
wallets, and the current pilot's source/receipt, queue, hedge, and
cancellation rules. For B, after the first full HL hedge, place one
post-only RH sell at the then-current valid best ask for no more than the
actual RH long quantity. Freeze that initial price rule, a five-second
maximum rest, cancel/requote only on best-ask change or invalid hedge depth,
and no favorable later-price choice. Count only public **buy-aggressor**
flow at/through the standing RH ask after activation, depleting same-price
visible queue ahead; report touch, trade-through, possible partial/full
flow, and ambiguity. A print is possible flow, never a private fill.

For each attributed RH maker-sell increment, initiate the equal-quantity
HL taker buy only after its local flow-confirmation receipt and a frozen
150 ms HL network/processing allowance; use the first eligible advanced
HL book and the same ten-basis-point directional limit and three-second
intent timeout as the entry hedge. Enforce venue minimums on every
increment; below-minimum dust stays open/unknown rather than being upsized.
At **ten seconds from the first full entry hedge**, cancel any remaining
RH maker sell and request RH taker sell plus HL taker buy for all remaining
matched inventory. Fills while cancellation is pending are obligations;
if they race with emergency taker exits, reconcile actual RH and HL
inventory before scoring. The request deadline is not a guaranteed flat
time. Record funding boundaries and unresolved positions separately.

A $1,000 **order budget does not imply a $1,000 first maker fill**. Public
flow can attribute a tiny RH partial below HL's $10 minimum or common lot;
the current frozen policy cancels the remainder after the first partial and
may leave unhedgeable dust. A distinct later **inventory-netting** variant
could accumulate successive RH partial increments until a valid HL hedge
lot is available, with at most **$20 gross unhedged RH value and one second
of unhedged time** from the first partial, and cancel/flatten at either
cap. It must accrue unhedged price exposure, reserve capital, count
never-hedged dust and losses, and retain any failed flatten as inventory.
It cannot treat the full original $1,000 quote as filled, retrospectively
net favorable fills, or exclude small failed partials. This variant is
separate from B's maker-exit comparison and needs its own frozen ledger and
prospective run; it is not a change to the current pilot.

Predeclare the comparison as all-original-candidate complete net after
four actual modeled fee legs, reserve and capital **with separate cash and
risk-charge columns**; include no-flow, one-leg, partial, timeout, and
terminal-inventory cases. Match A/B on candidate IDs and report paired
completed differences only for candidates with both complete outcomes;
report all-candidate coverage and censor fractions alongside them. The
specific falsifier is that B's additional RH spread capture after possible
fills fails to offset its second quote's no-fill rate, hedge adverse move,
late cancellation fills, and deadline flatten cost. A successful short
pilot would justify a new multi-day frozen run, not production promotion.

The existing cross-exchange maker design already treats quote price,
conditional flow, basis liability, and inventory jointly
([research review](sota-maker-hedging.md)); [Hummingbot's documented
cross-exchange market-making rule](https://hummingbot.org/strategies/v1-strategies/cross-exchange-market-making/)
is an operational reference for hedging actual maker fills, but its spot
connector workflow does not establish RH/HL perp fill probabilities or
completed cash returns.
