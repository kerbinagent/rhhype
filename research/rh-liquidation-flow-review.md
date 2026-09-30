# RH liquidation flow: scope review

30 September 2026, 10:38 UTC. A source review followed by one frozen,
classification-only traversal resolves a possible historical flow omission.
No book reconstruction, price/size economics, fill model or policy changed.

The old quote-distance adapter's `ignored_liquidations` counter included
subscription history before validation or deduplication. Its 62 crypto and
three RWA occurrences therefore did not establish 65 live market events.
The separately frozen classifier (`b6e5d30`) read both complete archives
once, under a 30-second limit. Compressed hashes matched before and after;
full gzip EOF and exact record counts passed. It published
[all classification counts](../reports/rh-liquidation-schema-review.json).

| Archive | Subscription liquidation rows | Live update liquidation rows | Source before capture start |
| --- | ---: | ---: | ---: |
| 19:39 BTC/ETH | 62 (32 BTC, 30 ETH) | 0 | 62 |
| 20:22 NVDA/XAG | 3 XAG | 0 | 3 |

All 65 identities are unique within their archive, all have type
`liquidation`, and both order identifiers are positive. Those identifiers
are descriptive; they do not prove an arbitrary hypothetical resting order
could have received the fills. All 65 are history preceding the captures,
so they cannot add flow to the later fixed ten-second quote windows.
Ordinary live update rows are 602 crypto and 105 RWA, consistent with the
older adapter totals. No nonreach, fill or profitability result is revised.

## Mechanism and remaining uncertainty

The [official Core WebSocket schema](https://apidocs.lighter.xyz/docs/websocket-reference)
separates ordinary and liquidation arrays and lists trade, liquidation,
deleverage and market-settlement types. It does not establish which records
represent matching against arbitrary resting orders. The [August 2025
zkSecurity block-circuit audit](https://resources.cryptocompare.com/asset-management/21393/1767888049289.pdf)
describes partial liquidation through an IOC order, separately from an
internal deleverage transaction that selects a counterparty and forces a
trade. An IOC could match resting orders; that is a mechanism inference,
not a current RH public-record mapping. The audit is historical, and the
reviewed current Core schema cannot establish RH behavior by analogy.

The peer source review agrees that blanket exclusion might omit reachable
liquidation flow in some other sample. Omitting fills is not necessarily
conservative for P&L: omitted fills can also create inventory and hedge losses.
The old results retain their ordinary-print-only scope. No all-liquidation
inclusion or guaranteed-inaccessibility claim is warranted.

The RH documentation pages and Lighter index were inaccessible during this
review (the index returned HTTP 403 via the direct bounded fetch). No VPN or
access workaround was used. Third-party summaries were discovery aids only;
mechanical conclusions above rely on the primary API schema and circuit audit.

## Decision and resources

This sample supplies no live liquidation event for another maker-flow study.
No strategy replay or successor capture follows. The separate allocation is
20,000 bytes: source/docs 12,000, output 6,000, provenance 2,000. It preserves
all prior allocations, taking the shared reservation to 32,742,904/33,000,000
bytes (257,096 remaining). Original raw inputs remain untouched and referenced
by digest. The canonical delayed-taker studies were not rerun or amended.
