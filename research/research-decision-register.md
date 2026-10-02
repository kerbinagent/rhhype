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
| Simple Core/RH spread entry and short hold | **Parked.** The [$100 test](../reports/core-rh-small-shortterm/readout.md): 11 paired losses, −$0.183554; removing costs did not rescue it. Entry deteriorated in 10/11. | Predict closing executable value above costs, with delayed entry and a contemporaneous control. |
| Constant carry / maturity holding | **Outside current scope.** Historical funding work is retained in [active idea research](active-idea-research.md). The already frozen BTC study continues to its endpoint without interim economic inspection. | A user scope change would be needed to make this the active research objective. |
| Same-block atomic round trips | **Parked at tested routes and size.** [Base](../reports/base-atomic-cycle-slow-transport/readout.md) and [RH stock routes](../reports/rh-atomic-stock-cycle/readout.md) were negative before gas. [NVDA](../reports/rh-nvda-complete-input-cycles/readout.md) retained incomplete-input quotes as unknown. | A changed route, price discrepancy or fee structure that first clears an exact full-cycle quote including full input consumption and gas. |
| Passive spot entry with delayed hedge | **Parked pending observable flow and conditional value.** [LIT](../reports/core-spot-passive-cashentry/readout.md) had one partial close, −$0.013952; [ETH](../reports/core-spot-passive-eth-cash/readout.md) had no ordinary live trades and an unknown cancel. | Concurrent assets with sufficient live trade coverage; predicted profit conditional on an attributed passive fill, adverse selection and the hedge delay. More unfilled quotes alone do not qualify. |
| Local large-trade / depth shock fade | **Inconclusive.** The [three-window result](../reports/single-venue-research/single-venue-executable-shock-readout.txt) did not replicate the selected LIT win. The [control check](../reports/single-venue-research/shock-controls-readout.txt) found seven events, two positive local returns and six quote-minus-reference values, all negative. Two ordinary controls matched; both lacked complete reference coverage. | More distinct events and usable controls under frozen rules, then untouched episodes. Show executable recovery beyond common drift; preserve missing controls. |
| Cross-venue premium / residual fade | **Parked in ordinary windows.** [NEAR's premium](../reports/single-venue-research/broad-basis-dynamics-readout.txt) persisted; [relative gates](../reports/single-venue-research/single-venue-broad-relative-readout.txt) admitted nothing. [Residual profiles](../reports/single-venue-research/residual-profile-readout.txt) had no positive group in both windows. | Local executable recovery above costs, replicated in untouched blocks. |
| Delayed directional response to the other venue | **Parked for the tested ordinary sessions.** The [fixed diagnostic](../reports/single-venue-research/directional-response-readout.txt) selected 15 and 11 episodes. Local mean quote returns were −2.814244 and −3.939537 bp; the predefined cost-plausible subset was also negative in both windows. No group passed the replication criterion. Only 4/26 episodes had complete executable controls, leaving relative attribution limited. | A materially different, motivated mechanism or regime that predicts movement remaining after entry and costs. The current result does not justify threshold tuning or a direct replication. |
| Queue imbalance and observed OFI | **Parked at tested delays.** The [static screen](../reports/single-venue-research/broad-queue-readout.txt) had 19/20 negative means. The [fixed OFI comparison](../reports/single-venue-research/queue-ofi-publication-fix-v1/readout.txt) has 13/20 fitted cells and no cell/size passing all 3 chunks. | A distinct, motivated delayed signal with absolute value after costs; no tuning of this linear version. |
| Higher-activity scheduled news regime | **Candidate unconfirmed.** News Core NEAR follow had +0.5889 stressed USDC. The fixed [ordinary successor](../reports/news-candidate-rolling-v1/run-v1/root-review.json) had zero primary/comparator attempts; all 100 policies flat-known and 20 audits passed. Coverage gate failed. | Untouched relevant regimes under the same rule. Separate LIT work does not replace this primary. No news replication or repeatable profit. |
| RH LIT depth fade | **Both prospective gates failed.** [Pair review](../reports/lit-depth-fade-prospective-v1/root-review-000100.json): chunks96/100 stressed −0.114295/−0.591443 USDG, 1/4 closes; all8 ledgers flat and audited. | Parked. No replacement, tuning or comparator promotion. |
| Inventory-reducing aggressive flow | **Parked: fixed gate failed.** Corrected [two-block result](../reports/single-venue-research/ordinary-feed-fix-v1/inventory-context-batch2-readout.txt) has 11/15 pairs. BTC/Core has only 4/2 pairs and negative absolute reducing quote means in both blocks. No group qualifies in both; RH/BTC also has explicit book-coverage failures. | A materially different, motivated hypothesis with adequate matched support and positive absolute value after costs. No caliper relaxation or execution study follows from these sparse comparisons. |
| Slowing flow with depth restoration | **Parked: measurement gate failed.** [Both blocks](../reports/single-venue-research/ordinary-feed-fix-v1/flow-recovery-batch2-readout.txt) contain zero persistent/unrecovered episodes; slow/recovered counts are 5/3. | Adequate observable support for both states under a separately motivated rule. No threshold tuning or economic replay follows this version. |
| Liquidation-label continuation | **Support gate failed.** The separate [coverage successor](../reports/single-venue-research/liquidation-coverage-v2/readout.txt) keeps stale identities and quarantines triggers. Six fixed blocks yield 17 episodes and one witness across 16 complete chunks; 2 failed captures remain unknown. No cell passes. Original v1 is preserved. | A separately motivated regime with enough observable episodes and comparable ordinary-flow controls before delayed absolute economics. No adaptive ordinary-window extension or price study follows this result. |
| Cross-asset return lag / OFI | **Inconclusive support.** Return-lag: 0/0/1 BTC events and no pairs. [Fixed OFI](../reports/peer-research/cross-asset-ofi-v1/root-receipt.json): 4/18 training cells, 0/0/0 common calendars; no models or economics. | A distinct mechanism with adequate causal coverage; no subset rescue. |
| Passive PERP entry with strict trade-through | **Parked: fixed gate failed.** [Readout](../reports/single-venue-research/passive-through-v1/readout.txt): 0/120 alternatives across three initial blocks; 610 full witnesses, 557 complete conditional values and 53 retained unknown closes. Later blocks stayed unopened. | A distinct mechanism with adequate observability. No execution branch or tuning follows this screen; whole-policy cash remains unknown. |
| Full-NO basket acquisition and conversion | **Parked at recorded quotes.** [Fixed screen](../reports/polymarket-no-basket/optimistic-books-v1/readout.txt): all15 cost floors4.009Q versus gross return at most4Q, before costs. All15 failed timestamp diagnostics, so simultaneous liquidity remains unverified. | A separately motivated positive necessary price condition and coherent data before conversion, depth or execution work. No timestamp relaxation or quantity increase rescues the recorded bound. |
| Native ETH issuance and immediate stETH sale | **Parked at the fixed modeled state.** [Four-size bound](../reports/primary-issuance-bound-local-v1/readout.txt): all four valid optimistic margins approximately −6.08 to −6.09 bp before gas; all 19 responses independently reconciled. | A separately motivated prospective state/route; this conditional source-model rejection does not prove source/runtime equivalence or obtainable inclusion. No execution branch follows. |
| Polymarket NO subsets and full-YES creation | **Parked at sampled prices.** [Extension](../reports/polymarket-no-basket/subset-conversion-books-v1/readout.txt): all 480 route-slots nonpositive, no missing observations. One of 15 sets passed the frozen timing checks; the other 14 are recorded-quote bounds. | A separately motivated positive necessary condition and coherent data. Do not relax timestamps, increase equal size or infer actual conversion/fills from these negatives. |
| Hyperliquid HIP-4 outcome conversions | **Static screen negative; observation running.** All 18 questions had no cycle. The [Q357 plan](../reports/experiment-storage/hip4-continuation-live-v1.json) covers 18:35–20:50 UTC. | [Replay v6](../reports/hip4-pairing-root-review-v6/review.json) passed 25+9 checks; blinded during collection. Executable closed cash remains unproved. |
| Contractual collateral sales and auction rewards | **WETH parent bound failed; broader census complete.** [All 13](../reports/comet-collateral-inventory-v1/root-reconciliation.json): 11 positive stocks, two zeros, 39 reconciled requests. | Fixed-route/price work continues with reviewed conditional tooling. Dependencies/value/execution unproved; child basefee 0 is not a cost. Clipper offline. |
| Aave atomic liquidation cash | **Simulation access only.** [Trace](../reports/aave-trace-access-v1/root-review.json) unavailable; [creation probe](../reports/creation-callback-access-v1/root-review.json) returned both markers; root/Sol audited all five requests. | Full liquidation, repayment, cash return and gas-cost bound remain untested. |

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
Answer them and continue unless the user explicitly asks to stop. Scheduled
jobs and the routine monitor do not replace active research.

This documentation change has a 32,768-byte allocation in
[the storage ledger](../reports/experiment-storage/research-process-review-v1.json).
It changes no strategy source, armed protocol, raw capture or historical result.
