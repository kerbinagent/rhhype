# Core/RH delayed taker implementation review

2026-09-30, 09:59 UTC. Root and independent peer accept the implementation
against the method frozen in `2a5bffd`. The user’s continuing public-data and
paper-experiment mandate authorizes this work. This note approves source
freeze and zero-raw preparation; root will separately review and commit the
prepared input freeze before launching the single historical traversal.

Root ran all 28 focused tests with Python `-B`: PASS in 5.164 seconds.
The actual CLI fixture exercises preparation, admission, two concatenated
gzip archives, the pinned decoder, staged publication and storage accounting.
All 1,008 identities remain: 992 synthetic complete quotes and 16 tail EOFs.
The independent auditor verifies those rows and summary arithmetic. These
are artificial fixtures, not market observations.

Coverage includes first illegal/shallow pair without retry, original sizing,
both anchor legs, own-leg fees, actual elapsed capital, unknown rules, tied
receipts, recovery after genuine gaps, source regressions, snapshot and nonce
controls, raw decimal collisions and legal replacements/deletions. Source
mutation, raw hash/count mismatch, cap failure, SIGTERM and failure after
manifest creation preserve the full null-economic roster and remove the
completion marker. Default CLI is a zero-raw, zero-network dry plan.

Pre-run findings were repaired before any historical stream read: numeric
rounding before raw identity checks, excessive tied-book retention, omitted
invalidation scope, decoder recovery after source regression, missing startup
provenance, absent separate source/runtime freeze, timeout marker cleanup,
and an oversized uncompressed summary. Summary gzip retains every group;
all original method economics, grid, timing and resource ceilings remain.

Five repository files total 144,874 bytes; their gzip copy is 43,331 bytes.
Source category subtotal 188,205 /190,000 internal bytes leaves the separate
10,000-byte documentation reserve. Decoded source copy is 147,879 /200,000
bytes. Aggregate allocation remains 600,000, included in 32,710,904 /33,000,000
shared allowance. All prior allocations and failed artifacts remain reserved.

The real diagnostic may use one decoded pass per archive under a 900-second
external wall limit and five-second termination grace. Both compressed raw
hashes must match before either decode and again before publication. Sources,
runtime, the prepared freeze and bounded owned-file inventories are rechecked.
No retry, extra capture, predictor fit or promotion is automatic. Results are
post-capture conditional quote arithmetic; private execution, historical
maximum base limits, funding and conversion remain unverified.

After completed publication, root may run the frozen derived-only auditor
once, then inspect the full retained denominator. No partial economics are
used to alter this run. Source files, method and tests stay fixed throughout.
