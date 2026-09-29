# Hyperliquid fast L2 feed probe — frozen method

The current [Hyperliquid subscriptions documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) lists `fast: boolean` as an optional `l2Book` subscription parameter and states that the fast feed has 5 levels per side versus 20 for slow. The documented WebSocket endpoint is `wss://api.hyperliquid.xyz/ws`. The [rate-limit page](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) lists 10 simultaneous connections per IP. These are protocol claims, not measured cadence or proof that the server honors the option.

## Experiment

`scripts/hyperliquid_fast_probe.py` opens exactly two independent public WebSocket connections for at most 60 seconds by default (hard CLI maximum: 120). Each subscribes to BTC, `xyz:NVDA`, and `xyz:SILVER`; one sends `fast:true`, the other explicitly sends `fast:false`. The connection identity is attached to each captured frame because `l2Book` messages identify the coin but do not repeat the fast setting. A subscription is confirmed only if its `subscriptionResponse` echoes the exact boolean on the correct connection. Missing, changed, or duplicate acknowledgements are errors, even if book frames arrive.

The probe sends six subscription messages total, uses no REST or private/order endpoints, and does not import or modify the paper monitor. It writes a timestamped `launch_manifest.json`, `raw.jsonl`, and `summary.json` under `reports/hl-fast-probe/`. The launch manifest, written before opening either socket, records the process ID, command, commit, and SHA-256 hashes of the three frozen probe files. Raw records stop at 5,000,000 bytes; whole records are skipped after the cap, and the drop count is reported. Analysis retains at most 20,000 book events, with a separate overflow count. Errors are bounded to 100 short entries. Run requires an explicit `--run`; without it, the CLI prints the plan and writes nothing.

Raw frames remain captured even when a book is excluded from analysis for a source timestamp after local receipt, nonfinite data, empty or crossed sides, unordered levels, or duplicate prices. Thus malformed snapshots cannot make depth coverage look better.

## Metrics fixed before capture

For each connection and coin, the summary reports message count, source and receipt interarrival medians/p95, receipt-minus-source age, median levels per side, and whether each displayed book can fill a matched base quantity near $1,000 on both sides. The quantity is floored to the current discovered Hyperliquid lot steps (`BTC` 0.00001, `xyz:NVDA` 0.001, `xyz:SILVER` 0.01); there is no assumed deeper liquidity.

Each fast book is compared to the latest slow book already received for that coin. Counts distinguish paired fresh quotes (both source ages ≤2 seconds and receipt skew ≤1 second), fast fresh while slow source age exceeds 2 seconds, and different best prices. The comparison is observational: two sockets can receive the same exchange state at different times.

The nominal 100 ms execution-delay metric uses each book receipt as an anchor. It finds the first **later** book whose receipt and source times are both at least anchor receipt +100 ms. A match must arrive within the following 3 seconds. It reports actual receipt delay, 3-second timeouts, and end-of-capture censoring separately. This is an eligible-book timing benchmark, not a trade or profit simulation.

## Review and launch

Dry plan: `python scripts/hyperliquid_fast_probe.py`

After review: `python scripts/hyperliquid_fast_probe.py --run --duration 60`

No live probe has been launched as part of preparing this method. Treat `fast` as unsupported or unverified if any acknowledgement fails to echo it, regardless of observed cadence. A shorter cadence alone does not establish full $1,000 executable depth or profitable opportunities.
