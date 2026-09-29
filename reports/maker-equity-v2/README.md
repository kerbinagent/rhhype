# NVDA/silver maker quote study, version 2

Status: code and method audited and frozen before capture.

This is one prospective post-market window, limited to 420 seconds and 25 MB
of compressed capture. The [method](../../research/maker-equity-plan.md),
public fee inputs, selected market metadata and source hashes must be frozen
before launch. The previous BTC/ETH study is a separate experiment.

Fresh public Core/RH market details, selected rows and response hashes are in
`unit-provenance.json`: both contracts were active with multiplier one and
zero published maker/taker fees. Public HL fee inputs were checked separately.
The v1 BTC/ETH replay retains exactly the same 95 cases and 48 cohort summaries
after the canonical HIP-3 market-name adapter.

## What changes

- NVDA and spot-silver perpetual references replace native BTC/ETH perps.
  Sampled HIP-3 fees are 0.3 bp maker and 0.9 bp taker, versus the prior native
  1.5/4.5 bp assumptions. Lighter Standard remains the declared zero-fee tier.
- Lighter Standard taker steps include 300 ms processing in addition to the
  100 ms observation allowance. Both source and receipt times must follow
  each step's due time.
- The exit is requested five seconds after the hedge quote. A complete
  observed unwind must occur within ten seconds of the public full-flow signal.
- The same original lot-compatible quantity must fit the first eligible
  hedge and paired exit books. Shallow books or venue minimum failures are
  censored immediately, with no retry at a more favorable quote.

## Interpretation

Opposite-aggressor trade volume exceeding displayed queue ahead plus the full
lot is a **hypothetical flow condition**, not proof of a maker fill. Orders,
queue priority and cancellations are unobserved. Every missing hedge remains
unresolved hypothetical one-leg exposure; missing exits are not zero-profit
outcomes. Complete-case summaries are selected by depth and feed coverage.

Four fees are charged on their own notionals. A separate five-basis-point
reserve applies to the larger entry leg. RH USDG/HL USDC quotes are compared
conditionally at parity; executable conversion and collateral fungibility
remain unmodeled. Equity and silver oracle differences can sustain a basis.

The 0.5/1/3-second maker-arrival scenarios and adjacent anchors share market
data. Their results cannot be summed as independent trades or daily income.
There is no all-taker control in this version, so it cannot isolate the maker
feature's incremental effect. No trading-policy change follows from a positive
displayed quote alone.
