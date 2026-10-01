# Core maker / RH hedge: activation comparison

Frozen before capture at `02cc90d`. Public data: 1 October 2026,
14:07:04–14:17:04 UTC, 600 seconds. Each arm is an independent
$100-per-leg portfolio with $200 USDC at Core and $200 USDG at RH.
Core passive buys were placed 10 bp below its best bid; RH shorts hedge
conditional maker fills. These are simulations; no orders were submitted.

| Assumed maker activation | Quotes | Paired closes | Rescue closes | Cash wins | Cash after fees | Capital + 5 bp stress net |
|---|---:|---:|---:|---:|---:|---:|
| 100 ms, primary | 83 | 2 | 0 | 0 | −$0.059399 | −$0.117399610 |
| 400 ms, control | 76 | 1 | 1 | 0 | −$0.067608 | −$0.167451486 |

The four closes across these overlapping counterfactual arms all lost cash.
Do not sum the arms. No-flow episodes numbered 81 and 74. Both finished
flat, without unknown episodes or unresolved quote obligations. The faster
maker activation assumption did not establish profitability in this sample.

One uninterrupted connection per venue; 18,574 records and 2,235,468
compressed raw bytes retained. Independent fill audit passed all 10 taker
book walks and four maker-flow matches, reconciled cash, inventory,
capital and stress, and checked execution delays. Independent quote audit
passed all 159 quote prices, quantities, admission windows, attempt caps
and activation deadlines, including ten preceding depth depletions.

Public trade flow cannot authenticate queue priority, private fills or ACKs.
Core's documented Standard maker delay is zero; the primary adds an assumed
100 ms network delay. RH execution delay remains an assumption based on
archived documentation. IOC minimum-size exemptions are source-consistent
but have not been verified against deployed API admission. USDG/USDC parity,
zero fees and executable depth are conditional. No funding credit was assumed.
