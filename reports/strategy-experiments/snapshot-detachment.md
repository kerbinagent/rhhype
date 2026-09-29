# Checkpoint snapshot detachment audit

Date: 2026-09-29. This is an offline code audit and component benchmark. No live
process was attached to a profiler or restarted.

## Reproduced race

`paper_monitor.checkpoint()` builds `engine.snapshot()` on the event loop, then
passes the result to `atomic_json` in a worker thread. Before this change,
`snapshot()` reused active episode dicts and ledger wallet dicts from the live
engine. A captured snapshot changed from `samples=1, last=1000` to
`samples=2, last=1000.2` after a normal book update and tick. Its JSON changed
after capture as well. The worker therefore could write episode or wallet
values newer than its `updated_at` and other counters.

The fix detaches the exported mutable fields: wallet dicts, position funding
payloads, top signals, active episodes, and recent episodes. The selector
snapshot, counters, and other emitted fields were already newly constructed.
`paper_monitor` replaces `runtime['funding_errors']` with a new result dict and
does not mutate the old dict in place, so that field needs no extra copy.
The monitor also overwrites the engine's top signals with store-decoded rows,
but direct `engine.snapshot()` callers now get detached signals too.

## Verification and cost

`tests/test_paper_snapshot_detach.py` checks that a captured snapshot remains
unchanged after real book/tick progress changes an active episode and wallet.
It also changes nested funding and history data and a top signal after capture.
Both tests require a strict JSON round trip. The engine, latency, and snapshot
test modules pass together: 24 tests.

For the component benchmark, a short read-only SQLite query copied one live
engine checkpoint, then the connection closed. The offline engine had 10 active
episodes, 10 positions, eight ledgers, 30 top signals, and 2,000 retained
finished episodes; its snapshot was about 48 KB. Five trials of 100 calls each
gave median times of 0.816 ms for the preceding code and 1.238 ms with
detachment, an added 0.422 ms per snapshot. This measures `snapshot()` alone;
it does not measure a live checkpoint or predict an observed loop-lag change.

`export_state()` still returns live references, but its sole checkpoint caller
performs `copy.deepcopy(engine.export_state())` on the event loop before
offloading serialization. This audit did not change that path.
