# Contingent entry trial: stopped checkpoint analysis

Checkpoint: `1790715639.367909193`; status: `duration_elapsed`.
Original candidates: 1; mapped: 1; missing mappings: 0.
Frozen evidence: `evidence.json.gz` (SHA-256 `67f02c62e788b54477fec04391b9cdefb419f1a35f43bb20fdffc158d4db6392`).

| Policy | Exact closes | Estimated | Aborted | Net, exact ledger | Fees | Reserve | Capital | Funding |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control | 1 | 0 | 0 | -0.9312 | 0.0000 | 0.4977 | 0.0000 | 0.0000 |
| treatment | 0 | 0 | 1 | N/A | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Ledger fees and charges include positions still open or awaiting funding; exact net includes settled exact closes only.

| Policy | Outcome counts for mapped candidates | Mapped complete equivalent unmatched seconds | Mapped complete wall seconds | Open observed equivalent seconds |
| --- | --- | ---: | ---: | ---: |
| control | closed=1 | 0.547 | 0.547 | N/A |
| treatment | aborted=1 | 0.000 | 0.000 | N/A |

| Policy | Entry class and outcome | Count | Recorded net USD |
| --- | --- | ---: | ---: |
| control | entry_failed:closed | 1 | -0.9312 |
| treatment | zero_abort:aborted | 1 | 0.0000 |

Mapped both exact-known original candidates: 1; treatment minus control: 0.9312 USD.
Mapped both fully filled and exactly closed: 0; difference: N/A USD.
Mapped foregone control matches: 0 (control wins: 0).

Coverage: mappings complete=True; terminal rows complete=True; missing referenced trades=0.
Equivalent unmatched seconds integrate |long remaining − short remaining| / original quantity. Same-time fills are batched; complete and observed-to-freeze times are separate.
N/A means no eligible observation; a measured zero remains 0.0000.
Peer fill latency is reported from the original candidate and from the later peer send as distinct clocks in analysis.json.
A zero-fill abort or abstention is foregone exposure, not a profitable execution. Paired differences include these known-zero cash outcomes.
Pending funding and open exposure have unknown net P&L. Timing for open positions is observed only to checkpoint time.

These are independent paper portfolios on shared public books. Their P&L must not be added; routes and events are correlated.

## One observed candidate

The study ran for 1,200.018 seconds, from 20:40:39.349703 to 21:00:39.367909 UTC on 2026-09-29. It selected one GRAM candidate: buy Lighter, sell Hyperliquid, original quantity 659 GRAM. The signal time was 20:57:56.517617 UTC.

| Event | UTC time | Since signal |
| --- | --- | ---: |
| Control Lighter long filled, 659 GRAM | 20:57:57.021032 | 0.503415 s |
| Hyperliquid short rejected in both policies | 20:57:57.091678 | 0.574062 s |
| Control Lighter long flattened, 659 GRAM | 20:57:57.568065 | 1.050448 s |
| Control settled | 20:57:57.570778 | 1.053161 s |

The Hyperliquid entry had `entry_rejection_reason=price_limit`: zero quantity was eligible within the original 10 bps limit. The book reported 143 GRAM of short-side quantity in total, with source age 0.374678 s at rejection. The control had already bought 659 GRAM on Lighter, then flattened that entire leg. Its price P&L was −$0.433502, reserve −$0.497686, capital cost −$0.000000863, fees and funding $0, yielding exact net −$0.9311888293. Its unmatched exposure was 0.547033 equivalent full-size seconds: 0.070646 before the rejection and 0.476386 while flattening.

The HL-first treatment received the same Hyperliquid rejection before sending its Lighter peer leg. Both treatment legs remained zero quantity, so its abort had zero trading cash and zero one-leg exposure. There is no treatment peer-send-to-fill clock and no both-filled comparison. The single paired cash difference, +$0.9311888293 for treatment relative to control, is one avoided failed-hedge loss; it does not establish profitable execution or a general policy advantage.

The source plan, stopped snapshot, launch record, markets list, frozen source manifest, and SHA-256 checksums are preserved beside this report in `run-manifest.json`. Every file in the frozen source manifest matched at analysis time. The retained trade mapping and terminal trade coverage are complete for this one selected candidate.
