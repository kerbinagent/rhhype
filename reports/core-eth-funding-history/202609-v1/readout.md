# Core ETH funding screen — 1 October 2026

One public request returned all 720 hourly slots for September. Fixed long
spot/short perp direction; four seven-day blocks plus the two-day remainder.
This is historical rate arithmetic, not fills, dollar P&L or fresh validation.

| September block | Funding bp | Less 2x-capital charge and 5 bp stress |
| --- | ---: | ---: |
| 1–7 | 18.62 | −5.56 |
| 8–14 | 14.57 | −9.61 |
| 15–21 | 9.92 | −14.26 |
| 22–28 | 19.92 | −4.26 |
| 29–30 | 5.69 | −4.79 |

Capital scenario: 5% annual on twice one-leg notional. Fees zero; all spread,
basis and execution costs omitted. The full month has 68.72 bp of rate sum.
No weekly block passes this necessary cost-recovery screen. Do not launch an
always-on execution study under these assumptions.

Even with zero execution cost, weeks 2 and 3 cannot fund 5% opportunity cost
on spot alone after 5 bp stress. Lowering margin is insufficient for those
weeks. Other collateral or selective-entry ideas need separate evidence.

Raw gzip hashes, complete denominators and arithmetic are in summary.json.
Source was committed before fetching (02bfa3f). Root recomputed every block
from the saved response; no independent model audit is claimed.
