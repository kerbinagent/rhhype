# RH maker replay performance

## 29 September 2026, before financial readout

The frozen 50-minute capture stopped at 22:11:32 UTC. Its unchanged replay
started around 22:11:44 as PID 2656054, writing
`data/derived/rh-small-maker-v1`. A separate replay started around 22:19 as
PID 2670694, writing `data/derived/rh-small-maker-v1-cached`.

The second process uses [a separate wrapper](../scripts/optimized_rh_maker_replay.py)
committed in **4f97d38**. It caches one immutable parsed book within each
event, rather than repeating Decimal conversion for each independent
portfolio. All frozen source files remain unchanged. Both processes use
the same captured events and frozen quote/execution rules. The output
explicitly identifies the wrapper as a **post-freeze implementation
variant** and records its hash and cache counters.

At approximately 22:23 UTC the original archive descriptor was at
1,196,032 bytes and the cached descriptor at 8,740,864 bytes out of
41,368,405 compressed bytes. These are buffered input positions, **not
percentages of computational work completed or reliable completion ETAs**.
Both replay processes were using about one CPU core. The live production
collector remains a separate process.

Three tests passed: multiasset/two-tier financial and ordered-audit
equivalence on synthetic executions; immutable book sharing and patch
restoration; and correct behavior when an input generator reuses a mutable
event dictionary. This does not establish full-capture equivalence. The
unchanged replay remains running for that comparison; neither financial
readout was available when this note was written.

The variant retains the original 96 MB compressed audit plus 32 MB summary
limit, including a 16 KiB provenance reserve. It adds one derived result
directory, not an unbounded repeating collector. Generated directories are
ignored by Git. No production fee, size, target, or entry policy changed.

## Interpretation

This is a historical simulation workload across 96 counterfactual
portfolios. It does not establish that Python is too slow for the live
monitor. Current live scheduling and CPU evidence belongs in the
[performance notebook](python-performance.md) and scheduled reviews.
Repeated parsing is avoidable work; additional threads would not by
themselves remove it. The separate replay process already isolates this
CPU-heavy research from the collector's event loop, though both still
share host resources.
