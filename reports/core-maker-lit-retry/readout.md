# Fresh LIT maker replication

Frozen `6c13c28`; public capture 1 October 2026, 13:40:44–13:50:45 UTC.
This prospectively repeats the corrected RH-maker/Core-hedge IOC scenario,
with both 5 bp and 10 bp offsets. The 10 bp arm was declared primary before
capture because its earlier exploratory replay had positive cash. Each arm
uses independent $100-per-leg / $400-prefunded accounting. No actual orders.

| Offset | Quotes | Paired closes | Cash wins | Cash after fees | Capital + 5 bp stress net |
|---|---:|---:|---:|---:|---:|
| 5 bp | 69 | 4 | 0 | −$0.428146 | −$0.628106152 |
| 10 bp | 70 | 2 | 0 | −$0.044492 | −$0.117557046 |

All six paired closes lost cash. No failed-hedge rescues, unknown episodes,
remaining inventory or live quote obligations. No-flow closes numbered 65
and 68. The earlier exploratory cash gain did not repeat prospectively.
The arms overlap and must not be summed as one portfolio.

The full 600-second capture ended normally with 20,218 retained records,
2,507,349 compressed raw bytes, 48,312 metadata bytes, one continuous
connection per venue and no transport errors. Frozen manifest SHA-256:
`ccdf325c8f088cfbb69a2cb34c8f0cc7a2724efd1837b246b64d7c33a32d6a27`.
The first sandboxed attempt timed out during its first metadata GET before
any market data. That failed attempt and its plan remain preserved separately;
the retry was frozen before collection and used the same economic rules.

Independent fill audit passed 20 taker depth walks and eight maker flow
matches, consuming exact scheduled hedge intents and ordered episode
boundaries, reconciling wallets, inventory, fees, capital and first eligible
books after 400 ms delays. A second raw-event audit checked all 139 quote
prices, quantities, admission times, attempt caps and activation deadlines.

Maker fills remain conditional public-flow queue simulations; private ACKs
and fills were not observed. The published validator's IOC minimum exemption
has not been verified against deployed API admission. USDG/USDC parity and
zero Standard fees are conditional. This is evidence against the tested
policy's profitability in this session, not proof that every maker policy
is unprofitable.
