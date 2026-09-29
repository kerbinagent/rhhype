# Closing spread versus exit delay

29 September 2026. The user asked whether losing unwinds are a latency
problem or were already unprofitable at the close decision.

The [review 19 decomposition](../reports/review19-baseline-spreads/REPORT.md)
found $100.6030 of opening price difference versus $132.3612 of final
closing liability across 91 paired paper trades. Gross P&L was -$31.7582
before fees. All 91 exits were **max_hold**, with no take-profit exit.
Their median exit-request-to-flat interval was 1.236 seconds.

That interval alone does not measure the loss caused by waiting. Deadline
exits stored no `exit_trigger_pnl_usd`, and their bounded detailed quote
evidence was already evicted when this question was investigated. Therefore
this cohort cannot establish the exact request-time versus fill-time loss.
The previously measured $1.0566 deterioration concerns **entry**, not exit.

An opening difference between two perpetuals is not locked-in profit: both
positions must be unwound. Persistent cross-venue basis and crossing both
books can erase it even with unchanged prices. For example, buy at 100 and
sell at 101, then sell the long at 99.90 and buy back the short at 101.10:
the gross result is -0.20 before any fee, with no intervening price move.
The ten-second deadline requests an exit even when convergence has not paid
for these costs; it is not a profitability guarantee.

## Prospective measurements

An unfrozen `ObservedPaperEngine` subclass attaches one compact record at
the first exit-intent request. It preserves the frozen base engine and
changes no policy, intent timing, fills, or accounting. The record retains
up to two exact remaining quantities, size-walked exit values, fee rates,
source and receipt ages, clock/receipt-skew checks, and a net liquidation
estimate when available. Funding uncertainty does not erase valid price
information. Old restored exits cannot acquire invented request-time books.

Scheduled reviews now calculate, for fully matched paired exits:

`exit price deterioration = actual closing liability − request-time closing liability`

Positive means the recorded close became more expensive; negative means it
improved. The metric excludes fees, funding, reserve, and capital. Missing
legacy/stale/shallow/partial observations remain explicit; zero observations
produce an unknown aggregate, not a zero-dollar effect. It measures changes
in public-book paper prices, not the causal effect of real network latency
or guaranteed executions at the earlier quote. The source/receipt ages are
needed to interpret stale observations and asynchronous books.

## First prospective check, 22:46 UTC

The [first review after deployment](../reports/unwind-instrumentation/first-review.json)
contains four valid baseline paired closes: three CRCL and one MSFT. All
four net liquidation estimates were already negative at the exit request,
totaling **-$3.540519**; final net was **-$3.801247**. Three closing prices
were unchanged within floating-point precision, and one worsened by
**$0.260744**. This price-only change differs slightly from the net change
because fees/capital can also change.

One other newly instrumented paired close lacked valid request prices; 85
older paired closes lacked the new record. They are not assigned zero
deterioration. These four concentrated observations support a preexisting
closing deficit in this tiny cohort; they cannot establish its prevalence
across all routes or the effect of a faster real execution system.
