# Cross-venue relative value at a ten-second horizon

**Research note, 29 September 2026.** This is a plan for a separate public-data
study, not a profitable-strategy claim or a change to the paper monitor. The
existing monitor trades the same named underlying on two perpetual venues,
long one contract and short the other. The quotes, contract multipliers,
collateral, funding rules, and exit liquidity all matter. A crossed entry book
does not lock the future exit price, and delayed or partial fills leave outright
exposure. This is **statistical relative value**, not certain arbitrage.

The local evidence argues against treating a large opening spread as enough.
In the [frozen holdout](../reports/fee-sensitivity/REPORT.md), 517 fully paired
baseline closes had zero wins after recorded costs; removing *all* fees and
the modeled 5 bp reserve still left their recorded price path at a $214.80
loss. The [review 12 audit](review12-hedge-failures.md) found 15 of 15
convergence closes were failed hedges: the peer filled and Hyperliquid later
had no quantity inside its signal-time 10 bp cap. These are correlated paper
events, not independent market trials. The [fixed-quantity 12–16 s study](../reports/fixed-markout-v1/final.md)
also found no primary conditional-model quote predictions above $0 among its
scored anchors after four frozen Standard fees. Quote markouts are not fills.

## What the primary literature supports

| Source and date | Mechanism to borrow | Boundary for this project |
| --- | --- | --- |
| [Engle and Granger, *Econometrica* (1987)](https://doi.org/10.2307/1913236) | A linear combination of nonstationary prices can be stationary; an error-correction term then describes adjustment toward a common relation. | Same-symbol perp prices may share a long-run level, but that does not establish a profitable **10 s** adjustment after spreads or prove a stable hedge ratio. Test stationarity and its horizon in past data. |
| [Avellaneda and Lee, *Quantitative Finance* (2010)](https://math.nyu.edu/~avellane/AvellanedaLeeStatArb071108.pdf) | Remove common factors, model the residual as an Ornstein–Uhlenbeck (OU) process, standardize distance from equilibrium, and estimate parameters using only information available before each trade. Their equity model also showed regime sensitivity and transaction-cost erosion. | Their estimation and holding periods are in days; copying their thresholds into a 10 s, cross-venue perp trade would be unjustified. A residual must be constructed from synchronized, comparable contracts and refit causally. |
| [Leung and Li, *International Journal of Theoretical and Applied Finance* (2015; 2014 preprint)](https://arxiv.org/abs/1411.5062) | Entry and liquidation are separate stopping decisions under OU dynamics, transaction costs, and a stop-loss. Higher costs move optimal boundaries; an extreme residual need not imply immediate entry. | Their analytical boundaries assume a specified diffusion and simplified trading friction. Our finite 10 s clock, asynchronous fills, and one-leg failures require a finite-horizon, execution-aware version. |
| [Cont, Kukanov, and Stoikov, *Journal of Financial Econometrics* (2014; 2010 preprint)](https://arxiv.org/abs/1011.6402) | Short-horizon price changes relate to best-book order-flow imbalance, with impact inversely related to depth. Limit orders, cancellations, and market orders all contribute. | Their NYSE result is a predictive-feature rationale, not evidence of positive net P&L on these venues. We must observe book updates causally and account for quote age and depth. |
| [Albers, Cucuringu, Howison, and Shestopaloff, *Applied Mathematical Finance* (2022)](https://arxiv.org/abs/2108.09750) | Cross-market order-book and trade-flow features can identify leader–lagger effects. The authors compare forecasts with cost-aware taker P&L and test a separate maker strategy live; fee regime affects leadership and viability. | Their Bitcoin-market 500 ms results do not transfer to Hyperliquid/Lighter perps or a 10 s hold. Prediction accuracy, crossed quotes, taker profitability, and maker fill probability are different endpoints. |

These papers provide models and falsifiable features, not a ready-made edge.
The live [Hyperliquid fee schedule](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
currently lists a 4.5 bp base perp taker rate, subject to tier, staking,
HIP-3, and deployer adjustments. For a $1,000 HL leg, two base taker fills
alone cost about $0.90; the monitor's modeled 5 bp reserve adds about $0.50
at that notional, before peer fees, spread crossing, price movement, and
capital cost. Use the frozen **market-specific** fee metadata in each
experiment rather than substituting this illustration. The reserve is a
model allowance, not an exchange charge.

## Model the residual, then the executable trade

For synchronized, valid same-contract midquotes, let
`b_t = log(mid_HL,t) − log(mid_peer,t)`. Estimate a route and regime equilibrium
`mu_t` from **past** data only. Cointegration or a stable common-price
relation is a prerequisite, not a label inferred from correlation. A simple
OU diagnostic is

`db_t = kappa(mu − b_t)dt + sigma dW_t`, giving
`E[b_(t+H) − b_t | b_t] = (mu − b_t)(1 − exp(−kappa H))` for `H = 10 s`.

If `log(2)/kappa` is far longer than ten seconds, the model predicts little
capture even for a conspicuous gap. Estimate `kappa`, uncertainty, and
regime stability out of sample; reject routes with too little past data or
no supported fast adjustment. A log-basis move must then be converted using
the actual contract multiplier and original quantity. It is never itself
the cash return.

For long venue L and short venue S at frozen original quantity `q`, the
**paper net-P&L identity** is

`N = sell_entry,S(q) − buy_entry,L(q) + sell_exit,L(q) − buy_exit,S(q)`
`    − entry_and_exit_fees − reserve − elapsed_capital_cost + funding`.

Each `buy` or `sell` is a depth walk at the eligible delayed book, not a
midquote. This is P&L algebra for perpetual contracts, not a claim that
their opening notionals move through the wallet. The four fee amounts use
their own actual notionals. A failed
hedge instead has its own partial-fill and flatten cashflows; it is not
assigned the matched-pair formula. Before entry, forecast the **distribution**
of this cash outcome, including `P(both legs fill)`, one-leg loss, missing
future depth, and delayed exits. For example, a predeclared decision score
could be

`U_t = p_pair E[N_pair | X_t] + p_fail E[N_fail | X_t]`
`      − lambda * ES_95(one-leg loss | X_t)`,

where `X_t` contains only information received by decision time. Estimate
the probabilities and conditional losses from training observations; do
not plug in perfect-fill assumptions. A zero-fill abort contributes zero
trading cash, while any filled one-leg failure contributes its actual loss.
The score is a research hypothesis,
not an expected profit until calibrated on untouched future data.

The current `convergence` selector instead subtracts a median **historical
closing spread** from today's modeled opening edge and checks a fixed dollar
threshold. Its prior sample does not condition on today's residual speed,
leader-side order flow, volatility, depth, quote age, or the chance that HL
rejects after the peer fills. It also uses one closing-spread statistic for
an exit that may occur after the requested ten seconds. The new hypothesis
is materially different only if those conditional forecasts improve
**delayed-fill all-cost outcomes**, not just the median quote error.
The [prior horizon-v2 model](../reports/horizon-v2/report.md) already improved
12–16 s closing-spread MAE over persistence; the later fixed-quantity screen
still produced no primary positive-after-fee candidates. Include that
conditional model as a benchmark where its features are available, and do
not treat another MAE gain as evidence of executable profit.

## Predeclared causal experiment

1. **Freeze the universe and capture.** Use comparable contract specs and
   preselected physical HL/peer pairs; record market metadata, fee schedule,
   source timestamp, receipt timestamp, generation, BBO, available L2
   depth, and any public trade prints needed to distinguish trades from
   cancellations. BBO-only changes are an OFI proxy, not a full event
   classification. Never splice BBO and L2 to invent liquidity. Collect multiple
   independent UTC days and several RWA sessions before fitting; a single
   20-minute trial cannot identify a stable OU half-life or regime. Mark
   funding boundaries and market sessions. If a route lacks enough past
   observations, it remains inactive rather than borrowing a favorable
   post-hoc threshold.
2. **Define opportunity and label before training.** On each eligible route
   event, freeze the original `q`, direction, candidate timestamp, and book
   versions. The simulated intent sees the first future book whose receipt
   *and source* are at or after its venue due time, with unchanged generation,
   price cap, lot, minimum, and displayed depth rules. Request exit at a
   frozen 10 s hold in the **new common simulation** for every entry model,
   including the historical-median comparator; model its actual delay.
   Record matched close, first/second-leg failure,
   abort, still-open exposure, funding unresolved, and depth-censored
   markout as distinct states. A finite-horizon stopping policy
   with cost-dependent boundaries is a **separate, predeclared** experiment
   whose exit order still faces normal venue delay. Do not choose a later
   favorable quote after the first eligible depth failure.
3. **Fit only past data.** Baselines are no trade, the existing historical
   median gate, persistence, and the existing horizon-v2 conditional model
   where applicable. Candidate model A fits a
   route-shrunk OU/error-correction residual. Candidate model B adds
   lagged 1–5 s best-book imbalance, venue-specific depth/spread,
   lead–lag innovations, source/receipt skew, and predeclared volatility
   or session regime. Fit a separate paired-fill/failure model. Feature
   timestamps must precede the decision receipt; the current book cannot
   train its own outcome. Choose architecture, window, and one utility
   threshold on training/validation data only.
4. **Walk forward.** Predeclare at least five training days, one validation
   day, then one untouched test day, repeating on later nonoverlapping test
   days if capture continues. At each boundary, include a training label
   only if a close was fully `settled_at` before the next block, or a
   zero-fill abort was known by `closed_at`; purge crossing outcomes and
   impose a 30 s book-overlap embargo. Longer open
   or funding-pending positions stay purged regardless of that embargo.
   Freeze all hyperparameters and selected routes before test outcomes.
   Cluster uncertainty by physical asset and UTC time block, since
   opposite directions and shared HL events are correlated.
5. **Judge economics, coverage, and risk together.** Primary endpoint:
   all-original-candidate net cash per independent policy after actual
   four-leg fees, reserve, capital, funding, and one-leg flatten costs,
   with pending outcomes unresolved. Report matched-trade net separately
   from failed-hedge net, selected count, fill rate, abstentions, censored
   depth, forecast calibration, and worst tail loss. Use a prespecified
   positive lower confidence bound for policy-minus-baseline net as the
   efficacy bar; no selected trades or incomplete coverage means
   **insufficient evidence**, not success. Keep the no-trade cash benchmark
   at zero. Do not sum independent counterfactual portfolio P&Ls.

Finally, decompose matched P&L into common-price movement, relative-basis
movement, fees, and residual directional exposure. Equal base quantity is
not automatically beta neutrality if contract multipliers or collateral
values differ; partial fills create outright risk even when a basis forecast
is correct. If `P_i = beta_i M + epsilon_i`, the common-market component of
the two-leg price change is `(q_L beta_L − q_S beta_S) ΔM`; only a matched
effective hedge cancels it. An apparent high `R²` for lead–lag returns or a lower residual
forecast error is useful only if the independent, costed trade endpoint and
hedge reliability pass the frozen test.
