# Native spot/perpetual displayed execution costs

Three fixed rounds30seconds apart, seven pairs, four sizes; all84rows passed the declared depth/minimum/receipt-timing checks. These are displayed books, not submitted orders or fills. Underlying book timestamps are not independently verified. Standard trading-fee scenario is zero.

| Asset | $100 | $250 | $500 | $1,000 | Sep monthly candle proxy | Proxy minus current $1,000 cost* |
|---|---:|---:|---:|---:|---:|---:|
| ETH | $0.04 | $0.11 | $0.21 | $0.43 | $-0.96 | $-1.39 |
| LIT | $0.11 | $0.27 | $0.55 | $1.15 | $-3.38 | $-4.53 |
| UNI | $0.14 | $0.44 | $1.06 | $2.86 | $3.92 | $1.06 |
| LINK | $1.22 | $3.04 | $6.15 | $12.56 | $2.33 | $-10.23 |
| LDO | $0.40 | $1.06 | $2.26 | $4.96 | $-11.14 | $-16.10 |
| SKY | $1.00 | $2.58 | $5.47 | $56.89 | $1.11 | $-55.78 |
| AAVE | $0.15 | $0.50 | $1.21 | $3.00 | $-2.08 | $-5.09 |

*Cross-period sensitivity only. Current quantities/prices differ from September; this is neither historical execution cost nor future-profit forecast. Costs cross both sides of both books on the same snapshots. Future exit books, execution delay, fees for a private account, collateral solvency and funding-value units remain unresolved. The September proxies already include assumed capital and5bp stress, but not spread/impact.

UNI is the only positive combined sensitivity, roughly$1.06permonth on approximately$2,000committed capital. Weekly candle results are unstable, and median spot daily volume was onlyabout$4,330. This thin surplus does not justify a larger collector or strategy promotion. LINK andSKY are rejected under this current-cost sensitivity; keep all other negative results.

Verified3raw hashes and84independent depth/cost accounting identities. Source frozen in `5b8e181`; synthetic checks covered insufficient depth, four-cross arithmetic and receipt skew.
