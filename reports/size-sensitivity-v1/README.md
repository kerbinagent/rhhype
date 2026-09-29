# Exploratory size replay evidence

The [frozen method](frozen-method.md) was written before this offline size replay. The design itself was chosen after the earlier NVDA/XAG maker capture result, so this is **post hoc** and uses the same stopped archive. [Full interpretation and coverage](../../research/size-sensitivity.md) accompanies the [summary](derived/summary.json), [all 1,992 cases](derived/cases.json), and [CSV](derived/cases.csv).

| Buy-side target | Candidate route/anchors | Complete conditional quote paths | Matched across all three sizes | Positive after four fees |
|---|---:|---:|---:|---:|
| $100 | 664 | 16 | 9 | 0 |
| $250 | 664 | 12 | 9 | 0 |
| $1,000 | 664 | 9 | 9 | 0 |

Every complete path also had negative gross displayed arithmetic. Missing and shallow first quotes, including one-leg unresolved outcomes, are retained as statuses rather than zero-return trades. The replay contains no actual fills or executable profit claim. The RH arithmetic assumes USDG/USDC parity conditionally and omits conversion execution.
