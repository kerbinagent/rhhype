# Experiment storage reconciliation after the completed passive capture

The 30 September 03:51 UTC inventory contains **seven raw archives and
166,973,971 apparent bytes** across the same six managed roots. The 512,000,000
byte limit is met, with 345,026,029 bytes of headroom. The four-archive count
target remains unmet. It cannot currently be met while preserving the required
raw evidence. A fixed prospective amendment to eight archives is proposed
below, preserving all seven and allowing only one further bounded study. The
four-archive value was a workspace planning target/example, not a user-imposed
requirement. No files were deleted, moved, renamed, or excluded from scope.

The [updated inventory](../reports/experiment-storage/inventory-20260930T0351Z.json)
uses the existing read-only planner and the existing one-hour completion age.
The [retention review](../reports/experiment-storage/retention-review-20260930T0351Z.json)
records exact file hashes, sizes, manifest evidence, published dependencies,
and replay status at the review time. Both artifacts are below the planner's
1 MB output bound. All seven raw files had unchanged size and modification
time during hashing. Hashing read 165,953,313 raw bytes without changing them.

## Scope and count

The selected roots remain `rh-passive-exit-v1`, `rh-passive-exit-preflight`,
`rh-small-maker`, `maker-capture`, `rh-maker-symmetric-v1`, and
`passive-three-venue`. The latter two contain no studies at this check.
“Study count” is the existing policy's physical archive count: directories
retaining nonempty `frames.jsonl.gz`, including preflights and interrupted
attempts. The empty `maker-capture/20260929T2020Z` directory contributes neither
a raw archive nor bytes.

This budget covers apparent regular-file lengths under those raw roots,
including manifests and metadata. It excludes production, derived replay
outputs, and reports; it is not a measurement of total workspace storage or
the raw-plus-derived per-study cap. Relative to the 03:26 inventory, the raw
scope grew by 16,712,389 bytes as the running capture completed; the archive
count stayed seven.

| Archive under `data/raw/` | Total bytes | Raw gzip bytes | Retention decision |
| --- | ---: | ---: | --- |
| `rh-passive-exit-v1/20260930T0252Z` | 48,931,302 | 48,680,716 | Preserve completed frozen input for both replays and reproducibility |
| `rh-passive-exit-v1/20260930T0227Z` | 23,212,036 | 22,966,216 | Preserve interrupted, unscored capture and interruption provenance |
| `rh-passive-exit-preflight/20260930T0222Z` | 855,162 | 603,977 | Only planner-eligible raw candidate; separate review required |
| `rh-small-maker/20260929T212132Z` | 41,620,769 | 41,368,405 | Existing pinned original |
| `maker-capture/20260929T1823Z` | 24,937,753 | 24,934,135 | Existing pinned original |
| `maker-capture/20260929T1939Z` | 23,658,122 | 23,644,715 | Preserve prospective BTC/ETH study and published diagnostics |
| `maker-capture/20260929T2022Z` | 3,758,827 | 3,755,149 | Preserve NVDA/XAG frozen study and published full-book diagnostics |

## Completed and interrupted passive inputs

The replacement capture ended at **03:42:58.061557 UTC** with `duration_limit`,
3000 configured seconds, `read_only: true`, `truncated: false`, and 124,019
records. Its gzip SHA-256 is
`c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6`, matching
the [final manifest](../data/raw/rh-passive-exit-v1/20260930T0252Z/manifest.json).
At review, the strict supervisor reported `replaying` and the correction
supervisor reported `replay_running`; both consume that same archive. Their
status hashes, the protocol hash, and the correction-freeze hash are recorded
in the retention review. Keep the input after these processes stop as well;
elapsed age alone does not make a frozen study's raw evidence disposable.

The interrupted predecessor still has no final manifest. The
[interruption record](live-operations.md) and
[experiment record](active-experiment-loop.md) explicitly preserve it as an
unscored attempt, with no scored holdout and no splicing into the replacement.
Its missing manifest is a retention exclusion, not permission to erase or
invent a completed terminal state.

## Exact conditional reclaimable candidate

The current planner proposes only
`data/raw/rh-passive-exit-preflight/20260930T0222Z/frames.jsonl.gz`, exactly
**603,977 bytes**. It is a 30-second read-only connectivity check that ended at
02:21:47.376444 UTC with `duration_limit` and no truncation, more than one hour
before the inventory. No PID hint, link, or unsafe file was present. Its hash
`44f84f78a71211ae22f7173b03e1a89acc65740bf04c203ac696b1d9f4874bda` matches both
the manifest and the saved [preflight diagnostic](../reports/rh-passive-exit-v1/preflight.json).
The diagnostic explicitly classifies it as neither calibration, holdout, nor
economic evidence, and records the verified raw/manifest hashes and counts.

This is a policy candidate, not an authorized deletion. Any later decision
to retire those raw connectivity frames must first accept that their exact
diagnostics can no longer be reconstructed locally from raw data. Preserve
the manifest, captured metadata, diagnostic report, and all source/protocol
records. No cleanup is performed by this proposal.

Even that single removal would leave **six archives and 166,369,994 bytes**.
It does not resolve the count target.

## Why the other two potential removals lose required evidence

After preserving the two pinned originals, the completed replacement, and its
interrupted predecessor, reaching four would require discarding all three
remaining raw archives: the preflight plus the 19:39 and 20:22 maker captures.
That would reclaim 28,003,841 bytes and leave 138,970,130 bytes, but would remove
the raw inputs for already published research:

- The 19:39 BTC/ETH archive supports the
  [prospective maker-roundtrip study](maker-roundtrip-prospective.md), its
  [frozen run record](../reports/maker-roundtrip-v1/README.md), and the
  [hedge-venue comparison](rh-hedge-venue-choice.md).
- The 20:22 NVDA/XAG archive supports the
  [frozen equity study](maker-equity-results.md) and the
  [full-book reconstruction](maker-book-archive.md).
- Both are explicit inputs to the published
  [quote-distance flow report](../reports/rh-quote-distance-flow/REPORT.md).
  Their newly computed gzip hashes match its saved
  [source hashes](../reports/rh-quote-distance-flow/summary.json). The equity
  summary and full-book manifest independently record the same 20:22 hash.

These older manifests lack a `frames_sha256` field, so the current planner
labels them `incomplete_or_invalid`. Their manifests nevertheless record
completed duration-limited, read-only, untruncated captures. The planning-gate
failure is a schema limitation; it does not establish that their raw data are
invalid or dispensable. The retained summaries and decoded books are derived
evidence and cannot replace the complete original public frames for later
decoder, queue, or source-timing audits.

## Fixed prospective amendment: eight archives, one future study

Preserve all seven existing archives and amend the planning count to **eight**
across the **same six roots**, keeping the aggregate raw limit at
**512,000,000 apparent bytes**. This is a fixed allowance for exactly one
future study; it is not an automatic count increase. The earlier four-target
inventory and retention review remain evidence of the original overage. The
[amendment proposal](../reports/experiment-storage/fixed-eight-amendment-20260930T0351Z.json)
records the exact fixed budgets and launch gates. It was subsequently
[adopted](../reports/experiment-storage/adoption-20260930T0409Z.json) after
reviewing both completed replay readouts and withholding the 11 provisional
closed contributions. The proposal's original pending status is retained
as dated provenance; the separate adoption record governs the new limit.
The original inventory-time replay statuses above remain historical observations.

The separate [eight-target dry inventory](../reports/experiment-storage/inventory-eight-20260930T0351Z.json)
passes both budgets with no cleanup proposal: seven archives, 166,973,971
bytes, and an empty removal plan. It uses the same physical archive definition
and the same roots. No preflight, interrupted attempt, or original is removed
from the count. Restricting roots or grouping directories into method families
is not used to make the old target appear compliant.

The one future study must have a **128,000,000-byte complete raw archive cap**,
including frames, copied metadata, and final manifest. At its maximum, the
projection is **eight archives and 294,973,971 raw bytes**, leaving
**217,026,029 bytes** under the unchanged raw limit. The earlier 384 MB
single-study ceiling is not the next-study allowance: another full 384 MB
archive would project 550,973,971 raw bytes and exceed this aggregate limit.

Cap semantics must be verified in the chosen collector. The existing
`rh_maker_capture.py` and `passive_three_venue_capture.py` wrappers subtract
copied metadata from writer capacity, reserve manifest space, and assert
`frames + metadata + manifest <= args.max_bytes`. Their `--max-bytes 128000000`
therefore limits the complete archive. A replacement that caps only frames
must instead allow at most **127,000,000 frame bytes plus 1,000,000 combined
metadata/manifest bytes**, and reject the preflight if overhead cannot fit.
Do not equate a generic payload cap with a total archive cap.

## Derived storage and disk headroom

Derived artifacts are budgeted separately from the selected raw roots:

| Artifact allocation | Maximum apparent bytes |
| --- | ---: |
| Current strict replay: 96 MB audit plus 32 MB summary/report | 128,000,000 |
| Current corrected replay, including its temporary staged result | 128,000,000 |
| Current comparison: 32 MB JSON plus 1 MB report | 33,000,000 |
| Exploratory ACK replay, base scenario: 96 MB audit plus 32 MB summary/report | 128,000,000 |
| Exploratory ACK replay, +200 scenario: 96 MB audit plus 32 MB summary/report | 128,000,000 |
| Proposed aggregate derived allowance for the one future study | 128,000,000 |
| Full current, two ACK, and future derived allocations | **673,000,000** |

The corrected result is published by renaming its staged directory, so staging
and final output are not two independent 128 MB allocations. Each current
supervisor log is capped at 1 MB. Each of the two ACK supervisors and the one
future supervisor also has a 1 MB log allowance, for five logs in total. The
two exploratory ACK replays reuse the same completed raw archive and add
**zero raw studies**. Their 256 MB derived allowance covers only the base and
+200 scenarios; additional ACK scenarios are not allowed automatically.

Counting all derived maxima again, even though completed or partial output
already exists, gives 128 MB new raw + 673 MB derived + 5 MB logs = **806 MB**
of conservative additional disk demand. Reserve **820 MB** for these artifacts
and metadata/control records in the future plan. This is a planning reservation,
not an existing filesystem quota or permission to launch.

At the original amendment check, the filesystem exposed **608,513,835,008 available
bytes**, which exceeds the revised reservation. The ACK amendment also records
a fresh filesystem-space check in the JSON proposal. A nearby read-only apparent-size
check found 59,327,199 bytes under `data/derived` and 32,178,192 under `reports`;
those outputs can grow while the current replays run. Available disk space
can also change independently of these studies, so recheck it immediately
before any future launch. Production storage remains separate and unchanged.

## Gates for the single future capture

Read and adjudicate both current replay outputs before selecting another
strategy or collecting future data. Freeze a separate future-only protocol
with exact markets, duration, collector, fresh output, and raw/derived/log caps.
Recheck all six roots for seven retained archives and verify no unaccounted raw
job exists. Verify the complete-archive cap and adequate disk headroom before
launch. No raw capture or deletion is performed by this proposal.

After that single additional archive, the count reaches eight. A ninth capture
requires a fresh explicit reconciliation; the amendment does not expand itself
or create an ongoing capture loop. Continue bounded analysis of stopped data
while current results and the separate future design are reviewed.


### Completed-output allocation for the fixed-anchor diagnostic, 04:40 UTC

The completed strict/corrected comparison, ACK readout, rejected-target reach
and static exit-distance reports are pinned in the
[offline allocation record](../reports/experiment-storage/fixed-anchor-allocation-20260930.json).
Their exact regular-file lengths total 9,810,275 bytes. Allocate at most
16,000,000 further bytes, including all observations, summaries, manifests
and reports, to one RH/HL fixed-anchor diagnostic on the stopped 02:52 archive.
This reuses the existing 33,000,000-byte comparison allowance as a shared
comparison-and-offline-diagnostic allowance: the projected total is
25,810,275 bytes. Completed files are pinned, and no additional
comparison rerun or scenario is automatically authorized. The full 673 MB
derived maximum and 820 MB reservation remain unchanged. No raw archive is
added and the one future capture slot remains unused.


### Reverse-route static bound allocation, 04:57 UTC

A [second explicit offline allocation](../reports/experiment-storage/reverse-bound-allocation-20260930.json)
allows at most 2,000,000 bytes for one reverse-route static upper-bound
calculation from the completed fixed-anchor CSV and metadata. It performs
zero raw traversals. Including the 72,636-byte completed ACK halt review,
shared comparison/diagnostic use at all allocated maxima is 27,882,911 bytes,
below the existing 33,000,000-byte allowance. The raw-study count, future
capture slot, total derived maximum and 820 MB reservation remain unchanged.

### Delayed taker quote allocation, 05:20 UTC

The [delayed quote allocation](../reports/experiment-storage/delayed-taker-allocation-20260930.json)
reserves 3,000,000 bytes for one fixed-quantity, four-horizon diagnostic on
the stopped 02:52 archive, including all reports, source copies and logs.
Projected use at all maxima is 30,882,911 bytes, leaving 2,117,089 bytes in
the existing 33 MB shared allowance. One canonical traversal is allowed
only after implementation review and source freeze; no new raw archive,
reservation increase or automatic retry is authorized. The helper must
enforce the aggregate cap before writes and retain every scheduled outcome.
