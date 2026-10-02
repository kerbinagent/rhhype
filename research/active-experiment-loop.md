# Active experiment and research loop

## User mandate, 30 September 2026 02:10 UTC

Run the proposed passive RH inventory-exit experiment and continue collecting,
researching and improving until the user stops the work or paper P&L is
convincingly positive. Public data and paper execution only. Maintain the
twenty-minute production reviews while experiments remain separate.

## Current status, 01 October 2026 16:10 UTC

Review 144 added 23 exact Premium paired losses/−$36.6424056276; no wins, estimates or aborts. Reviews 66–144 total 2,146 closes: 2,121 losses, two paired gains and 23 audited failed-hedge rescues. A Premium position was open in the report health snapshot; track its next-window closure without folding it into review144. The separate epoch snapshot matched convergence’s flat delta but Premium increased by 27 while the report showed 23; use report deltas only. Health remained running/ok with four feeds and 97 pairs; p95 lag 9.24 ms, CPU 55.23%, RSS 263.17 MiB and 910 books/s. Three pending funding items remain. Carry metadata at 16:05 had 187 sampled slots, persistent invalid slot71 and 676 future/interrupted slots; no error/retries/economic evaluation. Under the adopted 4,980,736 B archive cap, retained files are 3,598,614 B; 169 remaining report/snapshot pairs through 4 October 00:26 at prior worst 5,342 B project to 4,501,412 B, leaving 479,324 B. Next review: **1 October 16:26:33 UTC**.

Review 143 added seven exact losses/−$10.9692685336: one convergence failed-hedge loss and six Premium losses (three paired, three failed hedge); no wins, estimates or aborts. Reviews 66–143 total 2,123 closes: 2,098 losses, two paired gains and 23 audited failed-hedge rescues. Snapshot counters now match the report deltas. Health remained running/ok with four feeds and 97 pairs; p95 lag 20.59 ms, CPU 66.50%, RSS 265.41 MiB and 1,112 books/s. No open positions and three pending funding items. Carry metadata at 15:45 showed 183 sampled slots, persistent invalid slot 71, and 680 future/interrupted slots; no error/retries/economic evaluation. Under the 5 MiB cap, current archive size is 3,594,206 B; 170 remaining pairs through 4 October 00:26 at the prior 5,342 B maximum project to 4,502,346 B, leaving 740,534 B. Next review: **1 October 16:06:33 UTC**.

Review 142 added 22 exact losses/−$25.4840848349: nine convergence failed-hedge losses and 13 Premium losses (six paired, seven failed hedge), with no wins, estimates or aborts. Reviews 66–142 total 2,116 closes: 2,091 losses, two paired gains and 23 audited failed-hedge rescues. The separate epoch snapshot increased convergence by nine versus report +9 and Premium by 11 versus report +13; report deltas remain the review accounting source. Health remained running/ok with four feeds and 97 pairs, p95 lag 13.39 ms, CPU 60.56%, RSS 261.80 MiB and 960 books/s. No open positions; three pending funding items. Carry metadata at 15:25 had 179 sampled slots, persistent invalid slot 71, and 684 future/interrupted slots; no error/retries/economic evaluation. The 5 MiB manual archive cap now preserves prior artifacts; with 171 report/snapshot pairs remaining through 4 October 00:26 UTC and the prior worst compressed pair of 5,342 B, projected final use is 4,503,211 B, leaving 739,669 B. Next review: **1 October 15:46:33 UTC**.

Review 141 added 19 exact losses/−$27.8022448250: four convergence failed-hedge losses and 15 Premium losses (12 paired, three failed hedge); one separate convergence abort, no wins or estimates. The two review140 positives remain audited failed-hedge rescues, not paired gains. Reviews 66–141 total 2,094 closes: 2,069 losses, two paired gains and 23 audited rescue gains. Review141’s epoch snapshot increased convergence by three versus the report delta of four and Premium by 16 versus 15; retain report deltas for review accounting. Health remained running/ok with four feeds and 97 pairs; p95 lag 10.93 ms, CPU 61.53%, RSS 258.48 MiB and 1,011 books/s. No open positions; three pending funding items. Carry metadata at 15:05 showed 175 sampled slots, invalid slot71, and 688 future/interrupted slots; no error/retries/economic evaluation. Next review: **1 October 15:26:33 UTC**.

Review 140 is archived and both positive records have been audited. It added 19 exact closes/−$26.864979: two convergence and 17 Premium; there were two wins, both independently verified as failed-Hyperliquid-hedge one-sided NEAR-long rescues, plus one separate convergence abort. No estimated trades. Reviews 66–140 total 2,075 closes: 2,050 losses, two paired gains and 23 audited failed-hedge rescue gains. Both gains are recorded as rescues rather than paired arbitrage; neither changes the negative overall result. Epoch convergence increased by two, matching the report, while Premium increased by 16 versus 17 report closes; use report deltas for review accounting. Health remained running/ok with four feeds and 97 pairs, p95 lag 13.96 ms, CPU 67.87%, RSS 256.23 MiB and 1,269 books/s; no open positions and three pending funding items. The prior 98-pair list is not retained, so the single pair-count decrease cannot be identified from available snapshots; `markets.json` currently has 97 pairs and no failed venues. Treat this as coverage health only. Carry metadata at 14:45: 171 sampled slots, persistent `arrival_invalid` slot 71, and 692 future/interrupted slots; no error, retries or economic evaluation. Next review: **1 October 15:06:33 UTC**.

Review 139 is preserved under the 6 MiB deterministic-gzip archive policy. It added 40 exact losses/−$64.722872: eight convergence failed-hedge losses and 32 Premium losses (19 paired, 13 failed-hedge); no wins, estimates or aborts. Reviews 66–139 total 2,056 closes: 2,033 losses, two paired gains and 21 audited failed-hedge rescue gains. All eight strategy and aborted coverage fields are complete. The separate epoch snapshot at 14:28:57 UTC showed convergence 556/−$657.9792 and Premium 942/−$1,731.3196, both matching the report deltas. Health was running/ok with four feeds and 97 pairs; p95 lag 14.34 ms, CPU 66.50%, RSS 256.03 MiB and 1,266 books/s. No open positions; three pending funding items remain. Carry metadata at 14:25 showed 167 sampled slots, persistent `arrival_invalid` slot 71 and 696 future/interrupted slots, with no collector error, retries or economic evaluation; the sample remains unopened. Next review: **1 October 14:46:33 UTC**.

Review 138 is archived with lossless gzip compression; both raw records round-trip exactly, and future review archives use deterministic gzip under the 6 MiB manual cap. Reviews 66–138 contain 2,016 closes: 1,993 losses, two paired gains and 21 audited failed-hedge rescue gains. Review 138 added 58 exact losses/−$94.69717 (10 convergence, 48 Premium), no wins, estimates or aborts, and 20 entry price-limit rejections (19 Hyperliquid, one Lighter). All eight strategy and aborted coverage fields are complete. The epoch snapshot increased convergence by 10, matching the report; Premium increased by 54 while the report delta was 48, so review totals use report deltas only. A Premium position visible in the report health snapshot closed after the report window and was confirmed flat on follow-up; it belongs to the subsequent interval. At review time health remained running/ok with four feeds and 98 pairs; p95 lag 20.81 ms, CPU 76.67%, RSS 256.39 MiB and 1,328 books/s. One pending Premium position/funding record was reported in the review health data; the separate later snapshot retained three pending funding items and no open positions. Fresh carry v2 metadata at 14:05 had 163 sampled slots, one persistent `arrival_invalid` slot (71), and 700 future/interrupted slots, without terminal error, retries or economic evaluation. Next review: **1 October 14:26:33 UTC**.

No qualifying positive result. Prior passive, delayed taker and spread studies
remain negative or inconclusive; no strategy is promoted. After the host reboot,
production monitor PID 17101 and reviewer PID 19334 resumed the same database,
all eight saved ledgers, strategy epoch and three legacy funding obligations.
The 00:14 catch-up review96 covers an extended interval and is not a fresh
uninterrupted validation window. All four feeds are connected.

Reviews through 129 are preserved. Reviews 66–129 have 1,730 closes: 1,720 losses,
two paired gains and eight failed-hedge rescue gains. The four epoch paired gains
remain the WLD/CRCL records from review65 and two MU records from review85;
the latter share a signal and HL fill observation, and their full three-pair
convergence group lost $1.2929. Twenty-two epoch win records comprise four
paired and eighteen rescues. Estimated funding losses remain labeled estimated.
Cooldown cannot admit new pairs because its HL paper balance $1,000.35611 is
below the $1,000.50 minimum reserve before venue fees. No reset or top-up.
Review 103 added two exact convergence failed-hedge losses/−$2.53326; review 104
had no trade or abort changes. Review 105 added three exact Premium failed-hedge
losses/−$6.19308. Review 106 added 17 exact losses across convergence and
Premium/−$38.73372. No new wins or estimated trades. Three pending funding items
remain across convergence, Premium and standard; no open positions. Review 107
added eleven exact losses/−$20.72763: three convergence and eight Premium.
Review 108 added four exact losses/−$6.57846: two each from convergence and
Premium. Review 109 added two exact Premium losses/−$4.01441. Review 110 added
one exact Premium failed-hedge loss/−$1.63377. Review 111 added four exact
losses/−$9.20361: two each from convergence and Premium. Review 112 added two
exact losses/−$2.56473, one separate convergence abort and four price rejections.
The convergence epoch at review112 was 386/−$458.4817 and Premium
687/−$1,273.0287. Premium's report delta there was one close, while separate
epoch snapshots increased by two; retain their timestamps and use report deltas
for review totals. Review 113 added four exact losses/−$6.22512: two convergence
and two Premium failed hedges; four Hyperliquid price-limit rejections, no
aborts, wins or estimates. Reviews 66–113 have 1,637 closes: 1,627 losses, two
paired gains and eight failed-hedge rescue gains. The review113 epoch snapshot
at 05:47:18 UTC showed convergence 388/−$460.9603 and Premium 688/−$1,275.2228.
Since the 05:27:19 snapshot, convergence increased by two, matching its report
delta; Premium increased by one while the report delta was two. Review 114
added three exact convergence failed-hedge losses/−$6.06559 and three
Hyperliquid price-limit rejections, with no aborts, wins or estimates. Reviews
66–114 have 1,640 closes: 1,630 losses, two paired gains and eight failed-hedge
rescue gains. The review114 epoch snapshot at 06:07:07 UTC showed convergence
391/−$467.0259 and Premium 688/−$1,275.2228; since the 05:47:18 snapshot,
convergence rose by three, matching its report delta, while Premium was flat.
Four feeds remain connected with 106 pairs and performance ok; p95 lag 6.85
ms, RSS 191.76 MiB, CPU 43.61%, and 760.9 books/s. Metadata age is 3,143 s;
no open positions and three pending funding items remain. Review 115 had no
closed trades or wins/estimates; one separate convergence abort and two entry
rejections (one Hyperliquid price limit, one Lighter notional cap). The epoch
snapshot read at 06:27:10 UTC matched the prior snapshot at convergence
391/−$467.0259 and Premium 688/−$1,275.2228. Health remains running/ok, four
feeds and 107 pairs; p95 lag 5.59 ms, RSS 198.61 MiB, CPU 40.91%, 769.0
books/s, metadata age 738 s. No open positions and three pending funding items
remain. Next review: **1 October 06:46:33 UTC**. Carry v2 reports one
`arrival_invalid` slot at 06:25 (slot 71); do not open its sample under the
monitor-only constraint. It has no terminal error or economic evaluation.
Review 116 added three exact Premium failed-hedge losses/−$3.49904, with no
aborts, wins, estimates or rejections. Reviews 66–116 have 1,643 closes: 1,633
losses, two paired gains and eight failed-hedge rescue gains. The review116
epoch snapshot at 06:47:03 UTC showed convergence 391/−$467.0259 and Premium
692/−$1,280.3203. Premium's epoch count rose by four from the prior snapshot,
while the report delta was three; use report deltas for review totals. Four
feeds remain connected with 107 pairs and performance ok; p95 lag 7.00 ms, RSS
205.20 MiB, CPU 48.78%, and 849.4 books/s. Metadata age is 1,936.8 s; no open
positions and three pending funding items remain. Next review:
**1 October 07:06:33 UTC**.
Review 117 added six exact losses/−$9.92770: three convergence/−$5.35940 and
three Premium/−$4.56830; one separate convergence abort, seven Hyperliquid
price-limit rejections and one Lighter notional-cap rejection. No wins or
estimates. Reviews 66–117 have 1,649 closes: 1,639 losses, two paired gains and
eight failed-hedge rescue gains. The review117 epoch snapshot at 07:07:03 UTC
showed convergence 394/−$472.3853 and Premium 694/−$1,283.2901. Convergence
rose by three, matching its report delta; Premium rose by two while the report
delta was three. Use report deltas for review totals. Health is running/ok with
four feeds, 107 pairs, p95 lag 6.62 ms, RSS 208.21 MiB, CPU 50.86%, 999.8
books/s and metadata age 3,137 s; no open positions, three pending funding.
Carry v2 has 79 sampled slots through 07:05 and one persistent `arrival_invalid`
slot 71; terminal health has no error or economic evaluation. Next review:
**1 October 07:26:33 UTC**. Review 118 added ten exact losses/−$18.28396:
five convergence/−$9.32305 and five Premium/−$8.96091, plus one separate
convergence abort. There were nine Hyperliquid price-limit rejections and one
Lighter notional-cap rejection; no wins or estimates. Reviews 66–118 have 1,659
closes: 1,649 losses, two paired gains and eight failed-hedge rescue gains. The
review118 epoch snapshot at 07:27:09.752 UTC showed convergence 399/−$481.7083
and Premium 699/−$1,292.2511; both increased by five, matching their report
deltas. Four feeds remain connected with 105 pairs and performance ok; p95 lag
9.11 ms, RSS 213.50 MiB, CPU 58.51%, 1,141.2 books/s and metadata age 733.9 s.
No open positions; three pending funding items remain. Carry v2 at 07:25 has 83
sampled slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 119 added twenty exact losses/−$32.12380: five
convergence/−$7.07679 and fifteen Premium/−$25.04702, with zero wins,
estimates, aborts or rejections. Reviews 66–119 have 1,679 closes: 1,669
losses, two paired gains and eight failed-hedge rescue gains. The review119
epoch snapshot at 07:47:03.635 UTC showed convergence 404/−$488.7851 and
Premium 714/−$1,317.2981; both counts increased by the report deltas. Four
feeds remain connected with 105 pairs and performance ok; p95 lag 8.38 ms, RSS
218.83 MiB, CPU 54.12%, 1,105.7 books/s and metadata age 1,934.4 s. No open
positions; three pending funding items remain. Carry v2 at 07:45 has 87 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 120 added five exact losses/−$10.35090: three
convergence/−$6.41962 and two Premium/−$3.93128; four Hyperliquid price-limit
rejections, no aborts, wins or estimates. Reviews 66–120 have 1,684 closes:
1,674 losses, two paired gains and eight failed-hedge rescue gains. The review120
epoch snapshot at 08:07:04.056 UTC showed convergence 407/−$495.2047 and Premium
716/−$1,321.2294; both increased by their report deltas. Four feeds remain
connected with 105 pairs and performance ok; p95 lag 10.57 ms, RSS 225.12 MiB,
CPU 57.51%, 1,164.7 books/s and metadata age 3,132.6 s. No open positions; three
pending funding items remain. Carry v2 at 08:05 has 91 sampled slots and one
persistent `arrival_invalid` slot 71; no terminal error or economic evaluation.
Next review: **1 October 08:26:33 UTC**. Review 121 added five exact
losses/−$8.33527: two convergence/−$2.81583 and three Premium/−$5.51944; four
Hyperliquid price-limit rejections, no aborts, wins or estimates. Reviews 66–121
have 1,689 closes: 1,679 losses, two paired gains and eight failed-hedge rescue
gains. The review121 epoch snapshot at 08:27:06.863 UTC showed convergence
409/−$498.0206 and Premium 719/−$1,326.7488; both increased by their report
deltas. Four feeds remain connected with 106 pairs and performance ok; p95 lag
7.81 ms, RSS 227.49 MiB, CPU 50.32%, 966.5 books/s and metadata age 730.4 s.
No open positions; three pending funding items remain. Carry v2 at 08:25 has 95
sampled slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 122 added eight exact losses/−$13.82225: two
convergence/−$2.60499 and six Premium/−$11.21726; five Hyperliquid
price-limit rejections, no aborts, wins or estimates. Reviews 66–122 have 1,697
closes: 1,687 losses, two paired gains and eight failed-hedge rescue gains. The
review122 epoch snapshot at 08:47:11.540 UTC showed convergence 411/−$500.6255
and Premium 725/−$1,337.9661; both increased by their report deltas. Four feeds
remain connected with 106 pairs and performance ok; p95 lag 8.08 ms, RSS
233.06 MiB, CPU 42.89%, 761.2 books/s and metadata age 1,929.5 s. No open
positions; three pending funding items remain. Carry v2 at 08:45 has 99 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 123 added four exact losses/−$5.57802: one
convergence/−$0.39300 and three Premium/−$5.18502; two Hyperliquid price-limit
rejections, no aborts, wins or estimates. Reviews 66–123 have 1,701 closes:
1,691 losses, two paired gains and eight failed-hedge rescue gains. The review123
epoch snapshot at 09:07:05.872 UTC showed convergence 412/−$501.0185 and Premium
728/−$1,343.1511; both counts increased by their report deltas. Four feeds
remain connected with 106 pairs and performance ok; p95 lag 5.81 ms, RSS
233.23 MiB, CPU 41.69%, 729.3 books/s and metadata age 3,129.6 s. No open
positions; three pending funding items remain. Carry v2 at 09:05 has 103 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 124 added four exact losses/−$4.31127: three
convergence/−$3.02158 and one Premium/−$1.28969, plus one separate convergence
abort. There were four Hyperliquid and one Lighter price-limit rejections; no
wins or estimates. Reviews 66–124 have 1,705 closes: 1,695 losses, two paired
gains and eight failed-hedge rescue gains. The review124 epoch snapshot at
09:27:09.460 UTC showed convergence 415/−$504.0401 and Premium
729/−$1,344.4408; both increased by their report deltas. Four feeds remain
connected with 106 pairs and performance ok; p95 lag 6.59 ms, RSS 235.91 MiB,
CPU 48.87%, 909.4 books/s and metadata age 726.6 s. No open positions; three
pending funding items remain. Carry v2 at 09:25 has 107 sampled slots and one
persistent `arrival_invalid` slot 71; no terminal error or economic evaluation.
Next review: **1 October 09:46:33 UTC**. Review 125 added one exact convergence
failed-hedge loss/−$1.82697 and one Hyperliquid price-limit rejection, with no
aborts, wins or estimates. Reviews 66–125 have 1,706 closes: 1,696 losses, two
paired gains and eight failed-hedge rescue gains. The review125 epoch snapshot at
09:47:21.684 UTC showed convergence 416/−$505.8671 and Premium 729/−$1,344.4408;
convergence increased by one, matching the report delta, while Premium was
unchanged. Four feeds remain connected with 106 pairs and performance ok; p95
lag 6.77 ms, RSS 238.88 MiB, CPU 42.05%, 800.1 books/s and metadata age
1,925.5 s. No open positions; three pending funding items remain. Carry v2 at
09:45 has 111 sampled slots and one persistent `arrival_invalid` slot 71; no
terminal error or economic evaluation. Review 126 added twelve exact losses/
−$22.24032: eight convergence/−$13.80498 and four Premium/−$8.43535; nine
price-limit rejects (eight Hyperliquid, one Lighter), with no aborts, wins or
estimates. Reviews 66–126 have 1,718 closes: 1,708 losses, two paired gains and
eight failed-hedge rescue gains. The review126 epoch snapshot at 10:07:11.154 UTC
showed convergence 424/−$519.6721 and Premium 733/−$1,352.8761; both increased
by their report deltas. Four feeds remain connected with 106 pairs and
performance ok; p95 lag 8.72 ms, RSS 240.97 MiB, CPU 43.69%, 816.4 books/s and
metadata age 3,125.7 s. No open positions; three pending funding items remain.
Carry v2 at 10:05 has 115 sampled slots and one persistent `arrival_invalid`
slot 71; no terminal error or economic evaluation. Next review:
**1 October 10:26:33 UTC**. Review 127 added eight exact losses/−$12.49557:
two convergence/−$2.92337 and six Premium/−$9.57220; six Hyperliquid
price-limit rejections, no aborts, wins or estimates. Reviews 66–127 have 1,726
closes: 1,716 losses, two paired gains and eight failed-hedge rescue gains. The
review127 epoch snapshot at 10:27:10.084 UTC showed convergence 426/−$522.5954
and Premium 739/−$1,362.4483; both increased by their report deltas. Four feeds
remain connected with 106 pairs and performance ok; p95 lag 7.48 ms, RSS
242.08 MiB, CPU 46.04%, 893.2 books/s and metadata age 721.9 s. No open
positions; three pending funding items remain. Carry v2 at 10:25 has 119 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 128 added two exact losses/−$5.00081: one
convergence/−$3.29187 and one Premium/−$1.70894; one Hyperliquid price-limit
rejection, no aborts, wins or estimates. Reviews 66–128 have 1,728 closes:
1,718 losses, two paired gains and eight failed-hedge rescue gains. The review128
epoch snapshot at 10:47:14.505 UTC showed convergence 427/−$525.8873 and Premium
740/−$1,364.1572; both increased by one, matching their report deltas. Four
feeds remain connected with 106 pairs and performance ok; p95 lag 8.30 ms, RSS
241.81 MiB, CPU 43.27%, 730.0 books/s and metadata age 1,922.3 s. No open
positions; three pending funding items remain. Carry v2 at 10:45 has 123 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 129 added two exact losses/−$2.52271: one
convergence/−$0.81590 and one Premium/−$1.70681; one separate convergence
abort and four entry rejections (three Hyperliquid price limit, one Lighter
notional cap). No wins or estimates. Reviews 66–129 have 1,730 closes: 1,720
losses, two paired gains and eight failed-hedge rescue gains. The review129 epoch
snapshot at 11:07:10.589 UTC showed convergence 428/−$526.7032 and Premium
741/−$1,365.8641; both increased by one, matching their report deltas. Four
feeds remain connected with 106 pairs and performance ok; p95 lag 9.24 ms, RSS
243.09 MiB, CPU 54.90%, 1,066.5 books/s and metadata age 3,120.7 s. No open
positions; three pending funding items remain. Carry v2 at 11:05 has 127 sampled
slots and one persistent `arrival_invalid` slot 71; no terminal error or
economic evaluation. Review 130 added one exact Premium failed-hedge loss/−$1.70157; one Hyperliquid price-limit rejection, no aborts, wins or estimates. Reviews 66–130 have 1,731 closes: 1,721 losses, two paired gains and eight failed-hedge rescue gains. The review130 epoch snapshot read at 11:27:05 UTC showed convergence 428/−$526.7032 unchanged and Premium 742/−$1,367.5656, matching the Premium report delta. Four feeds remain connected with 106 pairs and performance ok; p95 lag 10.70 ms, RSS 247.79 MiB, CPU 53.64%, 878.5 books/s and metadata age 717.7 s. No open positions; three pending funding items remain. Carry v2 at 11:25 had 131 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Review 131 added two exact failed-hedge losses/−$2.89884: one convergence/−$1.65355 and one Premium/−$1.24529; two Hyperliquid price-limit rejections, no aborts, wins or estimates. Reviews 66–131 have 1,733 closes: 1,723 losses, two paired gains and eight failed-hedge rescue gains. The review131 epoch snapshot read 11:46:56 UTC showed convergence 429/−$528.3568 and Premium 743/−$1,368.8109, both +1 and matching the report deltas. Four feeds remain connected with 106 pairs and performance ok; p95 lag 10.76 ms, RSS 252.55 MiB, CPU 61.74%, 892.8 books/s and metadata age 1,915.9 s. No open positions; three pending funding items remain. Carry v2 at 11:45 has 135 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. The manual archive cap was reduced to 10 MiB under the current reserve allocation; the older 16 MiB wording in `research/live-operations.md` is stale. Current archive use is 3,377,377 bytes. Review 132 added three exact failed-hedge losses/−$4.84619: two convergence/−$2.31668 and one Premium/−$2.52951; three Hyperliquid price-limit rejections, no aborts, wins or estimates. Reviews 66–132 have 1,736 closes: 1,726 losses, two paired gains and eight failed-hedge rescue gains. The review132 epoch snapshot read 12:07:22 UTC showed convergence 431/−$530.6734 (+2) and Premium 744/−$1,371.3404 (+1), matching the report deltas. Four feeds remain connected with 106 pairs and performance ok; p95 lag 9.82 ms, RSS 256.05 MiB, CPU 53.54%, 996.7 books/s and metadata age 3,115.7 s. No open positions; three pending funding items remain. Carry v2 at 12:05 has 139 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,402,494/10,485,760 bytes under the reserve-v2 cap. Review 133 added five exact closes/−$7.10149: convergence three/−$2.94226 and Premium two/−$4.15924, with one positive convergence failed-hedge rescue and four losses; no estimates or aborts, five Hyperliquid price-limit rejections. The new win is trade `1790857580211159-23748-convergence`: HL long was rejected; 3,799 Lighter short units entered at $998.753599 and were covered at $998.012446 after 1.494255 s unhedged. Gross +$0.741153 less $0.4993768 other costs and $0.00000237 capital cost yields net +$0.24177383; no fees or funding. It is a failed-hedge unwind, not paired arbitrage. Root audit preserved in `reports/live-review-catchup/review133-positive-record.json`; retained depth rows are zero, so no new execution-depth audit claim. Reviews 66–133 have 1,741 closes: 1,730 losses, two paired gains and nine failed-hedge rescue gains. The review133 snapshot read 12:27:44 UTC showed convergence 435/−$535.5557 (+4 vs report +3) and Premium 746/−$1,375.4997 (+2, matching report); preserve this boundary mismatch and use report deltas for review totals. Four feeds remain connected with 105 pairs and performance ok; p95 lag 18.75 ms, RSS 251.61 MiB, CPU 64.53%, 1,180.5 books/s, metadata age 711.9 s; no open positions and three pending funding items. Carry v2 at 12:25 has 143 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,435,956/9,437,184 bytes under the adopted v3 cap. Review 134 added two exact convergence failed-hedge losses/−$5.71085, with no wins, estimates or aborts; two Hyperliquid price-limit rejections. Reviews 66–134 have 1,743 closes: 1,732 losses, two paired gains and nine failed-hedge rescue gains. The review134 epoch snapshot read 12:47:01 UTC showed convergence 436/−$539.3266 (+1 since review133 snapshot versus report delta +2) and Premium 746/−$1,375.4997 (flat, matching report). Preserve the boundary mismatch and use report deltas for review totals. Four feeds connected with 105 pairs and performance ok; p95 lag 10.90 ms, RSS 251.61 MiB, CPU 49.38%, 666.7 books/s and metadata age 1,911.7 s. No open positions; three pending funding items remain. Carry v2 at 12:45 had 147 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,460,697/9,437,184 bytes. Review 135 added seven exact closes/−$8.68141: convergence five/−$4.51431 and Premium two/−$4.16710, with one positive convergence failed-hedge rescue and six losses; no estimates or aborts, seven Hyperliquid price-limit rejections. The audited winner is trade `1790859980717247-23755-convergence`, route `NEAR|hyperliquid:NEAR|lighter:10`: Hyperliquid long rejected; Lighter short 203.1 entered at $999.239814 and covered at $998.151198 after 1.164010 s unhedged. Gross +$1.088616 less $0.499619907 stress allowance and $0.000001844 capital gives +$0.588994249. This is a profitable failed-hedge unwind, not paired arbitrage. Root audit is in `reports/live-review-catchup/review135-positive-record.json`; raw fill-depth evidence had aged out, so no independent execution-depth claim. Reviews 66–135 have 1,750 closes: 1,738 losses, two paired gains and ten rescue gains. The review135 epoch snapshot read 13:07:08 UTC showed convergence 441/−$543.8409 (+5) and Premium 748/−$1,379.6668 (+2), matching report deltas. Four feeds remain connected with 105 pairs and performance ok; p95 lag 12.03 ms, RSS 253.74 MiB, CPU 55.93%, 987.0 books/s, metadata age 3,112.1 s; no open positions and three pending funding items. Carry v2 at 13:05 had 151 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,494,549/9,437,184 bytes. Review 136 added 41 exact closes/−$66.93784: convergence 11/−$10.76323 and Premium 30/−$56.17461; four wins (one convergence, three Premium), 37 losses, one separate Premium abort, no estimates. All four gains were independently audited as failed-hedge rescues, not paired arbitrage; IDs and accounting are in `reports/live-review-catchup/review136-positive-records.json.gz`. Rejections: 42 Hyperliquid price limits and one RH Lighter notional cap. Reviews 66–136 have 1,791 closes: 1,775 losses, two paired gains and 14 failed-hedge rescue gains. The review136 epoch snapshot read 13:27:08 UTC showed convergence 453/−$555.2242 (+12 versus report +11) and Premium 778/−$1,435.8414 (+30, matching); preserve mismatch and rely on report deltas. Four feeds remain connected; pair count fell 105→98, performance ok, p95 lag 11.49 ms, RSS 255.24 MiB, CPU 62.86%, 961.6 books/s and metadata age 707.1 s; no open positions and three pending funding items. Discovery at 13:14:43 UTC logged 98 pairs/52 assets, `unavailable=[]`; no retained prior 105-pair list exists to identify seven removed pair IDs. Carry v2 at 13:25 had 155 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,525,091/9,437,184 bytes. Review 137 added 167 exact closes/−$239.15110: convergence 85/−$84.93707 and Premium 82/−$154.21403, with seven wins, 160 losses and four separate aborts; no estimates. Root audited all seven wins as one-leg failed-hedge rescues after Hyperliquid price-limit rejection, not paired arbitrage. The bounded trade payload archive is `reports/live-review-catchup/review137-positive-records.json.gz`; audit is `reports/live-review-catchup/review137-positive-root-audit.json`. The seven net gains sum to about $1.39915; paired closes (five convergence, sixteen Premium) all lost. Raw depth is unavailable; no fill-depth claim. Rejections: 145 Hyperliquid price limits, one Lighter price limit, three RH Lighter price limits and one RH Lighter notional cap. Reviews 66–137 have 1,958 closes: 1,935 losses, two paired gains and 21 failed-hedge rescue gains. The review137 epoch snapshot read 13:47:09 UTC showed convergence 538/−$640.5342 (+85) and Premium 860/−$1,590.0554 (+82), matching report deltas. Four feeds remained connected with 98 pairs and performance ok; p95 lag 29.29 ms, RSS 254.32 MiB, CPU 76.30%, 1,315.7 books/s and metadata age 1,907.1 s. No open positions; three pending funding items remain. Carry v2 at 13:45 had 159 sampled slots and one persistent `arrival_invalid` slot 71; no terminal error, retries or economic evaluation. Manual archive use is 3,562,309/9,437,184 bytes. Next review: **1 October 14:06:33 UTC**.

The original dated-carry run was interrupted by reboot after 136 recorded slots:
134 sampled and two late callbacks. Its last trusted index and all evidence
are preserved. The frozen no-resume and same-boot rules prevent resuming
sampling or publishing its economic analysis. The original status file is a
stale pre-reboot record; see its separate recovery observation.

The user explicitly authorized a separate fresh 72-hour run within the existing
storage budget. [V2 preparation](dated-carry-relaunch-v2.md) keeps the original
method and source files, subdividing the same 16 MiB into 1 MiB for retired v1
and 15 MiB for fresh v2. No new economic outcomes have been inspected.
All 44 focused/adjacent tests passed. Fresh metadata and freeze are committed;
PID 42223 launched at 00:26:07 UTC. Fixed window: 1 October 00:30 UTC through
4 October 00:30 UTC (3 October 8:30 p.m. Eastern endpoint). The 864-slot roster
is separate from retired v1. Check only terminal health until that endpoint;
all launch, finalization and recovery use `scripts/dated_carry_relaunch.py`.
Actual all-cost feasibility and closed P&L remain null because settlement,
conversion, net inventory, margin and execution details remain unresolved.

## Original experiment: RH passive exit v1

- Assets: XAG primary; BTC/ETH continuous crypto controls; NVDA a separately
  labeled out-of-regular-session cohort in the current UTC window.
- Sizes: $100/$250/$500/$1,000; primary $1,000. Standard public fees primary,
  Premium as a separately accounted sensitivity. Branches cannot be summed.
- Entry: RH maker buy at a valid best bid, contingent HL short after attributed
  public trade flow. The study assesses possible queue fills, not private fills.
- Four exit comparisons: ten-second taker control, best-ask passive ten-second,
  cost-targeted passive ten-second, cost-targeted passive sixty-second.
- Primary decision: XAG / $1,000 / Standard / targeted passive ten-second.
- Same-entry comparisons require identical admitted entries. A slower branch
  must not be compared with a faster branch using different trading periods
  without also reporting candidate coverage and portfolio differences.
- Fixed passive exit price in v1; no hindsight repricing. Full lifecycle includes
  delayed activation/cancel, partials, contingent HL buybacks, emergency exits,
  late prints and unresolved obligations. No reset that erases exposure.
- Calibrate the adverse HL buyback move from prior public buy-aggressor flow;
  freeze it for the holdout. Fees, capital and the 5 bp stress are separate.
- Freeze method, all implementation dependencies and fresh metadata before
  capture. Thirty minutes of calibration followed by twenty minutes holdout;
  final 80 seconds admit no new entries to permit bounded liquidation.

Engine, coordinator, metadata and independent accounting/performance reviews
completed before the source freeze at 02:27:26 UTC (commit `6886d59`). The
50-minute capture started at approximately 02:27:32 UTC, with calibration until
02:57:32 and holdout through 03:17:32. Original frozen replay files and the
production strategy remain separate. See the preserved launch manifest in
`reports/rh-passive-exit-v1/launch.json`.

## Operational success threshold

This is a research stopping threshold, not proof of executable profitability.
Require the predeclared primary policy to achieve all of:

1. At least 100 fully closed cycles over at least two fresh twenty-minute
   holdouts, with positive total stressed net in each holdout.
2. At least $10 combined net after all modeled fill fees, the declared 5 bp
   stress and capital; profit factor at least 1.5.
3. The net and profit factor include **all admitted known outcomes**, including
   failed hedges, partial/rescue losses and zero-flow attempts. They are not
   conditional on successful cycle completion alone.
4. No unresolved economic obligations, missing required funding or execution
   uncertainty in the scored portfolio. Unknowns do not count as zero profit.
5. Results and adverse tails remain visible by size, tier and asset. USDG/USDC
   parity and public queue assumptions remain explicit limitations.

Repeated research and stopping when results look favorable introduce selection
risk. A later promising policy needs its own frozen confirmation windows; a
positive branch discovered among many alternatives is exploratory evidence.

## Loop

Implement → audit → freeze → collect bounded fresh data → replay → examine
all outcomes and coverage → write notebook and commit → choose one justified
next change or replication. During collection, review production on its
twenty-minute schedule and research the next concrete hypothesis. Never alter
an in-flight experiment's frozen source or train on its holdout outcomes.

Each capture and derived output has an explicit cap. Before any repeat, check
the cumulative research footprint and retain a bounded number of raw studies;
do not create an unbounded automatic capture loop. The user may stop the active
work at any time; stop study collection gracefully and preserve terminal
inventory and manifests rather than fabricate a close.


## Connectivity preflight, 02:21 UTC

A separate 30-second public-feed check completed normally: 1,287 raw records,
855,162 bytes including frozen metadata and manifest. It is neither calibration
nor holdout and has no modeled economic outcomes. The normalized feed supplied
56 HL books per asset (median gap about 0.535 s), RH books for all four assets,
and RH trades for all four. XAG had one trade and a maximum RH book receipt gap
of 2.148 s; this short check cannot establish sustained fill opportunity or
rule out the experiment's two-second validity/confirmation failures. Exact
counts and source-age diagnostics are in
`reports/rh-passive-exit-v1/preflight.json`. This preflight preceded the long
capture described above.

## Research during collection, 02:41 UTC

The old stopped quote comparison has no complete-cycle fill evidence. Its
[cost headroom chart](../reports/passive-hedge-venues/cost-headroom.svg) shows
median $1,000 static headroom above the $0.10 target of only +0.09 bp for
RH/HL silver and +1.46 bp for RH/Core silver. Every group misses the additional
5 bp stress allowance. Smaller sizes face a larger relative $0.10 target.
The [cost sensitivity](passive-cost-buffer-followup.md) separates actual modeled
fill fees from hypothetical amortized rebalancing and the unpaid stress.
Prepared future-only modules permit a separate quote-selection allowance and
bounded three-venue capture; neither changes current v1. A broader, bounded
public universe screen is being prepared to find assets whose quoted spread
can clear the hedge costs before investing another full capture in them.

Public queue evidence remains a separate barrier. The prior Standard BTC/ETH
branches became unresolved within about two minutes; Premium's later fills
were not comparable observations. See the [common-window diagnostic](rh-entry-queue-followup.md)
and [queue uncertainty research](public-queue-uncertainty-followup.md).
Future latency/queue scenarios must be explicitly assumed, preserve every
resulting hedge and exit loss, and stay separate from the strict v1 control.


## Interruption and prospective restart, 02:53 UTC

The first capture ended without a final manifest before calibration completed;
its raw bytes and interruption evidence remain preserved. It has no scored
holdout. The unchanged method was re-frozen with fresh metadata at 02:52:37 UTC
and restarted at 02:52:57 UTC in a new directory. Current calibration ends about
03:22:58 and holdout about 03:42:58 UTC. See the live-operations restart entry
and `reports/rh-passive-exit-v1-restart/launch.json`. No outcomes from the
interrupted raw file informed the strategy. New subagents use gpt-6.1-sol high
as explicitly requested; no in-place model change was used.

## Next TUI rollout requirement, 03:07 UTC

The user requested that headline paper results show **only the latest strategy
version**, so the current policy's performance is apparent. Preserve historical
ledgers and archives; exclude their accumulated P&L from the new headline.
Display an explicit strategy version and start time. Keep current-version
counts, wins, fees and realized net durable across process restarts and rolling
trade retention. Positions admitted under an earlier version remain carryover
exposure and must not enter the new version's realized result when they close.
Available wallet balances and capital constraints remain real paper state;
versioning is not permission to replenish or reset them. Prepare this for the
next planned rollout, with focused migration/restart/carryover/resize tests.

## Screen and correction freeze, 03:23 UTC

The completed independent universe replication ran 03:11:00–03:15:07 UTC:
21 eligible markets, five rounds, 105 HL books, 320/420 valid size observations.
All 100 rejected size observations failed source/receipt freshness. None of
the valid static cycles cleared fees, $0.10 and the separate 5 bp stress;
the best eligible $1,000 median was XAG at −$0.508121. No positive-profit
candidate was nominated. The two-round connection failure remains separate,
and cumulative request use is disclosed in the [readout](../reports/passive-universe-screen/20260930T0310Z/readout.md).
An offline optimistic zero-hedge-cost budget will check whether fee savings
alone could justify another venue screen. It cannot predict future fills
or bound a price-changing cycle's eventual return.

The [retirement correction](passive-retirement-correction.md) was independently
reviewed and frozen at **03:18:43.851172 UTC**, before both the conservative
03:22:37 source-freeze-based deadline and actual holdout boundary. It fixes
late qualifying flow received on the callback that retires an entry quote:
the affected old episode becomes execution-unknown. No fill or cash is
invented. The correction is explicitly a calibration-time amendment to a
capture already in progress. Its separate wrapper pins the original 18
files plus two correction files and will publish separately from strict v1.
The one-shot supervisor is waiting to run strict v1 after capture completion;
the corrected replay will run separately against the same stopped raw file.

During holdout collection, future ACK timing scenarios and a strict/corrected
comparison utility are being prepared with synthetic tests only. None reads
the active holdout or changes its frozen strategy. A less restrictive assumed
ACK clock can improve measurable coverage; it cannot establish a real queue
position, eliminate economic costs or demonstrate executable profitability.

## Completed capture and current preparation, 03:53 UTC

The replacement capture completed normally at 03:42:58 UTC with 124,019
records and 48,931,302 total archive bytes. Strict v1 and the separately frozen
entry-retirement correction are replaying the same stopped archive, each with
a one-hour limit. Their completed readouts remain pending. The 20 original
and correction source files remain unchanged.

The current-version TUI was deployed at 03:36:13 UTC. Version
`e3e83cda71a6` has its own persistent epoch; older positions keep their
original attribution and wallet balances were preserved. See the
[rollout verification](../reports/paper-strategy-epoch-review/rollout-verification.json)
and [version display method](paper-strategy-version-display.md).

The future ACK scenario adapter is implemented in commit `8fc0365` and has
passed independent synthetic review. A possible replay on this completed
archive will be explicitly exploratory and post-capture, with its own source
hashes and outputs. It includes historical-evidence guards, duplicate-ID
handling and coverage checks as well as clock assumptions; any difference
cannot be attributed solely to latency.

Synthetic review also confirmed a separate frozen-parent limitation: after
an unrelated branch halt, a newly received old-source buy can bypass the
retired passive-ask guard. The portfolio remains unknown, but an earlier
closed episode can incorrectly retain known status. Before using episode
contributions from either frozen replay, inspect retired passive-ask counts.
Zero retained asks rules out this particular defect; retained asks with a
halt require separate historical-evidence adjudication. Keep the frozen
results intact and label any affected reported contributions provisional.

No further raw capture starts until the cumulative raw-study count is
reconciled with retention policy. Offline quote-distance arithmetic and the
storage review can proceed without collecting another archive.

## Frozen readout and next bounded diagnostic, 04:11 UTC

Both frozen replays completed at 03:58 UTC. The
[readout](../reports/rh-passive-exit-v1-restart/readout.md) has 29 known
complete independent portfolios, all negative, and 99 unknown. Primary
Standard XAG/$1,000 admitted 57 attempts and closed 56 without flow before
cancellation ambiguity; no completed primary trading cycle or paired
comparison. The entry-retirement correction changed no admissions or episode
classifications on this input. Eleven halted branches with retained passive
asks have provisional closed contributions withheld from validated inference.

Crypto targeted asks repeatedly exceeded the fixed 5 bp ceiling and were
not posted. The [static exit-distance diagnostic](../reports/passive-universe-exit-markup/0310Z-input-v1/readout.md)
confirms that cost-covering quote distances can exceed that ceiling, without
establishing any maker fill. The subsequently completed stopped-data
[flow-reach diagnostic](../reports/rejected-target-public-reach/REPORT.md)
found no eligible observed buy print reaching any of the 150 rejected targets
within its fixed window. Widening the ceiling alone is unsupported.

The base and plus200 exploratory ACK scenarios launched at 04:10:54 UTC,
each in its own process with a one-hour deadline and bounded outputs.
Their 21 dependencies are immutable through both runs. These scenarios keep
the frozen price/fee policies and expose execution-model sensitivity; a
favorable result would still need a separate prospective confirmation.

The [fixed storage amendment](experiment-storage.md) now preserves all seven
current raw archives and permits at most one additional 128 MB complete
archive, subject to separate design/freeze/preflight, under a fixed eight
archive/512 MB selected-raw limit. No new capture has launched. Next
production review after review 45 is 07:26:33 UTC.

## Completed ACK sensitivity, 04:30 UTC

Both exploratory scenarios completed with stable dependency hashes: base at
04:26:25 UTC and plus200 at 04:23:27 UTC. Base has 12 conditional complete
portfolios, all negative, and 116 unknown; plus200 has all 128 unknown.
The [comparison](../reports/rh-passive-ack-exploratory/readout.md) preserves
all four models and all six cohort alignments. The primary XAG branches
remain without a completed trading cycle. Timing-model changes combine
different clocks, coverage and historical-evidence checks; reduced losses
in partial records cannot be interpreted as improved profitability.

Next work checks the dominant coverage and late-anchor halt causes and
inventories existing evidence for a contemporaneous spread admission gate.
No further raw capture is justified by the results so far. Production review
37 remains negative; no strategy promotion or wallet reset.


## Fixed-anchor feasibility result, 04:59 UTC

The predeclared one-second scan of the completed 50-minute RH/HL archive
finished at 04:57:02 UTC, with one canonical traversal, unchanged hashes and
7,554,465 output bytes below its 16 MB cap. The
[readout](../reports/passive-rare-spread/0252Z-fixed-1s-v1/readout.md) preserves
all 48,000 scheduled asset/size/time rows: 47,624 valid, 20 initially missing,
304 stale and 52 lacking sufficient recorded HL depth. **Zero valid positives**
after four public fees, $0.10 and 5 bp stress, across every size/asset/stratum.
The best $1,000 margins are XAG−$0.373095, NVDA−$0.428904,
BTC−$1.298121 and ETH−$1.294737; all recurrence thresholds fail.

This stops the contemporaneous RH-maker/HL-taker gate on the covered fixed
anchors and quantities. It does not test Core, every market time, other assets,
price-changing cycles or future regimes. Capital/funding and actual execution
remain outside this static margin, and correlated observations are not treated
as independent trials. No new capture or strategy promotion follows.

The [reverse HL-maker/RH-taker bound](../reports/passive-rare-spread-reverse-bound/0252Z-v1/REPORT.md)
completed at 05:13:04 UTC after method/source commit `de2fdef` and nine
passing synthetic tests. All 47,624 evaluated upper bounds are nonpositive;
376 parent-invalid rows remain reverse-unadjudicated. All 48,000 identities
and 80 asset/size/stratum groups are retained. Published output is 852,744
bytes under the 2 MB allocation, with unchanged parent/source hashes and
no raw traversal or network request. This excludes only the unchanged
best-quote reverse margin at inherited q, with target and stress but excluding
funding. Other quantities, wider quotes and price-changing cycles remain
outside the bound. It supplies no reason for a new capture or promotion.


A supplemental [derived-row verification](../reports/passive-rare-spread/0252Z-fixed-1s-v1/verification.json)
was added after original publication; all manifest-covered files stayed
unchanged. Total with this 1,338-byte attestation is 7,555,803 bytes. Its
48,000 CSV rows, 12,000 timing references and all five strata reconcile.
At $1,000, 942 XAG and 69 NVDA observations clear trading fees plus $0.10,
but zero clear the additional 5 bp allowance. The greatest fee-only quoted
margins are XAG $0.226464 and NVDA $0.170798; BTC and ETH remain negative
even before target and stress. These assumed-fill quoted margins do not
establish execution or realized profit. The declared stress allowance is
separate from charged fees and has not been lowered after seeing results.

## Delayed taker quote diagnostic, 05:21 UTC

The [reviewed method](delayed-taker-fixed-quantity-plan.md), committed as
`71e4127` before implementation, tests a distinct question on the same stopped
archive: whether later basis movement can cover delayed four-taker quote
costs. It fixes 7,200 original candidates across both directions, four assets
and four sizes, each with a shared delayed entry and separate 10/30/60/300 s
outcomes. All 28,800 rows, initial failures and EOF outcomes remain visible.
Fees, stress, capital and unknown funding are separate. Paired quotes do not
model private fills, price-limit rejection, partials or hedge rescue.

Implementation and independent review completed with 31 passing synthetic
checks; source/tests were committed as `1b79060` before evaluation. One
canonical traversal launched at 05:48:25 UTC with its 33 input/dependency
hashes persisted before traversal. Output target:
`reports/delayed-taker-quotes/0252Z-v1`. An external 900-second deadline
and internal cap enforce the bound (deadline approximately 06:03:25 UTC).
The 3 MB aggregate output allocation is recorded in `d9e8124`; no raw
archive is added. The process exited with code 1 before the deadline:
the compressed outcome table exceeded its 1.85 MB sublimit. No completed
economic result was published. Preserve the 460,596-byte `.building`
directory and its [failure record](../reports/delayed-taker-quotes/0252Z-v1.building/failure.json);
all 33 input hashes were rechecked unchanged after failure.

A separate resource amendment passed root and independent review with 40
focused tests. Commit `337097a` freezes 4 MB maximum output, a larger outcome
sublimit, and bounded memoization of pure repeated level validation. Every
book's structural/grid validity and all timing rules remain enforced.
Candidate grid, economics, 900-second limit and stopped input remain fixed.
The second and final authorized traversal launched at 06:17:02 UTC into
`reports/delayed-taker-quotes/0252Z-v2`, with 33 dependency/input hashes saved
before traversal. Deadline approximately 06:32:02 UTC. Results remain pending;
no automatic retry or partial-result conclusion follows.
This is post-capture exploratory analysis with no automatic policy selection,
capture or promotion.


### Second attempt failure and separate resource amendment, 06:33 UTC

V2 ended with external timeout exit 124 at its original 900-second limit.
Its full canonical terminal was not verified and no economic results were
published. All 33 frozen inputs were rehashed unchanged; 117,265 bytes of
source/freeze/failure evidence are preserved in `0252Z-v2.building`.
An attempted early termination had been rejected by automatic approval
review and was not executed; the original timeout ended the process.

The author reproduced default-cache thrashing on synthetic 40,000-level
working sets: four cycles took about 0.8122 s cached versus 0.1866 s with
the original validator and 0.1981 s with the existing cache disabled. The
cache recorded zero hits, 160,000 misses and 152,007 evictions. This is a
synthetic diagnosis, not a measured hit ratio for the stopped archive.

Root explicitly supersedes the v2 second/final limit for one additional
resource-only revision, subject to independent review and a new commit/
freeze before launch. Inject the existing disabled-cache path; preserve
the full 7,200/28,800 grid and all economic/timing/validity criteria. Set
a fixed 1,200-second internal/external deadline, based on the first
attempt completing its canonical traversal within 900 seconds and the
limited synthetic comparison; completion is not guaranteed. Retain the
4 MB aggregate and 3.25 MB outcome limits. No automatic retry.

The v3 allocation reserves both failed attempts plus the new run and
20 KB additional documentation: 32,480,772 of 33,000,000 bytes, leaving
519,228 bytes. The 820 MB total reservation and raw archive count stay
fixed. Implementation is authorized; the traversal has not yet launched.

V3 passed root and independent review with 41 focused tests. Commit
`92f74a7` freezes the minimal uncached recovery before its one authorized
launch at 2026-09-30T06:37:00.151635+00:00. The helper saved all 33 hashes before
canonical traversal into `reports/delayed-taker-quotes/0252Z-v3.building`.
The fixed external deadline is approximately 2026-09-30T06:57:00.151635+00:00.
No other replay or raw capture is launched. Results remain pending;
no fourth attempt is authorized by this amendment.


### Delayed taker diagnostic completed, 06:52 UTC

The separately frozen v3 run completed at 06:52:04 UTC in 904.45 seconds.
All 7,200 candidates/28,800 outcomes remain, with 26,395 complete quotes
and 2,405 incomplete. **Every complete quote is negative after fees alone**
at each of 10/30/60/300 seconds, including all sizes and both directions.
All 33 actual input hashes and nine published output hashes match; the
independent derived-row verifier passed. Completed output is 2,530,132 bytes.
See the [audited readout](../reports/delayed-taker-quotes/0252Z-v3-analysis.md).

A separately labeled unchanged-quote fee-reduction bound also has zero
positives even after forgiving all trading fees while retaining original
stress/capital. It does not price another venue, maker execution or funding.
The completion reconciliation releases unused v3 output allowance and
reserves 100 KB for derived analysis/audit, giving 31,110,904 of 33,000,000
bytes. Both failed attempts remain; no new raw archive or replay follows.
These findings do not justify a selector fit, threshold relaxation,
strategy promotion or additional capture. The ongoing production review
schedule continues; the next review is 07:06:33 UTC.


### One prospective spread-regime prerequisite watch, 07:18 UTC

The old LIT optimistic peak does not justify a Core-specific static rerun:
only one of five valid rounds was positive and its median was negative.
Nonnegative hedge spread/fees can only tighten that unchanged-price bound.
No Core quote screen or full execution capture is launched.

A distinct [prospective method](rh-spread-regime-sentinel-plan.md), committed
as `f87191b` after root and independent review, asks whether NEW RH spreads
persistently pass the necessary ex-funding static cost budget across all
21 original assets. One fixed 20-minute window has 20 minute slots and
1,680 original size observations. The primary gate requires 16/20 valid,
a positive full-window median and positive medians in at least three of
four fixed five-minute blocks, each with at least four valid samples.
There is no economic readout before the endpoint or automatic repeat.

The 500 KB allocation `65fe3a0` explicitly counts new sampled public-network
evidence, including full fresh metadata, selected raw ticker messages,
source, derived rows, logs and failures. It is not a canonical flow archive
or evidence reuse. Projected shared maximum is 31,610,904 of 33,000,000 bytes.
At most three metadata requests and one RH ticker connection are permitted;
no Core/HL book calls or trade subscriptions. Receipt/sample clock guards
precede timestamp acceptance, with no clock rebaselining or stale fallback.

Implementation is authorized after method review; no new metadata or ticker
request has been made. Root will review code/tests, then separately review
fresh metadata and freeze sources before launching. Even a positive
prerequisite supplies no paired hedge, maker-fill or profitability evidence.


### Production review 46, 07:26 UTC

The complete twenty-minute review adds cooldown 50 exact closes/−$60.6943
and Premium three/−$5.1906, both zero wins. Cooldown remains −$35.7272
without the stress allowance. Current-version closed totals are −$758.7532
cooldown and −$155.3691 Premium; two cooldown positions are open in the
separate later snapshot. Four feeds remain connected. The sentinel is still
in implementation review with no collection started. Next production review:
**07:46:33 UTC**. Full accounting is in the [review journal](review-loop.md).


### Production review 47, 07:46 UTC

Cooldown adds45 exact closes/−$45.9149 and Premium six/−$9.5264, both zero
wins and complete coverage. Cooldown remains −$23.4442 before stress;
observed exit-price changes improved the result by $0.457314. The separate
later current-version closed totals are −$806.6607 cooldown and −$164.8956
Premium, with all current positions flat. Four feeds are connected. Final
sentinel implementation review continues; no collection has started. Next
production review: **08:06:33 UTC**.


### Sentinel implementation approved, 07:55 UTC

Root and independent review pass the final implementation with 13 focused
fixtures. The dry invocation made no network calls. Reviewed boundaries include
receipt clock checks before source watermarks, dual-clock metadata age,
malformed/error/generation invalidation, exact fixed-denominator gates, no
pre-endpoint economics, and reserved space for all missing rows and manifests.
Normal source/control writes reserve 8 KB for terminal reporting; the
pre-connection check leaves a further 2 KB for index growth. Total allocation
remains 500,000 bytes. All economic rules are unchanged.

Source/method/tests are committed before the single three-request fresh
metadata preparation. Root will inspect that preparation, freeze its hashes,
and launch the one fixed twenty-minute window only while each metadata
response remains within 120 seconds on both clocks. No retry, replacement
request, alternate endpoint or automatic reconnect is permitted.


### Sentinel failed before quote collection, 07:56 UTC

Implementation/source freeze `c16be2f` and fresh metadata freeze `53a2a66`
preceded the one launch. All three public metadata requests succeeded and all
21 original assets were eligible. The run then stopped before creating its
websocket task: control usage was **80,274 bytes**, above the unchanged
80,000-byte admission guard. No quote connection opened and no economics were
computed. All 1,680 uncollected rows and all metadata are retained. The audited
stage occupies **315,927 bytes**, including its failure readout and root audit.
The full original 500,000-byte allocation remains reserved; no budget is released.

The full-artifact fixture proved the 90,000-byte final category ceiling but
failed to exercise the actual stricter run-admission path. Root and independent
review missed that mismatch. This is an implementation/preflight failure, not
evidence about market spreads. Sources, tests, method and failed stage remain
frozen, with no retry or refetch. A new compression-wrapper proposal may reduce
redundant source archive bytes while preserving exact decompressed identities,
all dependencies, economics and aggregate cap. Only a read-only proposal is
requested now; implementation and another network study require separate review.
The next admission fixture must exercise actual prepare/freeze/run scheduling
through a fake websocket, using the retained metadata without any requests.


### Separate compact-source revision: implementation only, 08:03 UTC

Root and independent review accepted a new thin-wrapper proposal, preserving
all frozen sources and the failed stage. Compressing the three archived source
copies alone saves 37,181 bytes (56,344 to19,163). The wrapper must record
compressed and decompressed identities, hash all five original and three new
inputs, reject unmarked/old stages, and restore scoped runtime bindings.
Original economics, clock checks, request limits and 80/90/500 KB caps stay fixed.

A new offline fixture must exercise delegated prepare/freeze/run/receive through
a fake websocket using the retained failed metadata; it must reach actual
admission, subscribe21assets, wait the virtual endpoint, and publish420references/
1,680rows under the final cap. It must also reproduce the old guard rejection.
The former final-size-only fixture is insufficient. No network is authorized yet.

The compact allocation reserves an additional500,000bytes while retaining the
first full500,000bytes: shared projected maximum32,110,904of33,000,000bytes,
headroom889,096. Overall820MBreservation is unchanged. This permits considering
exactly one separately reviewed successor preparation/window; it does not retry
the old stage or authorize further automatic attempts. Total maximum across
both stages is six metadata requests and one actual ticker connection.


### Production review 48, 08:06 UTC

Cooldown44 paired closes/−$46.8586 and Premium six/−$9.2912 have zero wins.
Convergence four failed hedges total−$2.8037, including a new+$0.047294
CASHCAT Core partial-short rescue after HL rejected its long hedge. The raw
paper record is preserved; it is not a paired-cycle profit. Complete coverage,
four connected feeds and unchanged strategy version continue. The compact
sentinel wrapper remains offline under review. Next review: **08:26:33 UTC**.


### Compact wrapper approved for one fresh preparation, 08:12 UTC

Independent review passed six compact-wrapper fixtures; root passed those plus
all13originalfixtures together (19total), verified matching source hashes and
confirmed default dry mode reports zero requests. The new fixture reaches the
real delegated run/receive admission and complete virtual endpoint; its control
reproduces the old zero-connection rejection. Eight dependencies are verified
against the same before/after snapshot, and scoped bindings restore on success
or failure. Original frozen source/test/method and failed metadata are unchanged.

Root authorizes the separately allocated, single new three-request preparation
after committing the wrapper/test/resource note. Fresh eligibility and actual
control headroom must be checked before separate freeze/run. No retry or further
successor is automatic; the first failed study remains fully visible.


### Compact successor running, 08:12:47 UTC

Source/wrapper/tests freeze `c927e2a` and fresh marked metadata freeze `a531060`
preceded the separate launch. The three new metadata requests succeeded;
all21assets retained original identities/lots/ticks and zero public RH maker
fees. Root recomputed eligibility from full responses, checked all eight
input hashes and decoded archive identities, and measured52,884controlbytes
before root-freeze, leaving21,116bytes even after a6,000-byte freeze/schedule
allowance under the actual80,000-byte launch gate.

The one ticker window activated at08:12:47.655706UTC; T0is08:12:57.655706,
and the immutable endpoint is**08:32:57.655706UTC**. Firstslot dispatch lag
was0.66247ms;16source-timing-valid references and five stale references.
This is technical coverage only. No U or economic readout has been computed
or inspected. No reconnect/extension/automatic successor is permitted.
An independent derived-output auditor is being prepared on synthetic inputs;
it must refuse pre-endpoint/missing-manifest inspection and will run only
once the published window is complete. Nextproductionreview08:26:33UTC.

### Production review 49, 08:26 UTC

Cooldown50 paired closes/−$59.9870; Premium15/−$23.6685 (14paired, one
failed hedge); convergence one failed hedge/−$1.6130. No new wins, complete
coverage, four connected feeds. Later current-epoch totals are retained
separately; no balances reset. The compact sentinel remains unread until
08:32:57UTC. Next production review: **08:46:33 UTC**.

### Independent auditor frozen before endpoint, 08:27 UTC

Commit `3022b04` freezes the separate auditor and five synthetic tests.
Root and author both passed all five, including complete synthetic publication,
pre-endpoint refusal, and deliberately corrupted quantities, U, block medians,
block gates, source/receipt clocks, hashes and missing-row promotion. The
source is18,433bytes and tests10,032bytes; both plus a report below8,000bytes
and the entire stage must stay within the compact study's500,000-byte cap.
Auditor SHA256: `765491aa7437f0c4a5a0065a7caf7b64c8aaddd49f24338ba2ec618da65ae131`.

After the fixed UTC and monotonic endpoint and terminal manifest, root will
run it once. It checks eight dependencies, six compressed/decoded source
archives, all publication hashes and storage categories,420sample references,
1,680exact rows,84groups and336fixed blocks. Quantities/U/medians/gates use
independent exact arithmetic. It pins fresh metadata and eligibility rather
than re-running the selector; root independently reviewed those full responses
before launch. It cannot reconstruct every intervening invalidation or source
watermark from sampled tickers alone. No live economic data was read during
implementation or test review.

### Sentinel completed and rejected, 08:33 UTC

The fixed endpoint was reached and all 420 references/1,680 rows published.
The precommitted independent auditor ran once and passed; its author also
reviewed the completed readout without rerunning it. There are 1,340 valid and
340 stale size rows (335 valid/85 stale asset references). Every one of 84 observed
asset/size medians and 336 block medians is negative. Thirteen of 21 assets meet
primary coverage, but none meets the economic gate. Only NEAR slots 4/5 and
LIT slot 10 at $1,000 have positive U; these are optimistic budget surpluses,
not fills or profits, and cannot motivate selecting a different threshold.

The [separate analysis](../reports/rh-spread-regime-sentinel/20260930T0812Z-compact-analysis.md)
retains the original failure, all exclusions, quote/queue/funding uncertainty,
source/resource identities and close code 1006. No recorded pre-endpoint stop
is not proof of uninterrupted coverage or a graceful websocket close.
The stage is 337,548 bytes; auditor/test/report add 29,365 bytes and the analysis
keeps the complete package under 500,000. Neither 500,000-byte allocation is
released. No automatic repeat, Core/HL book screen or full capture follows.

Continuing work is a bounded, offline design review of a distinct causal
basis-prediction hypothesis, checked against the already-losing convergence
and confirmation policies. Existing agents may inspect small code/method/
readout files only; no new capture, raw-archive scan, policy implementation,
threshold change or source modification is authorized by that review.
Next production checkpoint remains 08:46:33 UTC.

### Production review 50 and bounded method proposal, 08:48 UTC

Cooldown 70 closes/−$80.1627 (69 paired, one failed hedge); Premium 21/−$34.8332
(19 paired, two failed hedges, plus one abort); convergence three failed
hedges/−$3.3530 plus two aborts. No new wins, complete retained coverage,
same collector/reviewer processes and strategy epoch. Next review 09:06:33 UTC.

The proposed new question is delayed **Core↔RH all-taker quote feasibility**,
using two existing 420-second archives only. Prior Core comparisons assume
RH maker entry at the anchor and maker exit at a later quote; replacing
those fills with takers at unchanged timestamps only worsens their negative
stressed results. A first eligible delayed entry followed by a ten-second
hold is not covered by that bound. The difference establishes a missing
test, not evidence of return or permission for fresh capture.

Method drafting and independent review only are authorized. Proposed scope:
1,008 fixed candidates, four original assets/sizes and both directions;
500 ms entry/exit quote delay with 2 s deadlines, unchanged quantity, costs and
stale/gap/tail denominators. Historical crypto rule gaps and funding remain
unknown; paired quote timing is not private execution. No renamed ECM or
flow fitting proceeds on the existing uniformly negative RH/HL outcomes.

The separately recorded 600,000-byte allocation includes all new method,
source/tests, provenance, outputs, audit and failures. Shared projected
maximum 32,710,904 of 33,000,000 bytes leaves 289,096; total 820 MB reservation and
all earlier study/failure reservations remain. No archive traversal or
implementation is authorized until the method and resource bounds pass
root and peer review.


### Review 51 and Core/RH implementation approval, 09:07 UTC

The new 20-minute window remains negative with no winners: Cooldown
64 paired closes/−$68.8576, Premium 19/−$35.9288 (14 paired, five failed
hedges), convergence nine/−$15.6411 (one paired, eight failed hedges).
Coverage is complete. Four feeds remain connected and the original strategy
epoch/capital history is retained. Next production review 09:26:33 UTC.

Root and independent peer accepted the final Core/RH method, frozen in
`2a5bffd`. Implementation and synthetic tests only are authorized in new
files. Review must exercise actual admission, bounded gzip/decoder handling,
all 1,008 candidate identities and publication using fake archives before a
separately authorized real run. Key amendments: both entry-direction anchor
legs require depth; known-grid flags cannot cause illegal first quotes to
be skipped; raw price collisions are detected before float conversion;
explicit invalidation controls censor current lifecycles; all failure rows
including the unread second archive retain null economics. No raw stream
has been hashed or decoded for this study, and no network/capture occurs.
All original modules/methods/evidence and storage reservations remain frozen.


### Production review 52 and pre-run code findings, 09:27 UTC

Cooldown 68 paired closes/−$72.3501, Premium six paired/−$9.8235,
convergence two failed hedges/−$2.2329 plus two aborts. No new winners,
complete retained coverage, four connected feeds, same epoch and capital
history. Review and later current-version snapshot are flat; three legacy
funding obligations remain. Next checkpoint 09:46:33 UTC.

The Core/RH helper and independent derived auditor are being implemented
within the existing 600,000-byte allocation. Root and peer review are fixing
pre-run integrity issues: preserve failed-pair references; avoid numeric
rounding before raw collision checks; keep only bounded current books across
tied receipts; propagate invalidation scope and source regressions into the
actual decoder state. Producer review confirms normal duration-limit EOF
can omit a raw close control; manifest closure and complete gzip/counts are
the correct terminal evidence. Five auditor arithmetic fixtures pass; full
admission/decoder/publication fixtures and final code review remain required.
No raw traversal, fresh capture, network request, or production change has
been made for this diagnostic.

### Production review 53 and synthetic publication review, 09:47 UTC

Cooldown 36 paired closes/−$39.2766; Premium seven/−$13.0495 (three paired,
four failed hedges); convergence five failed hedges/−$7.1814. No new winners
or aborts; complete retained coverage. Nine Hyperliquid price-limit
rejections account for the failed hedges. The later current-version snapshot
has one cooldown position; all previous losses, capital and three legacy
funding obligations remain. All four feeds are connected; 110 pairs after
metadata refresh. Next review 10:06:33 UTC.

Root's synthetic all-missing summary exceeded the frozen summary limit;
the helper now compresses the complete 32-group/128-stratum summary without
raising caps. Every candidate now receives provenance references, including
startup missing-book rows. The separate prepared source/runtime freeze,
SIGTERM failure roster and removal of failed completion markers are in place.
The independent auditor has seven passing synthetic tests. Main decoder
fixtures and final combined review remain pending; no historical raw stream
has been hashed or decoded for this study.

### Core/RH canonical replay launched, 10:01 UTC

Root's final 28 synthetic tests pass, including actual CLI/decoder admission
and all 1,008 identities; independent producer review also passes. Sources
are frozen in `279ccd7`, prepared inputs in `dec83c6`. The zero-raw preparation
and root review checked all 19 small source/input digests and eight historical
rule sets. Source category uses 188,205 of the 190,000 internal bytes before
the separate documentation reserve.

The single canonical traversal is now running with a 900-second timeout and
five-second termination grace, unchanged 600,000-byte allocation, unchanged
economics and no retry. It covers the two stopped Core/RH archives and all
1,008 scheduled candidates. The external log is capped at 9,000 bytes; no
partial economics guide changes. Root will run the frozen derived auditor
once only after completed publication, or retain the full failure roster if
the run fails. Production review remains due 10:06:33 UTC.

### Production review 54, 10:07 UTC

Cooldown 42 paired closes/−$51.0983; Premium two/−$3.0930 (one paired,
one failed hedge); convergence three failed hedges/−$3.5799. No new winners
or aborts, complete retained coverage, four Hyperliquid price-limit failures.
All four feeds connected; 110 pairs. The later current-version snapshot is
flat, with all previous losses, capital and three legacy funding obligations
retained. Next checkpoint 10:26:33 UTC.

The frozen canonical Core/RH replay continues within its 900-second limit.
No partial economics inspected, source edits, retries or additional capture.

### Core/RH delayed taker diagnostic completed, 10:12 UTC

The one canonical process completed in 349.271 seconds at 10:07:08 UTC.
Root's frozen derived auditor passed once; peer review agreed on all 32
groups and 128 strata. No raw rerun.

There are 842 conditional complete quotes and 166 retained null-economic
censors. All gross/fee-only results are negative with zero public fees:
best −$0.001974. Primary coverage 572/672; each smaller size 90/112.
Historical legality, funding and private execution remain unverified.

The full [readout](../reports/core-rh-delayed-taker/20260930T1000Z-analysis.md)
records all groups, failures and limitations. The 600,000-byte allocation
and all old reservations remain. Close this study without predictor or
successor. Next paper review 10:26:33 UTC; a new experiment needs a distinct
supported mechanism and separate bounded proposal.

### Single-settlement rate check, 10:18 UTC

A separate 12,000-byte source-only review (`db99951`) joins the existing
hourly Core/RH table: 192 matched asset/events. Even hindsight direction
and favorable payment subsets give at most 0.41 bp, versus 6 bp stress plus
target at $1,000. This is equal-reference-notional rate arithmetic, without
actual payment ownership or joined trading prices; no executable bound.
[Readout](../reports/funding-carry/core-rh-single-settlement-review.md).
No successor capture. Shared reservation 32,722,904/33,000,000 bytes; all
previous allocations retained. Next production review 10:26:33 UTC.

### Production review 55, 10:27 UTC

Cooldown 50 paired closes/−$57.6998; Premium three failed hedges/−$5.0790;
convergence three failed hedges/−$1.7965. No new winners or aborts; complete
coverage. Six Hyperliquid price-limit failures. Cooldown exit execution
improved $0.8433 across 49 observed comparisons, so removing adverse exit
slippage cannot explain this interval's loss. Four feeds connected, same
version and capital history; later snapshot flat, three legacy funding
obligations retained. Next review 10:46:33 UTC. Completed route and funding
checks provide no supported successor experiment; no capture or policy change.

### Liquidation counter scope resolved, 10:38 UTC

Primary-source review left public RH liquidation eligibility unresolved.
The old counter also included subscription history. A separate classifier
frozen in `b6e5d30` completed one non-economic pass over each old archive:
all 65 liquidation rows were subscription history predating capture; zero
live liquidation updates. No new flow enters the old ten-second windows.
[Scope review](rh-liquidation-flow-review.md). Old fill exclusions remain;
no successor replay/capture. Shared reservation 32,742,904/33,000,000 bytes,
all prior allocations retained. Next production review 10:46:33 UTC.

### Production review 56, 10:48 UTC

Cooldown 45 paired closes/−$50.0479; Premium three closes/−$5.7185
(two paired, one failed hedge); convergence one aborted attempt with both
legs rejected. No new winners; complete completion/abort coverage. Two
Hyperliquid and one Core Lighter price-limit rejections. Cooldown exit
execution improved $0.823811 across all 45 comparisons, yet net remains
−$27.5765 with stress removed. Four feeds connected, same version and
capital history; later snapshot flat, three legacy funding obligations
retained. Next review 11:06:33 UTC. No supported successor experiment or
production policy change.

### Cash-session coverage proposal reviewed, 10:56 UTC

A source-only peer review considered a predeclared cash-open observation
of NVDA/XAG with BTC/ETH controls, keeping the existing spread prerequisite.
No successor is allocated. NVDA previously had 16/20 valid sentinel rows
and no positive optimistic budgets; session coverage limits generalization
but is not positive economic evidence. One cash-open window and crypto
controls would not identify a causal session effect or recurrence.

The unchanged compact collector also has no demonstrated resource fit:
its prior metadata and control used 287,740 bytes, above the remaining
257,096-byte shared reservation before samples or outputs. Fewer
subscriptions do not shrink full metadata responses automatically. A
descriptive session study would need a separate priority and resource
design. No implementation, metadata request, capture or cap expansion.

### Production review 57 and research direction, 11:08 UTC

Cooldown 47 paired closes/−$58.8049 (46 exact, one estimated); Premium
16 closes/−$30.0337 (ten paired, six failed hedges); convergence one failed
hedge/−$1.6524 and one aborted attempt. No new winners; complete coverage.
Eight Hyperliquid price-limit and one Core Lighter notional-cap rejection.
All four feeds connected; review and later snapshot flat. Same version,
capital history and three legacy funding obligations retained. Next review
11:26:33 UTC.

The user selected “Prepare a broader research proposal.” Prepare a separate
plan for longer holding periods and a different return source while the
current paper reviews continue. No revised production policy, live orders,
new capture or research budget increase is implied by proposal preparation.

### Broader proposal prepared, 11:16 UTC

The [proposal](broader-carry-research-proposal.md) prioritizes funded spot
plus short dated futures, then spot/perpetual and cross-perpetual carry.
It proposes BTC, one 7–30 day expiry selected by a frozen rule, one spot
book and a single 72-hour feasibility window. ETH is a later replication
candidate. Current primary specifications expose routed-spot fees, partial
public trade coverage and cash-settlement/index mismatch; these are explicit
preflight and accounting conditions.

The proposed 16 MiB allocation is separate from the 257,096 bytes remaining
in the existing diagnostic allowance. No allocation or collector was started.
Paper production and the scheduled review daemon continue; next checkpoint
11:26:33 UTC. The proposal is ready for a decision on the bounded next stage.

### Broader recommendation authorized and implemented, 12:34 UTC

The user requested continued research and proceeding with the recommendation
at 12:12 UTC. The new 16 MiB public-data allocation is frozen in `139efe1`,
retaining every earlier allocation. Implemented a one-shot 72-hour BTC spot
and dated-future collector, full-denominator endpoint analysis, and bounded
metadata preparation. Contract preflight and independent method review identify
known public entry fees and unresolved settlement, inventory and collateral
cash flows. The method is `dated-carry-method-v1.md`. No quote request precedes
the frozen T0; fresh metadata and launch freeze are the next operational steps.

Production reviews 58–61 are preserved in the review journal. No new winners
occurred; the six old failed-rescue wins and three legacy funding uncertainties
remain. The production policy and its capital history are unchanged.

### Dated carry observation launched, 12:42:51 UTC

Source freeze `1a2081c` follows the initial implementation `22cc9cc`; fresh
metadata/config freeze is `f0b863b`. All 37 focused tests pass. Two fixed public
metadata requests returned HTTP 200; expiry-only selection chose BTC_USDC-9OCT26.
The config and freeze hashes are preserved in `source_control/config.json` and
`freeze.json` under `reports/dated-carry/20260930-v1`. PID 279840 recorded its
immutable UTC/monotonic/host/boot mapping before the first request deadline.
The fixed window starts 12:45 UTC today and ends 12:45 UTC on 3 October.
Initial accounted usage was 185,534 bytes (161,347 source/control, 24,187
metadata); subsequent terminal records remain under the 16 MiB allocation.
No quote or economic lookahead preceded activation. Missing slots are retained,
there are no retries or automatic successors, and economics run only at endpoint.

### Review 62 and first dated-carry observation, 12:49 UTC

Production: cooldown 19/−$41.1271, Premium 30/−$61.9382, convergence six/−$6.3697;
all exact, four aborts, complete coverage. One PUMP failed-hedge rescue made
+$0.1911 after stress, bringing epoch win records to seven, with no new positive
paired cycle. Its exact record is preserved; no policy promotion follows.
All feeds connected. Next checkpoint 13:06:33 UTC.

The first dated-carry slot arrived before deadline on both endpoints. No prices
or economics were evaluated. A bounded additional public-document review could
not resolve routed spot fee currency or the selected weekly linear delivery
exemption. The supplemental note retains those uncertainties; the frozen method
and capture schedule are unchanged.

### Review 63, 13:06 UTC

All 37 new paper closes were exact and negative: cooldown 23/−$45.4605,
Premium 8/−$16.7380, convergence 6 failed/−$9.2110. No aborts, complete coverage.
Seven earlier rescue wins remain distinct from paired-cycle evidence. Four feeds
connected, 110 pairs, one current cooldown position; three retained legacy
funding obligations. Next checkpoint 13:26:33 UTC. The dated-carry study has
five successful paired arrivals and remains frozen; no economic readout yet.

### Review 64, 13:26 UTC

All 44 closes exact and negative: cooldown 27/−$61.1594, Premium 9/−$18.1743,
convergence 8/−$12.0159. Zero aborts, complete coverage; review and later
snapshot flat. Seven earlier rescue win records remain, with no new winner.
All four feeds connected; next review 13:46:33 UTC. The dated-carry collector
has nine successful paired arrivals, no errors and no interim economic readout.

### Routine review 65 NVDA annotation prepared, 13:40 UTC

A bounded descriptive breakdown will accompany the next existing paper review,
splitting retained NVDA attempts by creation before/after 13:30 UTC. It preserves
strategy, version, epoch, completion quality and unsettled denominators; no
causal session or independent holdout claim. Source-only review and a synthetic
settlement-cutoff check passed. No new outcomes have been read.

The conservative 120,000-byte annotation reservation fits within the existing
33,000,000-byte shared allowance: reserved now 32,862,904, headroom 137,096.
All earlier reservations and the separate dated-carry allowance are retained;
overall reservation remains 836,777,216 bytes. No new quote capture or policy
change. The existing dated-carry source and economic endpoint stay frozen.

### Review 65 and bounded NVDA annotation, 13:49 UTC

165 exact closes: cooldown 20/−$38.2285, Premium 75/−$149.6087, convergence
70/−$80.8370; one abort, complete coverage. Two positive paired closes and
three rescue wins were preserved and reconciled; full-window convergence
profit factor 0.0214. No promotion. Twelve epoch win records now include two
paired and ten rescue outcomes. Four feeds connected; all portfolios flat at
review and later snapshot; three legacy funding obligations remain.

The one-shot NVDA annotation found one post-13:30 Premium failed hedge,
−$1.6442, and no pre-13:30 attempts in the retained denominator. No session
claim is supported. The annotation completed within its reservation; no
extension or retry. Dated carry remains frozen, with 13 paired arrivals and
no economic evaluation. Next production checkpoint 14:06:33 UTC.

### Review 66, 14:06 UTC

All 46 closes exact and negative: cooldown twelve/−$13.7992, Premium
24/−$43.4084, convergence ten/−$8.8190. No aborts, complete coverage, no new
winners. Four feeds connected; one cooldown position at review and later
snapshot flat. Twelve prior win records and three legacy funding obligations
remain. Next checkpoint 14:26:33 UTC. The carry study has 17 arrivals and no
reported errors; its economic endpoint remains unchanged.

### Review 67, 14:26 UTC

All 45 closes exact and negative: cooldown 25/−$48.5700, Premium twelve/
−$22.1022, convergence eight/−$9.0479; zero aborts, complete coverage. Twelve
prior win records remain. Four feeds connected; a brief busy CPU period
subsided without intervention. Review flat, later snapshot one cooldown
position; three legacy funding obligations retained. Next checkpoint
14:46:33 UTC. Carry has 21 arrivals, no reported errors and no interim
economic readout.

### Review 68, 14:46 UTC

All 41 closes exact and negative: cooldown 21/−$44.5702, Premium twelve/
−$20.4497, convergence eight/−$9.7006. No aborts, complete coverage. Twelve
prior win records remain. Four feeds connected; scheduled metadata refresh
expanded to 115 pairs and rebuilt stream counters, so cross-refresh gap-count
differences are not event deltas. Busy timing is monitored without a policy
change. Review had one Premium entry, later snapshot flat; three legacy
funding obligations retained. Next review 15:06:33 UTC. Carry has 25 arrivals,
no reported errors and no interim economic evaluation.

### Review 69, 15:06 UTC

All 38 closes exact and negative: cooldown twenty/−$27.6966, Premium nine/
−$17.9565, convergence nine/−$9.2764; one convergence abort, complete coverage.
No new winners. Four feeds connected and performance normal; review and later
snapshot one cooldown position. Twelve prior win records and three legacy
funding obligations remain. Next review 15:26:33 UTC. Carry has 29 arrivals,
no reported errors and no interim economic readout.

### Future-model fee inventory envelope, 15:24 UTC

A source-only algebra check addresses a different sizing rule for a possible
future paper model. It is not applied to the frozen carry study or its data.
Let q be the intended gross spot sale/future quantity and s the spot amount
grid. Assume nonnegative aggregate BTC entry fees at most f_e*g+d_e and exit
fees at most f_x*q+d_x, with 0<=f_e<1. Each additive cap must cover every fill's
rounding across the whole order. Then choose

`g = ceil_to_s((q*(1+f_x)+d_e+d_x)/(1-f_e))`.

This ensures `g-(f_e*g+d_e) >= q+(f_x*q+d_x)`: acquired BTC covers gross sale q
and the assumed exit BTC fee. The four entry/exit fee-currency combinations
are checked by the [exact helper](../scripts/spot_fee_inventory_envelope.py).
A [synthetic example](../reports/spot-fee-inventory-envelope/synthetic-v1.json)
uses q=0.01 BTC, s=1e-8 BTC, f_e=f_x=0.0005, d_e=d_x=1e-8 BTC. It requires
**g=0.01001003 BTC**. All four residual lower bounds are nonnegative; the
BTC/BTC case has lower bound 0.000000004985 BTC. These are mathematical
bounds, not actual fractional-satoshi balances or a venue fee-rounding rule.

This does not authenticate fee caps, fill quantities or fee currencies.
Quote fees still need separate cash; both orders need valid depth, minima,
limits and funded budget, and q must satisfy both relevant quantity grids.
Surplus BTC/dust remains exposed; do not call this an exact neutral hedge or
closed P&L. Use gross purchase cost, sale proceeds and residual inventory
consistently: charging the USD value of BTC fee debits again would double
count their cost. Terminal index/FX mismatch, delivery and margin unknowns
remain. All-in headroom and closed P&L stay null.

The 16,384-byte reservation fits inside the existing shared allowance,
leaving 120,712 bytes at allocated maxima. No raw data or network was read,
no capture/replay was launched, and existing reservations remain intact.

Independent source/output review passed the formula, all four cases, source
hash, exact ceiling and conditional claims. No frozen-study input was read.

### Review 70, 15:26 UTC

All 61 closes exact and negative: cooldown 41/−$43.0369, Premium thirteen/
−$22.2830, convergence seven/−$4.9933. Zero aborts, complete coverage, no new
winners. Four feeds connected and performance normal; review and later
snapshot one cooldown position. Twelve earlier win records and three legacy
funding obligations remain. Next review 15:46:33 UTC. Carry has 33 arrivals,
no reported errors and no interim economic readout. The fee-inventory algebra
remains a separate future-model calculation.

### Review 71, 15:46 UTC

All 58 closes exact and negative: cooldown 45/−$48.4952, Premium eight/
−$11.3790, convergence five/−$6.8001. Three aborts, complete coverage; no new
winners. Four feeds connected and performance normal. Review flat, later
snapshot one cooldown position; three legacy funding obligations retained.
Next review 16:06:33 UTC. All 37 due carry slots have passed arrival checks;
no overdue missing files or terminal error. Native quote validation and
economics remain deferred.

### Review 72, 16:06 UTC

All 49 closes exact: cooldown 39/−$39.8568, Premium seven/−$11.0503,
convergence three/−$1.6108. Zero aborts and complete coverage. One convergence
failed-hedge rescue on ENA gained $0.1134; the other 48 closes lost money.
The complete winning record is preserved and its accounting reconciles:
Core short only, Hyperliquid long rejected, fully closed after 1.648 seconds,
zero fees/funding, $0.49997 stress and $0.000002612 capital cost. No new paired
winner or positive strategy window. Thirteen epoch win records now comprise
two paired gains and eleven failed-hedge rescues across separate portfolios.
Four feeds connected and performance normal; review and later snapshot each
had one cooldown position. Three legacy funding obligations remain. Next
review 16:26:33 UTC. Carry has 41 arrivals with no overdue files or terminal
error; economics remain deferred.

### Review 73, 16:26 UTC

All forty closes exact and negative: cooldown 34/−$41.3033, Premium five/
−$10.9282, convergence one/−$0.7558. Zero aborts, complete coverage, no new
winners. Four feeds connected and performance normal. Review and later epoch
snapshot flat; three legacy funding obligations remain. Thirteen prior epoch
win records retained. Next review 16:46:33 UTC. Carry has all 45 due arrivals
through 16:25, no overdue missing files or terminal error, and no economic
evaluation.

### Review 74, 16:46 UTC

All 36 closes exact: cooldown thirty/−$42.8157, Premium three/−$5.7333,
convergence three/−$2.8741. Zero aborts, complete coverage. One LIT convergence
failed-hedge rescue gained $0.03375; the other 35 closes lost money. Its
complete record is preserved and arithmetic reconciles: Core short only,
Hyperliquid long rejected, 1.315-second exposure, zero remaining quantity and
complete funding. Fourteen epoch win records now comprise two paired gains
and twelve failed-hedge rescues across separate portfolios. Four feeds
connected, 112 pairs after metadata refresh, performance normal; review and
later epoch snapshot flat. Three legacy funding obligations remain. Next
review 17:06:33 UTC. Carry has all 49 due arrivals through 16:45, no terminal
error or overdue missing files, and no economic evaluation.

### Review 75, 17:06 UTC

All sixty closes negative (59 exact, one estimated): cooldown 39/−$45.5813,
Premium eleven/−$23.5179, convergence ten/−$15.2065. One convergence abort;
complete coverage and no new winners. The estimated XAG paired close is
preserved: it crossed 17:00 funding, with sampled/inferred reference values,
fully closed quantities and no missing funding events. Its +$0.00756 estimated
funding leaves −$0.86915 net; it remains estimated. Four feeds connected,
112 pairs, performance normal; review and later snapshot flat. Fourteen prior
epoch win records and three legacy funding obligations remain. Next review
17:26:33 UTC. Carry has all 53 due arrivals through 17:05, no terminal error or
overdue missing files, and no economic evaluation.

### Review 76, 17:26 UTC

All 41 closes exact and negative: cooldown 37/−$48.8503, Premium one/−$1.8377,
convergence three/−$3.0349. Zero aborts, complete coverage, no new winners.
Four feeds connected, 112 pairs and performance normal. Review flat; later
epoch snapshot had one cooldown position. Fourteen earlier epoch win records
and three legacy funding obligations remain. Next review 17:46:33 UTC. Carry
has all 57 due arrivals through 17:25, no terminal error or overdue missing
files, and no economic evaluation.

### Review 77, 17:46 UTC

All 44 closes exact and negative: cooldown 37/−$42.0146, Premium four/
−$11.1031, convergence three/−$6.8466. Zero aborts, complete coverage and no
new winners. Four feeds connected, 110 pairs after metadata refresh,
performance normal. Review had one cooldown and one convergence position;
later epoch snapshot flat. Fourteen earlier win records and three legacy
funding obligations remain. Next review 18:06:33 UTC. Carry has all 61 due
arrivals through 17:45, no terminal error or overdue missing files, and no
economic evaluation.

### Review 78, 18:06 UTC

All 57 closes negative (56 exact, one estimated): cooldown fifty/−$53.5220,
Premium four/−$8.1908, convergence three/−$2.8169. One convergence abort,
complete coverage and no new winners. The estimated NVDA close is preserved:
its RH short preceded 18:00 funding, while the HL long entered after the
boundary. Estimated RH funding +$0.00798 leaves −$0.96554 net; both legs
closed with no missing funding events. Four feeds connected, 110 pairs and
performance normal. Review had one cooldown position; later epoch snapshot
flat. Fourteen earlier win records and three legacy funding obligations remain.
Next review 18:26:33 UTC. Carry has all 65 due arrivals through 18:05, no
terminal error or overdue missing files, and no economic evaluation.

### Review 79, 18:26 UTC

All 57 closes exact and negative: cooldown 45/−$68.8777, Premium two/
−$4.2526, convergence eight/−$21.9070, confirmed one/−$3.3006 and conservative
one/−$4.0343. Zero aborts, complete coverage and no new winners. The two
CASHCAT selective-policy records are preserved and reconcile, including the
confirmed policy's 1.682-second confirmation with advanced source timestamps.
Both suffered wider closing spreads; these observations offer no support for
promotion. Conservative's epoch net is now negative. Four feeds connected,
110 pairs, performance normal; review and later epoch snapshot flat.
Fourteen earlier win records and three legacy funding obligations remain.
Next review 18:46:33 UTC. Carry has all 69 due arrivals through 18:25, no
terminal error or overdue missing files, and no economic evaluation.

### Review 80, 18:46 UTC

All fifty closes exact: cooldown 38/−$60.2452, Premium seven/−$14.6098,
convergence five/−$3.5742. Zero aborts and complete coverage. One CASHCAT
failed-hedge rescue gained $0.82757; the other 49 closes lost money. Core
filled 2,488.8 units long ($405.84), Hyperliquid short was rejected, and the
partial long closed 1.245 seconds later. Exact funding zero, no remaining
quantity, and net arithmetic including 5 bp stress reconcile. Fifteen epoch
win records now comprise two paired gains and thirteen failed-hedge rescues
across separate portfolios. Four feeds connected, 111 pairs after refresh and
performance normal. Review had no open quantities but one cooldown funding
settlement pending; later epoch flat with no new pending funding. Three legacy
funding obligations remain. Next review 19:06:33 UTC. Carry has all 73 due
arrivals through 18:45, no terminal error or overdue missing files, and no
economic evaluation.

### Review 81, 19:06 UTC

All 48 closes negative (47 exact, one estimated): cooldown 43/−$46.4490,
Premium five/−$9.7643; no other completions. Zero aborts, complete coverage,
no new winners. Estimated CRCL funding +$0.08599 leaves −$0.90161 net;
its complete record is preserved, with both legs closed and no missing
funding events. Four feeds connected, 111 pairs and performance normal.
Review had one cooldown position; later epoch snapshot flat. Fifteen earlier
win records and three legacy funding obligations remain. Next review
19:26:33 UTC. Carry has all 77 due arrivals through 19:05, no terminal error
or overdue missing files, and no economic evaluation.

### Review 82, 19:26 UTC

All 36 closes exact, paired and negative: cooldown 35/−$56.3786, Premium
one/−$1.6741; no other completions. Zero aborts, no entry rejections, complete
coverage and no new winners. Four feeds connected, 111 pairs and performance
normal. Review flat; later epoch snapshot had one cooldown position. Fifteen
earlier win records and three legacy funding obligations remain. Next review
19:46:33 UTC. Carry has all 81 due arrivals through 19:25, no terminal error
or overdue missing files, and no economic evaluation.

### Review 83, 19:46 UTC

All 46 closes exact and negative: cooldown 41/−$69.8016, Premium three/
−$5.9674, convergence two/−$3.7105. Forty-one paired closes and five failed
hedges; zero aborts and complete coverage. Four Hyperliquid price-limit entry
rejections. Four feeds connected, 110 pairs after metadata refresh and normal
performance. Review and later epoch snapshot have no open quantities; three
legacy funding obligations remain. The separate epoch snapshots straddle
different extra closes, reconciled in the review journal. Fifteen earlier win
records remain. Next review 20:06:33 UTC. Carry has all 85 due arrivals through
19:45, no terminal error or overdue missing files, and no economic evaluation.

### Review 84, 20:06 UTC

147 exact closes: 146 losses and one MU failed-hedge rescue gain +$0.94134.
Cooldown 35/−$49.9997, Premium 69/−$130.5542, convergence 43/−$58.6853.
All 75 paired closes lost money; 72 failed hedges include the single gain.
Three additional aborts have both legs unfilled and no remaining quantity;
coverage complete. 69 Hyperliquid price-limit rejections, plus six rejection
records on Lighter/RH. Premium's 45 GOOGL closes lost $86.6459. Full winning
record preserved and arithmetic reconciled, including 5 bp stress and zero
funding. Sixteen epoch win records comprise two paired and fourteen rescue
gains across separate portfolios. Four feeds connected, 110 pairs, normal
performance; review and later epoch snapshot flat. Three legacy funding
obligations remain. Next review 20:26:33 UTC. Carry has all 89 due arrivals
through 20:05, no terminal error or overdue missing files, and no economic
evaluation.

### Review 85, 20:26 UTC

87 exact closes: 84 losses, two paired MU gains and one MU rescue gain.
Cooldown 27/−$35.9522, Premium 38/−$71.4179, convergence 22/−$21.5008;
seven additional aborts and complete coverage. Full positive records and
all three convergence paired records preserved. Paired MU gains +$0.04732
and +$0.18958 share a signal time and Hyperliquid fill observation; later
MU paired loss −$1.52979 leaves that complete group at −$1.29289. The rescue
gain +$0.10139 is an unhedged Lighter long after Hyperliquid short rejection.
Arithmetic, zero exact funding and remaining quantities reconcile. Nineteen
epoch win records comprise four paired and fifteen rescue gains, with shared
observations precluding independent confirmation. Four feeds connected, 110
pairs, normal performance; review had one cooldown position, later epoch
snapshot flat. Three legacy funding obligations remain. Next review
20:46:33 UTC. Carry has all 93 due arrivals through 20:25, no terminal error
or overdue missing files, and no economic evaluation.

### Review 86, 20:46 UTC

53 exact closes: 52 losses and one MU rescue gain +$0.44918. Cooldown
36/−$54.0283, Premium twelve/−$18.5659, convergence five/−$2.9765.
All 45 paired closes negative; zero aborts and complete coverage. Eight
Hyperliquid price-limit rejections. Full winning record preserved: Lighter
long filled, Hyperliquid short rejected, long closed after 1.6100 s; zero
remaining quantity and exact funding, with arithmetic/stress reconciled.
Twenty epoch winning records comprise four paired and sixteen rescue gains.
Four feeds connected, 110 pairs and normal performance; review had one
cooldown position, later epoch snapshot flat. Three legacy funding
obligations remain. Next review 21:06:33 UTC. Carry has all 97 due arrivals
through 20:45, no terminal error or overdue missing files, and no economic
evaluation.

### Review 87, 21:06 UTC

All 81 closes negative: 80 exact and one estimated. Cooldown 58/−$73.3213,
Premium seven/−$13.0874, convergence thirteen/−$15.5968, conservative two/
−$1.3482 and confirmed one/−$0.7144. Seventy paired closes and eleven failed
hedges; zero aborts and complete coverage. All three selective-policy closes
were paired CRCL losses. The full estimated GRAM record is preserved:
+$0.01587 estimated funding leaves −$2.04245 net; both legs flat, arithmetic
and funding events reconcile. Twenty earlier win records and three legacy
funding obligations remain. Four feeds connected, 110 pairs and normal
performance; review had one cooldown position, later epoch snapshot flat.
Next review 21:26:33 UTC. Carry has all 101 due arrivals through 21:05, no
terminal error or overdue missing files, and no economic evaluation.


### Review 88, 21:26 UTC

82 exact closes: 81 losses and one ENA rescue gain +$0.50849. Cooldown
55/−$62.6677, Premium nineteen/−$30.6762, convergence eight/−$5.7531.
All seventy paired closes negative; zero aborts and complete coverage. Eleven
Hyperliquid price-limit rejections. Full winning record preserved: Lighter
long filled, Hyperliquid short rejected, long closed after 1.2921 s; zero
remaining quantities and exact funding, with arithmetic and stress reconciled.
Twenty-one epoch win records comprise four paired and seventeen rescue gains.
Four feeds connected, 110 pairs and normal performance; review and separate
epoch snapshot each had one cooldown position. Three legacy funding obligations
remain. Next review 21:46:33 UTC. Carry has all 105 due arrivals through 21:25,
no terminal error or overdue missing files, and no economic evaluation.


### Review 89, 21:46 UTC

83 exact closes: 82 losses and one LIT rescue gain +$0.16991. Cooldown
sixty/−$64.8304, Premium nineteen/−$36.0979, convergence four/−$7.2472.
All 74 paired closes negative; zero aborts and complete coverage. Nine
Hyperliquid price-limit rejections. Full winning record preserved: Lighter
long filled, Hyperliquid short rejected, long closed after 1.4390 s; zero
remaining quantities and exact funding, with arithmetic and stress reconciled.
Twenty-two epoch win records comprise four paired and eighteen rescue gains.
Four feeds connected, 107 pairs after metadata refresh and normal performance;
review and separate epoch snapshot flat. Three legacy funding obligations
remain. Next review 22:06:33 UTC. Carry has all 109 due arrivals through 21:45,
no terminal error or overdue missing files, and no economic evaluation.


### Review 90, 22:06 UTC

All 51 closes negative: fifty exact and one estimated. Cooldown 47 paired/
−$48.6282, Premium two failed hedges/−$3.0598, convergence two failed hedges/
−$2.8633. Zero aborts and complete coverage; four Hyperliquid price-limit
rejections. Full estimated CRCL record preserved: +$0.11127 funding leaves
−$0.92300 net; both legs flat, arithmetic and funding events reconcile.
Twenty-two earlier win records and three legacy funding obligations remain.
Four feeds connected, 107 pairs and normal performance; review had one Premium
position, later epoch snapshot flat. Next review 22:26:33 UTC. Carry has all
113 due arrivals through 22:05, no terminal error or overdue missing files,
and no economic evaluation.


### Review 91, 22:26 UTC

All 47 exact closes negative. Cooldown 44/−$44.1328, Premium one/−$1.4926,
convergence two/−$2.5219. Forty-four paired and three failed hedges; zero
aborts and complete coverage. Three Hyperliquid price-limit rejections.
Twenty-two earlier win records and three legacy funding obligations remain.
Four feeds connected, 107 pairs and normal performance; review and separate
epoch snapshot each had one cooldown position. Next review 22:46:33 UTC.
Carry has all 117 due arrivals through 22:25, no terminal error or overdue
missing files, and no economic evaluation. The user reiterated continuing
at 22:21 UTC; the collectors and review daemon survived the brief interruption.


### Review 92, 22:46 UTC

All 46 exact closes negative. Cooldown 43/−$47.9912, Premium two/−$2.7471,
convergence one/−$2.1559. Forty-four paired and two failed hedges; zero aborts
and complete coverage. Two Hyperliquid price-limit rejections. Twenty-two
earlier win records and three legacy funding obligations remain. Four feeds
connected, 108 pairs after metadata refresh and normal performance; review
flat, later epoch snapshot had one cooldown position. Next review 23:06:33 UTC.
Carry has all 121 due arrivals through 22:45, no terminal error or overdue
missing files, and no economic evaluation.


### Review 93, 23:06 UTC

All 39 closes negative: 38 exact and one estimated. Cooldown 38 paired/
−$44.9411, convergence one failed hedge/−$0.5337; no Premium completions.
Zero aborts and complete coverage; one Hyperliquid price-limit rejection.
Full estimated CRCL record preserved: +$0.08112 funding leaves −$0.78057
net; both legs flat, arithmetic and funding events reconcile. Twenty-two
earlier win records and three legacy funding obligations remain. Four feeds
connected, 108 pairs and normal performance; review and later epoch snapshot
flat. Next review 23:26:33 UTC. Carry has all 125 due arrivals through 23:05,
no terminal error or overdue missing files, and no economic evaluation.


### Review 94, 23:26 UTC

Two exact Premium losses: paired GOOGL −$1.53451 and failed XRP hedge
−$1.72016, total −$3.25468. Zero aborts, complete coverage and one Hyperliquid
price-limit rejection. Cooldown had no closes and is now capital constrained:
HL wallet $1,000.35611 is below the $1,000.50 minimum reserve before fees.
Source check and full selected health evidence preserved; no wallet reset or
top-up. Four feeds connected, 108 pairs, normal performance and no open
positions at either snapshot. Twenty-two earlier win records and three legacy
funding obligations remain. Next review 23:46:33 UTC. Carry has all 129 due
arrivals through 23:25, no terminal error or overdue files, and no economic
evaluation.


### Review 95, 23:46 UTC

One exact convergence paired SAMSUNGUSD close/−$1.07269; no other completions,
no aborts or entry rejections, and complete coverage. Cooldown remains
capital constrained. Four feeds connected, 106 pairs after metadata refresh,
normal performance. One convergence position at the review boundary, later
epoch snapshot flat with one additional close. Twenty-two earlier win records
and three legacy funding obligations remain. Next review 1 October 00:06:33 UTC.
Carry has all 133 due arrivals through 23:45, no terminal error or overdue
files, and no economic evaluation.


### Review 96 and reboot recovery, 1 October 00:14 UTC

The missed 00:06 review was captured after monitor/reviewer restoration. One
exact convergence paired SAMSUNGUSD loss −$2.07057, complete coverage, no aborts
or entry rejections. All saved ledgers and original epoch matched on restart;
no open exposure at the last durable checkpoint, three legacy funding records
retained. Next review 00:26:33 UTC. The original carry run is interrupted and
preserved; the user explicitly authorized a separate fresh run within the same
16 MiB budget. See the v2 addendum and recovery evidence.


### Review 97 and fresh carry launch, 1 October 00:26 UTC

Two exact Premium paired GOOGL losses/−$3.45060, complete coverage, no aborts
or entry rejections. Post-catch-up interval approximately twelve minutes.
Four feeds connected, 107 pairs, normal performance, review and epoch flat.
Next review 00:46:33 UTC. Fresh carry PID 42223 launched under the committed
v2 freeze after 44 passing tests. T0 00:30 UTC; endpoint 4 October 00:30 UTC.
Retired v1 remains intact. The existing 16 MiB allowance is enforced as 1 MiB
retired plus 15 MiB fresh, with no extra experimental reservation.


### Review 98, 1 October 00:46 UTC

All six exact closes negative: four Premium pairs/−$7.26233 and two convergence
SOXL failed hedges/−$2.59127. Zero aborts, complete coverage and two Hyperliquid
price-limit rejections. Four feeds connected, 107 pairs, normal performance;
review and epoch snapshot flat. Cooldown remains capital constrained.
Twenty-two earlier win records and three legacy funding obligations remain.
Next review 01:06:33 UTC. Fresh carry v2 has all four due arrivals through 00:45,
no terminal error or timing failures, and no economic evaluation.


### Review 99, 1 October 01:06 UTC

Two exact losses: one Premium GOOGL pair/−$1.66938 and one convergence
SKHYNIXUSD failed hedge/−$0.44088. One additional convergence abort, complete
coverage, two Hyperliquid and one Lighter price-limit rejections. Four feeds
connected, 107 pairs, normal performance. Review flat; later epoch snapshot
has one Premium position. Cooldown remains capital constrained. Twenty-two
earlier win records and three legacy funding obligations remain.
Next review 01:26:33 UTC. Fresh carry v2 has all eight due arrivals through
01:05, no terminal error or timing failures, and no economic evaluation.


### Review 100, 1 October 01:26 UTC

One exact Premium paired XAG loss/−$1.70881, no aborts or entry rejections,
complete coverage. Four feeds connected, 108 pairs, normal performance; review
and separate epoch snapshot flat. Cooldown remains capital constrained.
Twenty-two earlier win records and three legacy funding obligations remain.
Next review 01:46:33 UTC. Fresh carry v2 has all twelve due arrivals through
01:25, no terminal error or timing failures, and no economic evaluation.


### Review 101, 1 October 01:46 UTC

Two exact convergence failed-hedge losses, NEAR and ENA, total −$2.31827.
Zero aborts, two Hyperliquid price-limit rejections, complete coverage. Four
feeds connected, 108 pairs, normal performance; review and epoch snapshot
flat. Cooldown remains capital constrained. Twenty-two earlier win records
and three legacy funding obligations remain. Next review 02:06:33 UTC.
Fresh carry v2 has all sixteen due arrivals through 01:45, no terminal error
or timing failures, and no economic evaluation.


### Review 102, 1 October 02:06 UTC

One exact Premium NEAR failed-hedge loss/−$3.13207. Zero aborts, one
Hyperliquid price-limit rejection, complete coverage. Four feeds connected,
108 pairs, normal performance; review and epoch snapshot flat. Cooldown
remains capital constrained. Twenty-two earlier win records and three legacy
funding obligations remain. Next review 02:26:33 UTC. Fresh carry v2 has all
twenty due arrivals through 02:05, no terminal error or timing failures, and
no economic evaluation.


### Review 145, 1 October 16:26 UTC

Resumed the authorized routine after the agent interruption; external paper
and carry collectors continue advancing. Complete report coverage: 52 exact
losses, five convergence failed hedges/−$3.59406 and 47 Premium GOOGL
closes/−$77.08899 (46 paired, one failed hedge); no wins, estimates or
aborts. Five Hyperliquid price-limit rejections. Four feeds, 100 pairs,
running/normal performance, all portfolios flat, three legacy funding
obligations. Separately timed epoch snapshot retained; report deltas govern
window accounting. Deterministic archives verified with cap/growth guards;
3,603,224 B of 4,980,736 B used, projected 4,500,680 B through cutoff.
Carry v2 metadata at 16:25: 191 sampled, slot 71 still arrival_invalid,
672 future/interrupted; running, no errors/retries/economic evaluation.
No carry sample opened or services changed. Next review 16:46:33 UTC.


### Review 146, 1 October 16:46 UTC

Complete coverage: 37 exact closes/−$59.74430: seven convergence failed
hedges and 30 Premium (22 paired, eight failed hedges). Three new exact
failed-hedge gains (two convergence, one Premium) immediately sent to the
parent for audit; no paired gains or estimates. One convergence abort,
16 Hyperliquid price-limit rejections and one Lighter notional cap. Four
feeds, 100 pairs, running/normal performance. Independent epoch snapshot
preserved with exact report; archive 3,608,065 B, 167 future pairs project
4,500,179 B under restored 5,242,880 B cap (parent c31e204). Carry 16:45:
195 sampled, persistent invalid slot 71, 668 future/interrupted; no errors,
retries or economic evaluation. Next review 17:06:33 UTC.


Review146 parent audit confirmed all three gains as one-leg ZEC rescues
following rejected HL hedges, not paired wins. Accounting independently
reconciled; original raw depth unavailable. Root artifacts retained;
manual archive now 3,612,956 B, projected 4,505,070 B, margin 737,810 B.
Cumulative audited rescue gains now 26; paired gains remain two.


### Review 147, 1 October 17:06 UTC

Complete coverage: two convergence exact losses/−$1.27258; Premium 18
exact losses/−$29.02824 plus one estimated loss/−$1.29537, immediately
flagged to the parent. No wins/aborts; three HL price-limit rejections.
Four feeds, 100 pairs, running/ok; earlier busy pulse cleared. Independent
epoch snapshot retained, report deltas authoritative. Archive 3,617,755 B,
166 future pairs project 4,504,527 B, margin 738,353 B under 5 MiB cap.
Carry 17:05: 199 sampled, persistent invalid slot 71, 664 future/interrupted,
no errors/retries/economic evaluation. Next review 17:26:33 UTC.


Review147 parent audit verified MU pair funding-estimate arithmetic while
retaining estimated quality because RH lacks a funding reference price.
Estimated loss remains −$1.29537101245; audit artifacts preserved. Manual
archive 3,620,663 B, projected 4,507,435 B, margin 735,445 B.


### Review 148, 1 October 17:26 UTC

Complete coverage: 17 exact losses, two convergence failed hedges/−$1.68625
and 15 Premium/−$25.71632 (14 paired, one failed hedge). No gains, estimates
or aborts; three HL price-limit rejections. Four feeds, 102 pairs, running/
ok. Separate epoch snapshot retained. Archive 3,625,310 B; 165 future pairs
project 4,506,740 B, margin 736,140 B under 5 MiB. Carry 17:25: 203 sampled,
persistent invalid slot 71, 660 future/interrupted; no errors, retries or
economic evaluation. Next review 17:46:33 UTC.


### Review 149, 1 October 17:46 UTC

Complete coverage: 32 exact closes, convergence nine/−$12.52435 and Premium
23/−$38.09161. Two NEW PAIRED WINS (one each) immediately sent to parent
for audit; 30 losses, one convergence abort, no estimates. Eight HL price
limits and one Lighter notional cap. Four feeds/102 pairs remain running;
performance busy, p95 lag 62.58 ms. Preserved 17:30/17:35 busy pulses and
17:40 recovery in review journal; no daemon change or causal conclusion.
Archive 3,630,449 B, 164 future pairs project 4,506,537 B, margin 736,343 B.
Carry 17:45: 207 sampled, invalid slot 71, 656 future/interrupted; no errors,
retries/economic evaluation. Next review 18:06:33 UTC.


Review149 parent audit verified XAG +$0.2892293447 and ZEC +$0.1777317663
as paired paper gains at $1,000/leg, including terminal accounting and
ZEC profit mark. Original rolling depth unavailable; retained fill timing
shows material leg gaps, and these are not $100 study results. Audit
artifacts preserved; cumulative paired gains four, rescue gains 26.
Manual archive 3,636,492 B, projected 4,512,580 B, margin 730,300 B.


### Review 150, 1 October 18:06 UTC

Complete coverage: convergence five exact closes/−$7.76982, including a
NEW PAIRED GAIN +$0.3358306866 immediately flagged for parent audit;
four failed-hedge losses. Premium 16 exact losses/−$28.34131 (11 paired,
five failed hedges). No estimates/aborts; seven HL price limits. Four feeds,
102 pairs, running/ok, p95 lag 38.36 ms. Archive 3,641,329 B, 163 future
pairs project 4,512,075 B, margin 730,805 B. Carry 18:05: 211 sampled,
invalid slot 71, 652 future/interrupted; no errors/retries/economic
evaluation. Next review 18:26:33 UTC.


Review150 parent audit verified paired LIT gain +$0.33583068657 and its
profit mark, cash/fees/stress/capital/funding/flatness. Source signal skew
504.19 ms exceeds the $100 study gate, with legacy $1,000 size and no
original depth proof. Audited paired gains now five. Audit artifacts
preserved: archive 3,645,183 B, projected 4,515,929 B, margin 726,951 B.


### Review 151, 1 October 18:26 UTC

Complete coverage: seven exact losses, two convergence failed hedges/
−$2.45811 and five Premium/−$9.15962 (three paired, two failed hedges).
One convergence abort, no wins/estimates. Five HL price limits, one Lighter
notional cap. Four feeds, 101 pairs, running/ok; busy 18:15/18:20 health
pulses cleared at 18:25, retained in journal. Archive 3,649,755 B; 162 future
pairs project 4,515,159 B, margin 727,721 B. Carry 18:25: 215 sampled,
invalid slot 71, 648 future/interrupted; no errors/retries/evaluation.
Next review 18:46:33 UTC.


### Review 152, 1 October 18:46 UTC

Eight exact Premium losses/−$12.34246 (seven paired, one failed hedge),
no wins/estimates/aborts; one HL price limit. Retained-trade coverage complete,
with explicit collector gap 18:34:54.802744–18:42:14.795516 UTC following
WAL-budget checkpoint failure. Root recovered preserved ledgers/config/
epochs/positions with report interval 0.5 s and unchanged DB cap; no active
entry/exit exposure, three pending-funding records retained. Gap prevents
continuous feed claims. Four feeds/102 pairs fresh after recovery, running/
ok. Separate snapshot Premium increase nine versus report eight preserved.
Archive 3,654,216 B; 161 future pairs project 4,514,278 B, margin 728,602 B.
Carry 18:45: 219 sampled, invalid slot 71, 644 future/interrupted; no errors/
retries/evaluation. Next review 19:06:33 UTC.


### Review 153, 1 October 19:06 UTC

Complete coverage: 13 exact losses, two convergence failed hedges/−$2.05560,
11 Premium/−$18.34361 (nine paired, two failed hedges). No gains, estimates,
aborts; four HL price limits. Four feeds/102 pairs fresh, running/ok. Separate
snapshot Premium increase ten versus report eleven; report governs window.
Archive 3,658,883 B, 160 future pairs project 4,513,603 B, margin 729,277 B.
Carry 19:05: 223 sampled, persistent invalid slot 71, 640 future/interrupted;
no errors/retries/evaluation. Next review 19:26:33 UTC.


### Review 154, 1 October 19:26 UTC

Complete coverage: convergence six exact closes/−$9.29074, all failed
hedges including one new gain immediately flagged for parent audit.
Premium five exact losses/−$9.57557 (two paired, three failed hedges).
One convergence abort, no estimates/paired gains. Nine HL limits, one
Lighter notional cap and one Lighter limit. Four feeds/102 pairs fresh,
running/ok; no WAL incident recurrence. Separate epoch increase seven
convergence versus report six retained. Archive 3,663,660 B; 159 future
pairs project 4,513,038 B, margin 729,842 B. Carry 19:25: 227 sampled,
invalid slot 71, 636 future/interrupted; no errors/retries/evaluation.
Next review 19:46:33 UTC.


### Review 155, 1 October 19:46 UTC

Parent review154 VVV audit confirmed one-leg rescue +$0.219814582807;
audited rescue gains 27, paired gains five. Review155 complete coverage:
21 exact losses, six convergence failed hedges/−$10.73283 and 15 Premium/
−$22.75935 (seven paired, eight failed hedges), no wins/estimates/aborts;
14 HL price limits. Four feeds/103 pairs fresh, running/ok. Sandbox PID
absence was resolved by advancing snapshots, no new failure/intervention.
Separate convergence increase five versus report six retained. Archive
3,671,824 B; 158 future pairs project 4,515,860 B, margin 727,020 B.
Carry 19:45: 231 sampled, invalid slot 71, 632 future/interrupted; no errors/
retries/evaluation. Next review 20:06:33 UTC.


### Review 156, 1 October 20:06 UTC

Complete coverage: 17 exact losses, eight convergence/−$7.39925 (one
paired, seven failed hedges), nine Premium/−$13.01618 (three paired,
six failed hedges). No gains/estimates/aborts; 13 HL price limits. Four
feeds/103 pairs fresh, running/ok, no incident recurrence. Separate epoch
snapshot preserved, increments match report. Archive 3,676,765 B; 157 future
pairs project 4,515,459 B, margin 727,421 B. Carry 20:05: 235 sampled,
invalid slot 71, 628 future/interrupted; no errors/retries/evaluation.
Next review 20:26:33 UTC.


### Review 157, 1 October 20:26 UTC

Complete coverage: nine exact losses, four convergence failed hedges/
−$3.59244 and five Premium/−$8.47659 (two paired, three failed hedges).
No gains/estimates/aborts; seven HL price limits. Four feeds/103 pairs fresh,
running/ok. Separate epoch increments match report. Archive 3,681,440 B;
156 future pairs project 4,514,792 B, margin 728,088 B. Carry 20:25:
239 sampled, invalid slot 71, 624 future/interrupted; no errors/retries/
evaluation. Next review 20:46:33 UTC. Review156 preserved in root702b445.


### Review 158, 1 October 20:46 UTC

Complete coverage: one exact Premium paired loss/−$1.51661; no convergence
closes/gains/estimates/aborts/rejections. Separate epoch convergence rose
one after report boundary; keep it in next report. Four feeds/101 pairs
fresh, running/ok. Archive 3,685,739 B; 155 future pairs project 4,513,749 B,
margin 729,131 B. Carry 20:45: 243 sampled, invalid slot 71, 620 future/
interrupted; no errors/retries/evaluation. Next review 21:06:33 UTC.


### Review 159, 1 October 21:06 UTC

Complete coverage: 21 exact losses, three convergence failed hedges/
−$2.59243 and 18 Premium/−$33.99250 (17 paired, one failed hedge).
One convergence abort, no gains/estimates; five HL price limits, one
Lighter notional cap. Four feeds/101 pairs fresh, running/ok. Separate
convergence increase two versus report three retained. Archive 3,690,402 B;
154 future pairs project 4,513,070 B, margin 729,810 B. Carry 21:05:
247 sampled, invalid slot 71, 616 future/interrupted; no errors/retries/
evaluation. Next review 21:26:33 UTC.


### Review 160, 1 October 21:26 UTC

Complete coverage: five exact losses, four convergence/−$4.65743 (two
paired, two failed hedges), one Premium failed hedge/−$1.64576. No gains/
estimates/aborts; three HL price limits. Four feeds/101 pairs fresh,
running/ok. Separate epoch increments match report. Archive 3,695,000 B;
153 future pairs project 4,512,326 B, margin 730,554 B. Carry 21:25:
251 sampled, invalid slot 71, 612 future/interrupted; no errors/retries/
evaluation. Active batch/control economic outputs untouched.
Next review 21:46:33 UTC.


### Review 161, 1 October 21:46 UTC

Complete coverage: ten exact failed-hedge losses, six convergence/−$7.15650
and four Premium/−$5.82793. No gains/estimates/aborts; ten HL price limits.
Four feeds/101 pairs fresh, running/ok. Separate epoch increments match
report. Archive 3,699,569 B; 152 future pairs project 4,511,553 B, margin
731,327 B. Carry 21:45: 255 sampled, invalid slot 71, 608 future/interrupted;
no errors/retries/evaluation. Added authorized batch status health check;
window2→3 transition notified, no batch economics read.
Next review 22:06:33 UTC.


### Review 162, 1 October 22:06 UTC

Complete coverage: one convergence exact failed-hedge loss/−$0.98165,
no other closes/gains/estimates/aborts; one HL price limit. Four feeds/
101 pairs fresh, running/ok. Busy 21:50/21:55 cleared 21:59, retained in
journal. Separate epoch increments match report. Archive 3,703,796 B;
151 future pairs project 4,510,438 B, margin 732,442 B. Carry 22:05:
259 sampled, invalid slot 71, 604 future/interrupted; no errors/retries/
evaluation. Prior batch completion notified; new executable-shock batch
status-only scope added, no research economics read. Next 22:26:33 UTC.


### Review 163, 1 October 22:26 UTC

Complete coverage: 13 exact Premium losses/−$21.42802 (12 paired, one
failed hedge); no other closes/gains/estimates/aborts, one HL price limit.
Four feeds/101 pairs fresh, running/ok. Separate Premium increase 15 versus
report 13 retained. Archive 3,708,278 B; 150 future pairs project 4,509,578 B,
margin 733,302 B. Carry 22:25: 263 sampled, invalid slot 71, 600 future/
interrupted; no errors/retries/evaluation. Batch status-only window2→3
transition notified, no economic outputs opened. Next 22:46:33 UTC.


### Review 164, 1 October 22:46 UTC

Complete coverage: 24 exact losses, two convergence failed hedges/−$2.44679
and 22 Premium paired/−$36.33814. No gains/estimates/aborts; two HL price
limits. Four feeds/101 pairs fresh, running/ok. Separate Premium increase
20 versus report22 retained. Archive 3,712,827 B;149 future pairs project
4,508,785 B, margin734,095 B. Carry22:45:267 sampled, invalidslot71,
596future/interrupted; no errors/retries/evaluation. Status-only monitoring
confirmed normal executable-shockbatch22:34 and broadcapture22:45 endpoints;
no economic outputs opened. Next23:06:33UTC.


### Review 165, 1 October 23:06 UTC

Complete coverage: two exact Premium losses/−$3.80045 (one paired, one
failed hedge); no other closes/gains/estimates/aborts, one HL price limit.
Four feeds/101 pairs fresh, running/ok. Separate epoch increases match
report. Archive 3,717,206 B; 148 future pairs project 4,507,822 B, margin
735,058 B. Carry 23:05: 271 sampled, invalid slot 71, 592 future/interrupted;
no errors/retries/evaluation. Relative broad capture status-only scope
added; two connections/no errors, economic outputs untouched.
Next review 23:26:33 UTC.


### Review 166, 1 October 23:26 UTC

Complete coverage: one exact Premium failed-hedge loss/−$1.22951; no
other closes/gains/estimates/aborts, one HL price limit. Four feeds/101
pairs fresh, running/ok. Separate epoch increments match report. Archive
3,721,436 B; 147 future pairs project 4,506,710 B, margin 736,170 B.
Carry 23:25: 275 sampled, invalid slot 71, 588 future/interrupted; no errors/
retries/evaluation. Relative broad capture normal terminal23:15 confirmed
via status only, no economic outputs read. Next23:46:33UTC.


### Review 167, 1 October 23:46 UTC

Complete coverage, zero closes/gains/estimates/aborts/rejections. Separate
epoch unchanged. Four feeds/101 pairs fresh, running/ok. Archive 3,725,499 B;
146 future pairs project 4,505,431 B, margin737,449 B. Carry23:45:279sampled,
invalidslot71,584future/interrupted; no errors/retries/evaluation. Added
news capture and analysis-companion status supervision; both waiting with
fresh heartbeats, no economic outputs read or competing jobs launched.
Next review2October00:06:33UTC.


### Review 168, 2 October 00:06 UTC

Complete coverage: seven exact losses, three convergence failed hedges/
−$3.74442 and four Premium/−$6.83679 (three paired, one failed hedge).
One convergence abort, no gains/estimates; five HL and one Lighter price
limits. Four feeds/101 pairs fresh, running/ok. Separate epoch increments
match report. Archive3,730,151 B;145 future pairs project4,504,741 B,
margin738,139 B. Carry00:05:283sampled,invalidslot71,580future/interrupted;
no errors/retries/evaluation. News/analysis helpers waiting with fresh
heartbeats/hash matches. Next00:26:33UTC.


### Review 169, 2 October 00:26 UTC

Complete coverage: 16 exact losses, four convergence failed hedges/
−$3.90837 and 12 Premium/−$23.64698 (seven paired, five failed hedges).
No gains/estimates/aborts; nine HL price limits. Four feeds/101 pairs fresh,
running/ok. Separate Premium increase13 versus report12 retained. Archive
3,734,859 B;144 future pairs project4,504,107 B,margin738,773 B. Carry
00:25:287sampled,invalidslot71,576future/interrupted;noerrors/retries/evaluation.
News/analysiswaitingfreshheartbeats. Next00:46:33UTC.


### Review 170, 2 October 00:46 UTC

Complete coverage: five exact losses, one convergence failed hedge/
−$1.19891 and four Premium paired/−$6.83118. No gains/estimates/aborts;
one HL price limit. Four feeds/102 pairs fresh, running/ok. Separate Premium
increase three versus report four retained. Archive3,739,354 B;143future
pairs project4,503,260 B,margin739,620 B. Carry00:45:291sampled,invalidslot71,
572future/interrupted;noerrors/retries/evaluation. News/analysiswaitingfresh
heartbeats. Next01:06:33UTC.


### Review 171, 2 October 01:06 UTC

Complete coverage: two exact Premium paired losses/−$3.18521; no other
closes/gains/estimates/aborts/rejections. Four feeds/102 pairs fresh,
running/ok. Separate epoch increments match report. Archive3,743,713 B;
142future pairs project4,502,277 B,margin740,603 B. Carry01:05:295sampled,
invalidslot71,568future/interrupted;noerrors/retries/evaluation. News/analysis
waitingfreshheartbeats. Next01:26:33UTC.


### Routine review 172 — 2026-10-02 01:26:33 UTC

Two exact Premium losses / −$3.3787819758; no new gains or estimates. All coverage complete; report and independent epoch snapshot archived with exact verification and pre-write guards. Cumulative 2,522 completions: 2,489 exact losses, one estimate, five paired gains, 27 rescue gains. Fresh four-feed paper health; carry 299 sampled / one invalid / 564 future. News and offline companion waiting with fresh heartbeats, economics false; no competing jobs. Archive 3,748,059 B, projection 4,501,281 B against 5 MiB; next 01:46:33 UTC.


### Routine review 173 — 2026-10-02 01:46:33 UTC

Two exact Premium losses / −$3.3443028994, no gains or estimates; HL price-limit and Core notional-cap rejects one each. Complete coverage, independently timed snapshot and exact deterministic archives verified. Cumulative 2,524 completions: 2,491 exact losses, one estimate, five paired gains, 27 rescue gains. Paper fresh/ok, four feeds; carry 303 sampled / one invalid / 560 future. Both news helpers waiting with fresh heartbeats, economics false. Archive 3,752,453 B, projected 4,500,333 B under 5 MiB; next 02:06:33 UTC.


### Routine review 174 — 2026-10-02 02:06:33 UTC

Six exact losses: convergence two / −$2.2099200530, Premium four / −$7.2386710458; no gains or estimates, two HL price-limit rejects. Complete coverage and exact report/independent snapshot archived with guards. Cumulative 2,530: 2,497 exact losses, one estimate, five paired gains, 27 rescue gains. 02:02 fresh busy lag 52.39 ms retained; review fresh/ok 42.25 ms, four feeds. Carry 307 sampled / one invalid / 556 future; news helpers waiting/fresh, economics false. Archive 3,757,011 B; projection 4,499,549 B under 5 MiB; next 02:26:33 UTC.


### Routine review 175 — 2026-10-02 02:26:33 UTC

One exact Premium loss / −$1.8972010536; no gains or estimates, complete coverage. Independent snapshot advanced two closes across boundary and is not pooled. Exact deterministic archives/guards passed. Cumulative 2,531: 2,498 exact losses, one estimate, five paired gains, 27 rescue gains. Paper fresh/ok, four feeds; carry 311 sampled / one invalid / 552 future. News helpers waiting/fresh, economics false. Archive 3,761,335 B; projection 4,498,531 B under 5 MiB; next 02:46:33 UTC.


### Routine review 176 — 2026-10-02 02:46:33 UTC

Five exact Premium losses / −$8.6618455094, no gains or estimates; complete coverage, report/snapshot boundary counts separate. Exact archives and guards passed. Cumulative 2,536: 2,503 exact losses, one estimate, five paired gains, 27 rescue gains. Paper fresh/four feeds but busy 55.13 ms review lag; prior 64.37/57.06 ms pulses retained. Rolling operational-only scope added: chunk 000002 healthy, two connections/no errors/economics false; separate 2 GB store unchanged. Carry 315 sampled / one invalid / 548 future; news helpers waiting/fresh. Archive 3,765,696 B; projection 4,497,550 B under 5 MiB; next 03:06:33 UTC.


### Routine review 177 — 2026-10-02 03:06:33 UTC

Three exact Premium losses / −$5.1886823514, no gains/estimates/rejects; complete coverage and exact archives/guards passed. Cumulative 2,539: 2,506 exact losses, one estimate, five paired gains, 27 rescue gains. Prior fresh busy pulse retained; review fresh/ok four feeds, lag 44.03 ms. Rolling reserved-repeat chunk 000004 operational-only healthy, two connections/no errors/economics false; snapshot-quality counter clarification retained. Carry 319 sampled / one invalid / 544 future; news helpers waiting/fresh. Archive 3,770,058 B; projection 4,496,570 B under 5 MiB; next 03:26:33 UTC.


### Routine review 178 — 2026-10-02 03:26:33 UTC

Three exact Premium losses / −$5.3185196153, no gains or estimates, two HL price-limit rejects; complete coverage and exact archives/guards passed. Cumulative 2,542: 2,509 exact losses, one estimate, five paired gains, 27 rescue gains. Earlier busy pulse retained; review fresh/ok four feeds, lag 31.81 ms. Rolling reserved-repeat chunk 000006 operational-only healthy, two connections/no errors/economics false; root two offline exploratory analyses acknowledged. Carry 323 sampled / one invalid / 540 future; news helpers waiting/fresh. Archive 3,774,454 B; projection 4,495,624 B under 5 MiB; next 03:46:33 UTC.


### Routine review 179 — 2026-10-02 03:46:33 UTC

Five exact losses: convergence three / −$3.3302233051, Premium two / −$3.4212153665; no gains/estimates, four HL price-limit rejects. Complete coverage and exact archives/guards passed. Cumulative 2,547: 2,514 exact losses, one estimate, five paired gains, 27 rescue gains. Review fresh/four feeds but busy lag 51.13 ms, CPU 60.09%; prior 33.64 ms and root nice-19 rerun timing retained. Rolling chunk 000008 operational-only healthy, two connections/no errors/economics false. Carry 327 sampled / one invalid / 536 future; news helpers waiting/fresh. Archive 3,778,991 B; projection 4,494,819 B under 5 MiB; next 04:06:33 UTC.


### Routine review 180 — 2026-10-02 04:06:33 UTC

Three exact Premium losses / −$5.1380746459, no gains/estimates/rejects; complete coverage and exact archives/guards passed. Cumulative 2,550: 2,517 exact losses, one estimate, five paired gains, 27 rescue gains. Busy 55–57 ms pulses retained; review fresh/ok four feeds, lag 32.25 ms. Rolling chunk 000010 startup, no errors; next pulse to verify progress, economics false. Carry 331 sampled / one invalid / 532 future; news helpers waiting/fresh. Archive 3,783,346 B; projection 4,493,832 B under 5 MiB; next 04:26:33 UTC.


### Routine review 181 — 2026-10-02 04:26:33 UTC

Resumed original due timestamp; two exact convergence losses / −$1.8518889091, no gains/estimates, two HL price-limit rejects; complete coverage and exact archives/guards. Cumulative 2,552: 2,519 exact losses, one estimate, five paired gains, 27 rescue gains. Paper fresh/ok four feeds, lag 34.09 ms/CPU 55.51%; detached flow 1/2 running, inventory 2 exit 0. Rolling chunk 000012 healthy/economics false. Carry 336 sampled / one invalid / 527 future; news helpers waiting/fresh. Archive 3,787,597 B, projection 4,492,741 B under 5 MiB; next 04:46:33 UTC.


### Routine review 182 — 2026-10-02 04:46:33 UTC

Convergence four failed-hedge closes/two gains aggregate +$1.4682789251; Premium six losses −$12.2170600498; root immediately notified for gains audit. No paired win or estimate, eight HL price-limit rejects, complete coverage/exact archive guards. Cumulative 2,562: 2,527 exact losses, one estimate, five paired gains, 29 rescue gains (two pending audit). Paper fresh/ok four feeds lag 40.60 ms; rolling chunk 13 healthy/economics false. Corrected news helper added waiting/fresh, original helpers unchanged. Carry 339 sampled / one invalid / 524 future. Archive 3,792,230 B, projection 4,492,032 B under 5 MiB; next 05:06:33 UTC.


### Routine review 183 — 2026-10-02 05:06:33 UTC

Four exact losses: convergence three / −$3.7725895849, Premium one / −$1.4921609214; two convergence aborts, HL price-limit five/Core cap two rejects. Complete coverage/exact archive guards. Review 182 two correlated ZEC rescue gains root-audited and pending cleared; 4,224 B evidence included. Cumulative 2,566: 2,531 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 37.39 ms/CPU 72.33%; offline flow 1/2 exit 0. Rolling chunk 15 healthy/economics false; all three news helpers waiting/fresh. Carry 343 sampled / one invalid / 520 future. Archive 3,801,297 B, projection 4,495,757 B under 5 MiB; next 05:26:33 UTC.


### Routine review 184 — 2026-10-02 05:26:33 UTC

One exact convergence loss / −$0.5234160993, one abort; no gains/estimates, HL price-limit two/Core price-limit one rejects. Complete coverage/exact archive guards. Cumulative 2,567: 2,532 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 38.25 ms/CPU 61.14%; rolling chunk 17 healthy/economics false; three news helpers waiting/fresh. Carry 347 sampled / one invalid / 516 future. Archive 3,805,521 B, projection 4,494,639 B under 5 MiB; next 05:46:33 UTC.


### Routine review 185 — 2026-10-02 05:46:33 UTC

Four exact losses: convergence two / −$2.0021830893, Premium two / −$3.2621529991; no gains/estimates/aborts, three HL price-limit rejects. Complete coverage/exact archive guards. Cumulative 2,571: 2,536 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 30.71 ms/CPU 57.83%, 104 pairs; rolling chunk 19 healthy/economics false; three news helpers waiting/fresh. Carry 351 sampled / one invalid / 512 future. Archive 3,810,032 B, projection 4,493,808 B under 5 MiB; next 06:06:33 UTC.


### Routine review 186 — 2026-10-02 06:06:33 UTC

Three exact losses: convergence one / −$1.0462087445, Premium two / −$3.4877174327; no gains/estimates/aborts, one HL price-limit reject. Complete coverage/exact archive guards. Cumulative 2,574: 2,539 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 33.61 ms/CPU 57.74%; rolling chunk 21 healthy/economics false; three news helpers waiting/fresh. Carry 355 sampled / one invalid / 508 future. Archive 3,814,542 B, projection 4,492,976 B under 5 MiB; next 06:26:33 UTC.


### Routine review 187 — 2026-10-02 06:26:33 UTC

Eight exact losses: convergence five / −$8.8669155194, Premium three / −$8.9593928673; one convergence abort, no gains/estimates, HL price-limit nine/Core cap one rejects. Complete coverage/exact archive guards. Cumulative 2,582: 2,547 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 33.64 ms/CPU 64.36%; rolling chunk 23 healthy/economics false; three news helpers waiting/fresh. Carry 359 sampled / one invalid / 504 future. Archive 3,819,114 B, projection 4,492,206 B under 5 MiB; next 06:46:33 UTC.


### Routine review 188 — 2026-10-02 06:46:33 UTC

Two exact losses: convergence one / −$0.3015314457, Premium one / −$2.2167211046; no gains/estimates/aborts, two HL price-limit rejects. Complete coverage/exact archive guards. Cumulative 2,584: 2,549 exact losses, one estimate, five paired gains, 29 audited rescue gains. Transient CPU 89.50% busy/39.30 ms retained, later recovered; review fresh/ok lag 33.80 ms/CPU 65.56%. Rolling chunk25 healthy/economics false; three news helpers waiting/fresh. Carry 363 sampled / one invalid / 500 future. Archive 3,823,437 B, projection 4,491,187 B under 5 MiB; next 07:06:33 UTC.


### Routine review 189 — 2026-10-02 07:06:33 UTC

Three exact Premium losses / −$5.1630704036; no gains/estimates/aborts/rejects, complete coverage/exact archive guards. Cumulative 2,587: 2,552 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag 44.77 ms/CPU 52.89%; rolling chunk27 healthy/economics false; three news helpers waiting/fresh. Carry 367 sampled / one invalid / 496 future. Archive 3,827,790 B, projection 4,490,198 B under 5 MiB; next 07:26:33 UTC.


### Routine review 190 — 2026-10-02 07:26:33 UTC

Five exact losses: convergence one / −$0.7088411617, Premium four / −$6.8927556473; no gains/estimates/aborts, one HL price-limit reject. Complete coverage/exact archive guards. Cumulative 2,592: 2,557 exact losses, one estimate, five paired gains, 29 audited rescue gains. Paper fresh/ok lag33.99ms/CPU66.46%; rolling chunk29 healthy/economics false; three news helpers waiting/fresh. Carry 371 sampled / one invalid / 492 future. Archive 3,832,312 B, projection 4,489,378 B under 5 MiB; next 07:46:33 UTC.


### Routine review191 — 2026-10-02 07:46:33 UTC

Two exact convergence losses/−$3.9210484925;no gains/estimates/aborts,two HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,594:2,559exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Paperfresh/ok lag32.76ms/CPU57.37%;rootnice19 passive-through scan context retained,outcomesunopened. Rollingchunk31healthy/economicsfalse;three newshelperswaiting/fresh. Carry 375sampled/oneinvalid/488future. Archive 3,836,576B,projection 4,488,300B under5MiB;next08:06:33UTC.


### Routine review192 — 2026-10-02 08:06:33 UTC

Nine exact losses:convergence3/−$1.0342890071,Premium6/−$9.5962460378;no gains/estimates/aborts,four HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,603:2,568exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Busy52.44ms pulse retained;reviewfresh/ok lag42.23ms/CPU68.50%. Rollingchunk33 one Core socketclose08:03:12,3connections/advancingrecords,parentnotified;no intervention/economicreads. Three newshelperswaiting/fresh. Carry 379sampled/oneinvalid/484future. Archive 3,841,198B,projection 4,487,580B under5MiB;next08:26:33UTC.


### Routine review193 — 2026-10-02 08:26:33 UTC

22exactlosses:convergence7/−$7.7294470324,Premium15/−$25.7686206065;no gains/estimates/aborts,nine HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,625:2,590exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Busy60.65/51.06ms pulses retained;reviewfresh/ok lag38.87ms/CPU55.25%. Rollingchunk35healthy,no newerrors/economicsfalse;three newshelperswaiting/fresh. Carry 383sampled/oneinvalid/480future. Archive 3,846,098B,projection 4,487,138B under5MiB;next08:46:33UTC.


### Routine review194 — 2026-10-02 08:46:33 UTC

Five exact Premium losses/−$8.5448342029;no gains/estimates/aborts,HL/Coreprice-limit rejectoneeach. Completecoverage/exactarchiveguards. Cumulative2,630:2,595exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Paperfresh/ok lag35.93ms/CPU68.75%,106pairs;rollingchunk37healthy/economicsfalse;three newshelperswaiting/fresh. Carry 387sampled/oneinvalid/476future. Archive 3,850,491B,projection 4,486,189B under5MiB;next09:06:33UTC.


### Routine review195 — 2026-10-02 09:06:33 UTC

Nine exactlosses:convergence2/−$1.7558274191,Premium7/−$11.9089083999;no gains/estimates/aborts,two HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,639:2,604exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Paperfresh/ok lag35.45ms/CPU63.06%;rollingchunk39healthy/economicsfalse;three newshelperswaiting/fresh. Carry newinvalid389flagged metadataonly; 391sampled/twoinvalid(71,389)/471future. Archive 3,855,044B,projection 4,485,400B under5MiB;next09:26:33UTC.


### Routine review196 — 2026-10-02 09:26:33 UTC

Four exact Premium losses/−$6.8353806734;no gains/estimates/aborts/rejects. Completecoverage/exactarchiveguards. Cumulative2,643:2,608exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Paperfresh/ok lag32.67ms/CPU61.95%;rollingchunk41healthy/economicsfalse;three newshelperswaiting/fresh. Carry 394sampled/twoinvalid(71,389)/468future. Archive 3,859,422B,projection 4,484,436B under5MiB;next09:46:33UTC.


### Routine review197 — 2026-10-02 09:46:33 UTC

Seven exactlosses:convergence3/−$3.8568606433,Premium4/−$7.7739493798;no gains/estimates/aborts,four HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,650:2,615exactlosses,oneestimate,fivepairedgains,29auditedrescuegains. Paperfresh/ok lag36.21ms/CPU65.50%;rollingchunk43healthy/economicsfalse;three newshelperswaiting/fresh. Carry 398sampled/twoinvalid(71,389)/464future. Archive 3,864,055B,projection 4,483,727B under5MiB;next10:06:33UTC.


### Routine review198 — 2026-10-02 10:06:33 UTC

Convergence3failedhedgecloses/onegain,aggregate−$2.6174059879;Premium4losses−$6.9447202594. Rescuegain flaggedrootaudit,no pairedwin/estimate/abort;four HLprice-limit rejects. Completecoverage/exactarchiveguards. Cumulative2,657:2,621exactlosses,oneestimate,fivepairedgains,30rescuegains(latestpending). Paperfresh/ok lag36.60ms/CPU50.60%;rollingchunk46healthy/economicsfalse;three newshelperswaiting/fresh. Carry 403sampled/twoinvalid(71,389)/459future. Archive 3,868,725B,projection 4,483,055B under5MiB;next10:26:33UTC.


### Routine review199 — 2026-10-02 10:26:33 UTC

Six exactlosses:convergence1/−$0.1043223789,Premium5/−$8.1558688702;no gains/estimates/aborts,two HLprice-limit rejects. Completecoverage/exactarchiveguards. Review198 VVVrescue+$0.5379666444 rootaudited,pendingcleared,3,356B evidenceincluded;larger sizes authorized,earlier sizeexclusions superseded. Cumulative2,663:2,627exactlosses,oneestimate,fivepairedgains,30auditedrescuegains. Paperfresh/ok lag34.94ms/CPU50.44%;rollingchunk47healthy/economicsfalse;three newshelperswaiting/fresh. Carry 406sampled/twoinvalid(71,389)/456future. Archive 3,876,615B,projection 4,485,603B under5MiB;next10:46:33UTC.
