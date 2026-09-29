# Bounded public maker research capture

**Status:** implementation and offline tests are complete; **the capture has not been launched**. [`scripts/maker_capture.py`](../scripts/maker_capture.py) records public BTC/ETH quote and trade streams for later queue-ahead and adverse-price research. It does not submit orders, authenticate, request private data, or calculate maker P&L.

## Sources and frozen markets

The script reads only [`data/paper-monitor/markets.json`](../data/paper-monitor/markets.json), freezes its SHA-256 and BTC/ETH market IDs at launch, and fails if either market is missing. The current dry run selects Hyperliquid `BTC`/`ETH`, Lighter Core IDs `1`/`0`, and RH-domain Lighter IDs `1`/`0`. No metadata REST request is needed.

| Venue | Public WebSocket subscriptions for each coin | Source-time fields |
| --- | --- | --- |
| Hyperliquid | [`bbo`, `l2Book`, `trades`](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) | Book `data.time` and each trade `time`, milliseconds. BBO has one level per side, possibly null. L2 levels are aggregated by price. Trades have price, size, aggressor side and ID. |
| Lighter Core | [`order_book/{id}`, `ticker/{id}`, `trade/{id}`](https://apidocs.lighter.xyz/docs/websocket-reference) on the documented read-only WebSocket URL | Book and ticker `last_updated_at`, microseconds; trade `timestamp`, milliseconds, and optional `transaction_time`, microseconds. Book updates carry `begin_nonce`/`nonce`. |
| RH-domain Lighter | The same public read-only channels at `wss://api.rh.lighter.xyz/stream?readonly=true`; a prior bounded BTC handshake received all three feed types. The archived [RH order-level schema](../data/raw/comparators/rh_lighter/20260929T040726Z/sources/orderbookorders.md) is separate from this capture. | Same observed Lighter wire fields. This domain has separate books and USDG collateral. |

The [official Lighter protocol](https://apidocs.lighter.xyz/docs/websocket-reference#order-book) says the initial order-book subscription provides a snapshot, then absolute price-level updates batched about every 50 ms. Continuity requires each update's `begin_nonce` to equal the prior `nonce`; the API-server `offset` need only increase and is not a continuity counter. The collector records the full public frame and annotation. A nonce gap invalidates that market's book until a fresh subscription snapshot; it sends a paced public unsubscribe/resubscribe for that book only. Any disconnect creates a new stream generation, so later analysis cannot silently bridge missing trades or quotes across it. Lighter's [keepalive requirement](https://apidocs.lighter.xyz/docs/websocket-reference#keepalive-requirements) is satisfied with an outbound application ping every 60 seconds even under heavy inbound traffic; protocol WebSocket heartbeat also runs. The script answers a server application ping with a pong.

## Output and hard bounds

By default, the script ends after **600 seconds** or earlier if the data cap is reached. CLI validation forbids durations over 600 seconds and total data caps over **25,000,000 bytes**. The output directory contains only:

- `frames.jsonl.gz`: complete NDJSON records, each individually gzip-compressed as a concatenated gzip member. Every frame stores venue, market, channel, connection generation, UTC receipt nanoseconds, monotonic receipt nanoseconds, parsed source-time range, quality annotation, and the raw public JSON payload. Connection open/close and invalid-JSON events are also recorded when possible. Standard gzip readers can stream the members as one NDJSON file.
- `manifest.json`: frozen market plan hash and IDs, source endpoints, start/end times, termination reason, truncation flag, dropped complete frame count when the cap stops a write, generation boundaries, per-feed counts, nonce/timestamp invalidations, and bounded connection errors.

The writer checks the **compressed bytes of a whole next record before writing it**, so a cap never leaves a partial gzip member. It reserves 65,536 bytes for the manifest and checks that `frames.jsonl.gz + manifest.json <= configured cap`. If the next record would exceed the payload allocation, it records `end_reason=compressed_size_cap`, `truncated=true`, and the dropped-frame count in the manifest. If all three connections end or a termination signal arrives first, the manifest records that reason instead. Each venue has at most three connection attempts; reconnects never reuse a generation. The output directory must be new, preventing accidental overwrite of prior evidence.

Book and trade source timestamps are parsed with explicit expected units and a 2020–2100 range. Malformed book times, null Hyperliquid BBO sides, Lighter nonce breaks, and malformed trade times receive invalid annotations. `quality=wire_ok` means only that the **individual frame** passed parse and local feed checks; it does **not** mean an executable, synchronized book or known queue position. Source-time regressions are flagged **within** a venue, market, channel, and generation. Hyperliquid L2 may arrive after a newer BBO, so the collector never merges their states. The manifest states that no independent clock-offset check was performed. Later analysis must enforce per-channel source ordering, trade aggressor/ID/price/size validity, cross-venue clock skew, and one-time trade attribution. It must reject affected intervals; the collector itself makes no fill claims. Lighter trade messages also retain both `timestamp` and optional `transaction_time` in the raw payload.

## Review and verification

The non-network validation command is:

```bash
python scripts/maker_capture.py --dry-run
python -m unittest tests.test_maker_capture -v
```

The dry run reported all 18 expected public subscriptions and correct BTC/ETH market IDs without opening a socket or creating a file. Ten focused offline tests passed: exact gzip cap and readable output, concatenated gzip member decoding, cap termination reason, malformed timestamp rejection, null-side invalidation, nonce-gap persistence until a new snapshot, bad-trade generation gap, channel-local source regression, public-only market selection, and bounded final manifest. The separate live BTC handshake described in [maker-hedge feasibility](maker-hedge-feasibility.md) established feed availability, but this new multi-venue capture has **not** been started.

For a later reviewed run, the exact command is `python scripts/maker_capture.py` (or add `--seconds 60` for a shorter first check). The resulting data can support prospective trade-flow and post-event markout screens. It cannot identify a hypothetical order's actual queue position or fill probability. A trade-through case remains an **optimistic hypothetical execution scenario**, never observed maker P&L or a mathematical upper bound on it.
