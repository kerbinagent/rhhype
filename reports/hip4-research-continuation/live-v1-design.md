# HIP-4 continuation: live one-match touch stream v1 (design, offline draft, causal correction)

This draft authorizes no websocket, pilot or capture. Root reviews it and freezes a separate plan first.

It follows root's 13:27 UTC instruction of 2 October 2026:
- the smallest decisive one-match design;
- full raw receipts and a hard cap of about 3–4 MiB;
- complete route cost and order;
- residual claims valued only after observable settlement;
- a capped prefix treated as censored;
- no post-match idea without formal resolution rules and an observable event time.

**Causal correction.** The analysis was rebuilt after Sol's independent review of the server-time timeline. The correction implements root's decisions committed in `093c8c6` ([correction authority](../experiment-storage/hip4-live-causal-correction-fixture-v1.json); proposal: [correction design](live-v1-correction-design.md)).

Code: `scripts/hip4_continuation_live.py`, with offline tests in `tests/test_hip4_continuation_live.py` (21 tests, no network). The production-size reserve and raw-stop proofs run in memory, so only small fixtures touch disk.

## Why this test

The [books-v1 result](books-v1/projection.json) certified all 18 questions at 13:16 UTC (bundle `b5b6e244…`).
- **Empty fallback books.** All 18 fallback books were empty, so the only static route left is selling the named YES set.
- **Near-binding margins.** Pre-match named-bid sums came within 0.0002 of binding: Q363 −0.00017, Q357 −0.00024.

A goal reprices a match's three named members, possibly asynchronously. If the named bids then sum above 1 for long enough, a holder of complete sets receives positive immediate cash. The unsold empty fallback stays as a residual YES valued at 0 until observable settlement, so that cash is a candidate bound, not closed cash.

## Target and window

| Item | Value |
| --- | --- |
| Question | Q363, proposed: tightest books-v1 margin. Q359 (hint 2026-10-03 16:00 UTC) is the earlier alternate. Root selects at freeze; the code allows only the 11 frozen match questions. |
| Members | fallback 6833; named 6834, 6835, 6836 (frozen projection `66913ed2…`) |
| Schedule hint | `scheduledStart` 2026-10-04 18:45 UTC. It places the window only; it is not kickoff, end-of-play or resolution evidence. A test re-derives every hint from the frozen raw response. |
| Window | hint − 10 min to hint + 125 min (18:35–20:50 UTC) |
| Launch | between window open − 15 min and open − 2 min, else refused |

## Requests (public data only)

1. **`outcomeMeta` at open − 60 s.** It uses the frozen books-v1 `fetch_all`, with no retry, redirect or proxy. Weight 20.
2. **One websocket to `wss://api.hyperliquid.xyz/ws`**, without compression, proxy or reconnect, and with a 256 KiB maximum frame.
   - **Redirects.** aiohttp 3.13.2's `ws_connect` would follow redirects by default, so a trace `on_request_redirect` hook refuses any redirect. The stop is then `ws_connect_failed`, and the event body is `{"cause":"redirect"}`.
   - **Six subscriptions:** `bbo` for each member YES coin; `l2Book` (default) for the lowest named coin as the probe; and `outcomeMetaUpdates`.
   - **Liveness.** An application ping goes out every 30 s, and the capture stops after 90 s with nothing received ([timeouts](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats)).
3. **`outcomeMeta` again after the socket closes**, for any stop once the first read succeeded. Weight 20.

## Retention and censoring

**Retained.** Every delivered application message, every sent frame, the connection events, the stop event and both REST bodies are retained. Each becomes a framed record with consecutive indexes and local wall and monotonic clocks. Protocol ping and pong frames consumed by aiohttp's autoping are not retained.

**Persistence.** Records are appended as complete gzip members, one every 10 s or 32 KiB, and fsynced; the pending file is hard-linked once at the end.

**Two stops.**
- **Gzip cap.** Reading stops when the bundle reaches the 3,670,016-byte cap minus a 524,288-byte reserve.
- **Raw bytes (live only).** Reading also stops when raw bytes reach `RAW_LIMIT` − 1 MiB (66,060,288), with stop `raw_reserve_reached`.

Each remainder still fits: pending data, one 256 KiB frame, the stop event and a 196,608-byte meta_post. In-memory tests fill both limits, incompressible data for the cap and compressible data for the raw stop, and parse the result.

**Settle isolation.** Settle keeps the shared `STOPS` and `Capture` unchanged.

**Censoring.** Any stop other than `window_closed` is a censored prefix.

## Analysis (exact decimal context, prec 120, Inexact and Rounded trapped)

**One clock.**
- The wall/mono anchor is fixed once, at the `ws_open` record (or `meta_pre` if the socket never opened), and is never re-anchored.
- Window bounds map to monotonic instants through it, and the capture ends the window on the same monotonic instant, so a wall-clock jump cannot produce a false `window_closed`. Every interval is half-open.

**Causal state.**
- Records are replayed once, in capture order. An accepted frame changes the state at its own receipt; nothing is re-sorted, re-applied or backdated.
- bbo and the probe keep separate state and separate clocks, and the probe never changes bbo state.

**Frozen gates, keyed by (channel, coin).** Age is the anchored receipt wall time minus the source `time`.
- An identical repeat at the same source time is ignored without refresh.
- The coin is suspended until its next accepted frame by any of these:
  - a changed update at the same source time;
  - a regressed source time;
  - a future age below −250 ms;
  - a stale age above 2,000 ms;
  - an unusable update.
- **Unattributable frames.** Any of the following suspends every member until its next accepted bbo:
  - invalid JSON;
  - a missing, non-string, empty, unexpected or `error` channel (the channel is validated before dispatch);
  - a non-text frame;
  - a bbo without a coin.

The bars are frozen choices. This repo's perp probe measured median receipt ages of 0.322 and 0.402 s and p95 ages of 0.499 and 0.512 s; outcome-coin ages are unmeasured.

**Support at a receipt** requires all of:
- every named coin accepted and unsuspended;
- every required subscription acknowledged exactly once so far;
- an application message within the last 35 s;
- a time before the first relevant meta receipt, which is a target or member event or any unparsed update. Recognized updates must carry valid ids (documented `WsOutcomeMetaUpdate` shapes); `questionUpdated: {}` counts as unparsed;
- a time before falsification.

The fallback is traded only when it is supported; otherwise it is unsold residual. inverse_full needs every member supported and quoted with an ask.

**Carry.** "Unchanged unless pushed" is an unverified change-feed premise. A quiet coin may be unchanged rather than lost.

**Probe.** Each accepted probe is compared with the latest accepted probe-coin bbo received before it, and classed as one of:
- `unknown`: no usable bbo yet;
- `superseded`: the bbo source time is later than the probe's;
- `match`;
- `mismatch`.

A future, stale, order-failed or unusable probe suspends the probe coin until the next accepted probe. A compared mismatch suspends the probe coin until a later compared match; a new bbo alone does not restore it. Two consecutive compared mismatches falsify the reconstruction. Unknown and superseded probes leave the streak unchanged.

**Routes, with complete cost and order per unit:**
- **Forward.**
  - Hold complete sets made at par by `splitOutcome` + `negateOutcome`, at a basis of 1.
  - Sell every supported member YES that has a bid. Immediate cash = Σ bids − 1.
  - The disposition is `forward_closed` only when every member, the fallback included, is sold.
  - Otherwise it is `forward_residual`, with unsold members valued at 0 until observable settlement.
- **Inverse_full.** Buy every member YES at its ask, then `mergeQuestion`. Closed cash = 1 − Σ asks.

Fees are assumed zero, which is optimistic.

**Runs.**
- A run is a maximal supported positive interval per (route, disposition, sold set), so a change of sold set starts a new run.
- It qualifies only if start + 1,000 ms is strictly before its end. Invalidation, support loss or a changed state at that instant therefore wins the tie.
- Decision attributes use only pieces begun by the qualification instant: cash, minimum cash, units, minimum units, basis and residual.
- The rest of the run, and its end cause, are descriptive. The end cause is one of frame, support, liveness, invalidated, stop or close.

**Coverage.** Per route, the window is partitioned exhaustively. Each instant takes the first matching class, in this precedence: censored, invalidated, initial, gap, supported. A test checks that the parts sum to the window length.

## Decision

- **`candidate_supported_path`.** Any qualifying run, provided all of these hold:
  - meta_pre unchanged;
  - every subscription acknowledged exactly once;
  - not falsified;
  - no unlocated meta change, meaning meta_post changed without a received update.

  It is reported per disposition. It is a displayed-touch bound for a separately frozen timing, depth, fee and conversion review, never execution or profit.
- **`no_qualifying_supported_path`.** No qualifying run, and none of the following reasons:
  - a censored stop;
  - either meta read changed;
  - an acknowledgement missing or duplicated;
  - an anomaly or target meta event;
  - falsification;
  - no supported forward coverage.

  Its scope is the supported coverage of this window and question. It is never a whole-window or losslessness negative.
- **`inconclusive`.** Otherwise, with every reason listed. The projection lists up to 16 qualifying and 8 longest runs per disposition. Anomalies are enumerated into fixed keys plus `other`, and a worst-case test keeps the projection under 65,536 bytes.
- **Supervisor denominator.** Every run publishes one question with its three dispositions. On a start failure, a kill, a missing terminal, or a failed bundle or projection, availability is `unavailable` and the counts are null, never zero.

## Premises

| Premise | Meaning | How it is checked |
| --- | --- | --- |
| P1, membership | Q363 keeps its frozen structure | both REST reads plus meta updates |
| P3, conversions | split, negate and mergeQuestion at par, fallback included; amounts, granularity and fees unverified | assumed |
| P4, merged book | one YES book carries both sides | books-v1 mirrors consistent; not retested |
| P9, collateral | all members labelled USDC; identity unresolved | no USD claim |
| P10, change feed | a quiet coin is unchanged, not lost | unverified; the probe tests consistency only |
| P11, source time | block time; feeds the gates only | runs use the anchored receipt clock |
| P12, initial state | a coin is unknown until its first accepted bbo | initial coverage, never inferred |

## Not established

- takerability, fills or queue position;
- fees, conversion amounts or granularity;
- collateral identity or native units;
- kickoff or end-of-play time, or settlement;
- other matches;
- profit.

No acknowledgement format, initial `bbo` push or `outcomeMetaUpdates` channel name has been observed for outcome coins. A deviation becomes an anomaly or leaves a coin unsupported.
