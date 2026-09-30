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
2. Build and test a **new** three-venue event adapter. The frozen `rh_maker_events.py` accepts only RH and HL; mapping Core frames to `hyperliquid` would corrupt source and fee provenance. The adapter must reconstruct Core and RH books independently, dedupe update trades by source generation, exclude subscribed backlog/liquidations, and propagate invalidations.
3. Pair each actual hypothetical RH entry episode with both hedge branches at the **same entry time and quantity**, then apply each venue's processing delay, first eligible book, lot/minimum rules, fees, separate collateral, funding boundaries, and exit obligations. Missing Core coverage should be an explicit censored branch, not a later substitute book. Public trade-through is still only a possible maker fill because queue position, cancellation acknowledgment, and private execution are unknown.

No capture or strategy selection follows from this preparation alone.
