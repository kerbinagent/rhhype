# Why opening spread vanishes at the unwind, and what to test next

**Research follow-up, 2026-09-29.** The current paper policies and live
captures are unchanged. This note separates a stopped, quote-only 12–16 s
measurement from a proposed future strategy test. It does not infer fills,
select a profitable model, or authorize real trading.

## The cash identity that opening spread misses

At one frozen base quantity, let `E = short-entry sell proceeds − long-entry
buy cost`. Let `C_t = short buyback cost − long liquidation proceeds` at an
eligible paired quote. After four fees `F_t`, a risk allowance `R`, capital
`K_t`, and any actual funding `U_t`, the matched pair has

`N_t = E − C_t − F_t − R − K_t + U_t`.

`E > 0` is an opening difference, not a saleable profit. If both venue
prices carry a persistent relative premium, `C_t` can be positive at entry
and remain positive through exit. Crossing both bid–ask spreads on the way
in and out also makes an instant round trip costly. The amount that must
improve after entry is explicit: `ΔN_required = target − N_0`; the realized
quoted improvement is `N_H − N_0`. A large opening `E` is irrelevant when
its closing liability and execution toll are larger.

This is consistent with, but more specific than, the theory. [He et al.'s
perpetual-futures paper](https://arxiv.org/abs/2212.06888) derives pricing
bounds with trading costs and notes that a perpetual has no maturity forcing
spot convergence; applying that warning to two different perp venues is an
**inference**, not a theorem that their cross-venue basis must persist.
[Leung and Li](https://arxiv.org/abs/1411.5062) formulate entry and exit as
separate stopping decisions with transaction costs and a stop loss.
[Leung and Kitapbayev](https://arxiv.org/abs/1701.00875) solve a finite-horizon
mean-reverting spread problem whose entry/exit boundaries depend on time.
Their OU diffusion and friction assumptions do not describe our asynchronous
books, failed hedge legs, or 10-second execution; they motivate a
cost-dependent *no-trade region*, not a copied boundary value.

## Stopped fixed-quantity evidence

The [reproducible analyzer](../scripts/analyze_convergence_hurdle.py) reads
only the stopped [fixed-markout snapshot](../reports/fixed-markout-v1/fixed_markout_snapshot.json.gz),
validates all **2,134** retained anchors against all-run counters, and
exports [bounded evidence](../reports/strategy-convergence-followup/fixed-horizon-hurdle.json).
It reconstructs `N_0` from the original entry values and **same-anchor**
full-quantity liquidation books; the future is the previously frozen first
eligible 12–16 s quote. `N_0` has no latency and is a *diagnostic* instant
liquidation quote, not an executable fill. The 5 bp allowance is shown
separately from exchange fees.

| Stopped-book diagnostic | Count or median |
| --- | ---: |
| Anchors with positive opening `E` | 875 / 2,134 |
| Anchors with positive **instant full round-trip gross** | 0 / 2,134 |
| Instant net after four fees; after fee plus allowance | median −$0.99; −$1.49 |
| Required improvement to reach +$0.10, fee-only; with allowance | median $1.09; $1.59 |
| Observed 12–16 s improvement on 1,595 matched anchors | median approximately $0.00; p90 $0.17 |
| Perfect hindsight, observed matched only: future ≥+$0.10 | fee-only 1 / 1,595; with allowance 0 / 1,595 |
| Unknown future outcomes | 539 / 2,134 (493 future depth, 22 `outcome_missing`, 24 stopped pending) |

Even among **90** anchors whose opening spread exceeded the same-anchor
four fees, 5 bp allowance, and $0.10 target, only **83** had a matched
future quote; seven were censored. Their median *required* improvement
remained **$1.09**, while the matched median observed improvement was about
**$0.001**. None of the 83 reached +$0.10 after the allowance; one reached
it before the allowance. The 5 bp reserve is not a cash exchange fee, so
fee-only and reserve-adjusted columns must remain distinct.

This is an **oracle bound only for the observed matched 12–16 s quote
outcomes**: even a selector that knew those future matched prices could
choose no reserve-adjusted +$0.10 result in this sample. It says nothing
about the 539 censored outcomes, private fills, different entry timing,
resting exits, longer holds, or future days. Opposite route directions and
overlapping 12–16 s anchors share books. The result is not 1,595 independent
trading losses or proof that cross-venue convergence never works.

The older horizon-v2 conditional model lowered closing-spread MAE to
**0.927 bp** versus **1.094 bp** for persistence on the same 2,797 scored
anchors ([stopped report](../reports/horizon-v2/report.md)). But the later
fixed-original-quantity screen selected zero primary conditional quotes
above $0 after four fees; its 863 scored matched outcomes averaged
**−$0.85** after four fees and **−$1.35** after the allowance
([stopped result](../reports/fixed-markout-v1/final.md)). Lower prediction
error did not create an economic edge. A second model contest on this short
archive cannot repair the absence of observed positive labels.

## One different candidate, with a falsifier

The next **taker convergence** candidate should forecast the *distribution
of the completed, delayed net*, not a route's median historical closing
spread. At each original-quantity opportunity, form the executable
same-anchor liquidation deficit `D_0 = target − N_0`, plus a past-only
residual `r_t = basis_t − rolling_past_basis_equilibrium`. For each fixed
horizon `H`, estimate a route-shrunk response
`ΔN_H = α_H + β_H r_t + ε_H` and the lower tail of `ε_H`. A route is
eligible only if the **predicted lower quantile** of delayed net clears the
fee-only target and a separately reported risk allowance, with adequate
sample coverage and a predeclared maximum one-leg loss. This is an
error-correction hypothesis **on executable economics**: `β_H` must imply
large enough improvement *within H* to overcome the measured `D_0`.
A slow or unstable residual, or a negative lower-tail screen, means no
trade even if the opening book looks crossed. The current 20-minute
snapshot is too short to estimate a stable residual half-life or failure
probability; this rule is a design for a new, longer prospective sample.

Entry and exit are separate decisions. Once fully paired, an exit request
may be triggered by a *current* full-quantity all-cost liquidation quote
above a prior-trained profit barrier, but the result must be scored at the
**first valid book after each venue's exit delay**, including partials and
misses. A request at +$0.10 now can settle below +$0.10. A cost-aware stop
or maximum hold must likewise pay the actual delayed unwind rather than
marking a theoretical boundary. The finite-horizon papers justify testing
such boundaries, but no dynamic stopping claim can be extracted from this
snapshot's single future quote per anchor.

The next path capture should predeclare **10 s as the primary control** and
**30, 60, and 300 s as separate diagnostics**, each with its own capital,
funding, terminal exposure, and candidate denominator. Use source/receipt
validated advancing books, generation continuity, original quantity,
full-depth first-eligible outcomes, four own-notional fees, normal order
delays and price caps, and explicit one-leg failures. Do not choose the best
future timestamp, merge horizons, or select a horizon from the same test
outcomes. Before fitting any predictor, report the perfect-hindsight
*quote-only* positive count and censor fraction at each horizon, then test
one frozen lower-quantile gate on later UTC days with a chronological
train/validation/test split and an outcome-overlap embargo. Report no-trade,
all-original-candidate net, matched net, failure net, and unresolved
inventory separately. No positive feasible delayed quotes or too many
censors means insufficient basis-convergence evidence, not a reason to
relax thresholds after seeing the data.

A **different execution** experiment may be more promising than a more
complex residual model: reduce a crossed exit leg with a passive order or
recycle existing venue inventory, while retaining the short hedge and a
bounded taker-flatten deadline. That changes the bid–ask toll rather than
assuming a faster basis. It adds queue, cancel-race, partial-fill, and
inventory risk, so it needs its own prospective ledger and cannot be
credited with hypothetical maker fills. The separate
[RH maker-exit design](rh-maker-inventory-exits.md) specifies one such
narrow test. This is a research priority suggestion, not a profitability
claim or a change to the running policy.
