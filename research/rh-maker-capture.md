# RH and Hyperliquid small-maker public capture

`scripts/rh_maker_capture.py` is a separate, read-only collector for the BTC, ETH, NVDA, and XAG RH perpetual routes paired with Hyperliquid. The frozen public metadata is at `data/raw/rh-maker-metadata/20260929T210845Z/`: one RH `GET /api/v1/orderBookDetails` response and two Hyperliquid `POST /info` `meta` responses (native and `xyz`). Each exact raw response has a sidecar with method, URL, request body, UTC request/response nanoseconds, status, byte count, and SHA-256. `market_plan.json` freezes route IDs; `normalized.json` records the derived constraints and explicit unknowns. The collector verifies these hashes and the plan before connecting.

The [official Lighter WebSocket reference](https://apidocs.lighter.xyz/docs/websocket-reference) defines full `order_book/{id}` snapshots, nonce-linked deltas, and `trade/{id}` messages. The [official Lighter Python SDK](https://github.com/elliottech/lighter-python/blob/main/lighter/api/order_api.py) documents supported price and size decimal counts and public market metadata. RH's frozen response reports supported price decimals BTC 1, ETH 2, NVDA 2, XAG 4; normalized decimal grids are therefore 0.1, 0.01, 0.01, and 0.0001. These come from explicit metadata, never from displayed book formatting. RH size steps are 0.00001, 0.0001, 0.0001, and 0.01. RH minimum quote is 10 USDG; minimum base quantities and `order_quote_limit` are preserved per market. No max base quantity or processing delay is published in this response, so those fields stay null. The response's Standard maker/taker fee values are zero.

Hyperliquid native and xyz size decimals come from their frozen `meta` response. The [official tick/lot rule](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size) gives prices at most five significant figures and no more than `6 − szDecimals` decimal places for perps, with integer prices exempt from the significant-figure limit. Thus the normalized HL `price_tick` is null and `price_tick_semantics` is `hl_perp` for a dynamic validator. The [error response documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) states a $10 minimum order value. The [fee schedule](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) gives Standard native perps 4.5 bp taker and 1.5 bp maker; the frozen xyz `growthMode=enabled` and `deployerFeeScale=1` produce a **fee assumption** of 0.9 bp taker and 0.3 bp maker under the monitor's public fee-scaling rule. These are not measured account-specific fees. Both HL meta responses have `collateralToken=0`; this does not establish account wallet fungibility with RH USDG.

The dry plan opens no socket and writes nothing:

```bash
python scripts/rh_maker_capture.py --metadata-dir data/raw/rh-maker-metadata/20260929T210845Z
python -m unittest tests.test_rh_maker_capture -v
```

After strategy and code freeze, the read-only 50-minute capture command is:

```bash
python scripts/rh_maker_capture.py --metadata-dir data/raw/rh-maker-metadata/20260929T210845Z --run --seconds 3000 --out data/raw/rh-small-maker/NEW_RUN_ID
```

The first 1,800 seconds are calibration and the next 1,200 seconds are holdout. The default compressed collector cap is 384,000,000 bytes including copied metadata and manifest; the hard CLI maximum is 512,000,000, leaving a separate 128 MB derived-state budget for the default study. Exactly two public WebSocket connections subscribe to HL `l2Book` with `fast:true` plus `trades`, and RH full `order_book` plus `trade`, for all four markets. No BBO, private endpoint, order, or signature is used. Every raw frame keeps generation, receipt UTC/monotonic nanoseconds, payload, and source/nonce quality annotation. A missing or changed HL fast subscription acknowledgement terminates the capture. RH nonce gaps invalidate the book and trigger a paced resubscription; disconnects start new generations.

Output is `frames.jsonl.gz` (concatenated complete gzip NDJSON records), `manifest.json`, and a copy of `metadata/`. The manifest includes `frames_sha256`, termination reason, truncation flag, sizes, market and metadata hashes, bounded errors and reconnect history, and subscription plan. A Ctrl-C/TERM or compressed-byte cap writes a terminal manifest. This collector records public evidence only; hypothetical maker fills and P&L belong to the separate replay model.
