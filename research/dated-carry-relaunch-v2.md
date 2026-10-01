# Fresh dated carry run after the host reboot

## Authorization and separation

On 1 October 2026 the user reported a host restart and requested continuation,
then explicitly selected: “Start a fresh run within the existing storage budget.”
This authorizes one separate 72-hour public-data run. It does not resume, extend,
repair or replace the observations in the interrupted run.

The original run remains in `reports/dated-carry/20260930-v1`. Its last trusted
index has SHA-256
`4b15af4f7c06ad9745b69da8a8f291efa4a385fe2239ec3d16b41a76d4599cb1`.
It contains 136 recorded slots: 134 `sampled`, two `callback_late`, and 728
uncollected identities in the fixed 864-slot roster. `sampled` is only a
collection status; quote validity and economic outcomes were never inspected.
The original same-boot gate now prevents economic publication. Its index,
samples, metadata, source freeze and stale last running status remain preserved;
`terminal/recovery-20261001.json` records the interruption explicitly.

## Fixed method

Use the original [v1 method](dated-carry-method-v1.md), collector, metadata
preparer, economic evaluator and endpoint gate unchanged. Fresh price-independent
metadata select the nearest eligible BTC USDC dated future and BTC_USDC spot.
The fresh config fixes T0 before collection, and the endpoint is T0 + 72 hours.
Retain 864 paired five-minute slots, six fixed decision anchors, four quantities
and $1,000 primary budget. Keep all 3,456 final rows, including missing slots.
No interim economic inspection, sample retry, sampling restart, clock rebase,
underfilled denominator, changed fee proxy or automatic successor is permitted.
All actual all-cost feasibility and closed P&L fields remain unknown.

The only implementation addition is `scripts/dated_carry_relaunch.py`. All v2
metadata preparation, freeze, launch and endpoint recovery use this entrypoint.
It constrains the fresh path, requires its own source and budget pins, and
applies the storage limits below before invoking the unchanged v1 functions.
The different frozen constants reject launching v2 with the original entrypoint.
No v1 source file is edited by this wrapper.

## One existing 16 MiB allocation

The total experimental reservation remains 836,777,216 bytes. The original
16 MiB dated-carry allowance is subdivided prospectively:

| Reservation | Bytes |
|---|---:|
| Retired v1, including its external pinned dependencies | 1,048,576 |
| Fresh v2 source/control, including external pinned dependencies | 1,048,576 |
| Fresh v2 metadata | 2,097,152 |
| Fresh v2 samples | 7,340,032 |
| Fresh v2 derived | 2,097,152 |
| Fresh v2 terminal/audit | 3,145,728 |
| Combined | 16,777,216 |

Only the fresh sample cap changes from v1: 7 MiB instead of 8 MiB. The fresh
category caps sum to 15 MiB, including temporary bytes during atomic writes.
Before each guarded write, the wrapper checks retired physical usage plus its
frozen external-byte accounting against 1 MiB, and verifies the retired freeze
and last index identities. This checks file sizes and control records; it does
not inspect the retired quote payloads. The original no-overwrite, file count,
terminal reserve and bounded input controls remain active. No raw data are
deleted, and no old experiment allocation outside this 16 MiB changes.

The smaller cap can only reduce coverage if reached; it does not relax
admissibility. A reboot ends this run too. A subsequent run requires a new
explicit decision and budget reconciliation.
