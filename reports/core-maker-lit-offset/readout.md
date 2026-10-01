# LIT maker offset experiment: unresolved execution

Capture frozen `4313c5d`: 600 seconds, 12:53:06–13:03:07 UTC on 1 October.
Replay compatibility correction frozen `9113c72` before any events were
processed. The original constructor rejected the adaptive entry policy;
its empty audit and failure record remain. A narrow wrapper initializes
parent bookkeeping then restores the originally intended configuration.
Ten integration/lifecycle/planner tests passed. No quote or delay parameter
changed; all original source and capture hashes are checked.

**Neither independent $100-per-leg branch produced a completed paired cycle.**
Each assumes $400 prefunding, a passive RH buy, contingent Core short,
400 ms order/cancel/hedge delays and a ten-second taker exit policy.

| Offset behind RH best bid | Quotes | No-flow completed episodes | Terminal condition |
|---|---:|---:|---|
| 5 bp | 9 | 8 | Eligible flow preceded the queue snapshot; execution unknown |
| 10 bp | 19 | 18 | Conditional 1.71 LIT maker partial, hedge below minimum, unresolved exit |

The 10 bp branch attributed one public-flow maker buy at 3.9381, cash
−6.734151 USDG. Its hedge was rejected by the normal-order minimum. A
fallback exit also failed that minimum check, leaving 1.71 LIT unhedged
in the model. Funding subsequently became unknown at the hourly boundary.
The −6.734151 cash entry is not a realized loss: the offsetting position
remains open. Its displayed mid mark is not an executable exit or profit.
Branch P&L is null for both policies, including the timing-unknown branch
whose recorded inventory remains zero. The metrics' zero known-close sums
do not include a terminal unknown quote as a zero-return completed trade.

The independent audit matched the one attributed increment to raw public
trade flow, checked exact cash and inventory, and independently recomputed
capital cost. There were no taker fills to audit. Queue priority and private
acknowledgements remain assumptions; public flow does not prove a real fill.
The strict uncertainty rules were preserved. Quotes farther from the touch
allowed more observable no-flow episodes but did not establish profitability.

Both feed connections remained continuous; 16,042 raw records, 1,952,893
compressed frame bytes, no transport errors or dropped frames. Complete raw
capture, both replay paths, metadata, all unknowns and audits are retained.

A practical next execution question is how to handle partial fills below a
hedge minimum. The frozen model does not assume a reduce-only exemption or
silently round a partial upward. Any aggregation or corrective order policy
needs explicit timing, exposure limits and accounting for additional fills.
