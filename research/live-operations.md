# Active paper research operations

Current process summary: 2026-09-30 05:46 UTC. All processes below are paper simulation or
public quote observation. No private keys or real orders are involved.

| Process | PID | Output | Expected end |
|---|---:|---|---|
| Production collector, original ledgers, 10s/10-cent exit | 3280600 | data/paper-monitor → paper-monitor-10s | Continuous |
| Scheduled audit capture, 1,200s cadence | 2765645 | data/strategy-reviews | Continuous |
| Passive-exit v1 public capture, restarted | stopped | data/raw/rh-passive-exit-v1/20260930T0252Z | Completed 03:42:58 UTC |
| One-shot strict replay supervisor | stopped | reports/rh-passive-exit-v1-restart/supervisor | Completed 03:58:17 UTC, exit 0 |
| One-shot corrected replay supervisor | stopped | reports/rh-passive-exit-v1-restart/corrected-supervisor | Completed 03:58:14 UTC, exit 0 |
| Exploratory ACK base supervisor / child | stopped | reports/rh-passive-ack-exploratory/base | Completed 04:26:25 UTC, exit 0 |
| Exploratory ACK plus200 supervisor / child | stopped | reports/rh-passive-ack-exploratory/plus200 | Completed 04:23:27 UTC, exit 0 |
| Legacy horizon v1, depth | stopped | data/horizon-research | Ended 18:14 UTC |
| Legacy horizon v1, BBO | stopped | data/horizon-research-bbo | Ended 18:23:39 UTC |
| Horizon v2, BBO, four frozen models | stopped | data/horizon-research-v2-bbo | Ended 18:45:22 UTC |
| Corrected paper source pilot, depth | stopped | data/paper-monitor-feed-v2-depth | Ended 18:45:52 UTC |
| Corrected paper source pilot, BBO | stopped | data/paper-monitor-feed-v2-bbo | Ended 18:45:52 UTC |
| Fixed-original-quantity quote study | stopped | data/fixed-markout-research-v1-bbo | Ended 18:43:22 UTC |
| BTC/ETH public trade/quote capture | stopped | data/raw/maker-capture/20260929T1823Z | Ended 18:29:56 UTC at cap |

Do not assume a PID is still live: verify `/proc/<pid>/cmdline` and snapshot
age. Old paper feed pilots `paper-monitor-feed-depth` and `-bbo` are stopped
and preserved because of the partial-exit accounting defect. Their final
report is [flawed-pilot-final.md](../reports/feed-experiment/flawed-pilot-final.md).

## Next review and interpretation

Review 41 was actively read at 05:46 UTC. **Next: 06:06:33 UTC**.
Read `data/strategy-reviews/latest.json`; do not also run a one-shot capture
against that output, because it advances the same baseline. The scheduler
collects evidence; the active agent researches and evaluates changes.

The corrected passive replay was separately frozen at 03:18:43 UTC and
launched after capture stopped, with the wrapper's separate corrected
output directory. The original supervisor launches strict v1 only. Versioned TUI
accounting was deployed at 03:36:13 UTC; existing viewers need a fresh
`scripts/monitor.py --watch` invocation to load the layout. Later sections
below are a chronological operations journal; their older PIDs and deadlines
are historical.

Both frozen replays completed without errors. The
[readout](../reports/rh-passive-exit-v1-restart/readout.md) reports all 29
known complete branches negative and 99 unknown; primary XAG had 56 closed
no-flow attempts followed by cancellation uncertainty. The comparison found
no changed admissions or execution classifications from the entry correction.
Eleven halted branches with retained passive asks have provisional closed
contributions pending separate historical adjudication. No strategy was
promoted. The exploratory ACK replay completed in both declared scenarios;
no further raw capture has started. Both ACK processes use the same completed
archive, separate outputs and 21 unchanged dependencies. Both stayed within
the one-hour deadline, 128 MB derived cap and 1 MB log cap. Their model changes combine
assumed clocks with coverage, ID and historical-evidence guards; these are
post-capture sensitivities, not prospective confirmations or isolated latency
effects. Launch and implementation records are in
`reports/rh-passive-ack-exploratory/`. Its [readout](../reports/rh-passive-ack-exploratory/readout.md)
shows 12 conditional negative complete portfolios in base and none complete in
plus200; all remaining totals unknown. No promotion follows.

### Versioned P&L rollout, 03:36 UTC

Commit `6fa0f4e` passed 42 targeted tests and independent accounting review.
The old collector exited gracefully after its final checkpoint; new collector
3280600 resumed the same database, ten-second exit request, $0.10 target and
shadow strategies. Reviewer 2765645 and the separate capture/supervisor stayed
running. No wallet was replenished. The cutover's legacy ledger matches the
stopped checkpoint exactly. Three old funding-pending positions retained their
legacy origin; the fourth old position closed after restart and was excluded
from current-version results. All four feeds reconnected.

Current version **e3e83cda71a6**, epoch **b8204da0453a4e8a940d3d1b3c33714e**,
began **03:36:13.545437 UTC**. At the first verification, cooldown had two new
settled losses totaling −$1.986147; all other current totals were zero. This
starts measurement at rollout and does not erase or reclassify earlier losses.
All 20 frozen passive-replay source hashes still match. See
`reports/paper-strategy-epoch-review/rollout.json`, `rollout-verification.json`
and `LIVE-80x24.txt`. The already running viewer retains its loaded old layout;
Ctrl-C and `.venv/bin/python scripts/monitor.py --watch` loads the new one.

### Passive capture completed and both replays launched, 03:43 UTC

The restarted capture ran **02:52:57.958514–03:42:58.061557 UTC**, ending
at its duration limit without truncation or recorded capture errors. It
contains **124,019 records**, 48,680,716 compressed payload bytes and
48,931,302 total archive bytes. Gzip SHA-256:
`c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6`.
The copied final manifest is
`reports/rh-passive-exit-v1-restart/capture-complete-manifest.json`.

Strict replay started automatically at 03:42:59 after stable-manifest and
source/raw hash checks. Corrected supervisor 3296006 launched at 03:43:34
using the committed `run-corrected-once.py`, with the same stopped archive
and 20 frozen sources. Both runs have a 3,600-second deadline and 1 MB log cap,
plus the existing audit/result bounds. Their output directories remain
separate. A completed capture is not a claim of valid queue/fill coverage
or profitable paper outcomes; those await the replay readouts and comparison.

Production keeps targeted REST and depth feeds. The two source pilots disable
REST identically to isolate transport behavior; neither represents the full
production configuration. They contain independent fee/policy scenario ledgers,
not additive income. Their accounting uses committed decimal-lot fix 16be742.
The fresh pilots had no positions older than 45 seconds at an early check,
with 101 BBO partial fills already exercised.

Horizon forecasts measure basis-level quote errors at variable quantity. The
v2 study fixes outcome detection missed by the legacy sampling cap and exports
frozen forecasts for route/time-block analysis. Keep its results separate from
v1. Improved quote MAE does not establish a profitable execution policy.

## Current evidence and decisions

- Production review 8: baseline 182 closes / -$198.08; historical median eight
  closes / -$12.16; confirmed and conservative no entries. No thresholds relaxed.
- Chronological holdout: 527 closes / -$624.27. All selected entry filters lose.
  [Filter study](../reports/filter-experiments/REPORT.md).
- Same holdout still loses $228.90 with both trading fees and modeled 5 bp
  reserve removed. [Fee sensitivity](../reports/fee-sensitivity/REPORT.md).
- No tested asset paid back four Standard taker fees through one day of
  holdout funding alone. [Funding screen](../reports/funding-carry/REPORT.md).
- BBO substantially speeds source updates, but displayed top-level depth can
  be insufficient and failed/partial hedges remain material. An execution bug
  invalidated profitability ranking of the first source pilot.
- Next-phase research: original-quantity quote economics with four fees, and
  conservative maker/hedge feasibility. These need their own prospective
  evidence before any production strategy promotion.

## Storage and review commands

At 18:11 UTC: production 51 MiB; the four finite paper pilot directories totaled
about 28 MiB; each horizon directory was below 1 MiB; audit output 220 KiB.
Each pilot has a 32 MiB DB target, bounded trade/evidence rings, and rotating
logs. Horizon snapshots are replaced and their row counts are capped. Audits
retain at most 72 reports of 256 KiB each, plus state/latest and rotating logs.
There is no unattended loop creating more experiment directories.

```bash
.venv/bin/python scripts/compare_feed_experiments.py \
  --depth data/paper-monitor-feed-v2-depth \
  --bbo data/paper-monitor-feed-v2-bbo \
  --name corrected-pilot-latest
# Run after the v2 observer stops:
.venv/bin/python scripts/analyze_horizon.py \
  data/horizon-research-v2-bbo/horizon_snapshot.json \
  --out reports/horizon-v2
```


### Deployed display corrections

Snapshot detachment 5626345 deployed at 18:27:05 UTC. The captured display now
owns copies of mutable wallet/episode fields. Main SQLite checkpoints already
used a detached copy. Finite studies retain their original loaded code.

Position display correction 1297815 deployed at about 18:33:40 UTC as PID
1922387. Two XAG positions shown as 8,000+ seconds old were already flat:
actual holding times 12.1267s (premium) and 11.7846s (Standard). Uncertain Aster
funding near the 16:00 boundary keeps accounting unresolved. Snapshots now
separate these into `pending_settlements`, with `holding_seconds` and
`funding_wait_seconds`. Engine ledgers and venue capital reservations are
preserved. Existing viewers stop listing them as active; restarting a viewer
also loads the new settlement-count line. UI resize and Ctrl-C tests passed.

The fixed-quantity pilot started at 18:23:22 UTC from commit 93dfc86. Its
Standard fees are frozen from current discovery metadata; four fee notionals,
original-size future exits, censored depth, and frozen forecast selections are
recorded. It is an optimistic zero-entry-latency quote screen, not filled P&L.
All four forecast models have predeclared $0/$0.25 screens; the linear forecast
is primary and persistence a reference. The [stopped analysis](../reports/fixed-markout-v1/README.md) is archived: 1,595
matched quotes, one positive after four fees, none after extra reserve.

Maker capture also started at 18:23:22 UTC from d880579. It uses public BTC/ETH
quotes/trades on HL, Core and RH, with a hard ten-minute/25-MB total cap. The
later five-line unknown-market invalid-trade guard was committed separately;
its offline analysis must invalidate both HL trade streams if such a malformed
frame is present. `wire_ok` means only frame parsing/nonce continuity. It is
not an executable quote, proven queue position or maker fill. No maker P&L
classifier is deployed.

Maker capture reached its 25 MB total cap at 18:29:56 UTC after 68,229 records;
manifest errors were empty. [Stopped-archive analysis](maker-capture-analysis.md) is complete: no positive
BTC/ETH four-taker quote outcome at any tested 1/2/5/10s horizon.


## Completed round at 18:47 UTC

- [Corrected matched source pilots](../reports/feed-experiment/corrected-pilot-final.md):
  BBO improves observation coverage and enables paired entries; both baselines
  lose. Their disabled REST and incomplete retained rows limit comparison to
  production. Positions at duration end remain frozen, explicitly reported.
- [Horizon v2](../reports/horizon-v2/README.md): conditional-linear MAE 0.927bp
  versus persistence 1.094bp over 2,797 matched scored anchors. No profit claim.
- [Fixed quantity](../reports/fixed-markout-v1/README.md): 2,134 anchors, 1,595
  matched, 539 censored; primary screen selects zero; four observed secondary
  median-screen selections all lose. No strategy promoted.
- [Maker archive](maker-capture-analysis.md): 394 seconds, bounded 25MB;
  startup replay excluded. Maker quote/trade-flow overlaps are not fills or
  profitable unwinds. All eight venue/horizon four-taker groups have zero
  positive after-fee displayed markouts.

Only production collector PID 1922387 and audit scheduler PID 1749934 continue.
Scheduled captures are automatic; AI research/strategy decisions need an active
session. Next useful research is a predeclared maker post-flow hedge and unwind
study with explicit queue/acknowledgement assumptions, not relaxing taker gates.
No further background experiment directories are being created.


## Active continuation, 19:34 UTC onward

The user identified that strategy reviews had stopped after the prior final
response. The evidence scheduler had stayed live. Root reviewed both missed
windows at 19:34 and resumed active work; baseline losses were -$212.20 and
-$220.29, no policy promoted. The 19:36 accounting reconciliation passed.

Fresh maker public capture PID 2028209 started 19:39:03.940 UTC into
`data/raw/maker-capture/20260929T1939Z`, maximum 420 seconds / 25,000,000 bytes.
Frozen metadata and rule hashes were committed before launch in
`reports/maker-roundtrip-v1/`. Expected stop by 19:46:04 UTC (or earlier cap).
No prospective outcomes are inspected until code and independent audit finish.
Old 18:23 data are exploratory: 12 complete primary conditional maker paths,
all negative after fees, with 15 other full-flow paths censored for shallow
hedge or exit books. The model is an optimistic quote diagnostic, omitting
Standard Lighter's 300ms taker processing; it is not account-compatible fills.

Next scheduled audit 19:46:33 UTC; root is staying active through the research
and scheduled check rather than treating background capture as AI review.

## Active review and research, 19:46–20:00 UTC

Review 11 was read on schedule at 19:46 UTC; see [review journal](review-loop.md).
Maker capture PID 2028209 stopped normally at 19:46:04 after 420 seconds.
The prospective primary scenario had 14 complete conditional quote paths,
all negative after four fees. Nine hedge and nine exit outcomes were censored;
they are not zero-profit paths. Results and immutable design hashes are in
[prospective maker analysis](maker-roundtrip-prospective.md), commit 157c701.

The main collector and review scheduler remain running. At 19:56 all four
feeds were connected, snapshot age was 2.2 seconds, and the main output
directory occupied 54.6 MB. Two flat XAG records still await uncertain
funding settlement; neither has remaining position exposure.

A separate impulse-dislocation observer is under code review, not yet launched.
Root required entry delay to begin at confirmation, both venue source AND
receipt timestamps to follow the due time, and explicit stale-history gates.
Eight physical BTC/ETH/NVDA/XAG pairs, two arrival scenarios per candidate,
original quantity, four fees, and bounded storage are planned. The next
scheduled strategy review is approximately 20:06:33 UTC / 4:06 p.m. ET.

Impulse pilot PID **2090065** started **20:00:36 UTC**, duration 1,200 seconds,
expected stop **20:20:37 UTC**. Output `data/impulse-research-v1`; frozen code,
method and eight-pair metadata are committed in **473e0c3**. Independent core
audit and 14 focused observer/analyzer tests passed, including a real-model
stopped-snapshot integration test. All three subscribed venue feeds connected
at startup. Production entry policies are unchanged. This is an optimistic
paired quote experiment, not a fill simulator or cash profit tally.

## Status at 20:21 UTC

- Production PID 1922387 and review scheduler PID 1749934 remain active.
  Review 12 was read on time at 20:06; next scheduled review 20:26:33 UTC.
- Impulse PID 2090065 stopped normally at 20:20:37 after 1,200 seconds.
  [Final evidence](../reports/impulse-v1/README.md): one NVDA/Core arm rejected
  at confirmation, zero selected entries, zero accounting residuals. Frozen
  method/code hashes matched; no policy promoted and no timing/profit inference.
- NVDA/XAG maker launch PID 2167455 at 20:20:30 failed before collection:
  root's wrapper had created the output directory, whereas `maker_capture.py`
  requires it absent. No data were collected; `failed-launch.json` preserves
  that attempt. Corrected PID **2173403** began **20:22:56 UTC** from **e6d5706**,
  with its process and capture file verified one second later. Output
  `data/raw/maker-capture/20260929T2022Z`, 420 seconds / 25 MB maximum; expected
  stop **20:29:57 UTC** or earlier at the byte cap. Frozen unit/fee evidence
  and delayed hedge/exit rules were unchanged. No orders are sent.
- A separate HL-first paper experiment is being implemented. Both its control
  and treatment will use the same WebSocket stream, without extra REST calls.
  Version 1 requires a full original-size HL fill before sending the other
  leg; a partial HL fill is flattened in full. No live process or main-policy
  change has been made for that study.

## Status at 20:40 UTC

- Review 13 was read on time at 20:26; next review is 20:46:33 UTC.
- Maker capture PID 2173403 stopped normally at 20:29:56, with 10,619 records
  and 3.76 MB total storage. Frozen input hashes matched. Its single silver
  flow case had no eligible complete exit, so net P&L remains unknown.
  [Results and coverage](maker-equity-results.md) distinguish the frozen
  result from a post hoc inspection of later, ineligible quotes.
- The HL-first experiment passed 31 focused/adjacent tests and independent
  storage and accounting review. Root requested normalized exposure metrics
  before freezing and launching the 19-pair, 20-minute isolated trial.

HL-first trial PID **2256789** launched at **20:40:39 UTC**, from frozen
commit **7742531**, with 19 routes and a 1,200-second duration. Process and
snapshot were verified after one second. Expected stop **21:00:39 UTC**.
Output `data/contingent-research-v1`; public WebSockets only, no orders.
Production monitor and 20-minute review loop continue independently.

## Status at 21:08 UTC

- Review 15 read on schedule at 21:06; next due 21:26:33 UTC.
- Contingent PID 2256789 stopped normally at 21:00:39, 1,200.018 seconds.
  One GRAM candidate: simultaneous control -$0.9311888293, HL-first zero-fill
  abort. Complete cohort evidence and hashes are in
  [final analysis](../reports/contingent-v1/final-analysis/REPORT.md).
  One avoided failed hedge is not demonstrated profitable execution.
- The systematic [strategy review](sota-strategy-review.md) now prioritizes
  RH passive bids priced from HL hedge proceeds and expected closing basis.
  A separate public-data experiment is being prepared, with $100/$250/$500/
  $1,000 sizes and $1,000 primary benchmark, following the user's correction.
- The [book reconstruction](maker-book-archive.md) recovers much better RH
  coverage than ticker. Earlier frozen results remain intact; the old size
  replay's completed outcomes were Core-only and do not reject the RH idea.
- A 60-second isolated HL fast-L2 probe completed at 20:52:47. It observed
  roughly 0.54s source cadence versus 5.38s default L2, using five levels
  versus twenty. It supports a better research feed; it proves no fills or
  strategy profits. Production subscriptions remain unchanged.

## Status at 21:28 UTC

- Scheduled review 16 was generated at 21:26:33 and actively read at 21:28.
  Next due 21:46:33 UTC. Production monitor and review loop remain active.
- RH maker collector PID **2445190** launched **21:21:32 UTC** from
  **9054b25**. Output `data/raw/rh-small-maker/20260929T212132Z`, duration
  3,000 seconds, default raw+metadata cap 384 MB. Output file and process
  verified after one second; subsequent byte growth confirms collection.
  Frozen public metadata, plan and launch record are in
  [rh-small-maker-v1](../reports/rh-small-maker-v1/launch.json).
- Calibration ends about **21:51:32 UTC**; evaluation then runs to about
  **22:11:32 UTC**. Replay implementation must be frozen before evaluation
  begins. The experiment method was fixed before capture. No private orders.
- Latest production exposure check found actual held positions below ten
  seconds; old XAG records are flat funding settlements, not stale exposure.

## Status at 21:47 UTC

- Review 17 was actively read on schedule; next due 22:06:33 UTC. All four
  production feeds connected; 66.06% of one core, 12.15ms p95 loop lag.
- RH maker capture remains collecting (20 MiB at 21:45, 384 MB cap), with
  holdout planned 21:51:32–22:11:32. Implementation freeze **38950ef** at
  21:38:24 records source hashes and 46 focused tests; no capture outcomes
  have been inspected. Production directory was 52 MiB and reviews 500 KiB.
- Separate historical hedge-venue comparison and symmetric maker-sell
  follow-up preserve the current frozen pilot.

## Status at 22:07 UTC

- Review 18 actively read on schedule; next due 22:26:33 UTC. All four
  production feeds connected; 55.39% of one core, 10.19ms p95 loop lag.
- Original RH maker capture remains frozen and unread, planned stop
  22:11:32. Run original replay after its terminal manifest exists, then
  the lifecycle report and separate retired-quote late-flow adjudicator.
  The latter defect was independently reproduced before any outcome read
  and recorded in f313525; original source files remain unchanged.
- A separate symmetric bid/ask model and guarded execution driver are being
  tested for a future capture. No symmetric capture or protocol is frozen
  or running yet. It must not use the current pilot as a new holdout.

Original RH maker capture stopped normally at **22:11:32.790024 UTC**,
3,000.193 seconds after actual start 21:21:32.597194. Raw frames: 104,790,
41,368,405 compressed bytes, SHA-256
`07cf628056fda14b2d93553fdd1591ae842e260455d9bb47b249967f113c90fa`.
One RH reconnect was during calibration; no holdout reconnect in manifest.
Frozen replay PID **2656054** / root exec session **31859** started about
22:11:44, output `data/derived/rh-small-maker-v1`; at 22:13 it used one
CPU core and 126 MiB RSS. All 23 frozen file hashes matched before replay.
After it finishes, run lifecycle summary and independent retired-quote
late-flow adjudication. Next scheduled production review remains 22:26:33.

## Status at 22:27 UTC

- Review 19 actively read on schedule at 22:26:33. Baseline 91 paired
  closes -$109.8851, cooldown 32 paired -$45.0755, historical-median one
  failed hedge -$4.7722; zero wins. Conservative/confirmed no completions.
  All four feeds connected, CPU 67.48% of one core, p95 loop lag 18.29ms.
- Original replay PID 2656054 remains running. Cached variant PID 2670694,
  root exec session 33191, writes `data/derived/rh-small-maker-v1-cached`.
  Both outputs remain bounded; no new capture is running. Current wrapper
  and independent variant provenance checks committed as 4f97d38/00641bd.
- Next scheduled production review **22:46:33 UTC / 6:46 p.m. ET**.

## Status at 22:54 UTC

- Review 20 actively read on schedule at 22:46:33. Baseline 92 closes
  -$117.466 (90 paired, two failed hedges), cooldown 32 -$76.173, median
  one failed hedge +$0.433 and two aborts. No winning paired closes or
  policy promotion. Next due **23:06:33 UTC / 7:06 p.m. ET**.
- Exit-request instrumentation deployed with checkpointed restart at
  **22:45:28 UTC**, collector PID **2765644**, review loop **2765645**.
  All four feeds reconnected. All three exposed positions present at the
  stopped checkpoint subsequently closed with zero residual; two old flat
  funding-pending records remain preserved. Balances/counters were retained.
  Four baseline exits already provide valid request-price measurements;
  see `reports/unwind-instrumentation/first-review.json`.
- Cached RH maker replay completed with no errors, 96 branches. Its
  independent late-flow check passed without flags; lifecycle summary
  completed after correcting Decimal aggregation order by exactly 1E-28
  in one branch. Readout: `reports/rh-small-maker-v1/CACHED-RESULTS.md`.
  Original reference PID **2656054** remains running; do not mistake the
  completed cached variant for a completed full-original comparison.
- Canonical AMM capture PID 2749337 stopped normally at 22:46:07. Five
  rounds, 320 quoter results, 20 HL books, 542,478 bytes. Its separate
  readout is `reports/rh-small-canonical-amm/REPORT.md`. No capture is still
  running. Future symmetric maker method has not been frozen or launched.


## Status at 23:08 UTC

Review 21 actively read on schedule: baseline 91 completions −$102.0626,
cooldown 14 −$27.9128, median five failed hedges −$8.4011. No policy promoted.
86 valid baseline exit observations show only +$0.057486 aggregate price
deterioration after the request; missing/tail caveats are in the review journal.
Collector 2765644 and scheduler 2765645 remain running, four feeds connected.
Next report due **23:26:33 UTC / 7:26 p.m. ET**. Original maker reference replay
2656054 remains pending; cached results are separately labeled. No new raw
capture. Data 601 MiB and reports 25 MiB at 23:05 UTC, bounded as documented.

Committed full-cycle strategy research and stopped quote-hurdle analyzer in
181e43e (four focused analyzer tests; ten combined with AMM tests). Findings
and proposed tests: `research/unwind-strategy-decision.md`. The live ten-second
policy remains the control; passive inventory exits and longer horizons are
specified future experiments, not deployed replacements.


## Status at 02:30 UTC, 30 September

User explicitly requested the passive-exit experiment and an ongoing
experiment/data/research loop until stopped or convincingly positive paper
P&L. The mandate and operational success threshold are in
`research/active-experiment-loop.md`.

- Audited v1 implementation **a0f8e50**, protocol **6886d59**, frozen
  **02:27:26.148934 UTC** before capture. Root's combined 31 focused tests
  pass; independent reviewer also ran related legacy tests (43 total).
- Active collector **PID 2953071**, root exec session **70643**:
  `data/raw/rh-passive-exit-v1/20260930T0227Z`. Fifty minutes total;
  calibration ends about **02:57:32**, capture about **03:17:32 UTC**.
  Exact start/end comes from the terminal manifest. First connection record
  02:27:34.126588; 983 KB compressed at the first running check.
- Raw cap384 MB, audit96 MB, summary32 MB, total512 MB study maximum.
  Source closure in `reports/rh-passive-exit-v1/protocol.json` is immutable
  through replay. No current holdout result has been inspected or used.
- Replay after collector completion:
  `.venv/bin/python scripts/analyze_rh_passive_exit.py replay --capture data/raw/rh-passive-exit-v1/20260930T0227Z --protocol reports/rh-passive-exit-v1/protocol.json --out data/derived/rh-passive-exit-v1`
- Production monitor **2765644**, review loop **2765645** remain running.
  Review31 read; next **02:46:33 UTC**. Baseline flat/capital-limited;
  cooldown continues losing. Original frozen reference **2656054** remains
  running (~4h17 elapsed at02:28); cached prior results separately labeled.
- Parallel stopped-data research covers RH entry queues and HL/Core hedge
  economics. Any resulting strategy change will use a new method and fresh
  data; current v1 is unchanged. No other economic capture is running.


## Restart after interruption, 02:53 UTC

The user requested continuing with gpt-6.1-sol subagents at high effort. All
previous subagents were absent from the live task list; new agents resumed
their saved files. The production monitor/reviewer (2765644/2765645) survived.
The temporary passive capture 2953071 and original reference replay 2656054
were no longer running. The first passive raw file was 22,966,216 bytes with
no final manifest; it is preserved as an interrupted, unscored study, never
spliced into the replacement. The original reference replay has only its
empty audit output; full original/cached equivalence remains unestablished.

Fresh three-response metadata was fetched at 02:51 UTC. All normalized market
rule fields match the prior study. Unchanged strategy sources and fresh
metadata were frozen at 02:52:37.908796 UTC in commit 014a761. Replacement
collector PID 3045038 launched detached at 02:52:57.775724 UTC:
`data/raw/rh-passive-exit-v1/20260930T0252Z`. Calibration ends approximately
03:22:58, capture ends 03:42:58. Exact time comes from its final manifest.
Protocol: `reports/rh-passive-exit-v1-restart/protocol.json`; launch record
and capture log are alongside it. Cap 384 MB; unchanged 30+20 minute method.
Replay output must be a new `data/derived/rh-passive-exit-v1-restart` directory.
A bounded one-shot completion/replay watcher is being prepared.

Production review 32 was actively read at 02:46; next 03:06:33 UTC. No production
ledger has been replenished or strategy promoted.
