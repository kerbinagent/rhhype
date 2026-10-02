# Current research decisions — 2 October 2026

## Objective and process correction

Find convincing closed paper profit over seconds to minutes using public data.
Directional one-venue trades and larger sizes are in scope: the user clarified
on 2 October that $100 was an example. Evaluate size against depth, costs and
required capital. No strategy currently meets the repeatability objective.

The main process failure has been allocating too much work to execution
variants before demonstrating a cost-adjusted predictive signal. Accounting
checks have caught real defects and should remain, but they cannot establish
an edge. Prior plans already called for forward samples and controls; the
improvement is enforcing those requirements before the expensive stage.

Specific lessons from retained evidence:

- The [short-horizon loss audit](../reports/short-horizon-loss-audit/REPORT.md)
  reconciled trade and wallet arithmetic while finding overwhelmingly negative
  economics. Healthy collectors and correct cashflows are measurement results.
- The [basis forecast diagnostic](../reports/basis-forecast-diagnostic/readout.md)
  improved forecast error without making its execution branch profitable.
  Score the forecast against the movement required to close the trade.
- The [cash-only maker exit replay](../reports/core-maker-cash-exit/readout.md)
  reproduced both prior traces exactly: the changed exit gate never fired.
  Check decision activation before implementing another full variant.
- The [ETH passive sample](../reports/core-spot-passive-eth-cash/readout.md)
  had no ordinary live spot trade updates and an unresolved cancellation.
  Measure channel suitability before interpreting a sparse execution test.
- The [three-window LIT result](../reports/single-venue-research/single-venue-executable-shock-readout.txt)
  relied on one favorable move entered by two alternative rules. The winning
  move also occurred on the reference venue. It is neither two replications
  nor evidence that a local liquidity shock caused the gain.
- The [residual profiles](../reports/single-venue-research/residual-profile-readout.txt)
  contained thousands of overlapping profiles but no positive group that
  persisted across both short windows. More rows did not provide more regimes.

## Decision register

“Parked” applies to the tested version and assumptions, not every possible
strategy in its family. “Inconclusive” is not a successful economic result.

| Mechanism | Current evidence and decision | Evidence that would justify the next stage |
| --- | --- | --- |
| Simple Core/RH spread entry and short hold | **Parked.** The [$100 primary test](../reports/core-rh-small-shortterm/readout.md) closed 11 paired trades with no winners and −$0.183554 cash; costs removed did not rescue it. Entry deteriorated in 10 of 11. | A prospective forecast of the closing executable gap exceeding measured entry and exit costs, with a same-time control and delayed entry. A large opening gap alone is insufficient. |
| Constant carry / maturity holding | **Outside current scope.** Historical funding work is retained in [active idea research](active-idea-research.md). The already frozen BTC study continues to its endpoint without interim economic inspection. | A user scope change would be needed to make this the active research objective. |
| Same-block atomic round trips | **Parked at tested routes and size.** [Base](../reports/base-atomic-cycle-slow-transport/readout.md) and [RH stock routes](../reports/rh-atomic-stock-cycle/readout.md) were negative before gas. [NVDA](../reports/rh-nvda-complete-input-cycles/readout.md) retained incomplete-input quotes as unknown. | A changed route, price discrepancy or fee structure that first clears an exact full-cycle quote including full input consumption and gas. |
| Passive spot entry with delayed hedge | **Parked pending observable flow and conditional value.** [LIT](../reports/core-spot-passive-cashentry/readout.md) had one partial close, −$0.013952; [ETH](../reports/core-spot-passive-eth-cash/readout.md) had no ordinary live trades and an unknown cancel. | Concurrent assets with sufficient live trade coverage; predicted profit conditional on an attributed passive fill, adverse selection and the hedge delay. More unfilled quotes alone do not qualify. |
| Local large-trade / depth shock fade | **Exploratory, no established edge.** A selected [LIT depth win](../reports/single-venue-research/depth-readout.txt) did not lead to a robust [three-window result](../reports/single-venue-research/single-venue-executable-shock-readout.txt). The [fixed control check](../reports/single-venue-research/shock-controls-readout.txt) found seven distinct events, two positive local quote returns and six measurable quote-minus-reference values, all negative. Only two ordinary controls matched; neither had complete reference coverage, so the controlled comparison is inconclusive. | More distinct events and usable controls under a separately frozen analysis, followed by untouched independent episodes. Demonstrate executable local recovery beyond common drift. Keep missing controls; do not loosen their rules after viewing returns. |
| Persistent cross-venue premium and smaller residual fade | **Parked for the observed ordinary windows.** [NEAR's premium](../reports/single-venue-research/broad-basis-dynamics-readout.txt) persisted. [Original relative gates](../reports/single-venue-research/single-venue-broad-relative-readout.txt) admitted nothing; [smaller residual profiles](../reports/single-venue-research/residual-profile-readout.txt) had no positive group in both windows. | Temporary residual movement with enough subsequent local executable recovery to cover costs, replicated in untouched blocks. A stable premium is not sufficient. |
| Delayed directional response to the other venue | **Parked for the tested ordinary sessions.** The [fixed diagnostic](../reports/single-venue-research/directional-response-readout.txt) selected 15 and 11 episodes. Local mean quote returns were −2.814244 and −3.939537 bp; the predefined cost-plausible subset was also negative in both windows. No group passed the replication criterion. Only 4/26 episodes had complete executable controls, leaving relative attribution limited. | A materially different, motivated mechanism or regime that predicts movement remaining after entry and costs. The current result does not justify threshold tuning or a direct replication. |
| Static top-of-book imbalance | **Parked at the tested 10-second horizon.** The [broad quote screen](../reports/single-venue-research/broad-queue-readout.txt) had 19 of 20 high-imbalance asset/venue means negative; the lone positive was +0.300454 bp on overlapping profiles. | A separately motivated forecast and cost budget. Any different horizon or dynamic-flow feature is a new hypothesis, not a reinterpretation of this result. |
| Higher-activity scheduled news regime | **Frozen, awaiting observation.** One ten-minute, ten-asset [capture protocol](../reports/experiment-storage/single-venue-news-v1.json) and separate [corrected analysis companion](../reports/experiment-storage/single-venue-news-ordinary-feed-fix-v1.json) are armed for 2 October 12:26–12:36 UTC. Original sources and helper remain intact. Both families and all arms will be reported. | First establish complete event coverage and usable signals. A favorable result warrants a separately frozen replication; this one event cannot establish durable profit. Incomplete data or zero entries remain inconclusive. |
| Inventory-reducing aggressive flow | **Parked: fixed gate failed.** Corrected [two-block result](../reports/single-venue-research/ordinary-feed-fix-v1/inventory-context-batch2-readout.txt) has 11/15 pairs. BTC/Core has only 4/2 pairs and negative absolute reducing quote means in both blocks. No group qualifies in both; RH/BTC also has explicit book-coverage failures. | A materially different, motivated hypothesis with adequate matched support and positive absolute value after costs. No caliper relaxation or execution study follows from these sparse comparisons. |
| Slowing flow with depth restoration | **Parked: measurement gate failed.** [Both blocks](../reports/single-venue-research/ordinary-feed-fix-v1/flow-recovery-batch2-readout.txt) contain zero persistent/unrecovered episodes; slow/recovered counts are 5/3. | Adequate observable support for both states under a separately motivated rule. No threshold tuning or economic replay follows this version. |
| Liquidation-label continuation | **Observable, insufficient support.** [Frozen preflight](../reports/single-venue-research/liquidation-delay-v1/readout.txt) witnesses one delayed different-order event among 9/2 complete episodes; stale evidence suppresses substantial later coverage. | Enough distinct observable episodes and comparable ordinary-flow controls before delayed absolute economics. One public-order witness establishes no common parent or trading edge. |
| Cross-asset return lag | **Parked: insufficient support.** [Unchanged availability audit](../reports/peer-research/20261002-0544/decision.txt): 0/0/1 BTC episodes, zero target/control pairs; no economics. | Separate lagged-OFI protocol. |

## Rules for the next research decision

1. Define one missing question, event, comparator, costs and failure denominator
   before calculation. Prior-inspected inputs remain exploratory. For local
   shocks, distinguish executable event-specific recovery from common drift.
2. Retain every tested asset/rule and missing outcome. Cluster repeated signals;
   adjacent chunks and correlated assets are not independent regimes. Alternative
   ledgers cannot be summed into a portfolio.
3. Require delayed absolute closed value after costs as well as conditional
   improvement. Extra 5 bp stress is a scenario, not a measured fee or fill cost.
4. Advance only when a concrete result changes the decision. Park a failed
   version; a new mechanism or justified regime needs a separately frozen test.

## Experiment implementation and operations

Reuse captures, replay and independent accounting across hypotheses. Preserve
frozen sources. Test concrete economic invariants, clock boundaries and observed
defects; avoid broad refactors or more wrappers for empty branches.

Report gate activation, data coverage, delayed execution, forecast quality,
closed cash and uncertainty separately. Preserve original failures and
unresolved outcomes. One compact decision register points to detailed
historical reports; routine health logs stay with the monitor.

User questions and status checks do not stop the ongoing research request.
Answer them and continue unless the user explicitly asks to stop. The armed
news jobs and existing routine monitor do not replace active research.

This documentation change has a 32,768-byte allocation in
[the storage ledger](../reports/experiment-storage/research-process-review-v1.json).
It changes no strategy source, armed protocol, raw capture or historical result.
