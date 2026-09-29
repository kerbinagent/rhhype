# Active paper research operations

Last updated: 2026-09-29 19:43 UTC. All processes below are paper simulation or
public quote observation. No private keys or real orders are involved.

| Process | PID | Output | Expected end |
|---|---:|---|---|
| Production collector, original ledgers, 10s/10-cent exit | 1922387 | data/paper-monitor → paper-monitor-10s | Continuous |
| Scheduled audit capture, 1,200s cadence | 1749934 | data/strategy-reviews | Continuous |
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

The automatic loop captured the 19:06:33 and 19:26:33 scheduled reviews; the active agent reviewed them late at 19:34 UTC. **Next: 19:46:33 UTC**.
Read `data/strategy-reviews/latest.json`; do not also run a one-shot capture
against that output, because it advances the same baseline. The scheduler
collects evidence; the active agent researches and evaluates changes.

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
