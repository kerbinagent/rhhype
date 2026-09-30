# Prepared three-venue passive-exit capture

**Status: prepared only; no three-venue capture has started.** The [new capture wrapper](../scripts/passive_three_venue_capture.py) and [offline tests](../tests/test_passive_three_venue_capture.py) support a future comparison of the **same RH Lighter maker entry and passive exit** hedged on Hyperliquid or Lighter Core Standard. This preparation does not alter the frozen [passive-exit v1 protocol](../reports/rh-passive-exit-v1/protocol.json) or its recorder, event adapter, model, or engine. It makes no trading request.

## Feasibility and route identity

The current public monitor plan has all four proposed perp assets on three distinct venues. These IDs are **plan candidates**, not permission to run on stale metadata:

| Underlying | RH Lighter (`rh_lighter`) | Hyperliquid (`hyperliquid`) | Lighter Core (`lighter`) |
|---|---:|---|---:|
| BTC | 1 | BTC | 1 |
| ETH | 0 | ETH | 0 |
| NVDA | 15 | `xyz:NVDA` | 110 |
| XAG | 41 | `xyz:SILVER` | 93 |

The same BTC/ETH numeric IDs on RH and Core are a coincidence across **separate domains and order books**; the raw `venue` field always remains `rh_lighter`, `hyperliquid`, or `lighter`. The [Robinhood Chain domain documentation](https://docs.robinhood.com/chain/lighter-domains/) identifies the RH domain separately from Lighter Core. The existing [stopped three-book diagnostic](rh-hedge-venue-choice.md) gives a reason to study Core as an alternative hedge, but its static quote paths did not establish passive fills or profitable completion.

The recorder subscribes to full order books, ticker, and ordinary public trade feeds on both Lighter domains, plus Hyperliquid BBO, L2, and trades. It reuses the public recorder's per-venue book snapshot/nonce checks, separate connection generations, source-time regression annotation, and receipt UTC/monotonic stamps. A bounded update-trade ID set annotates repeated IDs **within venue, market, and generation**; subscribed backlog and liquidation prints stay in raw frames and must be excluded from fresh flow by a future adapter. ID-cap exhaustion ends capture rather than silently losing exact dedupe. Gaps/reconnects invalidate the affected generation; no cross-generation order book is reconstructed. `wire_ok` remains a frame-level check, not an executable or synchronized book claim.

## Metadata and limits

Before a future run, the wrapper requires six fresh, byte-preserved public responses: RH and Core `orderBookDetails` and `assetDetails`, and Hyperliquid native and xyz `meta`. It records HTTP method, URL, start/end UTC timestamps, status, raw byte count, and SHA-256; the frozen market plan is hashed. The run refuses metadata older than 30 minutes. It checks each Core market's ID/symbol, active perpetual status, unit contract and quote multipliers of 1, current and supported decimal grids, minimum base/quote amounts, maximum quote amount, and metadata zero maker/taker fees. The RH/HL checks reuse the existing frozen metadata normalizer. Core prices and sizes are then per one base perp unit on its declared decimal grids. RH `assetDetails` must show margin-enabled USDG, and Core `assetDetails` must show margin-enabled USDC. These checks establish eligible collateral assets, not the actual wallet holdings or sole allowable collateral. The future analysis must model the separate prefunded wallets and any conversion rather than treating those dollars as identical cash.

The default invocation is **dry** and prints routes/subscriptions only. A future authorized `--fetch-metadata` makes six public reads and writes a new immutable metadata directory; `--run` requires that directory and an explicit flag. Hard bounds are **3,000 seconds and 384,000,000 bytes total** across raw gzip frames, copied metadata, and manifest. The frame writer reserves manifest space and stops before a partial record. It records a final frame hash, truncation reason, error counts, generation records, and quality counts. A stopped venue after bounded reconnects ends the entire capture so a long two-venue tail is not mistaken for three-venue coverage. No private endpoint, authenticated fee quote, order acknowledgment, fill, or account state is observed.

## Required before an execution comparison

1. Freeze the new study's protocol, route plan, fresh metadata, tier/delay assumptions, and code hashes **before** opening sockets. The Core Standard public account table lists zero maker/taker fees and a 300 ms taker processing delay; these are account-type assumptions, not a measured account quote or network latency. See the [Core account table](https://apidocs.lighter.xyz/docs/account-types), the [RH account table](https://apidocs.rh.lighter.xyz/docs/account-types), and the [HL fee table](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees).
2. Freeze and use the **new** [three-venue event adapter](../scripts/passive_three_venue_events.py), whose offline contracts are described below. The frozen `rh_maker_events.py` accepts only RH and HL; mapping Core frames to `hyperliquid` would corrupt source and fee provenance.
3. Pair each actual hypothetical RH entry episode with both hedge branches at the **same entry time and quantity**, then apply each venue's processing delay, first eligible book, lot/minimum rules, fees, separate collateral, funding boundaries, and exit obligations. Missing Core coverage should be an explicit censored branch, not a later substitute book. Public trade-through is still only a possible maker fill because queue position, cancellation acknowledgment, and private execution are unknown.

No capture or strategy selection follows from this preparation alone.

## Prepared offline event adapter

[passive_three_venue_events.py](../scripts/passive_three_venue_events.py) now streams normalized book, ordinary trade, invalidation, control, and end records for a future capture. This is still preparation; no three-venue archive or comparative execution result exists. It reuses `maker_book_archive.BookRebuilder` and its full-book parsers without changing any of the 18 frozen v1 files. Every source event has `source_venue`, `source_market`, and `source_generation`; the corresponding `venue`, `market`, and `generation` retain that same identity. Optional `hedge_venue='hyperliquid'` or `'lighter'` adds a semantic `role` (`maker`, `hedge`, or `reference`) without changing source fields, fees, IDs, or timestamps.

The caller supplies an independently pinned manifest SHA-256, and the adapter verifies that manifest before taking its gzip hash, selected routes, and bounds as input. It verifies the gzip bytes, compressed byte count, record count, complete NDJSON lines, receipt order, available receipt monotonic stamps, and configured duration. Hard replay bounds are 384,000,000 archived bytes, 4 GiB decoded bytes, 2,000,000 records, 8 MiB per line, 750,000 retained trade IDs, and 12 source generations. Callers may lower those limits. All six frozen metadata responses and their request records are checked against their recorded method, endpoint, HTTP status, byte count, and payload SHA. The frozen plan and normalization must match the captured route selection, including **Core's own market IDs**. Every response must have completed before capture start and within the preceding 30 minutes; offline replay does not confuse that requirement with freshness on the later replay date. Metadata files, raw gzip, and manifest are hashed again before the completion marker.

RH and Core update trades use independent venue/market/generation ID sets, including deduplication within a batch. `subscribed/trade` backlog and liquidation arrays are excluded from fresh flow. Ordinary trade objects must identify the selected market of their actual domain. Malformed batches, future source times, source regressions, or exhausted ID capacity invalidate that market's flow before any partial batch is emitted; later flow stays censored until a new source generation. Trade nonce values are retained as observations, with **no inferred trade nonce continuity**. Hyperliquid public trade objects are normalized using their own coin, side, and trade ID fields.

Book snapshots and nonce deltas remain independent by source. A nonce gap, invalid annotation, source regression, missing snapshot, or source clock ahead of receipt produces an invalidation. A future book cannot seed later deltas. Connection close/error, malformed JSON, explicit generation invalidation, and generation changes clear book/flow continuity; frames cannot revive a terminated generation. BBO and ticker frames never splice or refresh a full book. Capture end invalidates remaining books and flow. The final end record carries truncation, recorded capture errors, counts, source/metadata hashes, and adapter/decoder hashes. A consumer must require this completion marker before trusting a complete replay; it must explicitly censor missing coverage and errors in a later execution comparison.

`hedge_execution_assumptions(...)` is a separate helper for a later replay. Core uses its own verified public Standard profile: zero metadata maker/taker fees and **300 ms taker processing plus an explicitly supplied network delay**. Hyperliquid's default 150 ms processing value is explicitly labeled a model assumption and has a separate supplied network delay. The adapter never shifts event timestamps or applies these delays itself. Execution still requires same-entry paired branches, each venue's lot/notional rules, prefunded collateral, fees, funding, and exit obligations; this adapter supplies no private fills, acknowledgments, queue model, P&L, or engine comparison.

Offline verification:

```bash
python -m unittest discover -s tests -p 'test_passive_three_venue_events.py' -v
```

The synthetic tests cover separate venue provenance/IDs/fees, backlog and liquidation exclusion, duplicate IDs, generation resets, nonce gaps, future books and trades, independent source regression checks, connection close/error handling, metadata freshness and own Core identity, manifest/gzip/metadata hash rejection, and payload bounds. A future offline invocation takes an already pinned hash:

```bash
python scripts/passive_three_venue_events.py CAPTURE_DIRECTORY \
  --manifest-sha256 PINNED_MANIFEST_SHA256 --hedge-venue lighter
```
