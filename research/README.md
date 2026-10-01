# Research map

## Current work

The user redirected the primary agent to active idea research on 1 October,
with routine monitoring delegated to `gpt-6-luna`. The
[active idea memo](active-idea-research.md) contains a new absolute-funding
screen and prioritizes same-venue ETH spot/perpetual carry, collateral design,
and a later Core/RH funding comparison. No profitable strategy is established.

The [broader carry proposal](broader-carry-research-proposal.md) led to a
BTC dated-futures feasibility study. Its original run was interrupted by a
host reboot and is preserved without resumption or economic evaluation.
The explicitly authorized [fresh v2 run](dated-carry-relaunch-v2.md) is
collecting from 1 October 00:30 UTC to 4 October 00:30 UTC within the same
16 MiB budget. Its frozen samples remain unopened for economic analysis.
Actual all-cost feasibility remains unresolved.

[Active experiment loop](active-experiment-loop.md) records the mandate,
prospective primary policy, success threshold, and next decision. The current
RH maker-entry/passive-exit study restarted at 02:52 UTC on 30 September
after an interrupted capture. Its fresh 50-minute window completed at 03:42:58 UTC;
strict and separately frozen corrected replays completed at 03:58 UTC.
The [holdout readout](../reports/rh-passive-exit-v1-restart/readout.md) found
29 known complete portfolios, all negative, and 99 unknown. The primary
XAG branch had no completed trading cycle. Current process IDs and
commands are in [live operations](live-operations.md); the twenty-minute
production readouts are in the [review journal](review-loop.md).

The completed offline diagnostic tested delayed taker entry and fixed
10/30/60/300-second exits on that same stopped archive, across all 7,200
candidates and 28,800 outcomes. The [method](delayed-taker-fixed-quantity-plan.md)
keeps funding-inclusive returns unknown and distinguishes quote feasibility
from fills. Two failed resource attempts are preserved. The separately
reviewed cache-disabled revision completed at 06:52 UTC: all 26,395 complete
quotes were negative after fees alone. The [audited readout](../reports/delayed-taker-quotes/0252Z-v3-analysis.md)
retains 2,405 incomplete outcomes and all funding uncertainty. Even forgiving
all trading fees does not clear the declared stress allowance at these quotes.

The [spread-regime prerequisite watch](rh-spread-regime-sentinel-plan.md)
failed its storage admission check after fresh metadata preparation, before
opening any quote connection. Its [failure readout](../reports/rh-spread-regime-sentinel/20260930T0755Z/readout.md)
preserves all 1,680 uncollected rows; no economics were computed. The original
stage will not be retried. The separately allocated compact study completed
its fixed 08:12:57–08:32:57 UTC window and passed an independent output audit.
Its [result](../reports/rh-spread-regime-sentinel/20260930T0812Z-compact-analysis.md)
has 1,340 valid and 340 stale size rows; all 84 asset/size medians are negative,
and none of 21 assets passes the $1,000 prerequisite. Three isolated positive
optimistic budgets do not rescue the failed gate. No hedge-cost or execution
study follows automatically; the sampled quotes establish no fills or P&L.

## What the evidence currently supports

The [Core/RH delayed taker diagnostic](../reports/core-rh-delayed-taker/20260930T1000Z-analysis.md)
completed at 10:07 UTC and passed independent audit: all 842 complete quotes
were gross-negative with zero public taker fees; 166 candidates remain
censored. No predictor or strategy promotion follows.

- [Reverse static route bound](../reports/passive-rare-spread-reverse-bound/0252Z-v1/REPORT.md):
  all 47,624 evaluated HL-maker/RH-taker upper bounds are nonpositive after
  target and stress; 376 rows remain unadjudicated. This covers fixed prices
  and inherited quantities, excluding funding and dynamic cycles.
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
- [Optimistic hedge-cost bound](../reports/passive-universe-hedge-budget/0310Z-input-v1/readout.md):
  deleting all fees and hedge spread still leaves every eligible asset
  median negative. One favorable LIT round is retained and disclosed;
  the bound concerns unchanged-book arithmetic, not future price paths.
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

## Latest completed diagnostics

- [Exploratory ACK readout](../reports/rh-passive-ack-exploratory/readout.md): base 12 conditional negative complete portfolios, plus200 none complete; other totals unknown.
- [Rejected-target public reach](../reports/rejected-target-public-reach/REPORT.md): no eligible observed print reached any of 150 reconstructed strict targets within its fixed window; public completeness unproven.
- [Rare-spread admission design](passive-rare-spread-admission-design.md): evidence prerequisite for a different entry gate; no capture launched.
- [Fixed-anchor RH/HL feasibility](../reports/passive-rare-spread/0252Z-fixed-1s-v1/readout.md): zero positives among 47,624 valid observations on the full 48,000-row grid; tested gate stopped.
- [ACK halt review](passive-ack-halt-review.md): source-freshness expiry and late anchor revisions retain unknown execution; first-evidence retention issue documented.
- [Single-settlement rate review](../reports/funding-carry/core-rh-single-settlement-review.md): favorable direction and payment-subset arithmetic on 192 existing Core/RH observations yields at most 0.41 bp; actual funding cashflow and combined trading P&L remain unverified.
- [Liquidation flow review](rh-liquidation-flow-review.md): all 65 old liquidation rows were subscription history predating capture; zero live liquidation updates add flow to the tested windows. Public order eligibility remains unresolved.
