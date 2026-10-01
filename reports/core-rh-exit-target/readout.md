# Exit target only: 1 bp versus 6 bp

Frozen `f078b81`; fresh PONS/CASHCAT capture on 1 October 2026,
15:25:06–15:40:06 UTC. Same immediate entries and 1 bp forecast hurdle;
only the profit-exit target differed. Both retained 400 ms order delays,
10 bp entry limits, 60-second holding limit, zero Standard fees conditional
on metadata, and independent $100-per-leg / $600-prefunded portfolios.

| Exit target | Paired closes | Rescue closes | Cash wins | Cash after fees | After capital + 5 bp stress |
|---|---:|---:|---:|---:|---:|
| 1 bp | 4 | 1 | 0 | −$0.472273 | −$0.721995048 |
| 6 bp | 4 | 1 | 1 | −$0.394387 | −$0.644111192 |

All five entries matched exactly across branches, including quantities,
entry values and times. Three PONS pairs reached the 60-second hold limit
and lost identically. One CASHCAT attempt failed its short hedge, leaving
a long-side rescue loss of $0.120700 in each arm. All inventory ended flat;
no partial fills, aborted attempts, unknown closes or below-minimum exits.
These shared observations are not ten independent trades.

The remaining PONS pair illustrates a useful but limited result:

- The 1 bp arm requested exit at a +$0.014113 net mark and finished about
  0.501 seconds later with a **$0.060912 cash loss**.
- The 6 bp arm waited another 6.777 seconds, requested exit at a +$0.064121
  net mark, and finished about 0.505 seconds later with **+$0.016974 cash**.
  It made +$0.016970907 after the modeled capital cost, before stress.
- Entry values were $99.769400 long and $99.875016 short. The gain does not
  survive the separate 5 bp stress allowance. The total 6 bp portfolio was
  still negative; one improved exit does not establish positive expectancy.

The independent audit passed all **36 fills** and reconstructed both
profit-request marks from retained executable depth. It checked the unchanged
1 bp forecast hurdle, past-only reference, source clocks and first eligible
400 ms fills, lots, cash, capital, same-hour inventory, holding-limit requests
and both venue wallets. `matched-entry-comparison.json` retains every matched
attempt, including all losses.

The fixed 900.046-second capture completed without errors or reconnects:
25,892 messages / 12,262,054 inbound bytes. Retained raw data is 146,034 bytes,
with 1,430 reference samples, 10 branch admissions, 152 pending-book records,
36 fills, eight paired exit requests, 10 terminal positions and four shutdown
invalidations. Each arm generated 59 positive forecasts and five attempts.

No orders were sent. USDG/USDC parity, network delay and private execution
remain conditional. Full wire data and idle depth were not saved; the frozen
callback collector determines completeness. The separate maker-model reserve
clarification does not affect this taker trial: its execution target includes
fees and capital, with the 5 bp stress applied only in reporting.
