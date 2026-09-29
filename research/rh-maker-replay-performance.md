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

## Bounded read-only diagnosis at 22:26–22:28 UTC

I inspected only `/proc` file descriptors for the two running replays and
read a small prefix of the stopped capture in separate, lower-priority
diagnostic processes. Neither running replay, frozen source file, capture,
nor output was modified or stopped. Both processes were still near one CPU
core. In one 15-second interval, the original input descriptor advanced
4,096 bytes (273 bytes/s), while the cached one advanced 327,680 bytes
(21,844 bytes/s). The corresponding descriptor positions were about
1.27 MB and 11.80 MB of the 41.37 MB gzip file. A later read showed
1.35 MB and 14.86 MB. Gzip buffering, variable event density and book
depth make these positions unsuitable as work percentages or end times.

The first 1,000 normalized events were yielded by the archive decoder in
0.60 seconds without strategy processing. Their RH books had the following
median levels per side; Hyperliquid `l2Book` had five levels per side.

| RH asset | Bid levels | Ask levels |
|---|---:|---:|
| BTC | 3,847 | 4,028 |
| ETH | 819 | 674 |
| XAG | 348 | 455 |
| NVDA | 139 | 98 |

On one actual normalized book per asset, repeated isolated parse calls gave
the following approximate cost per call. The original invokes
`Book.parse` once for each of 24 branches of the same asset; the wrapper
invokes it once per event. The two model tiers also parse the same event
separately into float levels.

| RH asset | `Book.parse` Decimal | Model float parse | Original 24 branch parses |
|---|---:|---:|---:|
| BTC | 18.85 ms | 5.01 ms | 452 ms |
| ETH | 1.96 ms | 0.82 ms | 47 ms |
| XAG | 1.37 ms | 0.40 ms | 33 ms |
| NVDA | 0.41 ms | 0.14 ms | 10 ms |

A separate 500-event reproduction used the actual normalized prefix, all
96 branches and both model tiers, with per-event engine parse caching. It
performed no audit writes and was run at `nice=10` while the full replays
continued. `model.consume` took 1.80 seconds, and cached
`branch.process` took 3.66 seconds (5.46 seconds total). The sample is
calibration-only, so it does not measure holdout quote diagnostics or output
compression. These timings identify repeated full-depth Decimal parsing as
the main original bottleneck. The remaining cached cost includes one
full-depth Decimal parse, two float parses, branch state work and strategy
logic; archive decompression and normalization are smaller on this prefix.

An additional per-event model parse cache could remove one of the two float
parses, but it would be another post-freeze implementation variant. Its
complete financial summaries and ordered audit rows would need exact
comparison against the unchanged replay before it could be used for the
study. No such variant was implemented or launched in this diagnosis.
