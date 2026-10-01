# ETH displayed quote costs — 1 October 2026

Five paired rounds, 02:42:39–02:44:39 UTC, ten public GETs. All 20 size
rows passed structure, depth, RTT and receipt-skew gates. Zero Standard fees.

| Target USDC | Median round-trip cost | Range, bp |
|---|---:|---:|
| 100 | $0.0327 | 0.074–4.282 |
| 250 | $0.0894 | 0.086–4.323 |
| 500 | $0.2085 | 1.849–4.583 |
| 1,000 | $0.4725 | 2.791–5.455 |

Same-snapshot four-side book walks, not fills or a future exit. Snapshot
engine ages are unknown. Opening basis was negative in every row. Quantities
use best-ask target rounding; impact can overspend that target (largest
$1,000-row buy: $1,000.142247). A future cash-limited simulator must enforce
the full-depth budget. All cost identities were rechecked with Decimal.

This small sample does not erase the historical carry lead, but combining
these costs with past funding is only a sensitivity. Future basis, funding,
settlement cash and deposit/withdrawal costs remain unresolved. No promotion.
