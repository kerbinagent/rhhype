# Active paper research operations

Last updated: 2026-09-29 18:35 UTC. All processes below are paper simulation or
public quote observation. No private keys or real orders are involved.

| Process | PID | Output | Expected end |
|---|---:|---|---|
| Production collector, original ledgers, 10s/10-cent exit | 1922387 | data/paper-monitor → paper-monitor-10s | Continuous |
| Scheduled audit capture, 1,200s cadence | 1749934 | data/strategy-reviews | Continuous |
| Legacy horizon v1, depth | stopped | data/horizon-research | Ended 18:14 UTC |
| Legacy horizon v1, BBO | stopped | data/horizon-research-bbo | Ended 18:23:39 UTC |
| Horizon v2, BBO, four frozen models | 1806918 | data/horizon-research-v2-bbo | ~18:45 UTC |
| Corrected paper source pilot, depth | 1807958 | data/paper-monitor-feed-v2-depth | ~18:46 UTC |
| Corrected paper source pilot, BBO | 1807959 | data/paper-monitor-feed-v2-bbo | ~18:46 UTC |
| Fixed-original-quantity quote study | 1876679 | data/fixed-markout-research-v1-bbo | 18:43:22 UTC |
| BTC/ETH public trade/quote capture | stopped | data/raw/maker-capture/20260929T1823Z | Ended 18:29:56 UTC at cap |

Do not assume a PID is still live: verify `/proc/<pid>/cmdline` and snapshot
age. Old paper feed pilots `paper-monitor-feed-depth` and `-bbo` are stopped
and preserved because of the partial-exit accounting defect. Their final
report is [flawed-pilot-final.md](../reports/feed-experiment/flawed-pilot-final.md).

## Next review and interpretation

The automatic loop captured the 18:26:33 scheduled review. **Next: 18:46:33 UTC**.
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

- Production review 7: baseline 185 closes / -$201.31; historical median four
  closes / -$5.73; confirmed and conservative no entries. No thresholds relaxed.
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
is primary and persistence a reference. Offline analysis is being prepared.

Maker capture also started at 18:23:22 UTC from d880579. It uses public BTC/ETH
quotes/trades on HL, Core and RH, with a hard ten-minute/25-MB total cap. The
later five-line unknown-market invalid-trade guard was committed separately;
its offline analysis must invalidate both HL trade streams if such a malformed
frame is present. `wire_ok` means only frame parsing/nonce continuity. It is
not an executable quote, proven queue position or maker fill. No maker P&L
classifier is deployed.

Maker capture reached its 25 MB total cap at 18:29:56 UTC after 68,229 records;
manifest errors were empty. Stopped-archive analysis is in progress.
