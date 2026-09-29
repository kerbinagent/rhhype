# Strategy decision after the opening-spread/unwind investigation

29 September 2026. Root synthesis of primary research and our stopped public
data. Proposed policies below have not been promoted to the live monitor.

## Diagnosis

The current two-perpetual trade is a **basis-convergence position**. An opening
price difference is insufficient to establish profit. For matched quantity q:

`cycle gross = q × (short entry − long entry + long exit − short exit)`.

Subtract all four own-notional fees, add actual funding, and account for capital
and any currency conversion. Maintain separate USDG and USDC balances; their
parity is an explicit valuation assumption. A hedge reduces common directional
exposure but leaves basis and venue margin risks. Perpetual contracts have no
expiry that forces convergence. [He et al., revised September 2026](https://arxiv.org/abs/2212.06888).

An instant taker round trip crosses each venue's spread twice across its two
orders. With uncrossed books, negative gross is mechanically expected, even
when the cross-venue opening prices look crossed. The empirical question is
whether the subsequent basis change or liquidity income overcomes that toll.

Our new [stopped-snapshot decomposition](strategy-convergence-followup.md)
uses 2,134 original-quantity anchors. 875 have positive opening differences;
none has a positive immediate round-trip gross. Median immediate net is
−$0.99 after four fees, or −$1.49 with the separate 5 bp stress allowance.
To reach the $0.10 target therefore requires median improvement of $1.09 or
$1.59 respectively. Observed 12–16 s improvement on 1,595 matched anchors
has a median near zero and 90th percentile about $0.17. Only one matched
future outcome reaches $0.10 fee-only; none does with the allowance.
The other 539 future outcomes remain unknown. These are overlapping quote
measurements, not independent executed trades or a bound at other horizons.

The new exit-request observer also helps distinguish movement during execution
from losses already present at the decision. Its first four valid baseline
closes were already negative at the request (sum −$3.54), finishing at −$3.80;
the reconciled additional price deterioration was about $0.261. This tiny,
concentrated sample is not a causal estimate of latency cost. The historical
91-close cohort lost $31.76 gross before fees/reserve and lacked request-book
evidence. [Attribution and limitations](unwind-attribution.md).

The subsequent **23:06 UTC scheduled review** provides 86 valid baseline
exit-price comparisons: 19 worsened, 24 improved, 43 were unchanged; aggregate
price deterioration was only **+$0.057486**, median zero, p95 $0.1664. Three
other paired closes lacked valid request prices. The full 89-paired cohort
lost $95.6696 after modeled costs. The cohorts differ, and offsetting moves
hide individual adverse outcomes; this is descriptive evidence against exit
delay alone explaining that interval's loss. It does not estimate the effect
of faster entry, cancellation or execution on a different strategy.
[Preserved review](../reports/unwind-instrumentation/review21.json).

## Research conclusions and ranked next tests

| Priority | Mechanism | What changes economically | Evidence and decision |
|---|---|---|---|
| 1 | RH maker entry and maker inventory reduction, with HL hedges of each filled increment | Earn RH bid–ask spread on a completed cycle; reduce the cost of crossing the RH exit book | Test XAG first as a narrow falsification, NVDA separately during regular equity hours, BTC/ETH as controls. No demonstrated edge yet. |
| 2 | Cost-aware residual convergence and entry/exit boundaries | Enter only when a temporary basis deviation predicts sufficient net improvement before the deadline | Need full future paths and separate days. Current matched short-horizon sample gives little scope for profitable selection. |
| 3 | Funding plus basis carry | Receive funding across multiple settlements | Deprioritize for this short-hold objective: sampled SOL/RH fee payback is measured in days and depends on unstable rates. |

### 1. Joint quoting and inventory reduction

The operational pattern is to quote on a less liquid venue, hedge actual fills
on the more liquid venue, and refresh orders when hedge economics change.
[Hummingbot XEMM](https://hummingbot.org/strategies/v1-strategies/cross-exchange-market-making/)
documents that pattern for spot. Its opening spread arithmetic cannot be
transferred to two perps without keeping their closing obligations.

[Barzykin, Bergault and Guéant](https://arxiv.org/abs/2106.06974) model quoting
and external hedging jointly, with inventory affecting whether to wait for
opposite customer flow or hedge externally. [Guilbaud and Pham](https://arxiv.org/abs/1106.5040)
likewise combine limit and market orders under inventory risk. These are
useful mechanisms and models, not performance estimates for RH/HL.

For our first bounded version: maker-buy RH, taker-sell HL, then offer the
existing RH long passively and buy back the corresponding HL short only when
that RH sale is attributed. Reverse the signs for the opposite direction.
Cap inventory at one original pair; prohibit an exit from opening excess
reverse inventory. Keep cancellation races, partials, below-lot dust and failed
hedges as actual obligations. A ten-second deadline still requests cancellation
and taker flatten of residuals. A separate 60-second paper branch may test
more time for opposite flow; it cannot replace the ten-second control after
seeing its losses. [Exact ledger and proposed rules](strategy-inventory-followup.md).

Evaluate an exit against **immediate feasible liquidation**. Entry fees are
sunk for that marginal decision but remain costs of the completed cycle.
A useful decision score is the expected improvement over immediate liquidation:

`P(exit fills) × E[passive advantage | fill]`
`+ P(no fill) × E[delayed fallback advantage | no fill] − added holding costs`.

Condition both terms on book state and adverse selection; do not multiply an
unconditional midpoint forecast by a naive fill probability. Missing public
queue evidence yields an unknown score. Merely leaving a losing position open
or crediting every quote touch as a fill will exaggerate the benefit.

The small prior static XAG screen has median **+$0.110 per $1,000 after modeled
fees**, assuming both RH maker fills and unchanged future books. After the
5 bp allowance it is about **−$0.390**, and its margin above the $0.10 target
is **−$0.490**. The target is not an expense. NVDA's fee-only median is already
−$0.048. These 16 and 15 paired anchors are hypothetical, continuous-price
screens; they do not validate order ticks, fills, future hedges or conversion.
This is a cheap hypothesis to reject with flow evidence, not a positive result.

The completed 50-minute maker pilot ran 17:21–18:11 Eastern. Its adaptive
branches received no attributed maker flow; completed fixed-best Premium
BTC/ETH cycles lost money. All 96 branches ended with unresolved conditions,
so whole-portfolio returns remain unknown. A new equity test should separate
regular and extended sessions. More regular-session flow might help fills,
but tighter spreads might remove the edge. [Cached pilot readout](../reports/rh-small-maker-v1/CACHED-RESULTS.md).

### 2. Joint entry and exit for a reverting basis

[Leung and Li](https://arxiv.org/abs/1411.5062) solve entry and liquidation
jointly with transaction costs and a stop loss. [Leung and Kitapbayev](https://arxiv.org/abs/1701.00875)
extend spread timing to a finite horizon. Their assumptions motivate a
cost-dependent no-trade region and time-dependent exits. They do not establish
that our basis follows their mean-reversion model.

Use a past-only route equilibrium and estimate how much an executable basis
residual predicts **completed net improvement**, at a fixed horizon. Require
a conservative forecast to exceed the current liquidation deficit plus the
profit target. Include delays, own-notional fees and failed-leg outcomes.
Calibrate entry and exit on earlier data, then freeze both for later days.
Measure realized net and the rejected-candidate denominator; forecast error
alone is insufficient. Our existing more accurate closing forecast selected
no profitable original-size trades.

For an existing paired position, compare the net value of closing after normal
execution delays with the predicted value of waiting, subject to exposure and
deadline limits. The original loss is sunk; waiting is justified only by an
incremental expected benefit. A profit target alone is not an optimal stopping
rule, and a stop request does not guarantee its quoted execution price.
Retain ten seconds as control and use 30/60/300 s only as separately scored
research horizons. The existing one-future-quote archive cannot test optimal
stopping or choose the best intermediate exit. [Detailed next test](strategy-convergence-followup.md).

### 3. Carry does not rescue the ten-second trade

The stopped funding holdout's strongest clean crypto route, short HL/long RH
SOL, earned 4.52 bp over 24 hours. At a constant continuation of that sampled
rate, 9 bp four-taker fees need about 48 hours; adding the 5 bp allowance needs
74 hours. The monitor's capital assumption extends those estimates to about
121/189 hours. Actual future funding and exit basis are unknown. This is
break-even arithmetic from one day, not a forecast or a sustainable yield.
[Funding research and primary venue sources](strategy-carry-followup.md).

## Experiment and accounting requirements

Keep $100/$250/$500/$1,000, primary $1,000. A fixed $0.10 target is 10 bp at
$100 and 1 bp at $1,000, so smaller size only helps when depth/impact savings
outweigh its larger relative hurdle. Report each size and policy separately.

Keep exchange fees, paid conversion/transfer costs, funding, capital charges,
and the 5 bp stress allowance in separate columns. Fee tiers change whether
an edge is feasible; use documented base-account assumptions plus explicitly
labeled higher-tier sensitivity, never assume unavailable volume discounts.

Estimate any future execution-risk buffer from earlier observed delay and
failure outcomes, then freeze it before evaluation. Do not charge observed
depth impact or delayed fill movement twice by also labeling the same loss
as a separate slippage fee. Preserve the current 5 bp scenario as a stress
comparison; reducing an arbitrary allowance can reveal a fee-only hypothesis,
but cannot improve its cash result or demonstrate robustness.

For passive cycles collect the entire entry-to-exit path and subsequent late
flow, with bounded storage. Track no-entry, no-flow, partial, failed hedge,
forced close, complete close, and unresolved terminal inventory. Require a
material number of complete cycles across sessions with positive full-cycle
net and controlled failure losses before promoting a replacement policy.
No strategy described here has passed that gate.

This follow-up adds a reproducible stopped-data analyzer and strategy designs.
It does not change the running entry/exit rules. The scheduled review daemon
continues to record results every twenty minutes.
