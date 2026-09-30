# Dated carry: independent method and risk review

30 September 2026. Review following the user's authorization to proceed.
This neither launches collection nor authorizes orders, private account
requests or a later lifecycle study. Existing ten-second policies and capital
history remain separate. Only this review file was written.

## Decision

Collecting paired books is meaningful even with the all-cost gate blocked:
snapshots measure entry premium, displayed capacity and a declared cost
scenario, not completed carry return. Freeze this distinction: unknown costs
never become zero; scenario-positive rows are never all-cost-positive decisions.

Structural/resource failures stop preflight. Cost, collateral and settlement
uncertainty permit conditional arithmetic with missing fields but block
all-cost admission. No automatic successor follows.

## Fixed scope and denominator

Use BTC/USDC spot and the nearest listed BTC linear USDC dated future with
7--30 days remaining at activation. Fix its exact instrument identity, expiry,
units and selection evidence before quotes. If unavailable, retain the failed
stage; do not choose another asset, maturity, inverse future or perpetual.

The 72-hour stage has slots `j=0..863`, due at `T0+300*j` seconds, and endpoint
`T0+259200` seconds. There are 864 original pairs, at most 1,728 scheduled
book observations and 3,456 size rows. Budgets are 100/250/500/1000 dollars;
only 1000 dollars is primary. The six decision slots are
`0,144,288,432,576,720`. Define whether "two days" means calendar UTC days or
fixed 24-hour study blocks before freezing; never change that interpretation
after seeing headroom. The 80% coverage gate requires at least 692 valid rows
per 864-row size cohort, without pooling sizes.

For budget `B`, use the proposal's original quantity:

`q = floor(B / max(best_spot_ask,best_future_bid) / common_lot)*common_lot`.

Derive the common lot from verified native BTC increments. Walk the spot asks
and future bids at exactly q. Insufficient displayed depth is a terminal null
for that size/slot, not permission to resize or use a later book. Validate
prices, quantity, minima and any known bounds. Reject either entry walk above
B without resizing. Prefund entry fees separately; further margin buffers
remain unknown. The future's quoted notional cannot purchase spot.

## Three distinct economic fields

Let `S` be the total sampled spot ask walk at q and `F` the total sampled
future bid walk at q, in conditional USDC comparison units. `F` is an entry
P&L reference. The observed entry premium is `G=F-S`; it is not realized profit.

Freeze one entry-notional cost proxy, with separate 0%, 5% and 10% annual
capital columns and 5% primary. Let E be the pinned expiry, t the scheduled
slot time, `Y=365*86400` seconds, and h=3600 seconds the declared spot
liquidation allowance after expiry. Allocate `A=2*B+entry_fees`, including
idle cash and separately prefunded fees. This is not a margin guarantee.

```text
entry_fees = spot_buy_rate*S + future_entry_rate*F
proxy_fees = entry_fees + spot_exit_rate*S + delivery_rate*F
proxy_capital(r) = A*r*(E+h-t)/Y
proxy_stress = 0.0005*max(S,F)
entry_notional_proxy_headroom(r) = G - proxy_fees
                                  - proxy_capital(r) - proxy_stress
```

Exit and delivery fee bases are entry proxies, not eventual notionals. The
one-hour allowance does not prove liquidation within an hour. A establishes
neither daily-debit funding nor extra collateral buffers; disclose omissions.

The official [fee notice](https://insights.deribit.com/exchange-updates/new-fee-schedule-on-deribit/)
is effective 1 August 2026. Root's live instrument check corroborates spot
taker 5 bp and future taker 3.5 bp. Freeze both; require configuration equality
and expiry equality to metadata. Public rates are not account discounts.
Future spot exit 5 bp and delivery 2.5 bp remain proxies (16 bp total only
when S=F). Resolve the weekly exemption before using zero linear delivery.
[Fee schedule](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).

`fully_costed_headroom` remains null unless a reviewed calculation resolves
required fees/bases or defensible allowances, spot/index mismatch, conversion,
collateral, funding budget, margin and terminal liquidation. Store missing
reasons. Never substitute G or a fee sensitivity. These formulas are scenarios,
not return bounds, expected returns, private fills or account eligibility.

## Why the all-cost field is unresolved

Linear futures have cash USDC settlement against an index TWAP, BTC order
amounts and daily 08:00 UTC settlement. The BTC settlement index assumes
USD/USDC parity; some collateral valuations use the actual exchange rate.
Spot sale therefore need not equal settlement index.
[Linear futures specification](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures).

For a completed matched long-spot/short-future lot, the identity is:

`net = F-S + spot_sale(q)-q*settlement_index - actual fees - other costs`.

Daily futures cash settlement must reconcile to terminal futures P&L exactly
once. Margin release returns capital; it is not income. A premature risk exit
uses the actual modeled futures buyback and spot sale instead of expiry
settlement. Neither retained spot nor a favorable index can be labeled a
completed close. Five-minute endpoint books cannot prove margin survival
between observations or finance future variation debits from spot appreciation.

Official spot documentation routes BTC_USDC to Coinbase Exchange, with
account-dependent availability and full purchase funding. Public book access
does not establish account permission, fee tier or custody/conversion costs.
[Spot specification](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments).

## Preflight classification

**Hard stop before quote collection:** no qualifying fixed future/spot route;
contradictory or unresolvable linear/base/quote/settlement identity; unavailable
or uninterpretable public book endpoint/timestamp; inability to establish q
and validate native grids/minima; unsafe schema/size handling; failed source,
instrument or schedule freeze; or inability to retain original denominators
and terminal evidence within the accepted allocation. Never repair these by
substitution, wider clocks, smaller size or a new activation after quotes.

**Conditional-only, all-cost gate blocked:** unknown effective account fees or
delivery exemption; future exit/delivery fee bases; unmeasured spot/index or
stablecoin residual; unknown collateral charges, required extra buffers,
daily-debit funding or account access; and no defensible terminal-liquidation
design. Quote collection is permitted only with these flags frozen and clearly
disclosed before launch. A known order/funding-budget violation blocks that
candidate even if its arithmetic proxy can be shown descriptively.

## Timing, continuity and cancellation

Freeze public endpoints, total requests, roster checks, timeouts and response/
depth limits. Refreshes confirm or invalidate the fixed route; never rerank it.
Verify timestamp meanings and UTC/monotonic mapping. Require nonfuture stamps,
both ages <=2 seconds, source skew <=250 ms and callback lateness <=250 ms.
Retain receipt skew and request intervals too.

Only books received by the scheduled decision may contribute to that slot.
HTTP pulls must therefore be planned before due with bounded timeouts; a
response received after due cannot retroactively fill that decision. Concurrent
requests are not atomic executions. A missed callback or invalid quote retains
its null status, with no favorable replacement timestamp or retry slot.

Polling establishes snapshots, not continuous validity or order survival.
Cancellation/routing changes prove no hypothetical fill. Suspension, malformed
response, clock or roster faults retain affected gaps. Later valid snapshots
serve only later slots. Never restart/reactivate to repair history or reset T0.
Freeze any bounded continuation after isolated request failures independently
of economics.

No orders or inventory exist here. User cancellation or technical/resource
stop retains collected rows and remaining uncollected slots, without claiming
completion or restarting. Routed spot's partial public tape supplies no maker
fill evidence.
[Routed-spot API notice](https://support.deribit.com/hc/en-us/articles/38375233938205-18-August-2026).

## Endpoint and resources

No interim premium/headroom rankings, admission counts, positive-slot messages
or outcome-guided changes. Technical clock, request and byte health may be
monitored. Only after the fixed endpoint and complete publication/audit should
the readout present G, proxy distributions, original coverage and the six
primary decision rows. Keep unavailable all-cost counts null, with a blocked
gate and reasons; do not relabel them zero profit or negative proven returns.
Passing the proxy alone authorizes no lifecycle stage or strategy promotion.

The proposed accepted ceiling is 16 MiB (16,777,216 bytes), with 1 MiB source/
control, 2 MiB metadata, 8 MiB sampled responses, 2 MiB derived and 3 MiB audit/
terminal/logs. Confirm actual allocation acceptance before network. Enforce
aggregate and category limits before every write, reserve failure/terminal
publication space, include final compressed trailers and measure decoded/line
limits too. Preserve full accepted sampled responses and their hashes; clipping
depth must be explicit, never synthetic capacity. Keep sources, instrument
roster and all prior allocations retained. A cap failure preserves failure
evidence and missing slots rather than raising a cap or overwriting output.

The 72-hour stage cannot settle its 7--30-day contract. A lifecycle study
needs separate policy, margin, settlement, cost, holdout and storage decisions.
Conditional collection does not waive the all-cost gate.
