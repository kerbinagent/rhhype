# HIP-4 continuation: settle-v1 gaps found by the live-v1 causal review (note, no edits)

Root's reviews of live-v1, through 15:49 UTC on 2 October 2026, found several defect classes. This note checks `scripts/hip4_continuation_settle.py` (sha `2c6a9162…`, unchanged) for the same classes. No settle file has been edited: the correction authority (`093c8c6`) covers live only. Line numbers refer to that file.

| # | Live finding | Settle status | Line(s) |
| --- | --- | --- | --- |
| 1 | `ws_connect` follows redirects | same call, no trace hook | 317–318 |
| 2 | wall-clock window end | `remaining = (close - now_utc())`; a wall jump can produce a false `window_closed` | 350 |
| 3 | end time from the maximum server time | `end_ms = min(close_ms, max_server)` | 548 |
| 4 | no raw-byte stop | the 2 MiB gzip cap with compressible frames can exceed the parser's 64 MiB raw limit, so the bundle becomes unparseable | 78, shared `lv.parse_bundle` |
| 5 | unbounded anomaly keys | `channel_{str(channel)[:32]}` and `bbo_invalid_{exc}` | 547, 539 |
| 6 | unvalidated channel and meta ids | a null or unknown channel only counts an anomaly; `settled_ids` skips malformed entries and ignores `questionUpdated` and `outcomeCreated` | 280–297, 546 |
| 7 | no source age, future or order gates | bbo events are kept without gates; the post-expiry activity test compares server times | 535–542, 91 |
| 8 | no explicit unavailable denominator | the supervisor reports only `conclusion_status` | 712 |

**Already causal or ex-post only, so not defects of the same kind:**
- the post-record book is the first `l2Book` sent after the record's local receipt (monotonic causality);
- `ex_post_runs` (453) is labelled ex-post and kept apart from any decision;
- the pre-record gap is always unavailable.

**Smallest corrections if root extends the authority:**
- Rows 1–4 and 8: reuse the live mechanisms, namely the trace hook, the monotonic close anchored at `ws_open`, a live-style raw counter in settle's `Capture` subclass, and the supervisor denominator.
- Row 5: the enumerated anomaly keys.
- Row 6: channel validation before dispatch, plus live's `meta_relevance` id checks, with any unparsed update invalidating the affected instruments.
- Row 7: label server-time quantities as descriptive, or apply the frozen gates.

None of this is needed for the frozen expiry run, which uses its own source.
