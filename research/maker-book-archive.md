# Reconstructed public full books for future RH maker research

The earlier NVDA/XAG maker and all-taker analyses used HL BBO and Lighter ticker quotes. The stopped [20:22 UTC capture](../data/raw/maker-capture/20260929T2022Z/manifest.json) also contains complete HL `l2Book` snapshots and Core/RH Lighter `order_book` snapshots plus nonce-linked deltas. [maker_book_archive.py](../scripts/maker_book_archive.py) reconstructs those full books into a separate [bounded event archive](../reports/maker-book-archive-v1/derived/manifest.json). It does not change either earlier replay or infer trades, queue position, latency, or fills.

## Reconstruction contract

- Read the original gzip NDJSON one **bounded record** at a time. The source must fit its 25 MB compressed capture cap, declare at most 200,000 records and 601 seconds, and expand to at most 256 MiB; a decoded line above 8 MiB fails. Output gzip plus diagnostics and manifest are capped at 25 MB. The archive records source and output SHA-256 hashes, the decoder file SHA, event count, decoded byte count, and an explicit end reason.
- Reuse `paper_streams.StreamManager` for the full-depth decoder. Lighter/RH starts with `subscribed/order_book` snapshot, applies `update/order_book` price/size upserts and zero-size deletions only when `begin_nonce == prior nonce` and new nonce increases, and invalidates on a gap, malformed/crossed/empty/overflow book, or disconnected generation. Up to 5,000 levels per side are retained, matching the production decoder's state limit. Each output event carries original venue, asset, market, generation, source UTC nanoseconds, local receipt UTC/monotonic nanoseconds, sequence, validity/reason, and every reconstructed bid and ask level.
- HL uses only its whole `l2Book` snapshots. An older BBO cannot refresh an L2 timestamp or be spliced into its depth. Ticker messages never refresh Lighter book state. A disconnect or generation change emits an invalid book event for **every** selected market, including HL, so a previously valid book cannot survive a close merely because it remains within an age threshold. Source times ahead of receipt invalidate the book.
- The book is public displayed state decoded to floating-point price/size pairs by the existing paper decoder. Its source and receipt clocks are not calibrated execution latency. It does not reveal the queue ahead of a hypothetical newly submitted order, hidden liquidity, future cancellations, order acknowledgement, or whether displayed depth would remain at order arrival.

The frozen capture had one generation for each venue, no recorded feed errors or invalidations, and 10,619 decoded records (8,060,709 decoded bytes). Reconstruction produced **5,864 valid full-book events and zero invalid events/gaps**: HL NVDA/XAG 79/79 snapshots, Core NVDA/XAG 1,141/2,356 snapshot/delta frames, and RH NVDA/XAG 1,039/1,170. The event gzip is **15,568,115 bytes**, below the 25 MB cap; the anchor diagnostic is 166 rows. These counts are a continuity check on this one archive, not a guarantee for a later capture.

## Post hoc RH coverage at the same 83 anchors

For this diagnostic only, a book or ticker observation is fresh when its **receipt age is at most 1 second**, source age at most 2 seconds, and source does not run ahead of receipt or the anchor. These are the earlier freshness thresholds; the diagnostic does not reclassify prior maker or all-taker cases. The numbers count unique 5-second anchors, before buy/sell or route repetition.

| RH perpetual feed | Fresh full book / 83 | Fresh ticker / 83 | Both fresh |
|---|---:|---:|---:|
| NVDA | **78** | 38 | 38 |
| XAG | **80** | 32 | 32 |

The book stream supplies many more fresh **observations** than the ticker in this post-market window. It does not prove that an order could execute or improve a strategy's realized latency. At the five anchors without a fresh NVDA book and three without a fresh XAG book, the last reconstructed book is excluded under the same clock rule; a quiet ticker does not affect it. [Hyperliquid documents BBO as change-triggered and L2 as a separate snapshot feed](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), which is why this loader never uses BBO to keep an old L2 book alive. The relative Lighter ticker/book cadence is an observation from this archive, not an asserted exchange service-level guarantee.

To assess sizes, `q` is fixed by flooring `$target / RH best ask` to the original common lot (NVDA 0.001 share; XAG 0.01 troy ounce). The frozen RH market minimum quantity, $10 minimum quote, maximum if present, and step are checked against each bid/ask separately. Counts below are **among fresh RH books** and report displayed quantity at one top level versus cumulative quantity over the archived full side. “Full side” has **no price-distance or slippage cap** and is therefore only a depth-availability indicator, not an executable quote.

| Asset | Target USD | Eligible books | Bid top ≥q | Ask top ≥q | Bid full ≥q | Ask full ≥q |
|---|---:|---:|---:|---:|---:|---:|
| NVDA | 25 | 78 | 78 | 77 | 78 | 78 |
| NVDA | 50 | 78 | 78 | 75 | 78 | 78 |
| NVDA | 100 | 78 | 78 | 66 | 78 | 78 |
| NVDA | 250 | 78 | 77 | 66 | 78 | 78 |
| NVDA | 1,000 | 78 | 58 | **13** | 78 | 78 |
| XAG | 25 | 80 | 80 | 80 | 80 | 80 |
| XAG | 50 | 80 | 80 | 80 | 80 | 80 |
| XAG | 100 | 80 | 80 | 80 | 80 | 80 |
| XAG | 250 | 80 | 80 | 80 | 80 | 80 |
| XAG | 1,000 | 80 | **40** | 74 | 80 | 80 |

The $1,000 NVDA ask illustrates why a one-level ticker and a full book answer different depth questions: only 13 fresh books displayed `q` at the best ask, while all 78 showed at least `q` across all ask levels. A future pricing model must **walk those levels and enforce a price/impact limit**. Treating all cumulative depth as available at the best price would be false. RH book freshness and depth are useful inputs for a small-quantity maker quote model; queue-ahead, fill probability, cancellation ambiguity, adverse selection, and opposite-venue hedge timing still require a separately frozen causal method. There is no new profit estimate here.

The [event archive](../reports/maker-book-archive-v1/derived/book-events.jsonl.gz), [anchor rows](../reports/maker-book-archive-v1/derived/rh-anchor-diagnostics.json), and [manifest](../reports/maker-book-archive-v1/derived/manifest.json) are reproducible from the stopped raw capture. The six focused tests cover snapshot/delta and nonce gap handling, ticker isolation, HL L2 isolation and clock guard, disconnect invalidation before the previous one-second expiry, size/minimum checks, and bounded input rejection.
