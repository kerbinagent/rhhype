# Twenty-minute live paper reviews

User requested ongoing reviews every twenty minutes on 2026-09-29.
`scripts/review_loop.py` now captures audits automatically on the existing
20-minute schedule; the active agent session interprets them and researches
changes. This scheduler never changes a strategy or sends orders.

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

Run `.venv/bin/python scripts/review_loop.py` for scheduled capture, or
`scripts/paper_review.py` for a one-shot audit when the loop is stopped. Avoid
concurrent one-shot captures because they advance the same baseline. Default output:
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

Deployed at 16:57:57 UTC, collector PID 1627074. First health check: all feeds
connected, 63.6% of one core, 17.2 ms p95 lag, 896 books/s, 107 MiB RSS; models
were still warming. Lifecycle counters start fresh with zero residual. Financial
reconciliation passes within $7e-11; all existing portfolios retained.

## Review 3: 2026-09-29 17:06:50 UTC

Window 16:46:51–17:06:50; next due 17:26:33 UTC. Counts reconcile with the
cumulative ledger; no profitable paired trade was observed in this interval.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 265 | -285.59 | 260 | 5 |
| Cooldown | 34 | -35.46 | 34 | 0 |
| Historical median | 11 | -11.20 | 0 | 11 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Median also had one no-fill abort; all twelve HL entry legs hit price limits.
Original Standard's one positive close was a failed hedge, not paired arbitrage.
All newly pending records from the 17:00 funding boundary subsequently settled;
only the two historical 16:00 Aster timing ambiguities remain. Financial audit
passes within $7e-11. All feeds connected, 70.3% of one core, 18.1 ms p95 lag,
837 books/s, 151 MiB RSS.

New lifecycle counters (since 16:57:57) identify six distinct armed candidates:
five ended at the skew gate, one lost its economic edge, zero remained pending.
The accounting residual is zero. No requests were labelled priority 4. This alone cannot prove starvation: a
refresh promoted to an entry/held/probe priority also updates confirmation books.
The skew cancellations motivate testing earlier refresh eligibility. Change it
to arm time; keep the one-second confirmation delay, both post-due source times,
all forecast/depth/budget checks and the four-second expiry. This improves the
observation attempt without fabricating a surviving opportunity. Existing
execution/risk scheduling shares and request cap remain unchanged. Thirty-one
focused refresh/selector/shadow tests pass before deployment.

## Review 4: 2026-09-29 17:33:21 UTC (delayed)

The review due 17:26:33 ran after the user resumed the active session. Window
17:06:50–17:33:21 is therefore about 26.5 minutes; the next anchored deadline
remains 17:46:33. Counts match durable deltas.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 356 | -413.77 | 348 | 8 |
| Cooldown | 61 | -85.71 | 60 | 1 |
| Historical median | 4 | -4.82 | 1 | 3 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Lifecycle cumulative: ten arms, eight skew cancellations, one economic
cancellation and one forecast cancellation, no entries; residual zero. No
priority-4-labelled requests, but higher-priority shared refreshes can still
serve these candidates. Entry thresholds unchanged; investigate faster source
observations rather than interpret this as ten observed short-lived profits.

User requested active parallel research between polls. Started a separate
40-minute, 12-pair public-WS horizon experiment at about 17:34 UTC, PID 1691034,
in data/horizon-research. It scores future spread forecasts, never cash income,
and has bounded output. Chronological entry-filter experiments, historical
funding-carry research, and direct BBO-versus-depth feed measurements proceed
in parallel. Existing paper ledgers and strategy gates remain unchanged.

### Active experiments between reviews 4 and 5

- Two direct public-feed captures measured BBO source gaps around 0.11–0.21 s
  versus about 5.4 s for HL L2. Same-size $1,000 top coverage varied sharply:
  both sides fit in 71–97% of BTC samples, 78–95% of ETH, but only 1/58 COIN
  updates. See research/hyperliquid-feed-cadence.md and frozen raw captures.
- Added opt-in `--hl-bbo`; every BBO is only its own displayed bid/ask level.
  Older L2 cannot overwrite fresher top quotes; contemporaneous depth requires
  matching top identity. Existing production collector remains unchanged.
- Started a second 40-minute horizon observer with BBO at about 17:43 UTC,
  PID 1727752, data/horizon-research-bbo. The first depth observer stays running
  as a separate coverage/model control. Early outcome coverage differs; neither
  has enough mature anchors yet for trained forecast-error comparisons.
- At 17:44:49 started matched 40-minute paper transport experiments, depth PID
  1730139 and BBO PID 1730140, under data/paper-monitor-feed-depth and -bbo.
  Both discover the same 21 pairs among 12 selected assets, use identical eight
  fee/strategy portfolios, $20k capital per portfolio, $1k per leg, 10s/10-cent
  exits, and disable targeted REST. Each DB is capped at 32 MiB, evidence and
  book ring at 4 MiB, 2,000 trades and 5,000 signals. These are independent
  scenario ledgers, not additive income or live orders. Initial CPU usage was
  about 16% and 21% of one core. No existing balances were reset.
- All 161 tests passed before these starts; CLI defaults also verified: targeted
  REST remains enabled and BBO disabled unless explicitly selected.


## Review 5: 2026-09-29 17:48:04 UTC

Window 17:33:21–17:48:04 (about 14.7 minutes after the preceding delayed
capture); next anchored deadline 18:06:33. Retained completion coverage is
complete for all eight portfolios.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 199 | -240.271 | 197 | 2 |
| Cooldown | 41 | -55.774 | 41 | 0 |
| Historical median | 2 | -1.658 | 0 | 2 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Lifecycle cumulative: 12 arms, ten skew cancellations, one economic and one
forecast cancellation; no entries and zero residual. CPU 67.5% of one core,
p95 event-loop lag 12.97 ms, RSS 215 MiB, about 1,015 book updates/s. Strategy
thresholds remain unchanged while separate prospective studies run.

At about 17:50 UTC started the scheduled audit loop, PID 1749934, with its
existing state/deadline. It captures every 1,200 seconds, preserves the prior
baseline on failed/stale reads, retries after 60 seconds, and has an exclusive
process lock plus interruptible SIGINT/SIGTERM handling. Reports retain the
72-file/256-KiB limits; loop logs rotate at 1 MB with one backup. Six focused
loop/audit tests pass. Data capture can continue without an active agent turn;
strategy research and decisions require the active session.

Between reviews, the frozen chronological filter experiment found zero wins
among 527 holdout closes and no profitable selected filter family (see
reports/filter-experiments/REPORT.md). A separate 48-hour funding screen found
no asset covering four Standard taker fees from 24-hour holdout funding alone
(see reports/funding-carry/REPORT.md). These negative results do not justify
lowering execution, fee or freshness assumptions.


### Execution and forecast audit before review 6

The initial BBO paper pilot stopped completing baseline trades because partial
exits left floats just below one lot. Both matched pilots were stopped together
at 18:01:20 UTC and preserved; see research/partial-exit-lot-audit.md and
reports/feed-experiment/flawed-pilot-final.md. Lower cumulative BBO losses were
confounded by these blocked positions. Depth baseline had only 2 paired closes
among 562; BBO had 54 among 80, plus four trapped baseline exits. These source
experiments disable REST and are distinct from the production configuration.

Committed decimal lot conservation and legacy checkpoint normalization as
16be742. Fills still require sufficient displayed quantity and a later eligible
book; no residual is written off as an invented exit. The full suite passed
188 tests, followed by 20 focused horizon tests after a final bounds regression.

Committed horizon model v2 as 3c293da. Independent review fixed valid future
quotes being dropped by the 1 Hz history sampling cap; future outcome detection
now examines every valid advancing paired quote. Predictions remain frozen
before same-tick outcomes can train them. Added route censor/coverage accounting,
separate generation-segment metrics, a bounded 5,000-row export, and offline
route/five-minute-block analysis. The predeclared fourth model shrinks a linear
forecast toward persistence. Anchors 12 seconds apart can overlap in outcome
time by up to four seconds; no independent-trial inference is made.

- 18:05:21 UTC: started separate forty-minute BBO forecast v2, PID 1806918,
  data/horizon-research-v2-bbo, 12 pairs. Old observers keep their loaded v1
  behavior and will be labeled accordingly; no results are merged across versions.
- 18:05:51 UTC: started corrected matched forty-minute paper source pilots,
  depth PID 1807958 and BBO PID 1807959, data/paper-monitor-feed-v2-depth and
  -bbo. Same commands/limits as their predecessors; fresh portfolios and no
  targeted REST. Their results are independent scenarios, never additive income.
- Production remains the REST-enabled control. Accounting fix deployment follows
  the 18:06 scheduled review so the preceding review has a clean code boundary.


## Review 6: 2026-09-29 18:06:33 UTC scheduled capture

SQLite checkpoint 18:06:30.712; window starts 17:48:04.123. The automatic loop
captured on the original schedule. Retained coverage is complete throughout.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 191 | -247.783 | 184 | 7 |
| Cooldown | 47 | -70.306 | 44 | 3 |
| Historical median | 5 | -4.528 | 1 | 4 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

No positive close in these portfolios. Lifecycle cumulative: 17 arms, 13 skew
cancellations, three economic and one forecast cancellation, no entries,
residual zero. CPU 81.9% of one core, p95 loop lag 47.5 ms, RSS 220.8 MiB,
about 1,109 book updates/s. This higher lag deserves another health check after
deployment; it is still much shorter than observed venue/source delays.
Next scheduled capture: 18:26:33 UTC.

Fee sensitivity on the fixed holdout remains negative even after removing both
explicit trading fees and the modeled 5 bp reserve: -$228.90 versus -$624.27
recorded. Neither cheaper tiers nor that cost reserve alone explains away the
negative sample. See reports/fee-sensitivity when finalized. No strategy gate
has been relaxed in response to these losses.


Production accounting deployment: gracefully restarted at 18:07:17 UTC as PID
1812668, original command/ledger retained, BBO still disabled and targeted REST
still enabled. First check: all four feeds connected; 114 discovered pairs,
64.8% of one core, 26.4 ms p95 lag. Market count changed from 115 through normal
fresh discovery, not a strategy asset filter. Baseline cumulative balances and
close counts continued; no experiment balances were merged into production.


## Review 7: 2026-09-29 18:26:33 UTC scheduled capture

SQLite checkpoint 18:26:31.324; window starts 18:06:30.712. All eight
portfolios have complete retained completion coverage.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 185 | -201.305 | 182 | 3 |
| Cooldown | 56 | -66.019 | 55 | 1 |
| Historical median | 4 | -5.731 | 1 | 3 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

The median policy's single positive close was a failed hedge, not a successful
paired arbitrage. Baseline and cooldown had no wins. Lifecycle cumulative:
23 arms, 16 skew cancellations, four economic, two forecast, one budget/depth;
zero entries and zero accounting residual. CPU 58.45% of one core, p95 loop lag
10.56 ms, RSS 185.16 MiB, about 819 book updates/s. Next capture 18:46:33 UTC.

Corrected matched source pilots at common cutoff 18:26:41 UTC are still losing:
depth baseline 865 closes / -$695.54; BBO 466 / -$465.47. Different numbers of
attempts and incomplete retained depth rows prevent ranking by aggregate loss.
BBO's retained 466 closes contain 367 paired and 99 failed hedges. Its 100ms
probe has 97.5% observation coverage but actual mean observation delay 566.8ms;
this is neither 100ms execution nor completed round-trip profit. Both pilots
have no old one-lot residuals. See corrected-pilot-review7 report.

Between reviews, committed and deployed snapshot detachment (18:27) and a
position display fix (18:33). The user's 8,000-second XAG records are flat trades
waiting for uncertain funding accounting, with actual holds about 12 seconds;
new snapshots distinguish active exposure from pending settlement. No funding
was invented and neither strategy thresholds nor ledger balances were reset.
Fixed-quantity quote and maker feasibility studies continue separately.


### Independent checks and research before review 8

At 18:36:09–10 UTC an independent read-only reconciliation passed both production
and corrected BBO. Largest arithmetic/wallet discrepancies were $5.64e-11 and
$2.55e-11. Retained closes were 4,973/10,673 lifetime (production) and
1,986/2,042 (BBO); retained P&L is not a lifetime total. No checkpoint position
with any positive remaining leg quantity was older than 45s. Maximum exposure
ages were 11.76s and 12.95s. Only the two zero-quantity XAG settlement waits
were hours old. The full suite passed 223 tests after the funding display fix.

The stopped maker capture's initial subscription packets include historical
trades. Its offline replay will exclude these startup snapshots and pre-capture
source times, so old trades cannot manufacture current trade-flow evidence.
Predeclared additional taker controls: 1/2/5/10-second fixed-quantity markouts,
at most one anchor per second per directed HL/Core or HL/RH route, all four
fees, missing outcomes explicit. No horizon chosen retrospectively as a winner.

At 18:38, the fixed-quantity pilot had scored crypto and equity/metal routes,
including BTC/ETH/SOL/ZEC/XRP/HYPE, NVDA/META/XAG and a small COIN sample.
All four frozen model screens had selected zero positive-after-four-fee
anchors so far. This interim diagnostic does not replace the stopped report.


## Review 8: 2026-09-29 18:46:33 UTC scheduled capture

SQLite checkpoint 18:46:31.988; window starts 18:26:31.324. Retained completion
coverage is complete for all eight portfolios; no winning closes in this window.

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 182 | -198.078 | 180 | 2 |
| Cooldown | 57 | -66.903 | 56 | 1 |
| Historical median | 8 | -12.158 | 1 | 7 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Lifecycle cumulative: 35 arms; 20 skew, six budget/depth, four economic, four
forecast, one invalid-quote terminal; zero entries and residual zero. CPU 67.58%
of one core; p95 loop lag 18.50ms; RSS 162.27MiB; 936 books/s. All four feeds
connected. This window includes the two display/checkpoint deployments.
Next scheduled audit: 19:06:33 UTC. Thresholds and execution assumptions unchanged.

Finite studies completed and archived:

- Corrected no-REST source pilots: depth baseline 1,599 closes / -$1,274.90;
  BBO 852 / -$840.79. Do not rank by total: activity and retained coverage differ
  (44.5% versus 75.2% for baseline diagnostics). Retained depth closes are failed
  hedges; BBO has 525 paired and 116 failed. No aged one-lot residuals. Duration
  stop leaves some exposure frozen; reported P&L excludes those unfinished trades.
  BBO 100ms probe observed 6,090/6,297 (96.7%), actual mean 573.7ms; delayed
  opening-edge survival is not round-trip profit. Production keeps REST/depth.
- Horizon v2: 2,797 common scored anchors, conditional-linear MAE 0.927bp versus
  persistence 1.094bp. Smaller quote error is not economic profitability.
- Fixed original quantity: 2,134 anchors, 1,595 matched, 539 censored, no export
  drops. One after-four-fee positive (NVDA +$0.3014), negative after reserve
  (-$0.1985), not selected by any frozen screen. Primary screen selected zero;
  historical-median selected five, four observed/all negative, one censored.
- Maker archive: five focused analyzer tests passed after independent audit
  found/fixed historical HL trades preceding first BBO. Fee-positive opening
  allowances with public trade-flow evidence do not establish a maker fill or
  closing P&L. Four-taker BTC/ETH controls at 1/2/5/10 seconds produced no positive
  after-fee displayed markouts on either HL/Core or HL/RH complete-book subsets.

Decision: no tested strategy promoted. Forecast improvement and transport speed
are useful engineering results; neither supplies a positive net trading edge.
The next maker investigation requires post-flow hedge and unwind evidence and
explicit queue/acknowledgement assumptions, rather than reclassifying opening
quotes as profits. Automatic 20-minute evidence capture continues; active AI
research decisions do not execute outside an active session.


## Reviews 9 and 10: captures at 19:06 and 19:26 UTC, reviewed late at 19:34

The active agent ended its prior turn, so these two captures were not analyzed
at their scheduled deadlines. The background scheduler did capture both on
time. The user pointed out the missed active follow-up. This was a workflow
failure: automatic evidence capture does not perform strategy research.

| Window ending UTC | Baseline closes / net USD | Cooldown closes / net USD | Median closes / net USD |
|---|---:|---:|---:|
| 19:06:31.739 | 181 / -212.200 | 37 / -46.025 | 1 / -0.337 |
| 19:26:32.920 | 184 / -220.291 | 37 / -55.291 | 2 / -4.647 |

All retained coverage complete, zero winning closes in these three policies.
Conservative and confirmed had no entries. At the second checkpoint the
confirmation lifecycle had 41 arms, no completed entry, residual zero; 23 skew,
seven forecast, six budget/depth, four economic, one invalid-quote termination.
CPU 51.56% of one core, p95 loop lag 6.79ms, RSS 181.16MiB. At 19:34 live feeds
were all connected and the snapshot was two seconds old. No strategy promoted.

Next capture is 19:46:33 UTC. Active work resumed at 19:34 with a maker
post-flow hedge/unwind diagnostic and an independent strategy alternatives
review. New maker rules are to be written before a prospective second capture;
the existing 18:23 capture is exploratory only.


## Review 11: 2026-09-29 19:46:33 UTC, actively reviewed on schedule

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 187 | -249.296 | 182 | 5 |
| Cooldown | 44 | -89.542 | 42 | 2 |
| Historical median | 7 | -16.386 | 1 | 6 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Retained coverage complete, no wins. Confirmation lifecycle 50 arms, zero
entries/residual; 29 skew, nine forecast, six budget/depth, five economic,
one invalid-quote cancellation. CPU 55.27% of one core, p95 lag 13.46ms,
RSS 197.18MiB, about 899 books/s. No thresholds relaxed. Next 20:06:33 UTC.

Prospective maker study ran 19:39:04–19:46:04 after rules were frozen before
launch. Independent code audit and synthetic tests preceded outcome inspection.
64,081 frames, 23.65MB raw capture, one generation per venue, zero recorded gaps
or errors, immutable market-plan hash matches. Primary 1s policy: 828 supported
opening quotes →32 hypothetical full-flow cases →23 full hedge quotes →14
full paired exits; all 14 negative after four fees. Nine missing hedge and nine
missing exit outcomes remain unresolved, not zeros. The sole entry-positive
full-flow case lost $0.99348 conditionally after fees. No source-ahead trades
or terminal-capture censors. Controls0.5s/3s had25/4 complete paths, all negative.
Fixed-path zero-fee primary sensitivity has two positive gross quotes, max
$0.052712; none reaches ten cents or clears the reserve. No maker fill or
fee-tier-compatible latency claim is made; Standard300ms processing is omitted.

Next research: a separately bounded, strictly hedged impulse-dislocation
observer for BTC/ETH/NVDA/XAG on HL versus Core/RH, with prior-only basis
features, four-fee economic gate, confirmed source updates, original quantity,
post-delay entry, and complete exit within10s. One-leg directional speculation
was proposed but not adopted for the arbitrage mandate. Code and tests are
being prepared, no production policy replaced and no pilot launched yet.

## Review 12: 2026-09-29 20:06:33 UTC, actively reviewed on schedule

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 188 | -299.260 | 179 | 9 |
| Cooldown | 43 | -117.376 | 37 | 6 |
| Historical median | 15 | -22.819 | 0 | 15 |
| Conservative | 1 | -1.331 | 0 | 1 |
| Confirmed | 0 | 0 | 0 | 0 |

Complete retained coverage, zero wins. Baseline paired loss -$247.805 and
failed-hedge loss -$51.456; cooldown paired -$94.456 and failed -$22.920.
Median-rule attempts all failed to form a paired entry in this window; an
independent read-only fill/venue/timing audit was assigned rather than attributing
this to Python speed or relaxing a gate without evidence. Baseline entry delay
median 1.285s / p95 2.002s; exit-request-to-flat median 1.256s / p95 1.859s,
among the 179 completed paired paths. Missing failed-hedge timing is explicit.

CPU 60.05% of one core, event-loop p95 lag 12.38ms, RSS 209.29MiB, 895 books/s.
Confirmation lifecycle 70 arms, no entry/pending/residual: 46 skew, 10 forecast,
six budget/depth, six economic, two invalid-quote cancellations. This review
crosses 20:00 UTC / 4pm ET; session timing is a possible explanatory feature,
not a demonstrated cause of the increased failed hedges.

The frozen impulse pilot began 20:00:36 UTC from commit 473e0c3 and runs until
approximately 20:20:37. Main portfolio policies are unchanged. Next scheduled
review **20:26:33 UTC / 4:26 p.m. ET**; root remains active for experiments and
the next review. A lower-fee NVDA/XAG maker quote model is being implemented
for review, with explicit Lighter Standard processing delays and no launch yet.

Follow-up at 20:07:39: independent reconciliation of 4,988 retained settled
trades passed; maximum wallet residual $3.46e-11. Five exposed positions had
maximum holding age 7.78s, and the same two flat XAG records awaited funding.
[Frozen exit-trigger analysis](../reports/exit-trigger-survival/README.md)
at 20:09:07 found three retained baseline profit-triggered exits, all finally
negative; median request-to-flat 1.432s. The other four represented independent
portfolios also had no winning profit-triggered exit in their small retained
subsets. These overlapping scenarios are not independent events, and elapsed
execution time does not identify the continuous lifetime of a profitable quote.

## Review 13: 2026-09-29 20:26:33 UTC, actively reviewed on schedule

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 102 | -150.450 | 98 | 4 |
| Cooldown | 53 | -85.914 | 51 | 2 |
| Historical median | 3 | -7.483 | 0 | 3 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Complete retained coverage, zero wins. Baseline paired -$139.742, failed
-$10.708; cooldown paired -$79.622, failed -$6.293. Baseline paired entry
median 1.269s / p95 1.961s; exit-request-to-flat median 1.117s / p95 1.920s.
CPU 57.52% of one core, p95 event-loop lag 15.82ms, RSS 209.29MiB, 827 books/s.
Confirmation lifecycle 77 arms, zero entry/pending/residual: 50 skew, 11
forecast, seven budget/depth, seven economic, two invalid-quote cancellations.

The impulse study is complete: one NVDA/Core arm failed its confirmation
hurdle, zero selected entries. Its 20-minute window is uninformative about
conditional P&L or delay differences; no threshold was changed afterward.
The audited NVDA/XAG maker capture is running from verified 20:22:56 start,
scheduled to stop 20:29:57. Its first launcher attempt failed before collection
and is explicitly recorded. An isolated HL-first versus simultaneous paper
trial is under entry/accounting/storage review; no production policy changed.
Next scheduled review **20:46:33 UTC / 4:46 p.m. ET**.

## Review 14: 2026-09-29 20:46:33 UTC, actively reviewed on schedule

| Standard-fee policy | Closes | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 93 | -94.970 | 91 | 2 |
| Cooldown | 44 | -43.457 | 43 | 1 |
| Historical median | 1 | -4.392 | 0 | 1 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Complete retained coverage, zero wins. Historical median also had one zero-fill
abort. Baseline paired -$92.235 and failed -$2.736; cooldown paired -$42.455,
failed -$1.002. Baseline paired-entry median 1.266s/p95 1.893s;
exit-request-to-flat median 1.143s/p95 1.668s. CPU 51.76% one core, p95 loop
lag 7.87ms, RSS 212.28MiB, 692 books/s. Confirmation lifecycle 81 arms, zero
entries/pending/residual: 53 skew, 12 forecast, seven budget/depth, seven
economic, two invalid-quote cancellations. No replacement policy promoted.

The frozen HL-first sequencing trial remains active until 21:00:39. Its
WebSocket-only convergence selector had no admitted candidates at the last
interim read; that is not a profitability comparison. An exploratory smaller-
size replay of the stopped NVDA/XAG capture is under final review. A newly
noticed documented HL fast-L2 option is being checked separately, without
changing the running production or experiment subscriptions.

The user explicitly redirected emphasis to a systematic current strategy
literature review. Root acknowledged that existing empirical strategy tests
were not a sufficient SOTA review. Primary-source work now covers maker/hedge
inventory policies, executable residual/optimal stopping, and carry/capital
allocation. Next scheduled review **21:06:33 UTC / 5:06 p.m. ET**.

## Review 15: 2026-09-29 21:06:33 UTC, actively reviewed on schedule

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 90 | -103.507 | 89 | 1 |
| Cooldown | 55 | -151.204 | 52 | 3 |
| Historical median | 4 | -14.818 | 0 | 4 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Complete retained window coverage, zero wins. Baseline includes one estimated
outcome (-$0.9933); 89 exact outcomes total -$102.5133. Its paired outcomes
total -$102.5449, failed hedge -$0.9618. Cooldown paired -$138.1064, failures
-$13.0975; six SHEIN outcomes contributed -$85.9412. Historical median's
four failures were HL price-limit rejections. Baseline paired entry median
1.287s/p95 2.205s; exit request to flat median 1.151s/p95 2.116s.
CPU 56.07% one core, loop lag p95 14.17ms, RSS 217.37MiB, 705 books/s.
Confirmation lifecycle: 85 arms, zero entry/pending/residual; 57 skew,
12 forecast, seven depth/budget, seven economics, two invalid cancellations.

The stopped HL-first trial had one GRAM candidate: simultaneous entry lost
$0.93119 after the HL hedge rejected; HL-first aborted with no fill or cash.
That is one avoided failure, with no successful paired comparison. Full-book
reconstruction improves RH freshness coverage to 78/83 NVDA and 80/83 XAG
anchors, versus 38/83 and 32/83 ticker anchors, without implying fills.
User specified $100 as the next experiment's approximate minimum and $1,000
as already small: next sizes are $100/$250/$500/$1,000, primary $1,000.
The new RH maker experiment is being prepared; no production policy changed.
Next scheduled review **21:26:33 UTC / 5:26 p.m. ET**.

## Review 16: generated 2026-09-29 21:26:33 UTC, read at 21:28 UTC

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 94 | -115.725 | 91 | 3 |
| Cooldown | 54 | -78.589 | 47 | 7 |
| Historical median | 3 | -1.260 | 0 | 3 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

All retained outcomes exact under the paper model; complete window coverage.
Baseline paired -$107.5008, failures -$8.2239; cooldown paired -$57.5675,
failures -$21.0217. Historical median had one winning **failed hedge**, not
a successful paired trade. The baseline and cooldown had no wins. Baseline
paired entry median 1.209s/p95 1.748s; exit request to flat median 1.136s/
p95 1.723s. CPU 60.36% of one core, loop lag p95 11.91ms, RSS 217.48MiB,
1,001 books/s. Confirmation: 96 arms, no entry/pending/residual; 62 skew,
18 forecast, seven depth/budget, seven economics, two invalid cancellations.

The public RH maker capture started at 21:21:32, with frozen method and
collector commit 9054b25. Primary $1,000, sensitivities $100/$250/$500;
BTC/ETH/NVDA/XAG, 30-minute calibration then 20-minute holdout, 384 MB raw
plus 128 MB derived maximum. Holdout begins about 21:51:32; capture stops
about 22:11:32. Lifecycle/replay code is being tested before the holdout.
No outcomes from this capture have been used to change its policy.
Next scheduled review **21:46:33 UTC / 5:46 p.m. ET**.

## Review 17: 2026-09-29 21:46:33 UTC, actively reviewed on schedule

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 91 | -97.583 | 91 | 0 |
| Cooldown | 46 | -48.763 | 46 | 0 |
| Historical median | 2 | -2.783 | 0 | 2 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

All retained outcomes exact under the paper model, with full window coverage
and zero wins. Median gate also had one zero-fill abort. Baseline lost
$27.7722 before $23.8670 trading fees, $45.9409 extra reserve, and $0.0033
capital: reducing costs alone does not repair those realized price paths.
Baseline paired entry median 1.261s/p95 1.745s; exit request to flat median
1.106s/p95 1.977s. CPU 66.06% of one core, p95 loop lag 12.15ms, RSS
217.11MiB, 578 books/s; all four feeds connected. Confirmation 99 arms,
zero entries/pending/residual: 64 skew, 19 forecast, seven depth/budget,
seven economics, two invalid cancellations. No replacement policy promoted.

RH maker replay implementation was frozen at 21:38:24 in **38950ef**,
before the 21:51:32 holdout, with 46 focused tests passing. The capture
continues toward its planned 22:11:32 stop; its outcomes remain unread.
Separate stopped-archive research compares Core versus HL hedge costs and
preregisters a mirrored RH maker-sell follow-up on new data. Current study
stays $100/$250/$500/$1,000, primary $1,000, buy-side only.
Next scheduled review **22:06:33 UTC / 6:06 p.m. ET**.

## Review 18: 2026-09-29 22:06:33 UTC, actively reviewed on schedule

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 93 | -106.073 | 91 | 2 |
| Cooldown | 46 | -57.244 | 46 | 0 |
| Historical median | 3 | -4.512 | 0 | 3 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Full retained window coverage, zero wins. Baseline comprises 92 exact
paper outcomes (-$104.5495) and one estimated outcome (-$1.5232); paired
-$104.1829, failed hedges -$1.8898. Cooldown outcomes all exact and paired.
Historical median also had one zero-fill abort. Baseline paired entry
median 1.205s/p95 1.771s; exit request to flat median 1.155s/p95 1.773s.
CPU 55.39% of one core, p95 loop lag 10.19ms, RSS 226.68MiB, 571 books/s;
all four feeds connected. Confirmation 105 arms, no entry/pending/residual:
67 skew, 20 forecast, eight depth/budget, eight economic, two invalid.
No replacement policy promoted.

Original RH maker holdout continues to 22:11:32 with frozen source hashes
and unread outcomes. Independent synthetic review discovered a retired-
quote late-print accounting defect, recorded before readout in **f313525**.
A separate raw/audit adjudicator will flag affected original results;
future bid/ask code now retains retired-quote evidence and marks execution
uncertainty explicitly. Historical quote-distance tests found no qualifying
flow at 5/10/20 bp behind best in their complete ten-second windows, and
separate nontrading-cost research distinguishes the 5 bp stress allowance
from published trading fees. Next review **22:26:33 UTC / 6:26 p.m. ET**.

## Review 19: 2026-09-29 22:26:33 UTC, actively reviewed on schedule

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 91 | -109.885 | 91 | 0 |
| Cooldown | 32 | -45.076 | 32 | 0 |
| Historical median | 1 | -4.772 | 0 | 1 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

Full retained completion coverage, all exact paper outcomes, zero wins.
Baseline also had one zero-fill abort. Its fees were $32.6752, reserve
$45.4484, capital $0.00324 and funding zero: approximately **-$31.7582
before these costs**. AVAX/Core contributed -$44.5980 across 22 closes;
CRCL/Core -$29.1932 across 32. The one historical-median failure was ZRO,
with the HL hedge rejected at its price limit. No policy promoted.

Baseline paired entry median 1.210s/p95 1.787s; exit request to flat
median 1.236s/p95 1.900s. CPU 67.48% of one core, p95 loop lag 18.29ms,
RSS 237.75MiB, 562 books/s, all four feeds connected, 113 eligible pairs.
Confirmation 106 arms, no entry/pending/residual: 68 skew, 20 forecast,
eight depth/budget, eight economic, two invalid terminal reasons.

The RH maker capture stopped normally at 22:11:32. Original replay remains
running; a separately labeled immutable-book cache variant avoids repeated
full-depth parsing. Synthetic financial/audit equivalence passes; the full
original/cached comparison is pending. Neither replay's financial results
were available at this review. See [performance record](rh-maker-replay-performance.md).
Sizes remain $100/$250/$500/$1,000, primary $1,000. Next review
**22:46:33 UTC / 6:46 p.m. ET**.

## Review 20: 2026-09-29 22:46:33 UTC, actively reviewed on schedule

| Standard-fee policy | Completed | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Fresh baseline | 92 | -117.466 | 90 | 2 |
| Cooldown | 32 | -76.173 | 30 | 2 |
| Historical median | 1 | +0.433 | 0 | 1 |
| Conservative | 0 | 0 | 0 | 0 |
| Confirmed | 0 | 0 | 0 | 0 |

The lone winning historical-median close was a failed hedge, not a paired
arbitrage success; that policy also had two aborts. Baseline paired closes
lost $110.2821 and failed hedges $7.1838. Cooldown paired lost $65.1552 and
failed hedges $11.0176. Full retained coverage, all exact paper outcomes.
No replacement strategy promoted.

At 22:45:28 the collector and review loop were checkpointed and restarted
to retain compact exit-request observations. Existing ledgers, positions,
targets and fees were preserved; forecast histories restart cold. The review
deadline stayed 22:46:33. New PIDs: collector 2765644, review loop 2765645.
The health snapshot therefore measures the recently restarted process:
47.64% of one core, 6.66ms p95 loop lag, 95.34MiB RSS, 518 books/s,
114 pairs, four connected feeds. It is not a before/after speed benchmark.
Baseline paired entry median 1.302s/p95 1.878s; exit-request-to-flat median
1.375s/p95 3.040s across this interval, which spans the restart.

The new exit-price metric has four valid baseline observations: three
unchanged and one worse by $0.260744. Their request-time net marks already
totaled -$3.540519; final net was -$3.801247. Of the remaining 86 paired
closes, 85 predate instrumentation and one has unavailable request prices.
Three of the four usable observations are CRCL and one MSFT; this is tiny
and concentrated. See [frozen evidence](../reports/unwind-instrumentation/first-review.json)
and [interpretation](unwind-attribution.md). Cooldown has one unchanged
observed close and 29 legacy missing; other policies have no paired sample.

RH maker cached replay finished: primary adaptive branches have no attributed
fills, Premium fixed-best crypto controls have losing completed contributions,
all branch totals remain unknown. Independent late-flow test found no flags;
full original/cached equivalence remains pending. The canonical AMM size
screen also stopped; four correlated fee-only positive entry gaps remain
below $0.10, off the HL lot grid, and negative after the modeled reserve.
Next scheduled review **23:06:33 UTC / 7:06 p.m. ET**.


## Review 21: 2026-09-29 23:06:33 UTC

Actively read at 23:06 UTC. Window 22:46:31.760–23:06:31.776;
next due **23:26:33 UTC / 7:26 p.m. Eastern**. All completion coverage complete.

| Policy | Completions | Net USD | Paired | Failed hedges |
|---|---:|---:|---:|---:|
| Baseline | 91 | −102.0626 | 89 / −95.6696 | 2 / −6.3929 |
| Cooldown | 14 | −27.9128 | 11 / −13.1512 | 3 / −14.7616 |
| Historical median | 5 | −8.4011 | 0 | 5 / −8.4011 |
| Conservative / confirmed | 0 | 0 | 0 | 0 |

Baseline includes 90 exact-funding completions and one estimated-funding
completion (−$0.9398); ledger closed_trades delta alone is 90 while completed
count is 91. No baseline/cooldown winners. Median has one winning failed
hedge, which is not a successful paired arbitrage, and four aborts.

New durable exit observations: baseline 86 usable of 89 paired, three missing
request prices. Price-only request-to-actual deterioration sum **+$0.057486**,
median zero, p95 $0.1664: 19 worsened, 24 improved, 43 unchanged. Cooldown
11/11 observed, sum **−$0.254297** (net improvement): two worse, five better,
four unchanged. Missing prices are unknown. Offsetting changes conceal tails;
these measurements do not identify a causal latency counterfactual or entry
latency effect. They support strategy economics as the main follow-up.

Baseline paired entry median 1.2531 s, p95 1.8852; exit-request-to-flat
median 1.1505 s, p95 1.7482. All four feeds connected, 114 pairs, CPU 55.68%
of one core, p95 event-loop lag 7.56 ms, resident memory 158.12 MiB,
679.7 book events/s. Health is a separate snapshot from the ledger checkpoint.
Confirmed lifecycle: 121 arms, zero entries/pending/accounting residual;
75 skew, 20 forecast, 15 depth, nine economic, two invalid terminations.

No replacement policy promoted. Strategy research and size-specific passive
exit hypotheses are recorded in `research/unwind-strategy-decision.md` and
`research/strategy-inventory-followup.md`. Preserved full review:
`reports/unwind-instrumentation/review21.json`.

## Historical catchup: 23:06–02:06 UTC, reviewed 2026-09-30 02:16 UTC

Ten scheduled checkpoints from 23:06 through 02:06 have complete retained
completion coverage. [Bounded evidence](../reports/live-review-catchup/evidence.json)
records each source report hash, policy count, ledger delta, exit diagnostic, and
health snapshot. Rows below are separate, correlated paper portfolios; their
dollar values should not be added together.

| Window ending UTC | Baseline closes / net | Cooldown closes / net | Baseline cumulative entries | Cooldown cumulative entries |
|---|---:|---:|---:|---:|
| 23:06 | 91 / −$102.06 | 14 / −$27.91 | 4,570 | 1,081 |
| 23:26 | 104 / −$179.44 | 47 / −$86.75 | 4,674 | 1,127 |
| 23:46 | 124 / −$170.40 | 41 / −$40.04 | 4,805 | 1,169 |
| 00:06 | 108 / −$177.60 | 43 / −$77.92 | 4,913 | 1,211 |
| 00:26 | 22 / −$30.55 | 58 / −$112.79 | 4,934 | 1,270 |
| 00:46 | 0 / $0 | 58 / −$112.04 | 4,934 | 1,327 |
| 01:06 | 0 / $0 | 58 / −$109.45 | 4,934 | 1,385 |
| 01:26 | 0 / $0 | 49 / −$96.16 | 4,934 | 1,435 |
| 01:46 | 0 / $0 | 53 / −$103.13 | 4,934 | 1,487 |
| 02:06 | 0 / $0 | 63 / −$118.46 | 4,934 | 1,552 |

The baseline's inactivity is **capital exhaustion on Hyperliquid**, not a
missing feed or an open-position queue. Its last retained entry began at
00:10:50 UTC; its entry counter stays at 4,934 thereafter while the policy's
allowed counter rises from 422,786 at 00:26 to 546,795 at 02:06. These are
repeated policy checks, not distinct trade opportunities. At the
02:16 snapshot it has no open, pending-entry, pending-exit, or funding position,
but only **$1,000.3345 in its HL wallet**. Every $1,000 new position requires
at least $1,000.50 on each venue under the frozen 100% margin and 5 bp reserve
rule, before fee reserves. Original Standard ($1,000.0614 HL) and Plus
($1,000.1954 HL) are also below this necessary floor. Premium's Lighter wallet
is $1,000.0789, preventing Lighter routes, while other routes still produced
ten losing completions in the final window. Cooldown retains $3,414.35 on HL
and continues entering. The live snapshot's global capital-rejection counter
exceeds 1.5 million; it is **not** a per-strategy count. All four feeds stayed
connected through the ten reviews, and 02:06 p95 event-loop lag was 14.9 ms
at 891 books/s. Keep the exhausted ledgers intact; a new notional or funding
allocation would be a separately named experiment.

Exit-request price evidence does not turn the late cooldown losses into an
unwind-latency-only explanation. In the five windows ending 00:46–02:06,
cooldown had 267 valid paired request-to-actual comparisons and six missing.
Actual short buyback minus long sale **improved by $6.3436 in aggregate**
relative to request-time executable liability, while its completed net was
−$539.23; 84 observations worsened and 108 improved. The final 02:06 window
had 59 valid of 60 paired closes, price-only movement −$0.6380, median
request-to-flat 1.212 s and p95 1.741 s, yet 63 completions lost $118.46.
Earlier tails were real: the 23:46 baseline window had +$29.1733 adverse
price-only movement across 82 valid paired closes (six missing), and Premium
had +$150.6728 across 60 valid closes (one missing). These are request-to-fill
comparisons, not causal latency estimates; fees, initial entry movement and
holding-period spread changes remain distinct. Windows with no paired closes
have **no exit-price observation**, rather than zero deterioration.

The unchanged frozen original RH maker replay was still running at about one
full CPU core after 3 h 58 m. A read-only process check found its input gzip
offset at 12,288,000 of 41,368,405 compressed bytes (29.7%) and its audit
output at zero bytes; it had not produced a finished analysis. Compressed byte
offset is not event-time or remaining compute work. A naive byte-linear
projection from 3 h 58 m elapsed is about **9.4 more hours**, but is too
uncertain for a completion deadline. The completed cached variant remains
separately labeled; full
original-versus-cached equivalence waits for the original to finish. No process
was stopped or restarted.


## Review 31: 2026-09-30 02:26:33 UTC

Actively read at 02:28 UTC. Completion coverage complete. Baseline remains
flat and capital-limited, with zero new completions. Cooldown completed 84
trades for **−$173.2020** (83 paired −$170.2735, one failed hedge −$2.9286),
zero wins. Historical-median policy completed two failed hedges for −$1.8367;
no paired trade. No strategy was promoted or existing ledger replenished.

Cooldown's 81 observed exit-price comparisons improved **$2.650557** in
aggregate (29 worse, 32 better, 20 unchanged); two paired comparisons are
missing. Median change zero, p95 adverse $0.3846. This price-only diagnostic
still does not explain the aggregate net loss. Health: 113 pairs, 1,038.4
book events/s, CPU 77.83% of one core, p95 loop lag 12.84 ms, RSS 261.51 MiB.
Next report due **02:46:33 UTC / 10:46 p.m. ET**. Preserved full review:
`reports/live-review-catchup/review-20260930T022633Z.json`.

## Review 32: 2026-09-30 02:46:33 UTC

Actively read on schedule; preserved as
`reports/live-review-catchup/review-20260930T024633Z.json`. Completion coverage
is complete. Baseline/Standard/Plus have no new closes, retaining their
capital constraints. Cooldown has 59 paired closes, zero wins, net
**−$84.9446**; Premium has two paired closes, zero wins, **−$3.3860**.
The cooldown accounting separates $21.2394 actual modeled fees,
$29.4624 other costs (the configured reserve), and $0.0021 capital. Adding
these back implies approximately **−$34.2407 gross price P&L**; removing the
reserve alone would still leave **−$55.4821**. The reserve is not the sole
reason this taker strategy loses.

Cooldown exit-price movement improved $0.531448 in aggregate across 57
valid comparisons (19 worse, 22 better, 16 unchanged); two are missing.
Median price movement zero, p95 adverse $0.220616. Median request-to-flat
1.179 s, p95 1.811 s across all 59 paired closes. This does not imply faster
execution never helps, but the aggregate loss was already largely present
before the final execution delay. RH XAG accounts for 16 closes/−$16.4697;
RH GOOGL 15/−$14.8102. Those routes motivate the separate passive-spread test,
not promotion of the current entries.

Health: all four feeds connected, 112 pairs, 647.5 books/s, CPU52.98% of one
core, p95 loop lag21.92 ms, RSS262.79 MiB. One cooldown paired position is
open at the snapshot; old Standard/Premium funding-pending records remain
preserved. Next review **03:06:33 UTC**. Passive v1 continues collecting;
its frozen source and production rules are unchanged.

## Review 33: 2026-09-30 03:06:33 UTC

Actively read at 03:07 UTC; full review preserved in
`reports/live-review-catchup/review-20260930T030633Z.json`. Completion coverage
complete. Cooldown closed 50 paired trades for **−$54.6757**, zero wins.
Premium recorded two failed hedges for **−$5.9806**, no paired completion.
Baseline/Standard/Plus remain without new completions; no ledger was topped up.

Cooldown's exit-price comparison is available for 48 of the 50 paired closes:
11 worse, 18 better, 19 unchanged, aggregate deterioration **+$0.134608**,
p95 adverse $0.087189. Two request-price observations are missing. The median
is numerically zero (floating-point residual about −1e−13). This remains a
small component of the interval's net loss, with offsetting observations.

Health: 112 pairs, CPU55.75% of one core, p95 loop lag13.47 ms, RSS264.11 MiB,
716.2 books/s. Next review **03:26:33 UTC**. New capture3045038 continues;
one-shot supervisor3161224 waits for its final manifest and will perform one
bounded frozen replay. The same-callback retirement correction is a separate
implementation variant under preparation, never an unlabeled replacement.

## Review 34: 2026-09-30 03:26:33 UTC

Actively read on schedule; preserved in
`reports/live-review-catchup/review-20260930T032633Z.json`. Completion coverage
is complete. Cooldown closed **58 trades, −$72.7472**, zero wins: 56 paired
closes contributed −$67.8478 and two failed hedges −$4.8994. Convergence
recorded four failed hedges for **−$5.3098**, zero paired closes or wins.
Premium had one zero-fill abort and no completion. Other strategies had no
new completion; baseline/Standard/Plus retain their capital constraints.

Cooldown's modeled fees were $17.2399, stress allowance $28.9624, and capital
$0.0020. Removing the allowance alone leaves approximately −$43.7848.
Exit-price movement improved the 54 observed paired comparisons by
**$3.933369** in aggregate (18 worse, 16 better, 20 unchanged; two missing).
Median movement zero, p95 adverse $0.099502. Median request-to-flat was
1.171 s, p95 2.095 s across the 56 paired closes. These are price diagnostics,
not a causal estimate of what a different execution policy would earn.

Health: all four feeds connected, 112 pairs, 821.7 book events/s, CPU51.52%
of one core, p95 loop lag9.66 ms, RSS263.59 MiB. The snapshot has no filled
open exposure and three flat funding-pending records. Next review
**03:46:33 UTC**. The passive capture remains in holdout; no holdout outcome
has been read or used to alter its frozen sources.

## Review 35: 2026-09-30 03:46:33 UTC

Actively read on schedule and preserved in
`reports/live-review-catchup/review-20260930T034633Z.json`. Complete coverage.
The twenty-minute interval spans the 03:36 display-accounting rollout:
cooldown had **62 paired closes, −$89.5273**, zero wins. Convergence had
eight closes for **−$8.8218** (seven failed hedges −$8.1785 and one paired
−$0.6433). Premium had three failed hedges for **−$5.8074**. No other new
completions or wins. Ledger and review baselines continued through restart.

Cooldown's modeled fees were $24.2655, stress allowance $30.9589, capital
$0.0022. Its 59 observed exit-price comparisons improved $0.716057 in aggregate
(20 worse, 23 better, 16 unchanged; three missing), with median zero and
p95 adverse $0.224272. Request-to-flat median 1.202 s, p95 1.777 s. The one
paired convergence close had $0.05157 adverse exit-price movement.

The separate current-version snapshot at **03:46:58 UTC**, saved in
`reports/live-review-catchup/current-epoch-at-review35.json`, starts at the
03:36:13 rollout: cooldown34 closes/−$51.0719 and convergence1/−$0.6433;
all other current closed totals zero. Three legacy funding obligations remain
carryover and their later settlements cannot enter these totals. This is a
different interval from the full scheduled review, not a replacement for it.

Health: all four feeds connected,112 pairs,CPU62.01% of one core, p95 loop lag
9.78 ms,RSS153.04 MiB,911.4 books/s. Both frozen passive replays remain active.
Next review **04:06:33 UTC**. No strategy was promoted and no capital reset.

## Review 36: 2026-09-30 04:06:33 UTC

Actively read and archived in
`reports/live-review-catchup/review-20260930T040633Z.json`; all completion
coverage is complete. Cooldown completed **69 trades for −$121.7652**,
zero wins: 66 paired contributed −$112.7713 and three failed hedges
−$8.9939. Of those outcomes, 68 are exact (−$118.2410) and one remains an
estimated settlement (−$3.5242). Convergence had three failed hedges for
**−$5.4494**, zero wins. All other strategies had no new completion.

Cooldown's modeled fees were $26.7715, stress $34.4551, capital $0.0024,
and recorded funding +$0.0812. Removing the stress alone still leaves
−$87.3102. Observed exit-price movement improved $0.855523 in aggregate:
24 worse, 20 better, 18 unchanged, four missing; median zero and p95 adverse
$0.116537. Request-to-flat median 1.130 s, p95 1.775 s for 66 paired closes.
Price movement after the exit request does not explain the overall loss.

The separately saved current-version snapshot begins at 03:36:13 UTC and
shows cooldown 101 exact plus one estimated completion for −$169.0843,
and convergence 4 exact completions for −$6.0927; zero wins. Three legacy
funding-pending records remain outside this version's result. This snapshot
and the scheduled twenty-minute interval have different start/end times.

Health: four connected feeds, 112 pairs, CPU 51.22% of one core, p95 loop lag
8.30 ms, RSS 178.85 MiB, 758.4 books/s. The scheduled snapshot has one active
cooldown position and three flat funding-pending records. Both passive
replays finished; their [readout](../reports/rh-passive-exit-v1-restart/readout.md)
has 29 known negative portfolios and 99 unknown. Next review **04:26:33 UTC**.
No strategy was promoted or capital replenished.


## Review 37: 2026-09-30 04:26:33 UTC

Archived in `reports/live-review-catchup/review-20260930T042633Z.json`;
all completion coverage is complete. Cooldown completed **65 trades for
−$99.0395**, all exact, zero wins: 61 paired −$89.3749 and four failed hedges
−$9.6645. Premium completed **18 for −$27.3569**, all exact, zero wins:
17 paired −$25.6815 and one failed hedge −$1.6754. Other strategies had
no new completions. These independent strategy ledgers are not summed.

Cooldown fees were $23.9488, stress $32.4535, capital $0.0022, funding zero;
removing stress still leaves −$66.5860. Its 57 observed exit-price comparisons
improved $1.220470 in aggregate (12 worse, 19 better, 26 unchanged, four
missing), median approximately zero and p95 adverse $0.183210. Request-to-flat
median 1.335 s, p95 2.062 s. Premium fees were $15.6372, stress $8.9889,
capital $0.0006; observed exit-price movement worsened $0.006934 across
16 observations (one worse, 15 unchanged, one missing).

The separate current-version snapshot at 04:27:09 UTC has cooldown 167 exact
plus one estimated completion for −$269.1555, Premium 18/−$27.3569 and
convergence 4/−$6.0927; zero wins. It is saved in
`reports/live-review-catchup/current-epoch-at-review37.json`. Version remains
`e3e83cda71a6`, begun 03:36:13 UTC. Three legacy funding obligations remain
outside its results. Snapshot and scheduled review cover different intervals.

Health: four connected feeds, 112 pairs, CPU 46.23% of one core, p95 loop lag
10.50 ms, RSS 188.93 MiB, 558.6 books/s. The scheduled snapshot has one active
cooldown position and three flat funding-pending records. Both ACK replays
finished without errors and produced no positive complete portfolio. Next
review **04:46:33 UTC**. No strategy promoted or capital replenished.


## Review 38: 2026-09-30 04:46:33 UTC

Actively read and archived in
`reports/live-review-catchup/review-20260930T044633Z.json`. Complete coverage
for every strategy. Cooldown **59 exact completions, −$73.9285**, zero wins:
58 paired −$71.7132 and one failed hedge −$2.2153. Premium **8 exact,
−$16.0973**, zero wins: two paired −$3.1405 and six failed hedges −$12.9568.
Convergence had **six failed hedges, −$6.0716**, all exact and zero wins.
All other strategies had no new completion. These independent ledgers are
not summed into a portfolio.

Cooldown fees were $19.1792, stress $29.4557, capital $0.0021, funding zero;
removing stress leaves −$44.4728. Its 54 observed exit-price comparisons
worsened $0.564518 in aggregate (16 worse, 16 better, 22 unchanged, four missing),
median zero and p95 adverse $0.122481. Request-to-flat median 1.122 s,
p95 2.356 s. Premium's two observed paired exit comparisons improved $0.193340
in aggregate. Six convergence failed hedges were all LIT routes, four via
Core and two via RH; recorded entry rejections were five HL and one Core
price-limit failures. Failed hedges do not supply paired exit-price evidence.

The separate version snapshot at 04:46:52 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review38.json`: cooldown 225 exact
plus one estimated completion, −$342.1200; Premium 26/−$43.4542;
convergence 10/−$12.1643; zero wins. Version remains `e3e83cda71a6`, begun
03:36:13 UTC; three legacy funding obligations remain carryover.

Health: four feeds connected, 111 pairs, CPU 48.92% of one core, p95 loop lag
8.54 ms, RSS 201.05 MiB, 613.0 books/s. No active filled position at the scheduled
snapshot; three flat funding-pending records. Next review **05:06:33 UTC**.
The single-scan offline spread-feasibility diagnostic is under review; no new
raw capture, strategy promotion or capital replenishment.


## Review 39: 2026-09-30 05:06:33 UTC

Read at 05:07 UTC and archived in
`reports/live-review-catchup/review-20260930T050633Z.json`; all completion
coverage is complete. Cooldown completed **40 trades for −$54.1946**,
zero wins: 38 paired −$51.3155 and two failed hedges −$2.8791. Of these,
39 settlements are exact (−$52.0611), one estimated (−$2.1335).
Convergence had two failed hedges for **−$2.6386**, and Premium two failed
hedges for **−$3.4927**, all exact and zero wins. Other strategies had
no new completions. Independent ledgers are not summed.

Cooldown fees were $12.6799, stress $19.9733, capital $0.0014, recorded
funding +$0.3101. Removing stress still leaves −$34.2214. Its 35 observed
paired exit-price comparisons worsened $0.230600 in aggregate (eight worse,
13 better, 14 unchanged, three missing), median zero and p95 adverse $0.587166.
Request-to-flat median 1.222 s, p95 2.587 s over 38 paired closes.

The separate current-version snapshot at 05:07:06 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review39.json`: cooldown 264 exact
plus two estimated completions for −$396.3592; Premium 28/−$46.9469;
convergence 12/−$14.8029; zero wins. Version remains `e3e83cda71a6`, begun
03:36:13 UTC. Three legacy funding obligations remain outside these totals.

Health: four connected feeds, 111 pairs, CPU 46.59% of one core, p95 loop lag
11.89 ms, RSS 215.87 MiB, 634.3 books/s. One active cooldown position and
three flat funding-pending records at the scheduled snapshot. Next review
**05:26:33 UTC**. The completed fixed-anchor RH-maker diagnostic found no
positive stressed static margin; reverse-route derived bounds are under
review. No new raw capture, promotion or capital reset.

### Interim inspection: correlated LIT rescue gains, 05:23 UTC

A read-only, bounded query found five current-version positive records, all
settled around 05:22:05 UTC and all `entry_failure` exits. The
[preserved records](../reports/live-review-catchup/current-version-positive-trades-20260930T0523Z.json)
show HL rejecting every long leg at its price limit; the Core or RH short
then gained before emergency buyback. Cooldown and conservative each show
+$2.319771 on identical Core fills; convergence shows +$3.317596 on Core
and +$2.709510 on RH; Premium shows +$2.297271 on RH after its fees.
These are correlated views of one market episode, not five independent
successes or paired arbitrage cycles. Their gains remain in each original
strategy ledger alongside all failed-hedge losses. They do not satisfy the
research success threshold or justify intentionally taking unhedged risk.


## Review 40: 2026-09-30 05:26:33 UTC

Read at 05:26 UTC and archived in
`reports/live-review-catchup/review-20260930T052633Z.json`. Completion coverage
is complete throughout. Cooldown has **44 exact completions, −$48.0900**:
42 paired −$48.3769 with zero wins and two failed hedges +$0.2869 with one
win. Premium has **five exact, −$7.7485**: one paired −$1.5744, four failed
hedges −$6.1741 including one win. Convergence has **six failed hedges,
+$2.0888**, including two wins; conservative has **one failed hedge,
+$2.3198**. All wins belong to the correlated LIT rescue episode documented
above. Other strategies have no new completion. These ledgers are not summed.

Cooldown fees were $11.5461, stress $21.9683, capital $0.0015 and funding
zero; removing stress still leaves −$26.1217. Its 42 paired exit-price
observations worsened $0.226043 in aggregate (10 worse, 18 better, 14
unchanged), median approximately zero and p95 adverse $0.112340.
Request-to-flat median 1.276 s, p95 1.864 s. Premium's only paired exit-price
comparison was effectively unchanged. Convergence's six failed hedges all
recorded HL price-limit rejection.

The separate current-version snapshot is saved in
`reports/live-review-catchup/current-epoch-at-review40.json`: cooldown 308 exact
plus two estimated completions for −$444.3544 (one win); Premium 33/−$54.6954
(one win); convergence 18/−$12.7141 (two wins); conservative 1/+$2.3198.
Version remains `e3e83cda71a6`, begun 03:36:13 UTC. Three legacy funding
obligations remain outside those totals. Its one active cooldown position
is additional to closed net; the earlier scheduled snapshot was flat.

Health: four connected feeds, 111 pairs, CPU 51.34% of one core, p95 loop lag
9.13 ms, RSS 221.22 MiB, 699.4 books/s. Next review **05:46:33 UTC**.
Both completed static-route diagnostics remain nonpositive; the separately
reviewed delayed quote helper is being implemented. No strategy promotion,
new raw capture or capital reset.


## Review 41: 2026-09-30 05:46:33 UTC

Read and archived at 05:46 UTC in
`reports/live-review-catchup/review-20260930T054633Z.json`. All coverage is
complete. Cooldown completed **39 exact paired trades, −$42.9572**, zero
wins. Premium completed **two exact, −$5.4492** (one paired −$1.7903 and
one failed hedge −$3.6589), zero wins. Convergence completed **two exact
failed hedges, −$3.5168**, zero wins, both HL price-limit rejection. Other
strategies had no new completion. Separate ledgers are not summed.

Cooldown fees were $7.9709, stress $19.4745, capital $0.0014, funding zero;
removing stress leaves −$23.4827. Its 39 exit-price observations worsened
$0.405347 in aggregate (12 worse, 14 better, 13 unchanged), median zero,
p95 adverse $0.172976. Request-to-flat median 1.172 s, p95 2.279 s.
Premium's one paired exit-price comparison improved $0.013510.

The separate current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review41.json` records cooldown
347 exact plus two estimated completions, −$487.3308 (one win); Premium
35/−$60.1446 (one win); convergence 20/−$16.2309 (two wins); conservative
1/+$2.3198. Existing wins remain the correlated LIT failed-hedge episode.
Version `e3e83cda71a6` and three legacy funding obligations are unchanged.
The later snapshot has one cooldown and one Premium position; their marks
are separate from closed net. The scheduled snapshot was flat.

Health: four connected feeds, 111 pairs, CPU 52.95% of one core, p95 loop
lag 11.86 ms, RSS 229.61 MiB, 814.5 books/s. Next review **06:06:33 UTC**.
The delayed quote helper has 31 passing synthetic tests and awaits final
independent signoff/source freeze. No new raw capture, promotion or reset.


## Review 42: 2026-09-30 06:06:33 UTC

Read at 06:07 UTC and archived in
`reports/live-review-catchup/review-20260930T060633Z.json`. Completion coverage
is complete. Cooldown has **41 exact paired completions, −$49.7978**, zero
wins. Premium has **10 exact, −$16.3885**: five paired −$8.1426 and five
failed hedges −$8.2459, zero wins. Convergence has **10 exact failed hedges,
−$7.8872**, zero wins, plus one aborted attempt. Its combined rejection
counts include 11 HL and one Core price-limit rejection. Other strategies
have no new completions; separate ledgers are not summed.

Cooldown fees were $11.4528, stress $20.4737, capital $0.0015, funding zero;
removing stress leaves −$29.3241. Its 37 observed exit-price comparisons
worsened $0.724761 in aggregate (12 worse, 15 better, 10 unchanged; four
missing request prices), median zero, p95 adverse $0.446156. Request-to-flat
median 1.292 s and p95 2.167 s over all 41 paired closes. Premium's five
observations worsened $0.074024 in aggregate.

The separate current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review42.json` records cooldown
388 exact plus two estimated completions, −$537.1670 (one win); Premium
45/−$76.5331 (one win); convergence 30/−$24.1182 (two wins); conservative
1/+$2.3198. No active positions in either snapshot; three legacy funding
obligations remain outside these current-version totals. Version remains
`e3e83cda71a6`; all wins remain the same prior LIT rescue episode.

Health: four connected feeds, 111 pairs, CPU 53.36% of one core, p95 loop lag
9.93 ms, RSS 236.92 MiB, 768.9 books/s. Next review **06:26:33 UTC**.
The first delayed quote scan reached its terminal checks but failed the
outcome-file sublimit before publication; no economic conclusion is drawn.
Its preserved failure and separately reviewed resource amendment are in
`16be20f`. No new raw capture, promotion or capital reset.


## Review 43: 2026-09-30 06:26:33 UTC

Read at 06:28 UTC; archived in
`reports/live-review-catchup/review-20260930T062633Z.json`. All completion
coverage is complete. Cooldown: **26 exact paired completions, −$44.7048**,
zero wins. Premium: **nine exact, −$13.5966**, four paired −$6.5269 and
five failed hedges −$7.0697, zero wins, plus one aborted attempt. Convergence:
**seven exact failed hedges, −$6.2239**, zero wins. Others have no new
completions. Separate strategy ledgers are not summed.

Cooldown fees $10.4195, stress $12.9846, capital $0.000933, funding zero;
without stress the interval remains −$31.7202. Its 23 observed exit-price
comparisons improved $0.403790 in aggregate (10 worse, eight better, five
unchanged; three missing request prices), median approximately zero and p95
adverse $0.204680. Request-to-flat median 1.199 s, p95 1.819 s over 26
paired closes. Premium's four comparisons worsened $0.094979.

The separate 06:28 current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review43.json` records cooldown
414 exact plus two estimated completions, −$581.7609 (one win); Premium
54/−$90.1297 (one win); convergence 38/−$31.4477 (two wins); conservative
1/+$2.3198. Version remains `e3e83cda71a6`; win counts have not increased.
The scheduled snapshot was flat; the later snapshot has one Premium open
position excluded from its closed net. Three legacy funding obligations
remain outside current-version totals.

Health: four connected feeds, 111 pairs, CPU 52.72% of one core, p95 loop
lag 9.93 ms, RSS 235.45 MiB, 731.7 books/s. Next review **06:46:33 UTC**.
The second delayed quote scan is still running under its preexisting
900-second deadline; no completed economic result is available. A separate
synthetic check reproduced cache thrashing, without reading raw data or
changing the running source. No new capture, promotion or capital reset.
