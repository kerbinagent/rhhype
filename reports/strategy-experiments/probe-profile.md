# Probe snapshot CPU profile

Date: 2026-09-29. This is an offline component profile. The running collector
was not restarted or attached to a profiler.

## Workload and measurements

I read up to 300 recent public `best_signal` and `signal_episode_start`
evidence rows from the live SQLite database, then closed the read connection.
The rows supplied 600 complete book observations. The replay used current
market metadata (116 pairs), 10,000 book events at 1,100 events/second, a
20 Hz engine tick, and the configured fee and shadow portfolios. Each replay
assigned fresh, increasing receipt/source timestamps and kept the full
evidence depth. It excluded WebSocket JSON parsing, network waits, funding
requests, and SQLite checkpointing.

The first cProfile run attributed about 1.04 of 2.06 profiled CPU seconds to
`PaperEngine._probe_update`, with roughly 1.00 second in recursive
`copy.deepcopy` calls. Those numbers are profiler-inflated. An unprofiled,
alternating comparison on the same replay measured:

| Probe book capture | Median CPU for 10,000 events | Trials | Engine result |
|---|---:|---|---|
| Recursive `deepcopy` | 0.349 s | 0.434, 0.349, 0.348 s | Baseline |
| Isolated level-list snapshot | 0.231 s | 0.231, 0.226, 0.234 s | Same core counters, position count, episodes, and probe results |

The component speedup was **1.51×** in this replay. It does not predict a
1.51× whole-process speedup: the replay contained only a subset of the live
market mix and omitted transport and storage costs. A regression test also
mutates the original outer book, an inner price level, a side list, and nested
metadata after capture; the saved observation and probe result remain fixed.

## Change

`snapshot_probe_book` copies the outer book and both full price-level lists.
Each price/quantity level becomes an immutable tuple. It recursively copies
other nested metadata. Probe timing, source generation checks, the first
eligible book rule, depth, and spread calculation remain the same.

## Other measured work

The running database's engine state was about 1.08 MB at inspection time.
Offline copies of that state took a median **19.7 ms** for `deepcopy`; a JSON
dump took **12.5 ms**. In the runtime, `copy.deepcopy(engine.export_state())`
runs on the event loop once per report. This can contribute to tail latency.
Moving that copy to a worker without an immutable engine snapshot would risk
mixing state across feed events, so the checkpoint path was left unchanged.

The latest live snapshot during this investigation reported about **894 book
events/second, 61% of one CPU core, and 13.9 ms p95 loop lag**. Earlier live
snapshots varied materially; these figures are observations, not a measured
effect of the offline code change.

