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


## Review 44: 2026-09-30 06:46:33 UTC

Read at 06:47 UTC and archived in
`reports/live-review-catchup/review-20260930T064633Z.json`. All completion
and aborted coverage is complete. Cooldown: **34 exact paired completions,
−$51.4051**, zero wins. Premium: **30 exact, −$50.5196**, 25 paired
−$40.5379 and five failed hedges −$9.9817, zero wins. Convergence: **five
exact failed hedges, −$3.6132**, zero wins, each with HL price-limit rejection.
Others have no new completions; separate strategy ledgers are not summed.

Cooldown fees $12.6536, stress $16.9788, capital $0.001221, funding zero;
without stress the interval remains −$34.4263. Its 33 observed exit-price
comparisons worsened $2.805735 in aggregate (10 worse, 10 better, 13 unchanged;
one missing request price), median zero and p95 adverse $0.876138. Its
request-to-flat median was 1.213 s and p95 1.789 s over all 34 paired closes.
Premium's 24 exit comparisons improved $0.040594 (one missing).

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review44.json` records cooldown
449 exact plus two estimated completions, −$634.0214 (one win); Premium
84/−$140.6493 (one win); convergence 42/−$33.9553 (two wins); conservative
1/+$2.3198. Version remains `e3e83cda71a6`; win counts have not increased.
The scheduled snapshot had one Cooldown position open, while the later
snapshot had one Convergence position open; these are excluded from the
respective closed nets. Three legacy funding obligations remain separate.

Health: four connected feeds, 111 pairs, CPU 55.74% of one core, p95 loop
lag 12.88 ms, RSS 236.09 MiB, 802.0 books/s. Next review **07:06:33 UTC**.
The separately reviewed cache-disabled quote diagnostic is active under
its 1,200-second limit; approximately two-thirds of compressed input had
been read at 06:46:45. This is progress only, not a completed result.
Independent derived-output verifier was committed as `c5645f5` before
publication. No new capture, strategy promotion or capital reset.


## Review 45: 2026-09-30 07:06:33 UTC

Archived in `reports/live-review-catchup/review-20260930T070633Z.json`;
all completion and aborted coverage is complete. Cooldown: **43 exact
completions, −$65.8059**, comprising 42 paired −$65.0853 and one failed hedge
−$0.7206, zero wins. Premium: **six exact paired, −$9.5293**, zero wins.
Convergence: **two exact failed hedges, −$0.9385**, zero wins, both with HL
price-limit rejections. Others have no new completions. Portfolios are separate.

Cooldown fees $15.0548, stress $21.4726, capital $0.001509, funding zero;
without stress it remains −$44.3332. Its 38 observed exit-price comparisons
worsened $0.667253 (11 worse, 16 better, 11 unchanged; four missing request
prices), median approximately zero and p95 adverse $0.415030. For 42 paired
closes request-to-flat median was 1.327 s, p95 1.790 s. Premium's six
comparisons improved $0.009343.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review45.json` records cooldown
492 exact plus two estimated completions, −$702.0528 (one win); Premium
90/−$150.1786 (one win); convergence 44/−$34.8938 (two wins); conservative
1/+$2.3198. Version `e3e83cda71a6` and win counts are unchanged. Both snapshots
are flat, with three legacy funding obligations outside current-version totals.

Health: four connected feeds, 111 pairs, CPU 57.69% of one core, p95 loop lag
10.25 ms, RSS 244.12 MiB, 950.2 books/s. Next review **07:26:33 UTC**.
The delayed quote study completed and was independently audited in `5ae08e9`: 
zero fee-only positives among 26,395 complete outcomes, with all 28,800
outcomes preserved. No additional canonical replay or execution capture is
justified by that result. A separate single 20-minute RH spread-regime
prerequisite watch is at method-review stage; no network collection launched.
The isolated old LIT peak does not justify overriding its failed median gate.


## Review 46: 2026-09-30 07:26:33 UTC

Archived in `reports/live-review-catchup/review-20260930T072633Z.json`;
all completion and aborted coverage is complete. Cooldown: **50 exact
completions, −$60.6943**, comprising 49 paired −$59.4120 and one failed
hedge −$1.2822, zero wins. Premium: **three exact completions, −$5.1906**,
comprising one paired −$2.7767 and two failed hedges −$2.4139, zero wins;
both recorded rejections were HL price-limit failures. Others have no new
completions. Portfolios are separate.

Cooldown fees $14.4360, stress $24.9671, capital $0.001757, funding zero;
without stress it remains −$35.7272. Its 48 observed exit-price comparisons
worsened $0.048471 (nine worse, 15 better, 24 unchanged; one missing request
price), median zero and p95 adverse $0.071628. For 49 paired closes,
request-to-flat median was 1.177 s, p95 1.822 s. Premium's single paired
exit comparison improved $0.128263.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review46.json` records cooldown
540 exact plus two estimated completions, −$758.7532 (one win); Premium
93/−$155.3691 (one win); convergence 44/−$34.8938 (two wins); conservative
1/+$2.3198. Version `e3e83cda71a6` and win counts are unchanged. The review
snapshot is flat; the later epoch snapshot has two cooldown positions open.
Three legacy funding obligations remain outside current-version totals.

Health: four connected feeds, 111 pairs, CPU 52.48% of one core, p95 loop lag
12.95 ms, RSS 241.59 MiB, 801.1 books/s. Next review **07:46:33 UTC**.
The single spread-regime prerequisite watch remains in implementation review;
no new metadata or ticker request has started. No production strategy change,
capital reset or interpretation of conditional quote budgets as realized P&L.


## Review 47: 2026-09-30 07:46:33 UTC

Archived in `reports/live-review-catchup/review-20260930T074633Z.json`;
all completion and aborted coverage is complete. Cooldown: **45 exact
completions, −$45.9149**, comprising 44 paired −$44.7648 and one failed
hedge −$1.1501, zero wins. Premium: **six exact completions, −$9.5264**,
comprising five paired −$8.9346 and one failed hedge −$0.5919, zero wins.
Each recorded one HL price-limit rejection. Others have no new completions;
portfolios are separate.

Cooldown fees $9.7383, stress $22.4707, capital $0.001576, funding zero;
without stress it remains −$23.4442. Its 43 observed exit-price comparisons
improved $0.457314 (nine worse, 18 better, 16 unchanged; one missing request
price), median zero and p95 adverse $0.070047. For 44 paired closes,
request-to-flat median was 1.174 s, p95 1.684 s. Premium's five comparisons
improved $0.085322. Exit price deterioration is not the main loss explanation
in this window.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review47.json` records cooldown
587 exact plus two estimated completions, −$806.6607 (one win); Premium
99/−$164.8956 (one win); convergence 44/−$34.8938 (two wins); conservative
1/+$2.3198. Version `e3e83cda71a6` and win counts are unchanged. The review
snapshot has one cooldown position open; the later epoch snapshot is flat.
Three legacy funding obligations remain outside current-version totals.

Health: four connected feeds, 108 pairs, CPU 59.38% of one core, p95 loop lag
7.95 ms, RSS 246.68 MiB, 793.9 books/s. Next review **08:06:33 UTC**.
The spread-regime prerequisite watch is still in final implementation review;
no metadata or quote connection has started. Twelve focused fixtures passed
independent review; final source/cap checks precede commit and collection.
No capital reset or production strategy change.


## Review 48: 2026-09-30 08:06:33 UTC

Archived in `reports/live-review-catchup/review-20260930T080633Z.json`;
all completion and aborted coverage is complete. Cooldown: **44 exact paired
completions, −$46.8586**, zero wins. Premium: **six exact, −$9.2912**,
comprising three paired −$5.4013 and three failed hedges −$3.8899, zero wins.
Convergence: **four exact failed hedges, −$2.8037**, one win. Recorded
HL price-limit rejections: four convergence, three Premium. Others have no
new completions. Portfolios remain separate.

The new convergence win is preserved in
`reports/live-review-catchup/review48-positive-failed-hedge.json`: CASHCAT,
ID `1790755022065217-20874-convergence`, Core partial short 1,119.2 units,
entry $195.177288 and rescue buyback $195.032405. Gross $0.144883 minus
$0.097588644 stress and $0.0000003583 capital yields **+$0.047294**; fees
and funding are zero. HL rejected its long hedge and filled zero. This is
unhedged rescue profit, not a paired cycle, and does not establish a
profitable arbitrage policy. Unlike the earlier five winning records from
one LIT episode, this is a new, separately identified CASHCAT episode.

Cooldown fees $10.0281, stress $21.9717, capital $0.001576, funding zero;
without stress it remains −$24.8869. Its 43 observed exit-price comparisons
worsened $0.396818 (14 worse, ten better, 19 unchanged; one missing request
price), median zero and p95 adverse $0.096200. For 44 paired closes,
request-to-flat median was 1.165 s, p95 1.765 s. Premium's two observed
comparisons improved $0.152796, with one request price missing.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review48.json` records cooldown
630 exact plus two estimated completions, −$852.6047 (one win); Premium
105/−$174.1868 (one win); convergence 48/−$37.6975 (three wins); conservative
1/+$2.3198. Version `e3e83cda71a6` is unchanged. The review snapshot is flat;
the later epoch snapshot has one cooldown position open. Three legacy funding
obligations remain outside current-version totals.

Health: four connected feeds, 108 pairs, CPU 57.20% of one core, p95 loop lag
9.79 ms, RSS 249.39 MiB, 764.2 books/s. Next review **08:26:33 UTC**.
The original sentinel failed its 80 KB admission guard before any quote
connection. All 1,680 uncollected rows remain, and a separate compact-source
wrapper is in offline implementation review. No new network request, policy
change, capital reset or claim of paired profitability.

## Review 49: 2026-09-30 08:26:33 UTC

Archived exact daemon output in `reports/live-review-catchup/review-20260930T082633Z.json`;
all completion and aborted coverage is complete. Cooldown: **50 exact paired
completions, −$59.9870**, zero wins. Premium: **15 exact, −$23.6685**,
comprising 14 paired −$22.3101 and one failed hedge −$1.3585. Convergence:
**one exact failed hedge, −$1.6130**. All have zero wins; others have no new
completions. Premium and convergence each recorded one HL price-limit
rejection. Independent portfolios are not added together.

Cooldown fees $15.1227, stress $24.9678, capital $0.001777, funding zero;
without stress it remains −$35.0192. Its 48 observed exit-price comparisons
improved $0.579356 (15 worse, 19 better, 14 unchanged; two missing request
prices), median zero and p95 adverse $0.080500. Request-to-flat median for
50 paired closes was 1.150 s, p95 1.623 s. Premium's 13 observed comparisons
worsened $0.337485, with one request price missing.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review49.json` records cooldown
680 exact plus two estimated completions, −$912.5335 (one win); Premium
120/−$197.8553 (one win); convergence 49/−$39.3104 (three wins); conservative
1/+$2.3198. Version `e3e83cda71a6` and win counts are unchanged. The review
snapshot has one cooldown position open; the later epoch snapshot is flat.
Three legacy funding obligations remain outside current-version totals.

Health: four connected feeds, 108 pairs, CPU 57.65% of one core, p95 loop lag
9.70 ms, RSS 253.35 MiB, 689.7 books/s. Next review **08:46:33 UTC**.
The compact sentinel is still collecting until its fixed 08:32:57 UTC endpoint;
no economic results have been inspected. The independent auditor passed five
synthetic tests, including deliberate arithmetic, timestamp and block-gate
corruption. No production policy change or capital reset.

## Review 50: 2026-09-30 08:46:33 UTC

Archived exact daemon output in `reports/live-review-catchup/review-20260930T084633Z.json`;
all completion and aborted coverage is complete. Cooldown: **70 exact closes,
−$80.1627**, comprising 69 paired −$76.9705 and one failed hedge −$3.1922.
Premium: **21 exact, −$34.8332**, comprising 19 paired −$31.8230 and two
failed hedges −$3.0102, plus one zero-fill abort. Convergence: **three exact
failed hedges, −$3.3530**, plus two zero-fill aborts. No new wins; others have
no new completions. Rejections: convergence five HL, one Core and one RH
price-limit; Premium three HL price-limit and one RH notional-cap. These
include aborted attempts and are not a count of completed trades.

Cooldown fees $21.5643, stress $34.9516, capital $0.002465, funding zero;
without stress it remains −$45.2111. Its 69 exit-price comparisons worsened
$0.688700 (19 worse, 15 better, 35 unchanged), median zero and p95 adverse
$0.160555. Request-to-flat median for 69 paired closes was 1.160 s, p95
1.642 s. Premium's 19 comparisons improved $0.039807.

The separate later current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review50.json` records cooldown
749 exact plus two estimated completions, −$991.6763 (one win); Premium
142/−$235.9299 (one win); convergence 54/−$46.0574 (three wins); conservative
1/+$2.3198. Version `e3e83cda71a6`, epoch and win counts are unchanged.
The review snapshot is flat; the later epoch snapshot has one cooldown
position open. Three legacy funding obligations remain outside epoch totals.
The different read times are retained, not reconciled by discarding closes.

Health: four connected feeds, 108 pairs, CPU 60.73% of one core, p95 loop lag
9.06 ms, RSS 253.82 MiB, 880.5 books/s. Metadata age 595.6 s, following its
normal refresh. Host process checks confirm the same collector 3280600 and
reviewer 2765645; no restart or capital reset. Next review **09:06:33 UTC**.

The sentinel ended with no passing asset. Offline review rejects fitting
another RH/HL flow/ECM model on the existing negative quote grid. A distinct
RH/Core delayed-taker quote feasibility method is being reviewed against
retained seven-minute archives and historical metadata gaps; no scan,
implementation, capture or production policy change has been authorized.


## Review 51 — 2026-09-30 09:06:33 UTC

Exact daemon output is retained in
`reports/live-review-catchup/review-20260930T090633Z.json`. Complete completion
and abort coverage across strategies; no new winning close or abort.

- Cooldown: 64 exact paired closes, −$68.8576; no failed hedge.
- Premium: 19 exact closes, −$35.9288: 14 paired/−$23.3122 and five failed
  hedges/−$12.6166. Five Hyperliquid price-limit rejections.
- Convergence: nine exact closes, −$15.6411: one paired/−$1.4731 and eight
  failed hedges/−$14.1680. Eight Hyperliquid price-limit rejections.
- Other strategy ledgers: no new completions. Strategies are separate
  hypothetical portfolios; their results are not summed.

Cooldown fees $17.7855, stress $32.4586, capital $0.0023255, funding zero;
without stress the window remains −$36.3990. Its 63 observed exit-price
comparisons improved $1.671582 (12 worse, 18 better, 33 unchanged), one
request-price observation missing, median zero and p95 adverse $0.080060.
Its 64 paired request-to-flat times have median 1.208 s and p95 1.967 s.
Premium's 13 observed exit comparisons worsened $0.512630, one missing;
convergence's one paired comparison improved $0.334000.

The separately timed current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review51.json` records cooldown
816 exact plus two estimated completions, −$1,063.5894 (one win); Premium
160/−$268.6174 (one win); convergence 61/−$58.3045 (three wins); conservative
1/+$2.3198. The six historical winning records still belong to the two
previously documented failed-hedge rescue episodes, not paired wins.
Version `e3e83cda71a6` and epoch remain unchanged. The review health snapshot
has one cooldown position open; the later epoch snapshot is flat. Three
legacy funding obligations remain outside epoch totals. Read times differ;
no records are discarded to force agreement.

Health: four connected feeds, 108 pairs, CPU 57.53% of one core, p95 loop lag
10.53 ms, RSS 257.59 MiB, 859.3 books/s, metadata age 1,796 s. Next review
**09:26:33 UTC**. No production restart, capital reset or policy change.

The Core/RH method passed root and independent review and was committed as
`2a5bffd`. Implementation and synthetic tests only are now authorized; raw
hashing/decoding, network, capture and policy deployment remain unstarted.
The 600,000-byte allocation and all prior failed-study allocations remain.


## Review 52 — 2026-09-30 09:26:33 UTC

Exact daemon output is preserved in
`reports/live-review-catchup/review-20260930T092633Z.json`. Completion and abort
coverage remain complete; there are no new winners.

- Cooldown: 68 exact paired closes, −$72.3501; no failed hedge or abort.
- Premium: six exact paired closes, −$9.8235; no failed hedge or abort.
- Convergence: two exact failed-hedge closes, −$2.2329, plus two aborts.
  Rejections include four Hyperliquid price-limit failures and Core one
  price-limit and one notional-cap failure, including aborted attempts.
- Other strategies: no new completed trades. Separate portfolios are not summed.

Cooldown fees $17.9639, stress $33.4573, capital $0.0023940, funding zero;
removing stress alone leaves −$38.8928. Its 66 observed exit-price comparisons
improved $0.634621 (19 worse, 24 better, 23 unchanged), with two request-price
observations missing. Median zero, p95 adverse $0.101380. All 68 paired
request-to-flat times are present: median 1.159 s, p95 1.644 s. Premium's six
exit comparisons improved $0.227009 (four better, two unchanged).

The separately timed current-version snapshot in
`reports/live-review-catchup/current-epoch-at-review52.json` records cooldown
882 exact plus two estimated completions/−$1,133.8242 (one win), Premium
166/−$278.4409 (one win), convergence 63/−$60.5375 (three wins), and conservative
1/+$2.3198. Version `e3e83cda71a6`, epoch and all six old failed-rescue win
records are unchanged. Both review and later epoch snapshot are flat; three
legacy funding obligations remain outside current-epoch totals.

Health: four connected feeds, 108 pairs, CPU 53.63% of one core, p95 loop lag
10.97 ms, RSS 257.61 MiB, 698.6 books/s, metadata age 2,994.6 s. Next review
**09:46:33 UTC**. No capital reset or production policy change.

Core/RH code remains under implementation and independent review. Initial
engine review found reference retention and Decimal-bound checks to fix;
adapter review found excess tied-event book retention, out-of-scope HL
reconstruction, pre-validation float parsing and source-regression recovery
issues. These are pre-run findings. No real archive hash/decode or network
has occurred. Independent auditor arithmetic tests pass, but its publication
checks and the main fake-archive run tests are not yet complete.

## Review 53 — 2026-09-30 09:46:33 UTC

Exact daemon output is preserved in
`reports/live-review-catchup/review-20260930T094633Z.json`; all completion and
abort coverage is complete. No new winners or aborts occurred.

- Cooldown: 36 exact paired closes, −$39.2766.
- Premium: seven exact closes, −$13.0495: three paired/−$5.1338 and four
  failed hedges/−$7.9156.
- Convergence: five exact failed hedges, −$7.1814.
- Other strategies: no new completed trades. The nine failed hedges each
  record a Hyperliquid price-limit rejection. Portfolios remain separate.

Cooldown fees $10.6789, stress $17.9763, capital $0.0012747, funding zero;
removing stress alone leaves −$21.3003. Its 35 observed exit comparisons
improved $0.283336 (nine worse, 15 better, 11 unchanged), with one missing
request price; p95 adverse $0.124187. All 36 paired request-to-flat times
are present: median 1.170 s, p95 1.634 s. Premium's three exit comparisons
improved $0.034240 (one better, two unchanged).

The separately timed current-version snapshot at 09:46:53 UTC is saved in
`reports/live-review-catchup/current-epoch-at-review53.json`: cooldown 917
exact plus two estimated completions/−$1,172.1607 (one win), Premium
173/−$291.4904 (one win), convergence 68/−$67.7188 (three wins), conservative
1/+$2.3198. Version `e3e83cda71a6`, epoch, and the six old failed-rescue win
records are unchanged. Review portfolios were flat; the later snapshot has
one cooldown position. Three legacy funding obligations remain.

Health: all four feeds connected, 110 pairs after normal metadata refresh,
CPU 50.66% of one core, p95 lag 7.44 ms, RSS 257.47 MiB, 734.1 books/s,
metadata age 590.9 s. A 09:41 storage check found the database 61,120,512
bytes, WAL zero and 565.65 GiB free. Next checkpoint **10:06:33 UTC**.
No capital reset or production policy change.

Core/RH code remains unrun on historical streams. Root's all-missing toy
summary exposed a 64,081-byte uncompressed output above the original
summary cap; compressed summaries preserve all 160 groups within unchanged
limits. Separate zero-raw source/runtime preparation, timeout failure
rosters and completion-marker cleanup are implemented. The independent
auditor's seven synthetic tests pass; the full decoder fixture and final
combined source review remain prerequisites to any run.

## Review 54 — 2026-09-30 10:06:33 UTC

Exact daemon output is preserved in
`reports/live-review-catchup/review-20260930T100633Z.json`; completion and
abort coverage is complete. There are no new winners or aborts.

- Cooldown: 42 exact paired closes, −$51.0983.
- Premium: two exact closes, −$3.0930: one paired/−$1.5717 and one failed
  hedge/−$1.5213.
- Convergence: three exact failed hedges, −$3.5799.
- Other strategies: no completed trades. Four Hyperliquid price-limit
  rejections account for the failed hedges. Portfolios remain separate.

Cooldown fees $14.7156, stress $20.9736, capital $0.0015018, funding zero;
removing stress alone leaves −$30.1247. Its 41 observed exit comparisons
worsened $0.271375 (11 worse, nine better, 21 unchanged); one request price
is missing. Median zero, p95 adverse $0.221220. All 42 paired request-to-flat
times are present: median 1.142 s, p95 1.862 s. Premium's one paired exit
comparison was unchanged within numerical precision.

The separately timed snapshot at 10:06:59 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review54.json`: cooldown 960
exact plus two estimated completions/−$1,224.2595 (one old win), Premium
175/−$294.5834 (one old win), convergence 71/−$71.2988 (three old wins),
conservative 1/+$2.3198. Version `e3e83cda71a6`, epoch and the six old
failed-rescue win records remain unchanged. The review had one open cooldown
position; the later snapshot is flat. Three legacy funding obligations remain.

All four feeds are connected, 110 pairs, CPU 53.63% of one core, p95 lag
8.19 ms, RSS 262.03 MiB, 739.5 books/s, metadata age 1,791.0 s. Next checkpoint
**10:26:33 UTC**. No capital reset or production policy change.

The one canonical Core/RH replay launched at 10:01:18 UTC remains running
without reported errors. Its sources and prepared inputs are frozen; the
900-second deadline and no-retry rule remain. No partial economics inspected.

## Review 55 — 2026-09-30 10:26:33 UTC

Exact daemon output is saved in
`reports/live-review-catchup/review-20260930T102633Z.json`; completion and
abort coverage is complete. No new winners or aborts occurred.

- Cooldown: 50 exact paired closes, −$57.6998.
- Premium: three exact failed hedges, −$5.0790.
- Convergence: three exact failed hedges, −$1.7965.
- Other strategies: no completed trades. Six Hyperliquid price-limit
  rejections account for failed hedges. Portfolios remain separate.

Cooldown fees $15.5031, stress $24.9678, capital $0.0017870, funding zero;
removing stress alone leaves −$32.7320. Its 49 observed exit comparisons
improved $0.843300 (11 worse, 20 better, 18 unchanged), with one request
price missing; median effectively zero and p95 adverse $0.087000. All 50
paired request-to-flat times are present: median 1.134 s, p95 1.698 s.
There were no paired Premium or convergence exit comparisons in this window.

The separately timed snapshot at 10:27:01 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review55.json`: cooldown 1,010
exact plus two estimated completions/−$1,281.9407 (one old win), Premium
178/−$299.6624 (one old win), convergence 74/−$73.0953 (three old wins),
conservative 1/+$2.3198. Version `e3e83cda71a6`, epoch and the six old
failed-rescue win records remain unchanged. One cooldown position was open
at review; the later snapshot is flat. Three legacy funding obligations
remain unknown and retained, with no outstanding market quantity.

All four feeds connected, 110 pairs, CPU 49.34% of one core, p95 lag 6.86 ms,
RSS 261.12 MiB, 618.3 books/s, metadata age 2,990.5 s. At 10:19 the database
was 61,517,824 bytes, WAL zero, with 607,357,042,688 free filesystem bytes.
Next checkpoint **10:46:33 UTC**. No capital reset or policy change.

Core/RH's completed diagnostic and independent audit found all 842 complete
quotes gross-negative, retaining 166 censors. A separate existing-table
funding check found a maximum 0.41 bp single-settlement rate credit under
hindsight direction and favorable payment ownership, versus a 6 bp
stress-plus-target hurdle at $1,000. This is an equal-reference-notional
scenario, not verified funding cashflow or a bound on combined trading P&L.
Neither result supports a new capture or strategy promotion.

## Review 56 — 2026-09-30 10:46:33 UTC

Exact daemon output is saved in
`reports/live-review-catchup/review-20260930T104633Z.json`; completion and
abort coverage is complete. There are no new winners.

- Cooldown: 45 exact paired closes, −$50.0479.
- Premium: three exact closes, −$5.7185: two paired/−$3.7274 and one failed
  hedge/−$1.9911.
- Convergence: one aborted attempt, no completion or booked P&L. Both
  Hyperliquid and Core Lighter rejected at their price limits.
- Other strategies: no completions. Premium's failed hedge adds one
  Hyperliquid price-limit rejection. Portfolios remain separate.

Cooldown fees $12.2294, stress $22.4714, capital $0.0016046, funding zero;
removing stress alone leaves −$27.5765. All 45 exit comparisons are present:
execution improved $0.823811 (nine worse, 17 better, 19 unchanged), median
zero, p95 adverse $0.037679. Request-to-flat median 1.176 s, p95 1.766 s,
with complete paired coverage. Premium's two paired comparisons worsened
$0.106590 (one better, one worse).

The separately timed snapshot at 10:46:56 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review56.json`: cooldown 1,056
exact plus two estimated completions/−$1,333.1526 (one old win), Premium
181/−$305.3809 (one old win), convergence 74/−$73.0953 (three old wins),
conservative 1/+$2.3198. Version `e3e83cda71a6`, epoch and six old
failed-rescue win records remain unchanged. Two cooldown positions were
open at review; the later snapshot is flat. Three legacy funding
obligations remain unknown and retained, with no outstanding market quantity.

All four feeds connected, 110 pairs, CPU 55.83% of one core, p95 lag 8.33 ms,
RSS 266.65 MiB, 754.5 books/s, metadata age 586.2 s. Next checkpoint
**11:06:33 UTC**. No capital reset or policy change.

The completed liquidation schema review found all 65 previously ignored
liquidation rows were subscription history predating capture, with zero
live updates. It supplies no additional flow or supported successor study.

## Review 57 — 2026-09-30 11:06:33 UTC

Exact daemon output is saved in
`reports/live-review-catchup/review-20260930T110633Z.json`; completion and
abort coverage is complete. No new winners occurred.

- Cooldown: 47 paired closes, −$58.8049: 46 exact/−$57.8550 and one
  estimated/−$0.9499. The quality labels remain separate.
- Premium: 16 exact closes, −$30.0337: ten paired/−$19.8240 and six failed
  hedges/−$10.2097.
- Convergence: one exact failed hedge/−$1.6524 and one aborted attempt.
- Other strategies: no completions. Across the interval there were eight
  Hyperliquid price-limit and one Core Lighter notional-cap rejection.
  Portfolios remain separate.

Cooldown fees $19.7465, stress $23.4704, capital $0.0016587, funding
−$0.0022453; removing stress alone leaves −$35.3346. Its 46 observed exit
comparisons worsened $2.580004 (20 worse, 16 better, ten unchanged), with
one request price missing; median effectively zero, p95 adverse $0.196870.
All 47 paired request-to-flat times are present: median 1.166 s, p95 1.847 s.
Premium's ten paired comparisons improved $0.950210 (one worse, six better,
three unchanged).

The separately timed snapshot at 11:06:59 UTC is preserved in
`reports/live-review-catchup/current-epoch-at-review57.json`: cooldown 1,101
exact plus three estimated completions/−$1,390.8197 (one old win), Premium
197/−$335.4146 (one old win), convergence 75/−$74.7477 (three old wins),
conservative 1/+$2.3198. Version `e3e83cda71a6`, epoch and six old
failed-rescue win records remain unchanged. Both review and later snapshot
are flat. Three legacy funding obligations remain unknown and retained.

All four feeds connected, 110 pairs, CPU 54.09% of one core, p95 lag 9.61 ms,
RSS 267.45 MiB, 786.4 books/s, metadata age 1,787.0 s. Next checkpoint
**11:26:33 UTC**. No capital reset or policy change.

## Reviews 58 through 60 — 2026-09-30 11:26 to 12:06 UTC

All three daemon checkpoints completed on schedule and are preserved byte for
byte in `reports/live-review-catchup/review-20260930T112633Z.json`,
`review-20260930T114633Z.json` and `review-20260930T120633Z.json`.
Completion and abort coverage is complete. All closes below are exact;
there were no new winners or aborts. Portfolios remain separate.

| Review | Cooldown | Premium | Convergence |
| --- | --- | --- | --- |
| 58 | 48 / −$65.6735; 46 paired, two failed | 6 / −$10.2831; four paired, two failed | No closes |
| 59 | 27 / −$45.0318; 26 paired, one failed | 4 / −$7.0742; two paired, two failed | One failed / −$5.4481 |
| 60 | 37 / −$49.1942; 35 paired, two failed | 4 / −$8.2189; two paired, two failed | Eight failed / −$10.4850 |

All feeds remained connected. Pair counts were 110, 109 and 109; p95 loop
lag 9.06, 8.07 and 9.68 ms; RSS 271.37, 269.11 and 272.39 MiB. The current
snapshot read at 12:14:35 UTC is separately preserved in
`current-epoch-after-review60.json`: cooldown 1,232 exact plus three estimated
completions/−$1,575.3208; Premium 214/−$366.3507; convergence 87/−$92.8604;
conservative one/+$2.3198. The six old rescue wins are unchanged. All current
positions are flat, with the same three retained legacy funding obligations.
Next checkpoint **12:26:33 UTC**. No production policy or capital reset.

The user authorized proceeding with the broader recommendation at 12:12 UTC.
The separate 16 MiB dated-carry allocation is frozen in `139efe1`. Contract
inventory preparation and collector implementation are underway; no quote
study has started.

## Review 61 — 2026-09-30 12:26:33 UTC

Exact daemon output and separately timed epoch snapshot are preserved as
`review-20260930T122633Z.json` and `current-epoch-at-review61.json`.
Completion/abort coverage is complete; all 46 closes are exact, with no wins
or aborts. Cooldown: 34/−$53.9742 (32 paired, two failed hedges). Premium:
9/−$15.3438 (three paired, six failed). Convergence: three failed/−$2.1797.
Nine Hyperliquid price-limit rejections. Portfolios remain separate.

Four feeds connected, 109 pairs, CPU 56.92%, p95 lag 9.12 ms, RSS 278.96 MiB,
874.0 books/s. One cooldown position was open at review. Epoch snapshot: conservative 1/2.3198; convergence 87/-92.8604; cooldown 1249/-1613.4328; premium 220/-376.3346. The same six old rescue wins and three legacy funding obligations
remain. Next checkpoint **12:46:33 UTC**. No policy or capital reset.

## Review 62 — 2026-09-30 12:46:33 UTC

Exact review and separately timed epoch snapshot: `review-20260930T124633Z.json`
and `current-epoch-at-review62.json`. Completion and abort coverage are complete.
All 55 closes are exact; four aborts are retained. Portfolios remain separate.

| Strategy | Completed | Net | Classification |
| --- | ---: | ---: | --- |
| Cooldown | 19 | −$41.1271 | 18 paired/−$37.1204; one failed/−$4.0068 |
| Premium | 30 | −$61.9382 | 14 paired/−$26.8112; 16 failed/−$35.1270; two aborts |
| Convergence | 6 | −$6.3697 | All failed hedges; one positive rescue; two aborts |

There were 24 Hyperliquid price-limit, one Core notional-cap and two RH
notional-cap rejections. No positive paired cycle occurred. The new convergence
winner is preserved as the exact trade payload in `review62-convergence-win.json`:
PUMP trade `1790771782086005-21714-convergence`, long 172,300 PUMP on Core,
short rejected by Hyperliquid's price limit. The 1.3575-second rescue made
$0.6892 in price P&L, charged $0.4981193 stress and $0.000002144 capital,
zero fees/funding, for **+$0.191078556**. This is directional failed-hedge
exposure, not a completed paired cycle; the full six-attempt set remains negative.
There are now seven current-epoch win records, six older rescue wins plus this one.

Cooldown fees $9.4320, stress $9.4865, capital $0.0006487, funding zero;
removing stress alone leaves −$31.6406. Its 17 exit-price comparisons improved
$0.497101 overall (ten improved, seven worsened, one request price missing),
p95 adverse $0.64898. All 18 paired request-to-flat times are present, median
1.174 s, p95 1.846 s. Premium's 13 comparable exits worsened $1.438491
(seven improved, six worsened, one request price missing).

Four feeds connected, 110 pairs, CPU 69.09%, p95 lag 16.35 ms, RSS 286.06 MiB,
1,373.6 books/s. The review itself was flat; the later snapshot had one cooldown
position. Snapshot current epoch: cooldown 1,262 exact plus three estimated
closes/−$1,644.8124 (one old win); Premium 251/−$440.1297 (one old win);
convergence 94/−$100.4677 (four wins); conservative one/+$2.3198. Same version
and capital history; three retained legacy funding obligations. Next review
**13:06:33 UTC**.

The new dated-carry collector passed its first arrival check: both HTTP 200,
predeadline, callback late only 1.188 ms, mapping drift roughly one microsecond.
Only status/timing fields were inspected; no interim economic evaluation.

## Review 63 — 2026-09-30 13:06:33 UTC

Exact archive `review-20260930T130633Z.json` and separate current-epoch read
`current-epoch-at-review63.json`. All 37 closes are exact; zero wins or aborts,
with complete completion/abort coverage. Portfolios remain separate.

- Cooldown: 23/−$45.4605; 20 paired/−$39.4488, three failed/−$6.0117.
- Premium: eight/−$16.7380; two paired/−$3.7285, six failed/−$13.0095.
- Convergence: six failed hedges/−$9.2110; no paired closes.
- Thirteen Hyperliquid price-limit rejections. Other strategies had no closes.

Cooldown fees $11.2672, stress $11.4825, capital $0.0007205, funding zero;
removing stress leaves −$33.9781. All 20 paired exit-price comparisons are
available: eight worsened, eleven improved, one unchanged, net deterioration
$2.143718; median −$0.029805, p95 adverse $0.83433. Their request-to-flat median
is 1.228 s, p95 1.788 s. Premium's two paired comparisons improved $0.055183
in total, one better and one worse.

Four feeds connected, 110 pairs, CPU 66.51%, p95 lag 11.77 ms, RSS 287.96 MiB,
1,085.1 books/s, metadata age 1,777.3 s. Review and later snapshot each had
one cooldown position. Snapshot epoch: cooldown 1,286 exact plus three estimated
closes/−$1,692.0248 (one old win); Premium 259/−$456.8658 (one old win);
convergence 100/−$109.3415 (four rescue wins); conservative one/+$2.3198.
The seven total rescue win records and three legacy funding uncertainties
remain. No policy/capital change. Next checkpoint **13:26:33 UTC**.

The fixed dated-carry study has five paired samples through 13:05, all with
successful arrival status, 6,139 sample bytes, no collection errors. No interim
price/economic evaluation; fixed endpoint remains 3 October 12:45 UTC.

## Review 64 — 2026-09-30 13:26:33 UTC

Exact review `review-20260930T132633Z.json` and separate epoch read
`current-epoch-at-review64.json` are preserved. All 44 closes are exact and
negative, with zero aborts and complete coverage. Portfolios remain separate.

| Strategy | Closes | Net | Paired / failed |
| --- | ---: | ---: | --- |
| Cooldown | 27 | −$61.1594 | 24/−$54.5144; three/−$6.6450 |
| Premium | 9 | −$18.1743 | three/−$4.9958; six/−$13.1785 |
| Convergence | 8 | −$12.0159 | two/−$2.1457; six/−$9.8701 |

Twelve Hyperliquid price-limit rejections. Cooldown fees $18.5390, stress
$13.4796, capital $0.0008668, funding zero; removing stress leaves −$47.6798.
Its 23 observed exit-price comparisons improved $1.179362 overall (eleven
better, ten worse, two unchanged, one request price missing); median effectively
zero, p95 adverse $0.353067. All 24 paired request-to-flat observations are
present: median 1.361 s, p95 1.699 s. Premium's three exit comparisons worsened
$0.145783; both convergence paired exits worsened, $1.069896 combined.

Four feeds connected, 110 pairs, CPU 70.07%, p95 lag 12.53 ms, RSS 294.22 MiB,
1,037.5 books/s, metadata age 2,976.6 s. Both review and later snapshot are flat.
Snapshot epoch: cooldown 1,312 exact plus three estimated closes/−$1,751.4323
(one old win); Premium 267/−$473.1850 (one old win); convergence 107/−$120.4569
(four rescue wins); conservative one/+$2.3198. Seven rescue win records remain,
with the same three legacy funding obligations. No policy/capital change.
Next checkpoint **13:46:33 UTC**.

The dated-carry collector has nine scheduled pairs through 13:25, all with
successful arrival status, 11,027 sample bytes and no collection errors.
Its fixed source, endpoint and economic-readout restrictions are unchanged.

### Planned annotation for review 65: NVDA attempt timing

For the next existing production review only, add a descriptive NVDA breakdown
using retained paper attempts created between review64's checkpoint and
review65's checkpoint. Split by attempt `created_at` before/after 13:30 UTC
(9:30 Eastern); keep strategy, paired/failed classification, exact/estimated,
abort and unsettled-at-checkpoint counts separate. A completion after the upper
checkpoint remains unsettled in this annotation, even if the later database
read contains its final P&L. Do not treat the unequal pre/post durations as a
causal comparison or as an independent holdout; rejected signals without a
paper attempt are outside this denominator.

The [published core cash session](https://www.nyse.com/trade/hours-calendars)
starts at 9:30 Eastern, and 30 September is not a listed 2026 holiday. This is
an annotation of the already running monitor, with no new quote capture,
policy change, threshold change or economic replay. One bounded read-only
query, at most 256 retained attempts and 64 KiB output; report incompleteness
rather than truncate or retry if a cap is exceeded. The dated-carry study
remains frozen and is not an input to this annotation.

## Review 65 — 2026-09-30 13:46:33 UTC

Exact review and separate epoch snapshot are archived. All 165 closes exact,
one convergence abort, complete completion/abort coverage. Portfolios separate.

| Strategy | Closes | Net | Paired / failed |
| --- | ---: | ---: | --- |
| Cooldown | 20 | −$38.2285 | 19/−$35.1220; one/−$3.1065 |
| Premium | 75 | −$149.6087 | 11/−$22.6274; 64/−$126.9813 |
| Convergence | 70 | −$80.8370 | five/−$2.2831; 65/−$78.5539 |

Five convergence wins: paired WLD +$0.358970 and CRCL +$0.325047; failed-hedge
rescues HOOD +$0.864641, SOXL +$0.105679, LIT +$0.112751. Exact records are in
`review65-convergence-wins.json`. All arithmetic reconciles (maximum floating
residual 1.4e-17), remaining quantities zero, funding complete. WLD and CRCL
both bought Hyperliquid and sold Core Lighter; matched quantities 1,768.1 and
11.853. WLD gross $1.753442, fees $0.894952, stress $0.499488, capital
$0.000032; CRCL gross $1.003791, fees $0.179275, stress $0.499462, capital
$0.000008. Funding zero. These are the first two positive paired records in
this epoch; ten rescue wins remain distinct. Convergence's full-window profit
factor is 0.0214, paired-only 0.2305. No promotion or stopping threshold met.
Independent review of the preserved records confirmed classification, full exit
quantities, arithmetic and review-window settlement. Entry legs were separated
by 0.739 s (WLD) and 0.891 s (CRCL). These remain paper fills; preserved funding
flags are not independently verified venue evidence.

Price-limit rejections: Hyperliquid 124, Core four, RH one. Removing stress
still leaves cooldown −$28.2439, Premium −$112.1972, convergence −$46.7438.
Cooldown's 19 paired exit comparisons worsened $2.68465 overall (11 worse,
seven better, one unchanged); median $0.091362, p95 $1.63294. Its request-to-flat
median 1.408 s, p95 1.838 s. Premium's ten available exit comparisons worsened
$1.148441 (one missing); all five convergence comparisons worsened, $4.195283.

Four feeds connected, 113 pairs, CPU 71.30%, p95 lag 17.38 ms, RSS 306.35 MiB,
1,361.7 books/s, metadata age 573.6 s. Review and later snapshot flat. Separate
later epoch read: cooldown 1,332 exact plus three estimated/−$1,789.6608;
Premium 343/−$624.3283 (one extra completion after review); convergence
177/−$201.2940; conservative one/+$2.3198. Twelve total win records, including
ten rescue records. Three legacy funding obligations remain. Same policy,
version and capital history. Next checkpoint **14:06:33 UTC**.

### Review 65 NVDA annotation result

The frozen one-shot reader completed: one retained attempt, all after 13:30,
Premium failed hedge −$1.644186; zero positive, aborted or unsettled attempts.
No attempts before 13:30 in the retained denominator. Pre/post exposures were
209.04/992.31 seconds; rejected signals are excluded. This single observation
supports no session-effect or profitability claim. Output is 1,930 bytes;
source, provenance and incremental documentation fit the 120,000-byte
reservation. No retry, capture, threshold change or extension follows.

The dated-carry collector has 13 paired arrivals through 13:45, 15,885 sample
bytes, no collection errors; economics remain sealed until 3 October 12:45.

## Review 66 — 2026-09-30 14:06:33 UTC

Exact archive `review-20260930T140633Z.json` and separate epoch read preserved,
with the manual-directory cap checked before writing (1,152,072/16,777,216
bytes). All 46 closes exact and negative, zero aborts, complete coverage.

- Cooldown: 12 paired closes, −$13.7992; no failed-hedge closes.
- Premium: 24/−$43.4084; seven paired/−$14.5107, 17 failed/−$28.8977.
- Convergence: ten/−$8.8190; two paired/−$1.6740, eight failed/−$7.1451.
- Twenty-four Hyperliquid price-limit rejections; other strategies no closes.

Cooldown fees $2.9628, stress $5.9933, capital $0.0004290, funding zero;
without stress still −$7.8058. Its eleven available exit-price comparisons
improved $1.22391 overall (six better, four worse, one unchanged, one missing);
median −$0.048971, p95 adverse $0.383577. All twelve request-to-flat observations
are present: median 1.206 s, p95 1.930 s. Premium's seven exit comparisons
worsened $1.597969; both convergence comparisons worsened, $0.948022 combined.

Four feeds connected, 113 pairs, CPU 74.25%, p95 lag 26.22 ms, RSS 310.96 MiB,
1,227.6 books/s, metadata age 1,773.5 s. The review had one cooldown position;
the separate later snapshot was flat. Epoch snapshot: cooldown 1,345 exact
plus three estimated/−$1,804.8741; Premium 368/−$670.8697; convergence
187/−$210.1130; conservative one/+$2.3198. Twelve win records remain, with
only the two earlier paired wins. Three legacy funding obligations retained.
No policy or capital change. Next checkpoint **14:26:33 UTC**.

The carry collector has 17 arrivals through 14:05, 20,740 sample bytes and no
reported collection errors. No interim prices or economics were evaluated.

## Review 67 — 2026-09-30 14:26:33 UTC

Exact review and separate current-epoch read preserved; manual archive
1,183,116/16,777,216 bytes after the guarded writes. All 45 closes exact and
negative, zero aborts, complete coverage. Portfolios remain separate.

- Cooldown: 25/−$48.5700; 23 paired/−$47.0561, two failed/−$1.5139.
- Premium: twelve/−$22.1022; four paired/−$7.7897, eight failed/−$14.3124.
- Convergence: eight failed hedges/−$9.0479; no paired closes.
- Price-limit rejections: Hyperliquid sixteen, Core one. No new winners.

Cooldown fees $10.0448, stress $12.4848, capital $0.0008292, funding zero;
removing stress leaves −$36.0852. All 23 paired exit comparisons are present:
fifteen worsened and eight improved, net deterioration $2.769111, median
$0.11471, p95 $0.61894. Request-to-flat median 1.288 s, p95 1.710 s. Premium's
four paired exit comparisons all worsened, $0.800906 combined.

Four feeds connected, 113 pairs, CPU 83.42%, p95 lag 21.14 ms, RSS 312.81 MiB,
1,347.3 books/s, metadata age 2,972.8 s. A temporary CPU rise to 91–97% around
14:15–14:17 triggered the existing busy indicator; snapshots stayed fresh,
RH gap count stayed 107, and funding errors were empty. CPU returned below
the busy threshold by 14:20. No process or code intervention was needed.

Review snapshot flat; separate later epoch read had one cooldown position.
Epoch: cooldown 1,369 exact plus three estimated/−$1,852.0300; Premium
378/−$688.3042; convergence 195/−$219.1609; conservative one/+$2.3198.
Twelve prior win records (two paired, ten rescues) and three legacy funding
obligations remain. No policy/capital change. Next checkpoint **14:46:33 UTC**.

Carry arrival status: 21 samples through 14:25, 25,607 bytes, no reported
errors; fixed source and endpoint unchanged, no interim economic analysis.

## Review 68 — 2026-09-30 14:46:33 UTC

Exact review `review-20260930T144633Z.json` and separate epoch read preserved;
manual archive 1,213,905/16,777,216 bytes after guarded writes. All 41 closes
exact and negative, no aborts, complete coverage. No new winners.

- Cooldown: 21 paired/−$44.5702; no failed-hedge closes.
- Premium: twelve/−$20.4497; seven paired/−$12.3626, five failed/−$8.0870.
- Convergence: eight/−$9.7006; one paired/−$0.9231, seven failed/−$8.7775.
- Twelve Hyperliquid price-limit rejections. Portfolios remain separate.

Cooldown fees $8.7975, stress $10.4877, capital $0.0007328, funding zero;
without stress −$34.0825. Twenty exit-price comparisons worsened $7.534403
overall (eleven worse, nine better, one missing), median $0.077088, p95
$1.062571. All 21 request-to-flat observations present: median 1.287 s, p95
1.754 s. Premium's five available exit comparisons improved $1.326415
(two missing); convergence's single paired exit worsened $1.05731.

Four feeds connected, 115 pairs, CPU 89.28%, p95 lag 47.78 ms, RSS 315.05 MiB,
1,440.9 books/s, metadata age 567.9 s. Log evidence places scheduled discovery
at 14:37:03 UTC: 115 pairs, 61 assets, unavailable venues empty. The changed
market set rebuilt the stream manager. Its counters are per manager, while
snapshot status fields can retain old values until overwritten: the RH display
change 107 to 115 is **not an eight-gap increment** across this boundary.
Source inspection confirms invalidation/resubscription on gaps, with affected
entry intents cancelled. No new disconnect timestamp or funding error was
observed in the checked snapshots, which were fresh and showed connected feeds.
Around 14:49 CPU was
76.81%, p95 lag 57.91 ms, current lag 7.22 ms; busy reflects the rolling lag
threshold then. No process or code change; continue watching health.

Review had one Premium position/pending entry; later epoch snapshot flat.
Epoch: cooldown 1,391 exact plus three estimated/−$1,897.7145; Premium
391/−$710.9771; convergence 203/−$228.8614; conservative one/+$2.3198.
Twelve old win records and three legacy funding obligations remain. All 132
closes in reviews 66–68 were negative. Next checkpoint **15:06:33 UTC**.

Carry has 25 scheduled arrivals through 14:45, 30,492 sample bytes and no
reported collection errors. Economic readout remains at the fixed endpoint.

## Review 69 — 2026-09-30 15:06:33 UTC

Exact review and separate epoch read preserved; manual directory cap checked,
now 1,245,208/16,777,216 bytes. All 38 closes exact and negative; one convergence
abort, complete completion/abort coverage. Portfolios remain separate.

- Cooldown: twenty paired closes/−$27.6966; no failed-hedge closes.
- Premium: nine/−$17.9565; four paired/−$6.8516, five failed/−$11.1049.
- Convergence: nine/−$9.2764; four paired/−$4.0749, five failed/−$5.2015.
- Hyperliquid ten price-limit rejections; Core one price-limit and one
  notional-cap rejection. No new winners.

Cooldown fees $7.2707, stress $9.9882, capital $0.0007247, funding zero;
removing stress leaves −$17.7084. Its nineteen available exit comparisons
improved $1.475624 overall (twelve better, seven worse, one missing), median
−$0.04798, p95 adverse $0.263472. All twenty request-to-flat observations
present: median 1.377 s, p95 1.688 s. Premium's four comparisons improved
$0.031318 overall; convergence's three available improved $0.07889, one missing.

Four feeds connected, 115 pairs, CPU 76.64%, p95 lag 20.48 ms, RSS 312.54 MiB,
1,369.2 books/s, metadata age 1,769.4 s. RH displayed gap count remains 115
within the current stream-manager interval. Review and later snapshot each
had one cooldown position. Epoch: cooldown 1,412 exact plus three estimated/
−$1,926.2301; Premium 399/−$726.7104; convergence 212/−$238.1378;
conservative one/+$2.3198. Twelve earlier win records and three legacy funding
obligations remain. All 170 closes in reviews 66–69 were negative. No policy
or capital change. Next checkpoint **15:26:33 UTC**.

Carry status: 29 arrivals through 15:05, 35,412 sample bytes, no reported
collection errors. No interim price/economic evaluation.

## Review 70 — 2026-09-30 15:26:33 UTC

Exact review and separate epoch read preserved; guarded manual archive total
1,276,881/16,777,216 bytes. All 61 closes exact and negative, zero aborts,
complete coverage. No new winners; portfolios remain separate.

- Cooldown: 41/−$43.0369; forty paired/−$42.1543, one failed/−$0.8826.
- Premium: thirteen/−$22.2830; seven paired/−$10.8982, six failed/−$11.3849.
- Convergence: seven failed hedges/−$4.9933; no paired closes.
- Price-limit rejections: Hyperliquid eleven, Core one.

Cooldown fees $8.8014, stress $20.4739, capital $0.0014368, funding zero;
removing stress leaves −$22.5630. Its 39 available exit comparisons worsened
$0.544425 overall (twenty better, fifteen worse, four unchanged, one missing),
median −$0.00033, p95 adverse $0.331333. All forty paired request-to-flat
observations present: median 1.273 s, p95 1.711 s. Premium's seven exit
comparisons improved $0.149006 overall (three better, two worse, two unchanged).

Four feeds connected, 115 pairs, CPU 77.73%, p95 lag 15.16 ms, RSS 313.86 MiB,
1,333.4 books/s, metadata age 2,969.7 s. Review and later snapshot each had one
cooldown position. Epoch: cooldown 1,453 exact plus three estimated/
−$1,970.3436; Premium 412/−$748.9934; convergence 219/−$243.1311;
conservative one/+$2.3198. Twelve prior win records and three legacy funding
obligations remain. All 231 closes in reviews 66–70 were negative. Next
checkpoint **15:46:33 UTC**. No policy or capital change.

Carry has 33 arrivals through 15:25, 40,331 sample bytes, no reported errors.
The separately reviewed synthetic fee-inventory envelope (`e4fdbf6`) is a
future-model algebra note only; it does not alter this frozen study or provide
verified fee caps, matched inventory, or P&L.

## Review 71 — 2026-09-30 15:46:33 UTC

Exact review and separate epoch snapshot preserved; guarded manual archive
1,307,535/16,777,216 bytes. All 58 closes exact and negative. Three aborts
(two convergence, one Premium); complete completion and abort coverage.

- Cooldown: 45 paired closes/−$48.4952; no failed-hedge closes.
- Premium: eight/−$11.3790; seven paired/−$10.8799, one failed/−$0.4991.
- Convergence: five/−$6.8001; one paired/−$1.0737, four failed/−$5.7264.
- Price-limit rejections: Hyperliquid five, Core two, RH three. No new wins.

Cooldown fees $10.1464, stress $22.4739, capital $0.0016195, funding zero;
without stress −$26.0212. All 45 paired exit comparisons present: 23 better,
17 worse, five unchanged; net deterioration $0.235539, median −$0.002333,
p95 adverse $0.307036. Request-to-flat median 1.325 s, p95 1.976 s. Premium's
seven exit comparisons worsened $0.076732 overall; convergence's one worsened
$0.86736. Portfolios remain separate.

Four feeds connected, 115 pairs, CPU 69.01%, p95 lag 15.03 ms, RSS 312.69 MiB,
1,124.1 books/s, metadata age 564.7 s. Metadata/stream refresh again changed
message counters; RH's displayed 116 is not interpreted as a cross-generation
event delta. Review flat, later epoch snapshot one cooldown position. Epoch:
cooldown 1,497 exact plus three estimated/−$2,016.7691; Premium
420/−$760.3724; convergence 224/−$249.9312; conservative one/+$2.3198.
Twelve old win records and three legacy funding obligations remain. All 289
closes in reviews 66–71 were negative. No policy/capital change. Next
checkpoint **16:06:33 UTC**.

Carry arrival check: all 37 due slots have files and `sampled` status, through
15:45; 45,242 sample bytes, zero overdue missing slots, no terminal error.
This status checks HTTP arrival/deadline/clock gates, not native quote/RPC
semantics or economics, which remain deferred to the frozen endpoint.

## Review 72 — 2026-09-30 16:06:33 UTC

Exact daemon report, separate epoch snapshot and the sole positive completion
preserved; guarded manual archive 1,345,474/16,777,216 bytes. All 49 closes exact:
48 losses and one gain. Zero aborts; complete completion and abort coverage.

- Cooldown: 39 paired closes/−$39.8568; no failed-hedge closes.
- Premium: seven/−$11.0503; six paired/−$9.3169, one failed/−$1.7334.
- Convergence: three failed hedges/−$1.6108, including one gain; no paired closes.
- Four Hyperliquid price-limit rejections (three convergence, one Premium).

The [preserved gain](../reports/live-review-catchup/review72-positive-records.json)
is ENA, ID `1790784145266776-22318-convergence`, closed at 16:02:27.405 UTC.
Its Hyperliquid long was rejected at the price limit; only the Core short of
3,693 ENA filled. Entry proceeds $999.93915 less buyback $999.3258 produced
$0.61335 price P&L. Fees and fully reconciled funding were zero; $0.499969575
stress plus $0.000002611971 capital left **+$0.1133778130**. All remaining
quantities are zero. Exposure lasted 1.647522 seconds. This is a failed-hedge
rescue with directional exposure; it supplies no paired-cycle win.

Cooldown fees $8.8915, stress $19.4783, capital $0.0013984, funding zero;
without stress −$20.3785. All 39 paired exit comparisons present: fourteen
better, twenty worse, five unchanged; net deterioration $0.052618, median
$0.002867, p95 adverse $0.176035. Request-to-flat median 1.290 s, p95 1.700 s.
Premium's six comparisons improved $0.101822 overall. Separate portfolios
must not be combined into an independently achievable result.

Four feeds connected, 115 pairs, CPU 62.36%, p95 lag 13.98 ms, RSS 317.65 MiB,
1,017.2 books/s, metadata age 1,763.2 s. Review and later snapshot each had one
cooldown position. Epoch: cooldown 1,540 exact plus three estimated/
−$2,057.6016; Premium 427/−$771.4227; convergence 227/−$251.5420;
conservative one/+$2.3198. Thirteen epoch win records: two paired and eleven
failed-hedge rescues. Three legacy funding obligations retained. All active
strategy windows remain negative; no policy/capital change. Next checkpoint
**16:26:33 UTC**.

Carry has all 41 due arrivals through 16:05, 50,175 sample bytes, zero overdue
missing files and no terminal error. Native quote validation and economics
remain deferred to the frozen endpoint.

## Review 73 — 2026-09-30 16:26:33 UTC

Exact report and separate epoch snapshot preserved; guarded manual archive
1,375,366/16,777,216 bytes. All forty closes exact and negative, with no aborts
and complete completion/abort coverage. No new winners.

- Cooldown: 34 paired closes/−$41.3033; no failed-hedge closes.
- Premium: five/−$10.9282; three paired/−$5.4461, two failed/−$5.4821.
- Convergence: one failed hedge/−$0.7558; no paired closes.
- Three Hyperliquid price-limit rejections (two Premium, one convergence).

Cooldown fees $14.9838, stress $16.9710, capital $0.0012055, funding zero;
without stress −$24.3323. Its 33 available exit comparisons improved $0.265775
overall (sixteen better, thirteen worse, four unchanged, one missing request
price); median approximately zero, p95 adverse $0.22526. All 34 paired
request-to-flat observations present: median 1.197 s, p95 1.605 s. Premium's
two available exit comparisons improved $0.04327 overall (one better, one
unchanged, one missing request price).

Four feeds connected, 115 pairs, CPU 69.46%, p95 lag 10.98 ms, RSS 316.35 MiB,
1,102.8 books/s, metadata age 2,963.4 s. Review and later epoch snapshot flat.
Epoch: cooldown 1,573 exact plus three estimated/−$2,098.8341; Premium
432/−$782.3509; convergence 228/−$252.2978; conservative one/+$2.3198.
Thirteen prior epoch win records and three legacy funding obligations remain.
No policy/capital change. Next checkpoint **16:46:33 UTC**.

Carry has all 45 due arrivals through 16:25, 55,134 sample bytes, zero overdue
missing files, no terminal error and no interim economic evaluation.
