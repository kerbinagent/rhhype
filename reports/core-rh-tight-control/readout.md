# Same-feed RH/Core entry-limit comparison

Frozen source/plan `06ca761`. Ten crypto assets,900.037seconds, two independent $100-per-leg portfolios with$600each ($300prefunded pervenue). Same synchronized-arrival120-secondmedian,5bp excursion,1bp forecast hurdle,400msorderdelay,60-secondmaximumhold, and1bp priceprofitexit. Arms differ only in the configured entry limit (including its order-budget/lot rounding). No real orders; USDG/USDCparity conditional.

| Arm | Attempts | Paired closes | Failed hedges | Cash P&L | After capital +5bp stress |
|---|---:|---:|---:|---:|---:|
| 1bp entry limit |3|0|3|−$0.064608|−$0.2143748073|
| 10bp entry limit |3|2|1|−$0.197547|−$0.3473117884|

The tighter limit improved cash P&L by$0.132939 in this small sample, but **all three tight-arm trades were failed-hedge rescues**. Its one positive cash result (+$0.002525) was a one-sided LIT unwind; another LIT unwind had zero price P&L before capital, and VVV lost$0.067133. The wide arm had two paired LIT losses ($0.045781,$0.084633) and the same VVV rescue loss. No stressed winners in either arm. These overlapping hypothetical portfolios are alternative policies; returns must not be added as one portfolio.

Each arm saw nine positive forecasts: three entered and six were rejected after the shared predeclared raw soft cap closed admissions. All attempted trades, rejected legs and rescue costs remain included. No aborts, open positions or below-minimum exits at endpoint.

Audit passed all16modeled fills, first eligible retained book callbacks, source/receipt clocks, public lot/minima/size caps, recorded reference-to-admission history, branch wallets and source/raw/metadata hashes. A separate addendum independently recomputed per-trade capital charges and confirmed no funding-hour boundary in any inventory interval. Zero-fee Standard metadata was verified. Full wire data is not retained; callback completeness rests on the frozen collector.

181,458messages,91,096,427ingress bytes,8,083reference samples and686,805compressed retained bytes. One connection pervenue, no errors or runtime truncation. The tighter-limit policy is not validated as profitable: it traded paired fills for short periods of unhedged exposure. A third-party venue follow-up proceeds separately; no current result is retuned.
