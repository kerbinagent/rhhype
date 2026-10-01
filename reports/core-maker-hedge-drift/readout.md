# Where the maker margin disappeared

Post-hoc diagnostic of the existing 14:07–14:17 UTC Core/RH LIT capture.
Five recorded fill increments span three overlapping policies and only
three distinct market events. They are not independent observations.
All numbers below are conditional public-book simulations.

| Event | Actual receipt-to-hedge-book delay | RH executable proceeds change | Observed outcome |
|---|---:|---:|---|
| First full fill, shared by both fixed-offset arms | 538 ms | 0 bp | Entry credit $0.040462; closing debit $0.082016; cash loss $0.041554 |
| Later full fill, slow fixed-offset and fair-value arms | 481 ms | −14.90 bp | Both 10 bp hedge limits filled zero; both required Core liquidation |
| Later partial fill, fast fixed-offset arm | 495 ms | −4.89 bp | Entry spread moved from +$0.000830 to −$0.007055; final cash loss $0.017845 |

For the fair-value quote, the delayed RH book offered about $0.149 less
proceeds on the $100-sized leg than the book visible when the maker fill
was reported. Its original forecast margin was about $0.0617. The forecast
was not locked in before the hedge market moved. The failed hedge is
preserved as a rescue, not silently modeled as a completed pair.

The first full fill had no hedge-price deterioration, yet still lost money:
its exit cost exceeded the entry credit. Faster hedging alone would not
resolve that example. The observed problems include both closing-spread
cost and adverse price changes while a hedge is pending.

The diagnostic reconstructs branch-specific remaining depth from the raw
books and audited fills. Reference books at maker-flow receipt were
76–91 ms old by their source timestamps. Delayed unlimited proceeds for
failed hedges are hypothetical quoted depth, not actual fills. No hypothetical
round-trip profit is calculated. Public trade-reporting delay, private ACKs
and actual queue priority remain unverified.
