# Hyperliquid fast L2, one 60-second public WebSocket comparison

Frozen probe commit: `c625218ec909c43a2f8904189f3187e89255e1f4`. The pre-connection [launch manifest](launch_manifest.json) records PID 2322712, command, and SHA-256 hashes; all three hashes match the committed source files. [Raw capture](raw.jsonl) has 375 complete records (232,580 bytes), equal to the reported message count, with no truncation. [Machine-readable summary](summary.json) contains the full counts. No REST or order endpoint was called.

| Coin | Fast books / median source gap / levels | Slow books / median source gap / levels | $1,000 two-sided depth fit | Fast best price different from last slow book |
| --- | --- | --- | --- | --- |
| BTC | 111 / 0.539 s / 5 per side | 12 / 5.383 s / 20 per side | 111/111 fast; 12/12 slow | 0/111 |
| `xyz:NVDA` | 111 / 0.539 s / 5 per side | 12 / 5.383 s / 20 per side | 111/111 fast; 12/12 slow | 30/111 |
| `xyz:SILVER` | 111 / 0.539 s / 5 per side | 12 / 5.383 s / 20 per side | 111/111 fast; 12/12 slow | 19/111 |

All six subscription acknowledgements echoed the exact `fast:true` or `fast:false` setting. The observed fast cadence was about 10 times the slow cadence. Median receipt-minus-source age was about 0.322 s for fast and 0.402 s for slow. On each coin, 76 of 111 fast books were fresh while the latest already-received slow book's source timestamp was more than 2 seconds old. Only 19 of 111 had both sources within 2 seconds of the fast receipt and receipt skew within 1 second.

For the frozen nominal 100 ms timing benchmark, 110 of 111 fast anchors had a **later** book whose receipt and source timestamps both cleared the due time within 3 seconds (one capture-end censor). Median actual wait from anchor receipt was about 0.548 s, with p95 about 0.848 s. On slow, none of 12 anchors had such a book within 3 seconds; 11 timed out and one was capture-end censored. These are eligible-book observations, not filled orders or profit estimates.

The $1,000 depth check floors a base quantity to the documented market lot step and asks whether both displayed sides of **that same Hyperliquid book** cover it. It does not test the paired venue, order queue position, execution slippage, or spread profitability. The 60-second sample covers one market interval. Both sockets were closed at the planned deadline; aiohttp recorded close code 1006, with no in-run disconnect message or error. Treat the close code as a capture limitation, not evidence of normal exchange close behavior.

This supports testing fast L2 as a faster, deeper alternative to BBO for these three markets. It does not justify a production switch across all assets without route-level execution and risk evaluation.
