# Research map

## Current work

[Active experiment loop](active-experiment-loop.md) records the mandate,
prospective primary policy, success threshold, and next decision. The current
RH maker-entry/passive-exit study restarted at 02:52 UTC on 30 September
after an interrupted capture. Its fresh 50-minute window ends about 03:42 UTC;
no holdout has yet been scored. Current process IDs and
commands are in [live operations](live-operations.md); the twenty-minute
production readouts are in the [review journal](review-loop.md).

## What the evidence currently supports

- [Unwind strategy decision](unwind-strategy-decision.md): the opening price
  difference is not locked profit for two perpetual positions. Four-fill
  costs and the closing basis must be included. Most observed losses were
  already present when the monitor requested the unwind.
- [Hedge venue comparison](passive-hedge-venue-followup.md): stopped, matched
  RH/HL/Core quotes show Core's lower fee hurdle, but assume both RH maker
  fills and do not establish realized profit.
- [Cost sensitivity](passive-cost-buffer-followup.md): separate actual
  modeled exchange fees from hypothetical rebalancing and the extra 5 bp
  stress. [Cost headroom chart](../reports/passive-hedge-venues/cost-headroom.svg).
- [Completed broad screen](../reports/passive-universe-screen/20260930T0310Z/readout.md):
  five rounds over 21 eligible markets produced 320 valid size observations;
  none cleared fees, the $0.10 target and the 5 bp stress. The 100 stale
  observations and failed first attempt remain visible. These are static
  quote margins, with no maker-fill or realized-profit claim.
- [Entry queue diagnostic](rh-entry-queue-followup.md): earlier Standard
  branches became unresolved quickly. Their shorter observation periods
  cannot be compared directly with Premium's later fills.
- [Public queue uncertainty](public-queue-uncertainty-followup.md): public
  prints cannot reveal the private queue position or acknowledgement of an
  order that was never submitted. Alternative timing models must remain
  explicit assumptions and account for all resulting losses.

No proposed replacement has yet demonstrated positive complete-cycle paper
returns across fresh confirmation windows. Quote screens, overlapping
counterfactual branches, and incomplete portfolios must not be summed into
one profit tally.

## Reproduction and prepared next tests

| Artifact | Purpose |
| --- | --- |
| [Frozen v1 method](rh-passive-exit-method.md) | Four exit policies, four sizes, two tiers, full lifecycle and matched entry cohorts |
| [Fresh metadata check](rh-passive-exit-market-check.md) | Contract units, grids, collateral, fees, processing delays and session |
| [Replay performance](rh-passive-exit-performance.md) | Shared event parsing and measured engineering limits |
| [Quote allowance variant](passive-exit-cost-policy.md) | Future selection-only 0/5 bp allowance; reported stress remains separate |
| [Three-venue capture](passive-three-venue-capture.md) | Prepared bounded RH/HL/Core data collection; not yet launched |
| [Universe screen](passive-universe-screen-method.md) | Prospective exploratory asset screen before a new full execution study |
| [Retirement correction](passive-retirement-correction.md) | Separate correction frozen during calibration; original v1 remains reproducible |
| [ACK scenario design](passive-ack-scenarios-design.md) | Explicit hypothetical timing model for future diagnostics; no private ACK evidence |

The [SOTA strategy review](sota-strategy-review.md) and
[carry follow-up](strategy-carry-followup.md) contain the broader literature
and mechanisms considered. All work uses public data and paper execution.
