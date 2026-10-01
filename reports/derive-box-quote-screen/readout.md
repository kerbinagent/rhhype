# Fixed ETH option-box quote screen

**No usable public quote scenario.** Three fixed snapshots between 03:20:07
and 03:21:08 UTC on 1 October 2026 returned zero bid, ask and displayed size
for all four preselected option legs. All 12 cash-budget outcomes remain
unknown. No economic result, fill or P&L was computed.

## Frozen selection and result

The completed catalogue contained 1,010 unique instruments. Before prices,
choose an active expiry 14–45 days away nearest 30 days (earlier tie-break),
then the largest strike at or below 90% of the metadata spot and the
smallest strike at or above 110%. This selected October 30, $2,400/$3,000:
long call 2400, short call 3000, long put 3000, short put 2400. All four
use ETH-USD, USDC, the same option contract and the same expiry.

The source, three 30-second observations and $100/$250/$500/$1,000 cash
budgets were frozen in commit `ba4adc9`. Sizes would be rounded to 0.01 ETH
and require at least 0.1 ETH on every leg, full top-book depth, four-order
fees, a 10%-of-payoff cash reserve, 5% capital charge and 5 bp stress.
No contract, size rule, timing gate or fee assumption was changed afterward.

| Round | HTTP seconds | Leg snapshot ages | Quote/size status | Unknown budget rows |
| --- | ---: | --- | --- | ---: |
| 0 | 0.472 | 7.31–7.46 s | All four legs zero | 4 |
| 1 | 0.424 | 6.90–7.05 s | All four legs zero | 4 |
| 2 | 0.440 | 6.56–6.70 s | All four legs zero | 4 |

In addition to empty books, snapshot ages exceed the frozen five-second
gate. All HTTP responses were successful and retained. The source's bare
quote-validity assertion produced an empty error string in the original
summary. The separate [diagnostic](diagnostic.json) identifies its cause
from those exact retained responses; the summary/source remain unchanged.

## Decision

This sample does not support an executable four-order box. It does not prove
the exchange has no RFQ liquidity. The documented special box fee applies
to recognized RFQ execution, whose price was never requested or observed.
Applying that discounted fee to hypothetical public-book fills would mix
two different routes. No account, private quote, RFQ solicitation or order
was submitted. Theoretical marks were not substituted for absent prices.

The payoff identity q*(K2-K1) remains algebraically valid for the matched
contracts, but entry debit, account margin, settlement costs if applicable,
transfers and execution still need evidence. Actual P&L remains null.
No repeated quote capture follows this failed prerequisite.

## Verification and storage

Before capture, synthetic checks covered terminal payoff across prices,
cash reservation, lot rounding, fee/capital accounting, depth and staleness.
Afterward, all three raw hashes and all 12 individual leg quote/size records
were checked in the root session. No independent-agent audit is claimed.
The 128 KiB allocation stays within the existing 4 MiB active research pool.
