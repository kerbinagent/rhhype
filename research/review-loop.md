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

## Review 1: 2026-09-29 16:26:45 UTC

Window 16:06:33–16:26:45; next due 16:46:33 UTC. All completion counts
match cumulative ledger deltas. Existing controls and confirmation thresholds
remain unchanged; the confirmation sample is not sufficient for tuning.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 336 | -423.96 | 333 | 3 |
| Cooldown | 61 | -96.29 | 60 | 1 |
| Historical median | 3 | -2.77 | 1 | 2 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed (started 16:08) | 0 | 0 | 0 | 0 |

- Both median failed hedges were ZEC across the two Lighter domains, using the
  same HL observation. Both HL legs hit their price limit after 1.23–1.40 s.
  These correlated attempts are not independent evidence.
- The paired median COIN trade forecast +$0.334, but the quoted opening gross
  advantage deteriorated by $1.285 before both entries completed (1.205 s).
  It closed at max hold for -$0.950. This supports measuring entry deterioration
  before relaxing confirmation or price limits.
- Confirmed recorded 12 confirmation-gate checks with no entries; these are
  repeated checks, not twelve independent candidate opportunities. Model had
  224 warm routes, so its inactivity was not a model warmup failure.
- All feeds connected; 67.3% of one core, 11.8 ms p95 loop lag, 913 books/s,
  186.6 MiB RSS. Reconciliation passed with maximum error < $5e-11.
- Original Standard and Premium portfolios made no new entries: flat XAG
  positions have unresolved Aster funding settlement timing near 16:00, which
  currently blocks spendable capital on both legs. Investigating venue-scoped
  funding completeness rather than inventing an exact settlement result.

Entry deterioration audit for the same completed window: baseline paired
median $0.000, p95 $0.180 (333 observations); cooldown median $0.000, p95
$0.222 (60); median strategy $1.285 (one). Median paired entry completion
times were 1.351 s, 1.348 s, and 1.205 s respectively. These entry costs alone
do not explain baseline losses: persistent closing spreads and full round-trip
costs remain central. Reports now include these metrics and explicitly exclude
partial or unmatchable signal quantities.

### Infrastructure correction after review 1

Verified funding independently by venue. The two historical XAG positions remain
flat and incomplete because Aster charge timing cannot be reconstructed exactly.
Their known Hyperliquid side can release margin while reserving any negative
funding; Aster remains reserved/unavailable. No uncertain receipts or trade P&L
are booked. Original Standard/Premium activity before this correction is not a
valid fee-tier comparison against active portfolios. Entry policy thresholds
remain unchanged. All 137 tests pass before deployment; restart again clears
rolling model history, requiring another two-minute warmup.

Deployed funding isolation at 16:36:45 UTC, collector PID 1568172. First live
check: Standard resumed 21 entries; Premium HL spendable cash $4,438.40, Aster
unavailable. Both original XAG records remain AWAITING_FUNDING with aggregate
cashflow null. Accounting reconciliation remains within $5e-11. All four feeds
connected, 63.4% of one core, 11.5 ms p95 loop lag. No fee/exit changes.

## Review 2: 2026-09-29 16:46:51 UTC

Window 16:26:45–16:46:51; next due 17:06:33 UTC. Retained completion counts
match ledger deltas. No strategy threshold changes at this checkpoint.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 270 | -291.74 | 268 | 2 |
| Cooldown | 59 | -62.51 | 59 | 0 |
| Historical median | 1 | -1.43 | 1 | 0 |
| Conservative | 1 | -2.70 | 1 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

- Median and conservative both traded CASHCAT about five seconds apart. These
  correlated trades improved on quoted entry prices by $0.751 and $0.182;
  nevertheless the forecast closing-spread costs (-$0.070 and $0.225) were far
  below the observed exit spread costs ($3.992 and $3.715). A rolling historical
  level is not a forecast of convergence within ten seconds. Investigating a
  causal forecast matched to the holding horizon before adding another policy.
- Confirmation had 80 cumulative gate checks but zero entries. Current counts
  mix repeated observations and distinct candidates; better lifecycle diagnostics
  are needed before interpreting its rejection rate or tuning the wait.
- Original Standard resumed 133 closes/-$145.56 and three aborts after funding
  isolation; Premium resumed nine closes/-$19.74. The two original XAG funding
  records remain incomplete, with only Aster reservation retained.
- Accounting reconciliation passes within $6e-11. All feeds connected. Snapshot
  showed 59.8% of one core, 65.5 ms p95 loop lag, 955 books/s and 163 MiB RSS.
  A follow-up showed 50.5 ms lag/73.1% CPU. Investigating offline hot paths; live
  py-spy attachment was denied by OS ptrace permissions and passwordless sudo
  was unavailable. No security settings were changed.

### Measurement corrections after review 2

Confirmation priority 4 previously had no scheduled turn and could starve while
probe traffic remained ready. Split the existing probe scheduling share evenly
between probes and confirmation: priorities over twelve turns now
`0,1,0,2,0,3,0,1,0,2,0,4`. Exit, entry and held-risk shares and the shared REST
request cap are unchanged. Record request/success/error counts by priority.

Add distinct candidate lifecycle counts with terminal reasons and the invariant
`armed = entered + terminal + pending`. Old repeated checks cannot be converted
into unique opportunities; new counters explicitly begin at deployment. This
instrumentation will separate lost economics from missing fresh observations.
No confirmation timing, source-skew or forecast threshold was relaxed.

Offline replay also identified costly recursive copies of probe books. Preserve
full level lists and mutation isolation using immutable level tuples and copied
metadata. Three controlled replays showed 0.349 to 0.231 CPU-seconds per 10,000
events (1.51x engine component, not a live-system speedup). Profile scope and
limits: reports/strategy-experiments/probe-profile.md. Lag subsequently recovered
to about 14 ms before deployment, so the earlier spike was not constant saturation.
All 141 tests pass, including continuous-load confirmation scheduling, candidate
accounting/restart, immutable probe observations, accounting and terminal behavior.
