# Streaming replay adapter for the RH maker capture

`scripts/rh_maker_events.py` converts a stopped public capture into ordered replay events. It does not place orders, infer maker fills, assign queue position, or calculate P&L. Consumers call `iter_events(capture_dir)` and process each yielded dictionary immediately; they need not load the capture or write another full-book archive. The final `end` event is mandatory for a complete replay. An exception before it means the replay failed and its partial observations must not be used as a completed cohort.

## Input and integrity

The adapter reads `manifest.json` and concatenated-gzip `frames.jsonl.gz`. It requires the exact compressed-frame SHA-256 recorded in the manifest (or supplied as `expected_raw_sha256`) and verifies the gzip again after replay. The `end` event gives the raw gzip, manifest, adapter, and imported full-book decoder hashes, together with the manifest start/stop, end reason, truncation flag, record counters, source-lag diagnostics, and decoder counters. Capture frames must have nondecreasing receipt UTC nanoseconds; equal timestamps preserve file order. It never estimates a clock offset or shifts source times.

Hard input limits are 512 MB for the whole archive, 4 GiB decoded, two million records, 8 MiB per NDJSON line, 3,001 seconds declared duration, and one million retained RH trade IDs. The iterator uses bounded `readline` and maintains only the latest decoder book state and bounded trade-ID sets. It rejects a bad hash, malformed record, backward receipt time, excess bound, or manifest count mismatch.

## Event contract

| `type` | Key fields | Meaning |
| --- | --- | --- |
| `book` | `venue`, `asset`, `market`, `generation`, `received_ns`, `receipt_ns`, `source_ns`, `sequence`, `valid=true`, `clock_valid=true`, `bids`, `asks`, `feed`, `level_count` | Complete public book as reconstructed by `maker_book_archive.BookRebuilder`. Levels are `[price, quantity]`; no BBO or ticker depth is spliced into it. |
| `trade` | Identity and times above, plus `price`, `qty`, `trade_id`, `side`, `buy_aggressor`, `clock_valid=true` | RH ordinary public trade only. `side` is the **aggressor**: `is_maker_ask=true` means a resting ask sold, so the aggressor bought. |
| `invalidate` | Identity, `received_ns`, `scope=book\|trade`, `reason` | Clear the affected book or trade-flow state. A malformed ordinary trade batch invalidates its entire asset and generation; source time ahead of receipt is malformed. No trade nonce-gap rule is invented. |
| `control` | `venue`, `generation`, `received_ns`, `control` | Connection open/close, invalid JSON, connection error, or generation invalidation. These are distinct from the resulting book/trade invalidations. |
| `end` | `started_ns`, `stopped_ns`, `reason`, `truncated`, counts and hashes | Terminal provenance and continuity diagnostics. Missing end is a failed replay. |

The adapter excludes subscription trade backlogs and liquidation trades from maker-flow evidence, counts both, and deduplicates live trades by exact market/generation/trade ID. A malformed or source-ahead batch invalidates the entire RH trade stream for that asset/generation; later same-generation batches are suppressed until reconnect. The public trade stream does not establish hypothetical ALO acceptance, queue position, or a fill. The engine must gate trade **source and receipt** against its own activation time and treat invalidations as pending-candidate censors. A book's presence alone does not satisfy freshness, quantity, fee, or execution constraints.

The `generation_invalidated` capture control is translated into a close for the committed full-book decoder so HL snapshots and RH delta state both clear. It also invalidates RH trade flow. Capture `connection_close`, `connection_error`, and `invalid_json` do the same. Repeated terminal controls can produce repeated invalidations; consumers should handle clearing idempotently. Large receipt gaps and trade source lags are counted, not silently calibrated away.

## Validation

Run `python -m unittest tests.test_rh_maker_events -v` and `python -m py_compile scripts/rh_maker_events.py`. Tests cover full-book normalization, subscribed-backlog exclusion, aggressor side, exact deduplication, batch invalidation before partial emission, source-ahead clocks, disconnect/error/generation clearing, hash failure, backward receipts, and declared duration. A smoke replay of the earlier stopped NVDA/XAG archive (`data/raw/maker-capture/20260929T2022Z`) emitted 5,864 full-book events and 105 RH ordinary trades, excluding 100 subscribed backlog rows and three liquidations; this is a parser check, not a new strategy result. The forthcoming 50-minute capture remains a separate prospective input and has not been analyzed here.
