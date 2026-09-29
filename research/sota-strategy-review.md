# Strategy review and the small-Robinhood-order hypothesis

Reviewed 29 September 2026. Root synthesis of the linked research notes and
our frozen experiments. This is a public-data research program, not a claim
that a profitable strategy has been found. The live paper monitor retains
its $0.10 target and ten-second exit-request policy.

## What was missing from our approach

The monitor became a detailed execution and accounting simulator before we
had established a source of expected return. Better scheduling, accurate
fees, realistic failures and bounded storage are necessary, but none creates
an economic edge. The original opening-spread tally was particularly
misleading for two perpetual positions: the future closing basis remains a
liability. The recent experiments tested short-horizon convergence, fixed-best
maker quotes, impulse confirmation, and a narrow funding screen. They did
not test the full class of competitive inventory-aware cross-venue strategies.

There is no public benchmark establishing the best private arbitrage desk's
strategy on this new venue. Here, “state of the art” means current documented
mechanisms and rigorous empirical methods, separating established research,
recent preprints, operational implementations, and our own proposals.

## Mechanisms and their relevance

| Family | Source of return | What must be modeled | Priority here |
|---|---|---|---|
| RH passive quote, HL hedge | Compensation for supplying scarce liquidity, conditional on the hedge and eventual unwind | Quote placement, queue, adverse selection, cancellation races, partial hedges, both venue inventories | First: directly tests the user's small-order hypothesis |
| Executable residual convergence | A temporary cross-venue basis moves toward an estimated equilibrium faster than costs accumulate | Causal residual forecast, regime and half-life, all four executions, failure losses | Second: retain ten-second control and test a materially different predictor |
| Funding plus basis carry | Earn signed funding differential while managing changing basis and scarce collateral | Future funding uncertainty, basis, margin, per-venue cash and priced rebalance | Secondary, longer-horizon mandate; not a replacement for the user's short hold |
| Spot/AMM cross-venue arbitrage | Buy an economically transferable asset cheaply and sell existing inventory dearly | Exact token identity, conversion/redemption, pool impact, gas/ordering, inventory replenishment | Separate canonical Robinhood Chain study, not interchangeable with RH Lighter perps |
| Multi-route inventory rebalance | Find a cheaper feasible path to restore constrained venue balances | Nodes are venue/asset balances, costs and delays on edges, executable capacity | Supporting control once a strategy has enough turnover to justify it |

The [maker research note](sota-maker-hedging.md) uses joint passive/active
control, queue-dependent flow, adverse selection and recent passive-impact
research. [Hummingbot's operational XEMM baseline](https://hummingbot.org/strategies/v1-strategies/cross-exchange-market-making/)
prices maker orders from the hedge market and required margin, updates them
as economics change, and hedges actual fills. Its documented V1 use is spot;
perpetual adaptation must retain a future closing-basis term. It is an open
baseline, not proof of current best performance.

The [relative-value note](sota-relative-value.md) combines error correction,
finite-horizon stopping and order-flow features. [Albers et al.](https://arxiv.org/abs/2108.09750)
provide a useful empirical distinction: cross-market predictive features,
fee-aware taker economics, and maker results validated with actual trading
are different tests. Their Bitcoin evidence is not a transferable HL/RH
profit estimate. Our prior conditional model improved quote forecast error
without selecting profitable trades; any added feature must improve net
outcomes on a future sample, not just forecasting accuracy.

The [carry/capital note](sota-carry-capital.md) treats funding and basis
jointly. [He et al., revised September 2026](https://arxiv.org/abs/2212.06888),
show why perpetual pricing with transaction costs produces bounds rather
than guaranteed near-term convergence. Our short funding holdout does not
identify a longer dynamic carry policy.

Two recent sources sharpen the AMM boundary. [Schwertfeger and Vogt,
Journal of Banking & Finance, July 2026](https://www.sciencedirect.com/science/article/pii/S0378426626000956),
report realized CEX/AMM trading, including operational costs and sequencing
risk, on historical 2023–24 windows. I could verify the publisher abstract
and author institution's research description, not inspect the complete
published paper; its returns are not a forecast for our venues. [He, Yang
and Zhou, revised September 2026](https://arxiv.org/html/2507.08302v3), model
competition over transaction ordering and inventory risk: publicly visible
price discrepancies are contested, and choosing the largest feasible trade
is not necessarily optimal. These AMM findings do not make two separate
perpetual order books atomic.

[Litvin, PMLR 2026](https://proceedings.mlr.press/v318/litvin26a.html), models
stablecoin routing with venue/asset nodes and execution costs. Its reported
result concerns search efficiency in its evaluation, not demonstrated
risk-free HL/RH trading. The transferable idea is to represent collateral
conversion and rebalancing as costed, capacity-limited actions instead of
assuming USDG and USDC are an immediately interchangeable wallet.

## The user's hypothesis, made testable

**Hypothesis:** small passive RH quotes can receive enough non-adverse flow
to pay for a Hyperliquid hedge, inventory risk, and a fully costed unwind.
A new venue could have less competition, but also thinner flow, less stable
references, or sparse executable depth. We must measure both possibilities.

Use $25/$50/$100/$250 orders, with $1,000 as a capacity control. Treat the
RH Lighter domain separately from Core Lighter and canonical Robinhood
Chain AMMs. Start with comparable crypto contracts and separate NVDA/XAG
cohorts; expand only after contract and feed checks. Volume, spread, flow
frequency, size validity, and hedge depth are universe diagnostics, not
post-outcome symbol selection.

At RH Standard, maker and taker fees are both zero. Thus the immediate
maker advantage is the RH spread earned versus crossed, not a saved RH
fee. Two HL native taker executions cost approximately 9 bp; sampled xyz
NVDA/silver executions cost about 1.8 bp, on their own notionals. Funding,
spread, capital, conversion and reserve are additional. Higher account
tiers trade explicit fees against processing behavior, so they need full
quote/fill/cancel scenario reruns rather than only ex-post fee subtraction.
The [archived official RH tier table](../data/raw/comparators/rh_lighter/20260929T040726Z/sources/account-types.md)
and frozen market metadata support these scenarios.

For a new RH buy and HL sell, a schematic maximum maker price is

`p_RH <= E[HL sell VWAP at hedge | RH fill, current state]`
`        + E[RH exit bid VWAP - HL exit ask VWAP | RH fill, current state]`
`        - (all fees + capital/conversion + risk allowance + target dollars)/q`.

Both expectations must use only earlier observations. This is a research
quote rule, not a locked price. Subtracting an arbitrary reserve while
silently setting the future exit differential to zero would recreate the
original opening-edge error. For inventory reduction, calculate the actual
marginal cash flow against existing dated lots and their remaining exit
liabilities. Hedging net delta to zero does not remove opposite venue
positions, margin use, funding or basis risk.

A $0.10 target means 40 bp at $25, 20 bp at $50, 10 bp at $100 and 4 bp at
$250. Accordingly, report **net > 0**, **net >= $0.10**, net basis points,
net dollars per hour and capital usage separately. Small positive cents
must not be inflated into a large income estimate by recounting the same
quote. The existing monitor target remains unchanged.

## Next strategy experiment: decisions before data

1. Build source-valid full-book event reconstruction for RH/Core snapshots
   and contiguous deltas, retaining gaps and generation changes. Our older
   maker replay intentionally used BBO/ticker only; all complete paths in
   the small-size replay were Core routes. RH had no complete path, so that
   replay cannot reject the RH hypothesis. This is a data-coverage issue to
   diagnose, not permission to assign missing outcomes zero or refresh old
   quotes artificially.
2. Freeze a small-size, RH-maker/HL-hedge quote policy and fixed-best control
   before a fresh window. Observe quote competitiveness, conservative
   queue-flow scenarios, late fills during modeled cancellation, partial
   hedges and the executable unwind. Hedge timing begins at local receipt
   of confirmation; exchange source time cannot grant knowledge early.
3. Retain ten-second close requests as the primary benchmark. Study 30/60 s
   inventory-recycling variants separately, with venue inventory caps and
   a final priced liquidation. Later opposite-side maker fills can reduce
   inventory; they do not erase fee-bearing hedge executions or make
   unliquidated P&L realized. No automatic production promotion follows.
4. Separate calibration and forward evaluation. Use earlier windows for
   fair-basis/flow estimates; freeze one simple quote rule and risk budget.
   Include no-trade and fixed-best controls. Preserve every decision,
   no-flow case, failed hedge, missing path and residual position; cluster
   results by underlying and time block. A short feasibility capture can
   reject a mechanism but cannot establish a stable return distribution.
5. Advance only if the fresh study finds positive completed net outcomes
   and enough coverage to assess failure losses and capacity. Public flow
   is still a counterfactual fill scenario. Actual queue acknowledgements,
   private fills and fees would be needed for execution validation; no
   real trading is authorized or included here.

## What the existing negative results establish

The 527-close fixed holdout lost $624.27; removing fees and the modeled
reserve on those same fills still left $228.90 loss. That rejects a fee-only
repair of those paths. The lower-fee NVDA/XAG maker capture produced no
complete exit; the impulse pilot selected no entries. Neither yields an
estimate of a different adaptive maker strategy's profitability.

The post hoc size diagnostic produced 16/12/9 complete public quote paths
at $100/$250/$1,000, all negative before fees, with nine shared timestamps.
**Every complete path was Core, not RH.** Smaller size improved observed
depth coverage but did not repair those Core paths. It leaves the user's
small-RH-order hypothesis untested economically. Our next priority is the
RH-specific adaptive quoting mechanism and its observable failure modes.
