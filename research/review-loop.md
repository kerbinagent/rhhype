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
