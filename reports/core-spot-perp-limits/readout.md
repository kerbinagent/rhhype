# Core spot/perpetual limit comparison — prospective paper result

Frozen before capture: dc5ac6e. Ten minutes, 2026-10-01 15:38:48–15:48:48 UTC; one Core connection, 26,207 messages, no reported capture error. LIT and ETH were eligible. One LIT opportunity entered in each independent portfolio; no ETH entry.

| Entry limit | Quantity per leg | Cash P&L | After capital and 5 bp stress |
|---|---:|---:|---:|
| 1 bp | 25.66 LIT | +$0.074855 | +$0.02486044 |
| 10 bp | 25.63 LIT | +$0.074768 | +$0.02483189 |

The variants observed the same event and are not independent wins. Wider limits slightly reduce quantity because the engine reserves the order limit within the $100 entry cap. Each portfolio had $600 USDC prefunded; $100 refers to each leg, not the total account.

For the 1 bp branch, spot purchase cost $99.812268 and sale returned $99.940568. Perpetual short entry was $99.987197 and cover cost $100.040642. Cash profit is their sum, +$0.074855; capital charge was $0.00000096647. Entry requests were at 15:46:31.1607 UTC; both legs were open by 31.7642 and closed by 34.8627. Spot and perpetual orders were separate; no atomic execution is assumed. The take-profit signal remained profitable through the modeled execution delays.

Independent audit passed all eight fills, first eligible retained books, 400 ms minimum order delays, size grids, entry limits, entry minima, past-only basis references and forecasts, settlement intervals, cash accounting and empty terminal spot inventory. Both portfolios ended flat; no abort, rescue, unresolved position or exit below public minimum occurred. Raw normalized callback evidence is retained (79,787 compressed bytes); full wire traffic and idle depth are not retained. Completeness relies on the frozen callback recorder.

This establishes one positive conditional public-book paper event, including a 5 bp cost allowance. It does not establish repeatability, private fills, account eligibility or realized trading profit. The next test is an unchanged prospective replication with all failures retained.
