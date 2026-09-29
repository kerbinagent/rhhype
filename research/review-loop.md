# Twenty-minute live paper reviews

User requested ongoing reviews every twenty minutes on 2026-09-29. The active
agent session performs these reviews; `scripts/paper_review.py` is a one-shot
audit command, not an unattended strategy optimizer or scheduler.

## Protocol

- Read a consistent SQLite checkpoint; compare cumulative ledger deltas against
  the prior checkpoint. Separate paired trades from failed hedge unwinds and
  exact funding settlements from estimated results.
- Check retained evidence coverage, feed freshness, execution timing, CPU and
  event loop lag. Missing evidence is not a successful observation.
- Preserve existing portfolios. Add a separately named, dated experiment for a
  changed entry policy. Keep fees, delayed fills, capital and exit policy explicit.
- Avoid selecting a winner from one short interval. Hold a policy unchanged when
  the sample is too small; record that decision rather than force a parameter edit.
- The collector remains paper only. No real orders or private credentials.

Run `.venv/bin/python scripts/paper_review.py`. Default output:
`data/strategy-reviews/latest.json`, checkpoint state, and at most 72 archived
reviews (approximately 18 MiB maximum plus current report/state). Each report
contains the next due time. Existing collector storage limits remain in force.

## Initial review: 2026-09-29 16:06:33 UTC

This establishes the first cumulative checkpoint; initial interval summaries use
retained trade records and cannot yet establish complete ledger-delta coverage.
Next review: **16:26:33 UTC**.

Recent twenty-minute retained completions:

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 343 | -382.54 | 333 | 10 |
| Cooldown | 44 | -48.17 | 42 | 2 |
| Historical median | 8 | -21.22 | 1 | 7 |
| Conservative | 0 | 0 | 0 | 0 |

An earlier 15:56:53 audit found 16 median-policy entry attempts: 14 one-leg
unwinds and two both-leg aborts. All 16 Hyperliquid legs failed (13 rejected,
three timed out); no exact rejection reasons survived the old evidence ring.
By the initial checkpoint one later median trade had paired, losing $1.39.

### Revision 3: independent confirmation experiment

Keep the preceding policies as controls. Add `confirmed`, requiring the same
median forecast and Standard fees, followed by a one-second observation wait
and fresh source timestamps from both venues. Re-evaluate the original
quantity, costs, historical forecast and depth. Cancel on lost eligibility;
expire candidates after four seconds. Passing confirmation submits ordinary
delayed paper intents; it cannot fill from the confirmation quotes.

Hyperliquid confirmation refreshes use only spare capacity after existing
exit/entry/held/probe priorities under the same request budget. This can reject
many candidates and does not guarantee a hedge. New compact leg diagnostics
preserve price-limit/depth/minimum/quantity rejection reasons in trade records.
Models start cold after deployment, while old balances and cooldowns persist.
