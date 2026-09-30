# Broader carry research proposal

Prepared 30 September 2026 in response to the request for longer holding
periods and a different return source. This is a proposal for public-data
research and paper execution. The existing ten-second monitor and its
twenty-minute reviews continue with their current settings and capital history.

## Recommendation

Start with a bounded feasibility study of **fully funded spot plus a short
dated future**, starting with BTC and one maturity seven to thirty days away.
The return being investigated is the futures premium over the acquired spot
asset, after carrying and closing the position. A defined settlement date
provides a concrete terminal reference to evaluate.

Keep **funded spot plus a short perpetual** as the second candidate, and
cross-perpetual funding plus basis carry as the third. Their funding payments
vary. The existing cross-perpetual sample does not cover its costs. BTC,
ETH and SOL are a possible later comparison universe; ETH is also the
first candidate for replicating a successful BTC dated-futures study. Defer
inventory-based market making until its public fill evidence and spread
economics support a separate design.

The first decision should take roughly **72 hours of scheduled observations
after implementation and preflight**. It would answer whether any route
merits a full lifecycle study. Demonstrating repeatable profit would take
multiple complete expiry or holding-period cohorts over subsequent weeks.
There is currently no profitable strategy to promote.

## Candidate comparison

| Priority | Mechanism and proposed holding period | Source of potential return | Main obstacle | Next decision |
| --- | --- | --- | --- | --- |
| 1 | Funded spot and short dated future, 7–30 days | Premium paid for futures exposure, realized through settlement and spot sale | Fees, capital, margin calls, and spot sale versus settlement-index mismatch | Does executable premium leave a material margin after every cost? |
| 2 | Funded spot and short perpetual, 1–7 days | Short receives positive funding while spot offsets price exposure | Variable funding, spot fees and ongoing basis risk | Does absolute funding offer a better funded return than the two-perpetual route? |
| 3 | Long one perpetual and short another, 24 hours–7 days | Accumulated funding differential plus any favorable basis change | Funding can reverse; closing basis and collateral remain costly | Does a prior-only funding estimate pay for a full cycle within the fixed maximum hold? |
| 4 | Inventory-based passive quoting, minutes–hours | Earn spreads and reduce repeated hedge turnover through offsetting customer flow | Unobserved queue position, adverse selection and residual inventory | Is there fresh evidence of enough compensated flow to justify an execution study? |

These are research priorities, not expected-return rankings. Neither increasing
the hold nor reducing turnover creates an edge by itself. Perpetual contracts
have no fixed maturity compelling convergence to spot.
[He et al., Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888).

## What the existing evidence contributes

The [completed research map](README.md) records consistently negative
short-hold diagnostics. They rule out promoting those tested policies; they
do not establish the returns of a different funded carry strategy.

The [settled-funding screen](../reports/funding-carry/REPORT.md) gives one
concrete starting point. Its selected SOL trade, short Hyperliquid and long
RH Lighter, earned 4.52 bp of rate difference over the held-out day. Its
four-fill fee scenario was 9 bp, before spreads and other costs. Under the
existing 5% annual capital charge on two fully reserved legs, capital alone
costs about 2.74 bp of one-leg notional per day. Holding those observed rates
constant gives about 189 hours to cover fees and 5 bp stress. That exceeds
the proposed seven-day maximum and is an extrapolation from only one day,
not a forecast. See the [carry assessment](strategy-carry-followup.md).

The [Core/RH single-settlement check](../reports/funding-carry/core-rh-single-settlement-review.md)
found at most 0.41 bp in one hour under favorable hindsight direction and
payment ownership. Zero public Standard trading fees do not establish
positive carry after capital, executable spread and conversion. A longer
rate history needs its own prior-only direction selection and full cashflows.

## First candidate and its accounting

Use Deribit's documented **linear USDC dated futures** as the initial
public-data venue candidate, with BTC/USDC spot. This is a
feasibility choice; instrument availability, effective fees, account routing
and margin treatment still need verification before a paper execution model.

Deribit's linear futures settle in USDC against a thirty-minute index TWAP.
BTC and ETH settlement indexes assume USD/USDC parity. Consequently,
cash settlement leaves a residual between the price actually obtained for
spot and the settlement index, including stablecoin valuation effects.
[Linear futures specifications](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures).

For equal base quantity `q`, a hold-to-expiry cashflow is:

```text
net = q × (futures entry sell price − spot entry buy price)
    + q × (actual spot exit sell price − futures settlement index)
    − trading and delivery fees
    − capital cost, conversion and replenishment costs
    − declared stress charge
```

Use quantity-specific executable prices, not midpoint or index entry prices.
Daily settlement cashflows must reconcile to the terminal futures result
without counting the same gain twice. If a risk exit occurs before expiry,
use the actual modeled futures buyback and spot sale, retaining the loss.
An expiry index cannot substitute for an unobserved spot sale.
The short future's entry notional is a P&L reference, not cash available to
buy spot. Margin release returns reserved capital; it is not trading profit.
Apply each fee to its prescribed execution or settlement notional.

Current documentation routes BTC/USDC and ETH/USDC spot through Coinbase
Exchange and applies routed-spot fees. It also distinguishes the instruments
available to different account types. Do not inherit the old assumption
that every Deribit spot fill is free.
[Spot specifications](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments).
The public fee page labels its tier table as upcoming; its effective date,
applicable product tier and delivery treatment are preflight requirements.
[Fee schedule](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).

Begin with taker-price feasibility. The official routed-spot API notice says
the public trade tape available through Deribit is partial, while order book
data remains available. That prevents treating this feed as complete maker
fill evidence. A shared API also does not make the spot and future fills
atomic.
[Routed-spot API changes](https://support.deribit.com/hc/en-us/articles/38375233938205-18-August-2026).

## Capital and return objective

Retain $1,000 per leg as primary, with $100, $250 and $500 as separately
reported size sensitivities. For the first comparison, fully fund the spot
purchase and reserve an additional dollar-for-dollar collateral budget for
the derivative. This is a conservative accounting benchmark, not a guarantee
against liquidation or an assertion of the venue's minimum margin requirement.
Do not count the spot holding as freely reusable derivative collateral.

Report net dollars, net basis points on one leg, and return on **all allocated
capital over elapsed calendar time**, including idle cash and required
buffers. Retain the current 5% annual capital assumption and a separate 5 bp
stress case; show 0% and 10% capital sensitivities without selecting the
successful one after seeing results. Price observed execution and conversion
costs explicitly instead of treating stress as their replacement.

For scale, a proposed $1,000 spot purchase plus $1,000 reserve incurs about
$1.92 of modeled capital cost over seven days. An **illustrative**, unverified
16 bp total trading/delivery fee scenario adds $1.60, and 5 bp stress adds
$0.50. The initial premium would therefore need to exceed **$4.02**, plus
spot/settlement mismatch and conversion, merely to break even. These are
cost arithmetic and a fee assumption, not a current quoted opportunity.

The broader study should optimize net return per capital-day with controlled
drawdown. The existing $0.10 per ten-second target remains in the existing
monitor. It is not the proposed carry strategy's entry or success criterion.

## Bounded first stage

### Contract and data preflight

Before collection, freeze one instrument-selection rule: take the nearest
listed BTC dated future with 7–30 days remaining at activation, or report
the route unavailable. Keep that exact expiry throughout the study, together
with BTC/USDC spot. Do not substitute an asset or expiry after seeing its
premium. Retain all four size diagnostics and every planned observation;
only $1,000 determines the primary admission gate.

For each budget `B`, set the original matched quantity to
`floor(B / max(spot_ask, future_bid) / common_lot) × common_lot`.
Validate both legs' grids and quantity/notional bounds. Hold that quantity
fixed for the candidate's cost calculation; do not resize at an adverse
exit. Derive the common lot from verified native base-unit increments.

Verify base units, common quantity increments, minimum/maximum orders,
settlement currency and index, effective fees, margin and daily cash-settlement
rules. Preserve source and receipt timestamps and quote freshness/skew rules.
If exact fees or a required rule remain unresolved, publish conditional
arithmetic with that limitation; it cannot pass an all-cost feasibility gate.

Before any later funding study, audit historical rate units and dollar
references for BTC/ETH/SOL on HL, Core and RH. Separate rates known at a
decision from later posted settlement rates. Each payment needs the signed
quantity actually held on that leg at settlement and the venue's own
reference price. HL uses its oracle; Lighter documents index-based payments.
[HL funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding),
[Lighter funding](https://docs.lighter.xyz/trading/funding).
RH applicability must be verified on its own domain. Existing inferred
units or estimated references remain labeled; they cannot become exact by
holding longer.

### Scheduled observations

Propose one fixed 72-hour window, sampling the two selected spot/future books
every five minutes: 864 scheduled pairs, at most 1,728 book observations.
Preserve the requested
depth and all missing/stale/invalid observations. Retain raw sampled responses,
metadata and provenance; do not archive the entire live stream. This sampling
can screen quoted capacity and premium persistence. It cannot establish
intraperiod margin safety, latency-sensitive fills or completed carry P&L.

Freeze UTC activation `T0` and a monotonic schedule before connection. Sample
at `T0 + 300j` seconds for `j = 0..863`; the six primary decision slots are
`j = 0, 144, 288, 432, 576, 720` (hours 0, 12, 24, 36, 48 and 60).
Only books received by the scheduled decision may be used. Proposed validity
requires each native book timestamp and receipt to be no more than two
seconds old, source time no later than receipt, paired source skew at most
250 ms and callback lateness at most 250 ms. Verify native timestamp meaning
before implementation. Missing or invalid decision quotes remain failures;
never move the decision to a later favorable quote.

No parallel funding collector is proposed in this stage. A later funding
proposal may enumerate a bounded historical pull of up to thirty days of
available settled rates, disclosing shorter listing histories. Its
calibration/validation split must be chronological, with direction chosen
from earlier observations only. Rates without matched basis, settlement
references and costs remain a preliminary rate screen.

### Decision at the fixed endpoint

Advance at most one mechanism to a separately specified lifecycle study only
if all apply:

1. Required identity, fee, unit and settlement checks are resolved; at least
   80% of its scheduled size-specific quote pairs are valid.
2. At the predeclared twice-daily decision times, a $1,000 route has positive
   conservative cost headroom on at least three occasions spanning at least
   two days. Report all scheduled decisions, including zero qualifying routes.
3. Headroom includes executable spread, effective fees, full allocated-capital
   cost, 5 bp stress, and explicit conversion/settlement-mismatch allowances.
   Charge capital and buffers for the **entire remaining time to the fixed
   expiry and the planned spot liquidation**, not just the 72-hour observation
   period. An unmeasured required allowance blocks this gate.
4. There is a feasible margin and terminal-liquidation design for the proposed
   hold. A rate screen or favorable expiry index alone does not satisfy it.

These are proposed admission rules, chosen for this study rather than
calibrated from a successful sample. Passing supports more research; it is
not a profitability result. Failure ends the stage with no automatic
repeat, fee-tier change, horizon extension or new asset search.

## What a later paper strategy must demonstrate

Before a lifecycle capture, freeze the policy, settlement and early-exit
rules, maximum hold, dollar inventory limits, collateral allocation, data-gap
response and terminal accounting. Use at most one position per underlying
in each independent portfolio. Different size, horizon and venue scenarios
must not spend the same simulated capital or be summed as one return.

For funding carry, select the direction and holding decision using only
information available before entry. Compare a simple prior-only funding
forecast with a fixed-direction control. Include funding reversals, basis
widening, failed second legs, forced unwinds and the cost of holding unused
collateral. For spot/perpetual carry, begin with funded long spot/short perp;
reverse carry requires separate verified borrowing economics.

For every mechanism, unresolved inventory or settlement remains an obligation.
Publish realized net separately from executable liquidation value. Dense
marks and margin observations are required for a later path-sensitive risk
test; the five-minute feasibility samples cannot certify that no liquidation
would occur between observations.

Use a frozen calibration period followed by **two untouched evaluation
blocks** with sufficient complete lifecycle coverage for the selected hold.
For dated futures, require multiple distinct expiry cohorts; for funding,
use nonoverlapping holding cohorts and keep correlated assets together in
uncertainty analysis. Choose block lengths and the minimum cohort count
before collecting the evaluation data. Close calibration positions before
evaluation and embargo overlapping outcome horizons at the boundary. A
sparse outcome remains inconclusive.

Proposed promotion requirements are positive total stressed net in each
evaluation block, combined profit factor at least 1.5 including all losses,
acceptable drawdown under a predeclared dollar budget, and no unresolved
execution or settlement obligations in the scored portfolio. Also require
the predeclared minimum independent-cohort coverage and a positive lower
95% uncertainty bound on mean excess return against a capital-matched
no-trade benchmark, using a dependence-aware method frozen before evaluation.
Apply the opportunity-cost hurdle once and disclose the benchmark cash-return
assumption. Apply these gates to the primary portfolio alone; correlated
size sensitivities cannot increase its sample count. Insufficient coverage
or an inconclusive uncertainty interval prevents promotion. Report dollars
and return on total allocated capital alongside uncertainty. A short-run
annualized yield is descriptive, not an income forecast. These requirements
supersede no existing threshold until a new policy is explicitly adopted.

## Storage and next action

The present shared diagnostic allowance has **257,096 bytes unallocated**;
it does not fund this new collection. Propose a separate **16 MiB ceiling**
for the entire first stage: sampled raw data, sources, metadata, derived
results, audit evidence and logs. Before launch, measure the collector's
output footprint and freeze category caps with a terminal-publication reserve.
Proposed sublimits are 1 MiB for source/control, 2 MiB for metadata, 8 MiB
for sampled responses, 2 MiB for derived results and 3 MiB for audit,
terminal records and logs. Their fit must be demonstrated before launch.
Exceeding a cap ends collection and preserves the failed denominator.

This would add 16,777,216 bytes to the current conservative 820,000,000-byte
reservation, for 836,777,216 bytes, while retaining all old allocations.
No allocation has been changed. A later multiweek lifecycle study needs its
own duration and storage plan; it is not included in this first-stage budget.

**Recommended next action:** implement and preflight the BTC dated-carry
feasibility stage, then run its single 72-hour window after its method and
16 MiB allocation are accepted. Deliver a full route/size table, cost
decomposition, coverage report and a clear stop-or-propose-next-stage decision.
This proposal has launched no collector, changed no production strategy,
and submitted no orders.
