# Core maker sells / RH buys: exploratory replay

Frozen policy `a287566`; reused the completed 1 October 2026,
14:07:04–14:17:04 UTC LIT capture after buy-side results were known.
This is exploration, not prospective replication. $100 maker quote budget,
$200 Core USDC and $200 RH USDG prefunding. No actual orders.

83 quotes produced 81 no-flow episodes and two fully hedged closes:

| Maker fill | Maker notional | Hedge notional | Cash after fees | After capital + stress |
|---|---:|---:|---:|---:|
| Full 25.71 LIT | $99.999045 | $100.091139 | −$0.086952 | −$0.137000982 |
| Partial 4.15 LIT | $16.145160 | $16.150555 | +$0.000830 | −$0.007245828 |
| Portfolio | | | **−$0.086122** | **−$0.144246809** |

The nominal $100 budget limits the maker quote; the delayed hedge can exceed
$100 slightly within its 10 bp price limit. The sole cash gain was on about
$16 of filled notional. No rescues, unknown episodes or unresolved obligations.
The result does not establish a profitable policy.

Quotes were 10 bp above the current Core best ask, rounded upward, with
100 ms maker activation, 400 ms cancellations and all taker orders, five-second
quote rest, and ten-second holding limit. The configured 1 bp profit target
was applied to the executable mark **after capital cost and the 5 bp reserve**.
Thus it required roughly 6 bp cash gain on a full-size pair; on partial fills
the target remained $0.01 while reserve scaled with filled notional. The
reserve was not an exchange fee, but it influenced this executed exit policy.

Independent audits passed all eight fills: six raw taker book walks, two
maker public-flow matches, fees, lot sizes, advanced source times, 400 ms
delays, first eligible executions, cash, capital and venue balances. A second
audit checked all 83 quote formulas, admission gates, freshness/skew, activation
queue snapshots and six preceding depth depletions. Public queue allocation,
IOC minimum exemptions, private ACKs/fills and USDG/USDC conversion remain
conditional. Source, input and outputs are hashed; the complete trace remains.

See `exit-threshold-clarification.json` for the same inherited reserve behavior
in the earlier Core buy and fair-value explorations. Their frozen results remain
as executed. A cash-based exit trigger is a separate variant requiring its own
outcomes; changing the description cannot create a profit.
