# Draft: small RH maker bids with contingent HL hedges

This is one authorized read-only prospective paper experiment, not an
order-placement policy. The primary question is whether $100–$1,000 passive
**bids** on the RH Lighter perp book can receive enough non-adverse flow to
pay for an HL short hedge and a complete ten-second unwind. The $1,000
branch is the primary benchmark; smaller branches test size effects. The [strategy review](sota-strategy-review.md)
found no completed RH path in the older small-size replay; its Core-only
losses do not answer this RH question. This pilot compares one adaptive
HL-derived bid with joining RH's fixed best bid on the **same** subsequent
market events. It does not fit a large control model, assume private fills,
or change the production monitor.

## Frozen universe, prices, and timeline

Use RH-domain and HL **perpetuals**, not Robinhood Stock Token swaps.
Preselect BTC, ETH, NVDA, and XAG. Confirm matching base units, contract
payout, funding schedule, and independent margin before a route is enabled;
do not pool crypto and equity/metal results. RH USDG and HL USDC are
treated at parity only for the quote screen: no executable conversion,
transfer path, or collateral fungibility is inferred. Account for separate
prefunded wallets and show the conversion omission in every result.

Freeze four maximum RH order budgets **$100, $250, $500, $1,000**.
Do not add $25/$50 without new venue-minimum and fill evidence.
At a decision, floor the order quantity to a lot valid on **both** venues;
the resulting actual notional must meet both venue minimums and remain
within the budget. Invalid small sizes are recorded as `no_valid_order`,
never upsized. Existing `markets.json` does **not** contain the RH price
tick/precision needed for tradable quotes. Before launch, fetch and freeze
public RH `orderBookDetails` price grid, lot, min/max quantity and notional,
and verify the corresponding HL price/size constraints for each contract.
Reject a quote that fails round-trip grid validation. Do not infer an RH
tick from displayed decimal places.

Capture 30 minutes for calibration followed by a **frozen 20-minute
holdout**. If coverage fails, stop and report infeasibility rather than
loosening warmup or fitting outcomes. Use the validated contiguous RH full
book and trade loader and the faster HL book path in a new bounded capture;
require source sequence/generation continuity, age ≤2 s, paired source and
receipt skew ≤1 s, and monotone timestamps. The full-book loader's observed
~0.54 s cadence is a feasibility observation, not a guaranteed fill or
hedge latency. A gap, reconnect, clock anomaly, crossed book, missing trade
side, or missing depth censors affected quote paths. Cap compressed raw events at 384 MB and derived state at 128 MB
(total 512 MB); hitting the cap stops the
study and records truncation. Use receipt order for decisions. Exchange
source time can reject stale evidence but cannot make information available
before local receipt.
Source clocks are not assumed synchronized with the collector or with each
other. Require source time no later than receipt time, and require **both**
source and receipt at or after the simulated activation, hedge, or exit due
time. Do not shift source timestamps by an estimated clock offset. Local
receipt and source gaps cannot identify one-way network delay or actual
exchange execution order; classify an ambiguous hedge or cancellation
ordering as unknown.

Each `(asset, size, policy, tier)` branch starts with 2× budget in its
RH USDG wallet and 2× budget in its HL USDC wallet. Reserve 100% of actual
entry notional on each venue without leverage; carry cash fees and losses
across episodes and never replenish from another branch or raise quantity
above budget. Charge capital on reserved actual notional and elapsed time.
Combined dollar net is conditional on the stated USDG/USDC parity and
excludes executable conversion cost. Each size and policy is an
**independent counterfactual ledger**. They can
refer to the same public flow; their fills and P&L must not be added as if
simultaneously executable. At most one RH bid per asset/size/policy is live
or pending cancellation/replacement, with prefunded RH and HL capacity and
one matched pair per branch. Preserve every quote decision, abstention,
rest interval, fill signal, hedge, exit, and unresolved position.
Cap open partial-fill lots at 64 per branch and partial events at 64 per
quote; on overflow stop new quotes, retain all existing exposure, and mark
the study truncated rather than dropping obligations.

## One simple causal price rule

For an RH maker buy of `q`, followed by an HL taker short, define the
ten-second **closing liability per base unit** at a valid paired quote as
`C(t,q) = [HL buyback ask walk(q) − RH sell bid walk(q)] / q`.
On calibration anchors spaced at least 10 s apart, take the **first time-eligible**
advanced paired books at 10–16 s and calculate `ΔC = C_future − C_anchor`
at the anchor's original `q`. Missing, shallow, stale, or generation-broken
outcomes are censored, not imputed. The first time-eligible shallow pair
censors the anchor immediately; a later deeper pair cannot rescue it. For each asset/size, freeze the median
of matured `ΔC` after at least 30 matched anchors spanning at least 10
minutes, with at least 50% of eligible calibration anchors resolving under
the fixed 10–16 s rule. Only outcomes fully observed before the
calibration cutoff enter either fitted statistic. No holdout observation trains its own or any later holdout quote;
the fitted median stays fixed throughout the holdout. If that threshold is
unmet, the adaptive branch makes no quote and reports `model_unready`.
This unconditioned location forecast is deliberately simple and may fail
on maker-selected adverse flow; score its conditional error on possible
fills as well as all valid anchors.

Estimate one short-horizon **conditional adverse hedge move** separately.
During calibration, at most once per second for each asset/size and at each
deduplicated RH seller-aggressor trade received
at/through the then-current RH best bid, freeze the first valid current
HL size-walked sell bid `H₀(q)`. Set a simulated HL hedge due time at that
**local trade receipt +150 ms** (100 ms network plus 50 ms HL processing).
Take only the first same-generation HL book with both source and receipt
at/after due and no later than one second after the trade receipt. The
first time-eligible shallow or invalid book censors this flow anchor
immediately; later depth cannot rescue it. Walk
the same `q` to obtain `H₁(q)`; missing, shallow, or source-invalid cases
are censored and counted. **Include** observed moves beyond the 10 bp
execution limit in this training distribution and flag them as would-reject:
dropping them would bias the adverse-move estimate upward in price. For resolved events,
`d = 10,000 × [H₀(q) − H₁(q)] / H₀(q)` is adverse when positive. Freeze
`A₇₅(q) = max(0, empirical 75th percentile of d)` separately by asset
and size. Require at least **20 resolved flow events spanning 10 minutes**
and at least **50% resolution** among eligible RH sell-flow confirmations
in the 30-minute calibration window. Otherwise the adaptive hedge model
is `model_unready`; no conditional quote is forced. Event count, span,
coverage, and the full training distribution are reported, since a 20-row
upper quantile is uncertain. This samples a public-flow condition, **not**
our actual future private fills.

At decision time, `Ĉ_close = C_now(q) + median_train(ΔC)` and
`Ĥ_sell = H₀_now(q) × [1 − A₇₅(q)/10,000]`. For each RH bid tick `p`, compute

`forecast_net(p) = q × [Ĥ_sell − p − Ĉ_close] − estimated four-leg fees − 5 bp reserve − capital allowance`.

Choose the **most aggressive valid, noncrossing RH bid tick** with
`forecast_net(p) ≥ $0.10`. Fees and reserve depend on the actual candidate
price/notionals, so evaluate ticks rather than treating costs as a constant
algebraic subtraction. The `A₇₅` forecast measures the first postdue HL
book after a public RH sell-flow event; it does **not** guarantee the HL
price when a resting maker order eventually fills. The 10 bp HL IOC
execution cap stays **separate and frozen** in the later fill simulation.
It is a risk limit, not the quote's expected hedge price. If the quote
rests while HL moves, the reprice/cancel race and any adverse later fill
remain in the outcome.

Estimate each fee on its own expected notional, using frozen Standard
metadata. On RH Standard, maker entry and taker exit are 0 bp; native HL
taker entry and exit are 4.5 bp each, while a **verified** xyz 0.9 bp
schedule implies 1.8 bp across its two HL fills. Do not apply xyz fees
to BTC/ETH. The reserve is 5 bp on the larger expected entry notional;
capital uses the same 5% annual rate and ten-second matched hold. Funding
crossing a settlement boundary is a separate unresolved cash item. The
future closing basis is explicitly present; it is **never set to zero**.
This is a quote-screen forecast, not a guaranteed execution price.

The adaptive bid may improve inside the spread or rest below the best bid.
If no valid tick satisfies the venue minimum, risk/capital limit, or
`$0.10` modeled net threshold, abstain. A **plain-persistence diagnostic**
uses `Ĥ_sell = H₀_now(q)` with the *same* closing-basis forecast, fees,
reserve, size, grid, lifecycle, and `$0.10` threshold. It isolates whether
the conditional adverse-move estimate adds value. The **fixed-best control** joins
the current RH best bid at the same `q` and timing whenever the venue and
hedge-depth checks pass; it does not use the forecast threshold. Thus the
comparison measures both missed flow and avoidance of uneconomic fixed
best bids. Report quote competitiveness (inside/join/behind), no-flow,
possible partial/full flow, and all-cost outcomes for both branches.

## Quote life, flow, and the hedge

Primary RH Standard assumptions are 0/0 bp maker/taker fees, 200 ms
maker/cancel processing, and 300 ms taker processing, **plus a frozen
100 ms client/network allowance**. Model activation at decision+300 ms
and cancellation effectiveness at cancel-request+300 ms; no quote or
replacement becomes active instantly. A quote rests for at most 5 s after
activation. Re-evaluate on each valid synchronized update. The adaptive and
persistence quotes request cancel if current prospective net falls below
$0.10, hedge capacity disappears, books become invalid, or desired price
changes by ≥1 tick. Fixed-best never cancels on a forecast net threshold;
it cancels only on invalid books/depth, best-bid change, rest expiry, or
fill. Request cancel of the unfilled RH remainder immediately after the
first attributed maker fill, while treating late fills before cancellation
effectiveness as new obligations.
Replacement is placed only after cancellation becomes effective and then
waits its own 300 ms. Count sell flow and possible fills **while cancel is
pending**. If the cancel interval lacks valid event coverage, classify
fill/cancel order as ambiguous; do not assert no fill.

At hypothetical activation, the source **and** receipt timestamps of the
queue book must be at or after activation. Freeze only the visible quantity
at our own bid price as the initial queue ahead. Better-priced displayed
demand has priority, but an observed sell print at or below our bid already
implies that the better-priced levels were traversed; do not subtract their
initial volume a second time. Count only deduplicated RH
seller-aggressor trades at/through the standing bid with both source and
receipt at or after activation as eligible flow. Qualified flow first
depletes the frozen same-price queue ahead; attribute
`min(excess qualified flow, remaining order)` at **our quoted bid price**,
not at a printed better price. A level disappearing without a matching
trade is never credited as our fill, and cancels ahead are not credited.
Separate same-price touches from strict trade-through volume and counts.
Delayed prints whose source predates activation are excluded even if
received afterward; if public timing leaves fill versus cancellation
ordering ambiguous, censor that path. Hidden liquidity, unknown private
acknowledgment and queue position, trade-side classification, and market
reaction to our order make even the primary signal a **counterfactual**,
not a private fill. Any sequence gap censors the queue until rebuilt.

For every attributed maker increment, the earliest hedge decision is the
**local receipt of its trade-flow confirmation**. Submit an HL IOC sell
for exactly that increment after 100 ms network + 50 ms HL processing;
use the first valid new HL book with both source and receipt at/after due,
matching generation, original-size depth, and a frozen 10 bp directional
limit from the HL executable bid **at the maker-flow confirmation receipt**,
not the earlier quote-post time. The actual IOC-style
lot-rounded partial/zero result, fee, and one-leg exposure are recorded.
Do not hedge a hypothetical full order when only a partial maker quantity
has possible flow. If an increment is below either venue lot or minimum
notional, retain it as unresolved dust; do not upsize it or claim a
completed hedge/close. If HL is partial, rejected, or unobserved by its normal
three-second timeout, request taker exits for **all** actual RH/HL
inventory and retain any unmatched or unflattened balance. A later maker
fill during cancellation or emergency flatten creates a new obligation;
it is never silently discarded. Report maker-confirmation-to-hedge due,
due-to-book, and actual quote exposure separately.

The episode ten-second clock starts at the **first fully hedged pair**,
with later fills and increments tracked as obligations in that same
episode. Once an increment is fully hedged, request both taker exits when an
executable all-cost mark reaches $0.10, otherwise **no later than 10 s
after the full pair is established**. RH exit uses Standard taker 300 ms
processing +100 ms network; HL uses 50 ms+100 ms. Fill against the first
eligible advanced books at original remaining quantities, accounting for
partial exits and retries under a three-second intent timeout. Actual
flatten time may exceed the request deadline; report that excess. Funding
crossings, unresolved fills, and terminal RH/HL inventory remain open or
unknown with an explicit priced mark, **not** zero P&L. Do not credit a
later opposite-side passive trade as an exit in this primary version.

## Reports, controls, and decision rule

RH Standard is the **primary** policy. A separate, fully rerun RH Premium
stress uses its own published 1.2/3.5 bp maker/taker schedule and faster
processing; it must reprocess quote placement, cancel races, flow, hedge
and exit, not subtract fees from Standard fills. No parameter sweep or
reinforcement learning is planned before observing RH coverage. HL fees
are frozen by actual asset metadata. Keep the no-trade branch explicit.

By asset, size, policy, and five-minute block, report the original count of
valid decision opportunities, invalid-size/model-unready/capital
abstentions, active quote seconds, cancellation races, no-flow, possible
partial/full maker flow, queue-censored paths, hedge zero/partial/full,
matched-pair exits, failed hedges, terminal gross/delta inventory, one-leg
seconds, and completed cash P&L after **all** actual modeled fees, reserve,
capital, funding and priced unwinds. Separate realized closed cash,
unrealized marked inventory, and unknown outcomes. Show net >0, net ≥$0.10,
net bp, dollars per hour, and capital held; never annualize sparse cents
without exposure and coverage. Match adaptive and fixed-best decisions on
the same event IDs, while recognizing that sizes and quote policies share
flow and are correlated. Show retained-row coverage and all-run cumulative
counts if storage truncates. A positive opening spread or queue touch is
not a completed win.
Rank the **$1,000 branch first** on complete all-candidate outcomes; use
$100/$250/$500 as predeclared size sensitivities. Compare conditional
adverse-move pricing against plain persistence on the same cost basis,
then against fixed-best flow/coverage. Do not tune quote thresholds or
add another horizon on these holdout results.

Treat this 20-minute holdout as feasibility and descriptive evidence only.
Even favorable outcomes do not promote a production policy. Sufficient
complete paths, consistent all-candidate results after missed flow, and
small terminal uncertainty can justify a newly frozen multi-day prospective
run. Otherwise report feasibility limits and stop. Do not tune the pilot
thresholds on this holdout. Private acknowledgements, actual queue position, fills, cancel
confirmations, fees, and balances remain unobservable in this public-data
pilot; no real trading is authorized.
