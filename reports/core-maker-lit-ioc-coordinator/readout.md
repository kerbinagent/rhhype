# Corrected IOC minimum scenario on sealed LIT capture

Exploratory replay of the previously inspected 12:53–13:03 UTC capture on
1 October 2026. It is not prospective evidence or a record of actual trades.
The source-consistent IOC minimum exemption applies to hedges and exits;
resting quotes retain ordinary minima. Deployed API acceptance is unverified.
The corrected coordinator evaluates quotes after deadlines and current-book
updates. It enforces the original admission window, offset, and attempt cap.
The earlier invalid replay and its validation failure remain preserved.

| Offset | Quotes | No-flow closes | Paired closes | Cash wins | Stress wins | Cash after fees | After capital + 5 bp stress |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5 bp | 69 | 64 | 5 | 2 | 1 | −$0.044629 | −$0.208043671 |
| 10 bp | 73 | 70 | 3 | 2 | 2 | +$0.136306 | −$0.013652904 |

Each independent branch uses $100 per leg and $400 prefunding, split equally
between venues. Their overlapping counterfactual results must not be added.
All positions and quotes closed; no unknown episodes or failed-hedge rescues.
The 10 bp cash gain survives its $0.000002275 capital charge, but not the
separate stress allowance. Its individual stressed gains were $0.044893305
and $0.019372924; the third close lost $0.077919133. This sample does not
establish a positive expected return.

Independent checks reproduced 27 taker depth walks, 11 maker flow matches,
first eligible entry/exit books after the 400 ms delay, partial hedge intent
quantities, zero fees, all inventory and venue cash, and capital charges.
A separate raw-event audit checked every one of the 142 actual quote prices,
quantities, admission times and 400 ms activation deadlines, subtracting
preceding taker fills from branch-local displayed depth.

The first episode-level audit failed because inclusive timestamps assigned
a preceding terminal fill to a new quote beginning on the same receipt.
The pinned auditor remains unchanged. A small, separately retained wrapper
uses ordered quote_requested-to-episode_flat boundaries; all checks pass.
No replay economics changed during that audit repair.

Public trade flow and modeled queue consumption cannot authenticate private
fills or acknowledgments. Zero Standard fees, USDG/USDC parity, IOC admission,
and the latency model remain conditional. The fixed offsets were examined
on this data before the repair; a new fixed-endpoint capture is needed for
prospective replication. No orders or authenticated requests were sent.
