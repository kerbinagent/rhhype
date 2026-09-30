# Bounded public experiment storage

`scripts/experiment_storage.py` inventories only named managed roots under
`data/raw`. Its default root is `rh-passive-exit-v1`; additional roots must be
chosen from the code allowlist. It is **read-only**: no option deletes files.
This is deliberate while capture jobs can be active without a PID file and
may be invisible to a sandboxed process listing.

Run a dry plan with explicit budgets:

```bash
.venv/bin/python scripts/experiment_storage.py \
  --root rh-passive-exit-v1 --root rh-small-maker \
  --max-retained-studies 4 --max-total-bytes 512000000 \
  --out reports/experiment-storage/inventory.json
```

`--out` must be a new file; omit it for JSON on stdout. Output is capped at
1 MB. Budgets apply across the selected roots. “Retained studies” counts
studies that still have `frames.jsonl.gz`; “total bytes” sums apparent regular
file lengths, including manifests and metadata. The plan chooses the oldest
eligible compressed raw archive first and reports projected count and bytes.
If pinned or incomplete studies make a budget impossible, it says so rather
than treating them as cleanup candidates.

The planner names **only** `frames.jsonl.gz`. Manifests, captured metadata,
source/protocol records, and directories remain in place. It excludes a study
when its final manifest is missing, malformed, too large, not read-only, or
does not record a recognized completed end reason and valid end time/hash. It
also excludes recent completions (default one hour), any PID hint (including
one that appears stale inside this sandbox),
symlinks, special files, hard-linked raw frames, and paths outside the allowlist.
The frozen RH original capture at `rh-small-maker/20260929T212132Z` and the
earlier original maker capture at `maker-capture/20260929T1823Z` are pinned.
These checks are conservative planning gates, not permission to erase a study.

At 2026-09-30 02:43 UTC, a read-only inventory of the RH passive v1 and RH
small-maker roots found two raw archives totaling about 61.6 MB. The passive
v1 capture had no final manifest while running, so it was ineligible. The RH
small-maker original was complete but pinned. The plan proposed no removal.
No raw capture was modified.
