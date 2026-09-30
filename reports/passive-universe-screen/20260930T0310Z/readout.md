# Completed RH/HL public universe screen

Five fixed rounds completed from 2026-09-30T03:11:00.168740+00:00 to 2026-09-30T03:15:07.215662+00:00. **No valid quote cleared modeled fill fees, the $0.10 target, and the separate 5 bp stress.** No realized P&L or maker fills were measured.

The fresh plan had 26 distinct RH/HL routes: 21 survived, four were excluded for unverified underlying equivalence (SPCX, PONS, SKHY, SOXL), and XAU was excluded because its HL metadata omitted required `growthMode`. Both venue volumes exceeded $1 million for every retained route. All 105 planned asset/round quotes were attempted once, sequentially. 320/420 size observations passed; 100/420 failed source/receipt freshness. There were no depth, HTTP, grid or other scored rejection reasons. Seventeen assets had at least three valid $1,000 rounds and were eligible for median ranking; TSLA/META/CRCL had two each and AMZN one.

## Ten best eligible medians at $1,000

Rank is by the predeclared median after fees, target and stress. Every score below is negative. USD figures are conditional USDG/USDC parity quote arithmetic.

| Rank | Asset | Valid rounds | Fee-only margin | After $0.10 target | After target + 5 bp stress |
|---:|:---|---:|---:|---:|---:|
| 1 | XAG | 4/5 | $+0.0915 | $-0.0085 | $-0.5081 |
| 2 | MU | 3/5 | $+0.0348 | $-0.0652 | $-0.5648 |
| 3 | MSFT | 3/5 | $+0.0173 | $-0.0827 | $-0.5824 |
| 4 | SNDK | 5/5 | $-0.0016 | $-0.1016 | $-0.6012 |
| 5 | NVDA | 5/5 | $-0.0046 | $-0.1046 | $-0.6044 |
| 6 | INTC | 5/5 | $-0.0075 | $-0.1075 | $-0.6072 |
| 7 | GOOGL | 3/5 | $-0.0239 | $-0.1239 | $-0.6237 |
| 8 | AAPL | 4/5 | $-0.0283 | $-0.1283 | $-0.6281 |
| 9 | AMD | 3/5 | $-0.0317 | $-0.1317 | $-0.6313 |
| 10 | NEAR | 5/5 | $-0.5982 | $-0.6982 | $-1.1981 |

Across all sizes, 74 of 320 valid static margins were positive after fees alone, 5 after the $0.10 target, and zero after target plus stress. The best individual stressed observation was $-0.1227; single favorable observations never determine ranking.

## Coverage and observed RH trade flow

The ledger contains 934 unique post-subscription ordinary prints, with cap reached = False. The stream ignored 1050 initial history rows and 4 updates outside the post-subscription source-time gate. Malformed trades = 0, duplicate updates = 0, invalid tickers = 0. The absence of a cap or malformed records does not establish complete tape coverage. Counts/notionals are descriptive aggressor flow, including warmup, and have no attribution to hypothetical quotes or actual fills.

| Asset | Valid $1,000 rounds | Missing size rows | Taker sells | Sell notional | Taker buys | Buy notional |
|:---|---:|---:|---:|---:|---:|---:|
| BTC | 5/5 | 0 | 72 | $21,910.58 | 83 | $128,533.96 |
| ETH | 5/5 | 0 | 32 | $26,337.55 | 14 | $23,815.42 |
| LIT | 5/5 | 0 | 123 | $38,542.06 | 138 | $55,921.15 |
| NVDA | 5/5 | 0 | 69 | $48,186.45 | 69 | $61,930.12 |
| SOL | 5/5 | 0 | 10 | $4,484.42 | 56 | $1,289.97 |
| HYPE | 5/5 | 0 | 7 | $520.62 | 14 | $6,359.01 |
| AAPL | 4/5 | 4 | 52 | $34,888.28 | 31 | $33,417.57 |
| XAG | 4/5 | 4 | 8 | $2,172.57 | 8 | $3,534.93 |
| GOOGL | 3/5 | 8 | 24 | $7,247.05 | 19 | $5,949.49 |
| SNDK | 5/5 | 0 | 17 | $2,232.67 | 16 | $4,496.83 |
| NEAR | 5/5 | 0 | 15 | $917.93 | 0 | $0.00 |
| ZEC | 4/5 | 4 | 0 | $0.00 | 0 | $0.00 |
| XRP | 4/5 | 4 | 3 | $29.41 | 0 | $0.00 |
| MSFT | 3/5 | 8 | 4 | $144.50 | 5 | $687.62 |
| MU | 3/5 | 8 | 8 | $570.50 | 1 | $486.09 |
| TSLA | 2/5 | 12 | 9 | $898.00 | 3 | $440.90 |
| META | 2/5 | 12 | 6 | $1,976.42 | 3 | $78.98 |
| CRCL | 2/5 | 12 | 0 | $0.00 | 0 | $0.00 |
| AMD | 3/5 | 8 | 0 | $0.00 | 5 | $4,116.83 |
| AMZN | 1/5 | 16 | 6 | $1,149.09 | 1 | $0.02 |
| INTC | 5/5 | 0 | 3 | $314.29 | 0 | $0.00 |

Receipt buckets for rounds 0–3 lasted 60.000410, 60.000708, 60.000601, 60.000440 seconds. The final round bucket lasted only **3.418212 seconds**, ending when the socket was intentionally closed after its quotes. Warmup begins at each market's recorded subscription acknowledgement and ends at round 0; durations vary by acknowledgement. [trade_flow_windows.csv](trade_flow_windows.csv) explicitly includes every asset/round, including zero observed flow, acknowledgement/receipt boundaries, seconds and side totals. Flow must not be compared across these unequal observation durations as though each were a full minute.

## Freeze, bounds and connection

All frozen input hashes and original HL response hashes match; every saved score reproduces from the frozen source and the summary reproduces exactly. Minimum round-start spacing was 60.000410 seconds. Eight offline tests passed, including the busy-inbound keepalive regression. The replication used three completed public metadata reads and 105 HL books, one RH socket/42 subscriptions, and 8 fixed application pings. It received 11081 messages and 10338 accepted tickers. Terminal socket status records requested_close=true, exception=null, and close_code=null; a negotiated final close code was not observed in the saved reader status. There was no premature termination of this replication.

The first attempt remains [separate and incomplete](../20260930T0303Z/readout.md): two rounds, 42 HL reads, no eligible ranking. The repair follows [Lighter’s published outbound-frame keepalive requirement](https://apidocs.lighter.xyz/docs/websocket-reference) and the existing workspace stream implementation. The restricted-network preflight is preserved separately with no saved metadata response or quote. Across the two quote studies there were **147 HL book reads and six successful metadata reads**; the aborted restricted-network metadata attempt remains disclosed. Earlier quotes are never pooled into replication medians.

Fees use the public Standard RH maker values and HL tier-0 taker schedule with fresh per-asset deployer/growth settings, as specified in the [frozen method](method.md) and [official HL fee formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees). RH top sizes are queue competition, not size-feasible maker execution. The quoted long RH maker bid-to-ask cycle and HL taker sell/buy depth walks assume unchanged books; maker fill probability, queue priority, adverse selection, delayed hedges, funding, financing and USDG/USDC conversion remain unmeasured. These negative stressed quotes provide no positive-profit nomination under the predeclared screen.
