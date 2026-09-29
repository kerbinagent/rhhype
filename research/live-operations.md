# Active paper research operations

Last updated: 2026-09-29 18:11 UTC. All processes below are paper simulation or
public quote observation. No private keys or real orders are involved.

| Process | PID | Output | Expected end |
|---|---:|---|---|
| Production collector, original ledgers, 10s/10-cent exit | 1812668 | data/paper-monitor → paper-monitor-10s | Continuous |
| Scheduled audit capture, 1,200s cadence | 1749934 | data/strategy-reviews | Continuous |
| Legacy horizon v1, depth | 1691034 | data/horizon-research | ~18:14 UTC |
| Legacy horizon v1, BBO | 1727752 | data/horizon-research-bbo | ~18:23 UTC |
| Horizon v2, BBO, four frozen models | 1806918 | data/horizon-research-v2-bbo | ~18:45 UTC |
| Corrected paper source pilot, depth | 1807958 | data/paper-monitor-feed-v2-depth | ~18:46 UTC |
| Corrected paper source pilot, BBO | 1807959 | data/paper-monitor-feed-v2-bbo | ~18:46 UTC |

Do not assume a PID is still live: verify `/proc/<pid>/cmdline` and snapshot
age. Old paper feed pilots `paper-monitor-feed-depth` and `-bbo` are stopped
and preserved because of the partial-exit accounting defect. Their final
report is [flawed-pilot-final.md](../reports/feed-experiment/flawed-pilot-final.md).

## Next review and interpretation

The automatic loop captured the 18:06:33 scheduled review. **Next: 18:26:33 UTC**.
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

- Production review 6: baseline 191 closes / -$247.78; historical median five
  closes / -$4.53; confirmed and conservative no entries. No thresholds relaxed.
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
