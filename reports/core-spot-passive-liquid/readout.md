# LIT / ETH passive spot entry, native perpetual hedge

Protocol frozen at `1485ebb`. Fresh read-only capture **2026-10-01 17:19:42.535829–17:29:43.353336 UTC** (600.818 seconds): one connection, no feed errors, 28,172 records and 3,840,542 compressed bytes. Two independent $600 USDC portfolios with $100 targets per leg; these are not a combined $600 portfolio.

## Result

| Asset | Quotes | Public-flow touches | Attributed fills | Cash / stressed P&L | End state |
|---|---:|---:|---:|---:|---|
| LIT | 6 | 1 | 0 | $0 / $0 | Flat, $600 cash |
| ETH | 0 | 0 | 0 | $0 / $0 | Flat, $600 cash |

No rescue, unknown inventory, funding payment or capital charge. Five LIT quotes canceled after the best bid changed; one canceled when the book pair failed freshness/skew checks. Actual activation observations arrived 197–456 ms after decision. The frozen assumed network/maker delay is 100 ms, but the model waits for an eligible observed book and does not invent a timely private ACK.

Both independent audits passed: six admissions, 649 reference rows, six queue episodes, six first-eligible activations and six first-eligible cancellations. All actual entry values were zero. Fill/exit/capital checks are vacuous. Both replay and audits completed without errors; the previously repaired, pinned schema adapter was used from the start. Conservative request-count bounds also pass the published limits.

## What the trade flow showed

After subscription backlogs were excluded and IDs deduplicated, the capture contained **442 LIT prints** totaling about **$76,784**, and **38 ETH prints** totaling about **$6,949**. LIT median print size was only $0.75; 282 were below $10.

Only one LIT sell print met a quote's active-time and price conditions: **16.02 LIT**, about **$63.02**, against **1,399.75 LIT / $5,506.62** of equal-price displayed queue ahead. It consumed queue and produced no modeled fill. Its existence does not establish that a different quote would have earned money.

`quote-flow-diagnostic.json` preserves each quote's activation delay, cancellation cause, queue size, forecast and eligible sell flow. Its one-tick diagnostic keeps the old time interval solely to measure available flow; it is not a new strategy replay or P&L estimate.

## Next hypothesis

A distinct prospective LIT-only test can improve the bid by one valid price tick, remain strictly below the ask, and account for the higher entry cost in the same historical-basis forecast. An adaptive cancellation rule is required so an inside quote is not automatically canceled merely because it differs from the public best bid. This changes quote price and cancellation behavior; it needs fresh data, explicit frozen rules, and independent audits. No code for this next hypothesis is included in this result.

## Execution and resource notes

Current Standard-account documentation agrees with zero fees, zero maker processing delay and 300 ms taker/cancel processing. The additional 100 ms network allowance remains an assumption. Source URLs and the current published request limits are retained in `documentation-check.json`.

Offline reconstruction of dense books took several minutes. Its CPU priority was lowered to nice +10 after the background monitor reported higher loop delay; independent audits also ran at nice +10. The capture had already completed. Runtime evidence is retained without asserting that the replay caused the monitor's delay.
