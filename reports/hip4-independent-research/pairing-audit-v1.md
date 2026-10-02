# HIP-4 pairing engine: independent audit (queue item 2)

This audit was done on 2 October 2026, before any Q357 capture data was read.

- **Engine audited.** The written results pin the engine sealed in the v3 plans:
  - source `scripts/hip4_continuation_pairing.py`, 54,160 B, sha256 `e69cd7f0…`;
  - tests 31,869 B, `82573679…`.
- **Re-run on v4.** The v4 repairs changed only verification, publication and admission code. The source is now 55,823 B, `bc7e9204…`, and the tests 35,600 B, `0d0e0eb2…`. Both harnesses were re-run dry on that engine at 18:27 UTC with identical results: 3,638 and 3,456 episodes, 0 mismatches. The write-once result files are not rewritten.
- **v5.** v5, sealed 18:49 UTC, is a blinded, during-collection implementation amendment: gate-term caching and a 150M step cap. Its outputs are byte-identical to the v4 snapshot in 1,609 cases, including forced work caps, and 100 cut-time checks show no lookahead ([equivalence result](pairing-equivalence-v5-result.json)).

## Method

Two independent checks were run.

1. **Reference simulator.** [`pairing-audit-v1.py`](pairing-audit-v1.py) is a 100 ms-grid reference written from spec revision 4.
   - It uses none of the engine's segments, snapshots, gates, fills or episode code.
   - Every instant in the synthetic streams lies on the grid, so stepping is exact. Those instants are frames, the 1,000 ms qualification, the 500 ms evaluation and the 35,000 ms liveness.
   - The usable view is rebuilt from the generator's own ground truth.
   - Each episode is compared field by field with the engine's trace. The fields are decision time, key, m, class, cash v, capital, holdings, attempts, misses, partials, zero-fill causes, every action (kind, time, cash, quantities, leg ages) and the open-class envelope.
   - The per-route class counts in the projection are compared as well.
2. **Coverage extension.** [`pairing-audit-v2.py`](pairing-audit-v2.py) adds targeted variants for the classes the random streams never reached.

| Run | Streams | Fee schedules | Episodes compared | Mismatches | Result |
| --- | --- | --- | --- | --- | --- |
| v1, seeds 0–299, random | 300 (100 censored, 53 invalidated) | 5 | 3,638 | 0 | pass, [result](pairing-audit-v1-result.json) |
| v2, seeds 0–119, targeted | 320 variants (100 censor, 100 unfilled, 120 attempt cap 2) | 5 | 3,456 | 0 | pass, [result](pairing-audit-v2-result.json) |

- **Schedules.** The five schedules are:
  - zero fees;
  - the three sealed sensitivity points;
  - an audit-only schedule with every fee term non-zero (f 0.003, split 0.001, negate 0.002, merge 0.0005).
- **Classes reached across both runs** (episodes):

  | Class | Episodes |
  | --- | --- |
  | not_admitted_size | 2,333 |
  | entry_closed | 1,274 |
  | open_at_window_end | 1,295 |
  | closed | 790 |
  | entry_censored | 328 |
  | entry_unfilled | 327 |
  | censored_open | 347 |
  | invalidated_open | 212 |
  | work_cap | 143 |
  | entry_after_close | 40 |
  | entry_invalidated | 5 |

- **Harness revisions.** Two revisions, both in dry runs before anything was written, corrected only the reference's ground truth. No engine code changed in response.
  1. The reference had treated locked books as valid. The frozen kernel instead suspends a coin on a crossed or locked frame until its next valid frame.
  2. The reference had aged the rejected frame of a suspended coin.

  Both are recorded in the harness docstring.

## Findings by audit dimension

| Dimension | What was checked | Finding |
| --- | --- | --- |
| Causal support | A view is usable only when acknowledgements are complete, the stream is live (last inbound frame + 35 s), not invalidated and before min(close, stop). Coin suspension on crossed frames, liveness lapses from 45 s pong gaps, and questionSettled invalidation are all exercised. | Exact agreement. Frames at an instant precede evaluation, and limits come from the qualification state. |
| Fees | The fee domain, and all four terms in every gate and cash flow. | Exact agreement on five schedules. Model placement: f applies to sells and to the settlement envelope only. This matches "Outcome trading only charges fees when closing or settling, not when opening outcome positions" ([Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), fetched 14:17 UTC, `75e55504…`). |
| Per-action cash and inventory | Make, merge, split and negate, buys and sells, and NO_F. | Exact agreement. The engine's own reconcile() also rechecks every episode. |
| Capital | The chronological cash prefix within an instant: make before sell, and buy before split and merge. | Exact agreement. The convention is conservative: the inverse-first split is charged before the merge that returns it at the same instant. |
| Censoring and end classes | Tie ranks: censored before invalidated before window end. Entry delays that straddle e. | Exact agreement on all entry and open classes. |
| Coherent depth | Fills are capped at the floored touch size at the evaluation instant, and no level beyond the touch is assumed. | Agreement. As designed, overlapping episodes reuse the same displayed size, so episode sums are not portfolio cash. |

## Not covered, and open assumptions

- **Kernel internals.** The frozen live-v1 kernel was accepted separately and is checked mark by mark against itself on every run. That covers its stale and future gates, probe and l2Book handling, meta-id validation and unattributable frames. The synthetic streams use a constant 300 ms source age and no probe traffic.
- **Run, seal and admission machinery.** These are covered by the 23 unit tests, not by this audit.
- **Merge as "closing".** Whether a merge (or a split or negate) is charged the trading fee as a closing is undocumented. If it is, c_merge = f. The sealed sensitivity points do not include that case. It is recorded here as an unverified assumption and is not added after sealing.
- **Settlement.** Settlement timing, order cancellation and post-settlement conversions remain unproven (ledger claims A–C, E). Open-class envelopes are therefore formal, valid only under A1–A3 of the spec.
- **Granularity.** Whole-token conversion and trading granularity is an explicit model premise (ledger claim M), not a documented rule.
