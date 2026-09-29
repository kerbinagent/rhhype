# Hyperliquid public quote cadence probe

**Scope.** Two read-only public WebSocket observations on 2026-09-29 UTC, using one connection per run to `wss://api.hyperliquid.xyz/ws`. The [standalone probe](../scripts/hyperliquid_feed_probe.py) subscribed to `bbo` and `l2Book` for the same three markets, plus native and xyz `allMids`. Run 1 was 17:34:32–17:35:12 UTC (40 seconds), raw [220 KB JSON](../data/derived/hyperliquid_feed_probe_20260929T173512Z.json). Run 2 was 17:37:21–17:37:51 UTC (30 seconds), raw [131 KB JSON](../data/derived/hyperliquid_feed_probe_20260929T173751Z.json). All eight subscriptions per run were acknowledged; no WebSocket errors. These are observed public API behavior at those times, not a cadence guarantee.

## What the public API exposes

Hyperliquid's [official subscription definitions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) specify `{"type":"bbo","coin":"BTC"}` for a best bid and offer update **only when BBO changes on a block**. Its `WsBbo` contains exchange `time` and `[bid, ask]`, where either side can be `null`. A non-null level has `px`, `sz`, and order count `n`. `l2Book` delivers `WsBook` snapshots with the same exchange time field and levels on both sides; its optional `nSigFigs`/`mantissa` fields aggregate price levels. The docs describe a book push on each block at least 0.5 seconds since the previous push. The [official REST info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#l2-book-snapshot) returns at most 20 levels per side. `allMids` supplies only a map of mids, with neither book depth nor a source timestamp; `dex:"xyz"` selects the HIP-3 venue, while no `dex` selects native perps and spot mids. Aggregation parameters change price grouping, not a documented update-frequency guarantee.

## Measured updates

The table uses distinct **exchange source timestamps** for cadence and receipt minus source for one-way age. It omits connection setup and subscription acknowledgements. No synchronized clock guarantee is assumed beyond the machine's UTC clock for the age estimate.

| Run / market | BBO events | BBO median source gap | BBO median receipt age | L2 events | L2 median source gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| 40 s / BTC | 233 | 0.110 s | 0.279 s | 9 | 5.383 s |
| 40 s / ETH | 229 | 0.125 s | 0.279 s | 9 | 5.383 s |
| 40 s / `xyz:SP500` | 190 | 0.135 s | 0.267 s | 9 | 5.383 s |
| 30 s / BTC | 141 | 0.133 s | 0.294 s | 6 | 5.397 s |
| 30 s / ETH | 177 | 0.111 s | 0.294 s | 6 | 5.397 s |
| 30 s / `xyz:COIN` | 58 | 0.210 s | 0.290 s | 6 | 5.397 s |

`allMids` arrived 8 times per dex in 40 seconds and 6 times in 30 seconds, about 5.1 seconds apart, and has no exchange timestamp. The BBO stream changed *size* far more often than price: BTC had only 7 of 232 consecutive updates change either best price in run 1, while every consecutive BTC update changed displayed size. The public API thus gives much fresher top-level quantity as well as price. The longest observed BBO source gap was 1.63 s for BTC, 1.54 s for ETH, 3.54 s for SP500 in run 1; a quiet or disconnected stream can be silent, so receipt freshness and connection health still matter.

## Can the top level support a $1,000 same-size quote?

For each BBO event, this diagnostic sets **one common base quantity** `q = $1,000 / ((best bid + best ask) / 2)`. Buying at the displayed ask is top-level-supported if `q <= ask.sz`; selling at the bid requires `q <= bid.sz`. Both-side counts require both inequalities at the same event. The actual strategy must use its chosen quantity, lot grid, and required side, not this diagnostic's midpoint convention. There were no null sides in these two short samples.

| Run / market | Ask supports buy | Bid supports sell | Both sides support same q |
| --- | ---: | ---: | ---: |
| 40 s / BTC | 233/233 | 165/233 | **165/233 (71%)** |
| 40 s / ETH | 211/229 | 196/229 | **178/229 (78%)** |
| 40 s / `xyz:SP500` | 189/190 | 187/190 | **186/190 (98%)** |
| 30 s / BTC | 141/141 | 137/141 | **137/141 (97%)** |
| 30 s / ETH | 170/177 | 175/177 | **168/177 (95%)** |
| 30 s / `xyz:COIN` | 27/58 | 9/58 | **1/58 (2%)** |

A BBO message **can** provide a complete one-level displayed fill calculation when the selected side's size covers the desired quantity. It cannot value the remaining quantity once the top level is insufficient, and it cannot establish a $1,000 walk through deeper levels. This is especially material for `xyz:COIN` in the measured period. Displayed size is not a fill guarantee after network and order latency.

## Timestamp relation and integration rule

Both feeds carry exchange millisecond `time`, but neither documented message contains a shared sequence number. Across the two runs, **5 L2 packets arrived after a BBO packet for the same coin while carrying an *older* exchange time**. Six L2 packets shared the latest BBO's source timestamp; their top bid/ask levels matched exactly, including price, size, and order count. Publishing an older L2 packet over the latest BBO would therefore regress the quote. These are observation counts, not protocol guarantees.

The existing [stream manager](../scripts/paper_streams.py) consumes only Hyperliquid `l2Book`, and the [paper refresh scheduler](../scripts/paper_refresh.py) already targets public REST books for due intents and held exposure at a bounded rate. A reviewable extension is:

1. Subscribe to `bbo` alongside `l2Book` for selected Hyperliquid coins. Treat every BBO as a **one-level book** with its own exchange time and receipt time. Null bid or ask invalidates that side. Do not splice the fresh top with older deeper levels.
2. Keep source time monotonic per market. Accept a later L2 as full depth; accept an equal-time L2 only if its top price and size match the current BBO; discard an older L2. Reconnect and stale-feed handling must invalidate prior top levels.
3. For the actual proposed base quantity, calculate one-level economics only if every required side's displayed `sz` covers the quantity. If a leg exceeds the top level, mark depth **unknown** until a fresh, rate-gated REST/L2 book with sufficient levels arrives. Keep cross-venue clock skew and stale-source limits in the decision path.
4. Use `allMids` for broad price discovery or a rough alert only. It cannot establish executable bid, ask, or size. Test a small set of routes first because BBO traffic was 2–6 messages per second per active coin in these samples.

This is a quote-observation improvement and an executable-*display* screen. It does not predict fills, adverse selection, or achievable arbitrage profit.
