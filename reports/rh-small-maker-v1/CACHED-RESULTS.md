# RH maker pilot: cached replay readout

29 September 2026. **No profitable strategy established.** This report is
from the explicitly labeled post-freeze immutable-book-cache wrapper. The
unchanged original replay is still running; full-capture equivalence is
pending. Synthetic financial and ordered-audit equivalence tests passed.
The original method, model and execution source hashes remain unchanged.

The capture ran 21:21:32–22:11:32 UTC: 30 minutes calibration followed by
20 minutes evaluation, four assets, four sizes, three quote policies and
two account tiers. Those 96 branches are independent counterfactual
portfolios on shared public events, not independent experiments or income
to add together. The cached replay completed without errors in 1,513.68
seconds, with 86,572 audit records in 12,967,541 compressed bytes.

## Primary panel: Standard, $1,000, adaptive RH bid

All four primary models met the predeclared calibration gates. Their
observed close-sample coverage was about 98.9%; flow-hedge coverage ranged
from 83.3% to 97.0%. Calibration readiness did not establish executable flow.

| Asset | Close samples / flow samples | Quote requests / observed activations | Closed episodes without attributed flow | Filled closes | Final uncertainty |
|---|---:|---:|---:|---:|---|
| BTC | 177 / 68 | 320 / 320 | 319 | 0 | Capture ended with outstanding quote obligation |
| ETH | 177 / 75 | 331 / 330 | 330 | 0 | Capture ended with outstanding quote obligation |
| NVDA | 173 / 64 | 15 / 14 | 14 | 0 | Activation book timeout |
| XAG | 174 / 32 | 45 / 45 | 44 | 0 | Cancellation confirmation book timeout |

The BTC primary quotes were behind the best bid throughout their recorded
quote decisions. There was no maker-attributed flow in **any adaptive branch**,
including the $100/$250/$500 sensitivities or Premium scenarios. Closed
no-flow episodes have zero cash contribution; unresolved quote obligations
prevent a complete zero-return claim. NVDA and XAG stopped on uncertainty
early, so their nominal twenty-minute horizon is not full active coverage.
All primary recorded inventories were zero at termination, but the model
could not rule out the indicated execution obligations.

## Fixed-best control and account tiers

Only Premium fixed-best BTC and ETH branches had completed filled episodes:
eight BTC and two ETH per size, all losing. These reuse correlated public
flow across sizes; they are not forty independent fills. Closed contributions
after modeled fees, reserve and capital were:

| Asset | $100 | $250 | $500 | $1,000 |
|---|---:|---:|---:|---:|
| BTC | -$1.4858 | -$3.6164 | -$6.3569 | -$9.6996 |
| ETH | -$0.3785 | -$0.9273 | -$1.4194 | -$2.4032 |

At $1,000, cash after trading fees but before reserve/capital was already
negative: BTC -$7.1008 and ETH -$1.7833. Premium has faster modeled request
processing and positive explicit fees; Standard has zero RH trading fees
and slower modeled processing. Each was rerun with its own timing, rather
than subtracting one fee tier from another tier's fills.

Every branch ultimately ended with an unresolved condition. Across the 96
branches: 32 capture-end obligations, 28 activation timeouts, 16 cancellation
confirmation timeouts, 12 eligible-flow-before-queue ambiguities, four
trade/cancel ordering ambiguities, and four eligible-flow-before-activation
ambiguities. Complete portfolio returns are therefore **unknown**. No branch
had a positive completed filled episode, but censoring means this is not a
complete economic rejection of all RH maker strategies.

## Timing and independent validation

Standard primary decision-to-observed-activation means were 0.478s BTC,
0.477s ETH, 0.791s NVDA and 0.881s XAG. These include configured processing
delays and eligible public-book observation; they are not private order ACKs.
For the $1,000 Premium fixed-best control, public-flow-to-hedge-result means
were 0.730s BTC (16 increments) and 0.808s ETH (two increments). Exit-request-
to-flat means were 0.784s and 0.735s respectively. No profitable opportunity
lifetime can be estimated from the primary no-flow branches.

The independent retired-quote late-flow audit verified provenance and scanned
4,459 RH trade events, including 2,182 sells, against 12,784 retired activated
quotes with remaining quantity. It found **zero affected branches/episodes**
for that specific defect. This does not validate private queue execution,
remove the other ambiguities, or establish original/cached equivalence.

The lifecycle postprocessor initially rejected one aggregate by 1E-28 because
it summed Decimal components in a different order. It now matches the
frozen episode-by-episode operation order exactly and discloses the tiny
component-rounding residual. The original financial output was not changed;
ten lifecycle tests pass.

## Evidence and next decision

[All branch summaries](cached-branches.csv),
[compressed full analysis](cached-analysis.json.gz),
[compressed lifecycle measurements](cached-lifecycle.json.gz),
[late-flow validation](cached-late-flow-validation.json), and
[checksums](cached-evidence-manifest.json) are retained. Full raw capture and
compressed audit remain in their bounded local data directories.

Keep $1,000 primary and $100 minimum. The observed failure is a trade-off
between quote economics, public-flow access and execution uncertainty,
not evidence that still smaller orders solve the problem. The prepared
[symmetric bid/ask implementation](../../research/rh-maker-symmetric-replay.md)
requires a fresh frozen protocol before collection. Maker sells, passive
inventory exits and alternative hedge venues remain separate hypotheses;
none is promoted from these censored buy-side results.

When the original replay completes, run `scripts/compare_rh_maker_replays.py`
with the original and cached directories to establish or reject exact
full-capture equivalence. Until then this remains a cached-variant readout.
