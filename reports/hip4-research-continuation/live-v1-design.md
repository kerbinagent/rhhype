# HIP-4 continuation: live one-match touch stream v1 (design, offline draft)

This draft authorizes no websocket, pilot or capture; root reviews it and freezes a separate plan first. It follows root's 13:27 UTC instruction of 2 October 2026:
- the smallest decisive one-match design;
- full raw receipts and a hard cap of about 3–4 MiB;
- complete route cost and order;
- residual claims valued only after observable settlement;
- a capped prefix treated as censored;
- no post-match idea without formal resolution rules and an observable event time.

Code: `scripts/hip4_continuation_live.py`, with offline tests in `tests/test_hip4_continuation_live.py` (13 tests, no network).

## Why this test

The [books-v1 result](books-v1/projection.json) certified all 18 questions at 13:16 UTC (bundle `b5b6e244…`).
- **Empty fallback books.** All 18 fallback books were empty, so the only static route left is selling the named YES set.
- **Near-binding margins.** Pre-match named-bid sums came within 0.0002 of binding: Q363 −0.00017, Q357 −0.00024.

A goal reprices a match's three named members, possibly asynchronously across quotes. If the named bids then sum above 1 for long enough, a holder of complete sets receives positive immediate cash within seconds. With the empty fallback unsold, that cash leaves a residual fallback YES valued at 0 until observable settlement, so it is a candidate bound, not closed cash. Only a run that also sells the fallback, or an inverse_full run, has zero residual. This is the most direct seconds-scale avenue in [avenues-v1](avenues-v1.md).

## Target and window

| Item | Value |
| --- | --- |
| Question | Q363, proposed: tightest books-v1 margin. Q359 (hint 2026-10-03 16:00 UTC) is the earlier alternate. Root selects at freeze; the code allows only the 11 frozen match questions. |
| Members | fallback 6833; named 6834, 6835, 6836 (frozen projection `66913ed2…`) |
| Schedule hint | `scheduledStart` 2026-10-04 18:45 UTC. It is used only to place the window; it is not kickoff, end-of-play or resolution evidence. A test re-derives every hint from the frozen raw response. |
| Window | hint − 10 min to hint + 125 min (18:35–20:50 UTC) |
| Launch | between window open − 15 min and open − 2 min, else refused |

## Requests (public data only)

1. `outcomeMeta` at open − 60 s, using the frozen books-v1 `fetch_all` (no retry, redirect or proxy). Weight 20.
2. One websocket to `wss://api.hyperliquid.xyz/ws`, without compression, proxy or reconnect, and with a 256 KiB maximum frame. Six subscriptions:
   - `bbo` for each member YES coin `#<10·outcome>`, ascending. The docs say these "are sent only if the bbo changes on a block" ([subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)).
   - `l2Book` for the lowest named coin with default settings, as the falsifier below. The docs call it a "Snapshot feed, pushed on each block that is at least 0.5 since last push". This repo's perp probe measured the default (non-fast) feed at a median source gap of 5.383 s with 20 levels ([hl-fast-probe](../hl-fast-probe/20260929T205147Z/analysis.md)).
   - `outcomeMetaUpdates`, which records any `questionUpdated` or `questionSettled` for Q363, or any `outcomeSettled` for a member.

   An application ping `{"method":"ping"}` is sent every 30 s, because the server closes a connection it has not sent to in 60 s ([timeouts](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats)). If nothing is received for 90 s, the capture stops. Six subscriptions and one connection are far inside the documented limits of 1,000 subscriptions and 10 connections ([rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)).
3. `outcomeMeta` again after the socket closes, for any stop once the first read succeeded. Weight 20.

Total REST weight is 40. The websocket uses no REST weight.

## Retention and censoring

Every frame sent or received, the connection events, the stop event and both REST bodies become framed records with consecutive indexes and local wall and monotonic clocks.

**Persistence.** Records are appended as complete gzip members, one every 10 s or 32 KiB, and fsynced to a pending file. At the end, that file is hard-linked to `capture.bundle.gz`.

**Cap.** The cap is 3,670,016 bytes (3.5 MiB), and reading stops once the bundle reaches the cap minus a 524,288-byte reserve. The reserve provably holds the worst-case remainder:
- the flushed member that crossed the threshold, at most 32 KiB of pending data plus one 256 KiB frame;
- the stop event;
- `meta_post`, at most 196,608 bytes.

A synthetic test fills the reserve with incompressible data and stays under the cap.

**Storage request.** 3,751,936 bytes: bundle, projection 65,536 and receipts 16,384. This needs a separate root allocation; root reported 5,455,872 bytes of global headroom at 13:40 UTC. No compression ratio is assumed.

**Censoring.** A stop for any reason other than `window_closed` is a censored prefix:
- `cap_reserve_reached`, `ws_closed`, `ws_error`, `liveness_lost`;
- `ws_connect_failed`, `transport_failure`, `meta_pre_failed`.

A censored prefix still yields a projection, but it can only add a candidate; it cannot support a whole-window negative.

## Analysis (exact decimal context, prec 120, Inexact and Rounded trapped)

**State.** For each coin, the state is the latest `bbo` at or before server time t, applied in (time, receipt) order. Updates with equal times are applied together, so one block's changes never create a transient mixed state. A coin is unknown before its first `bbo`.

**Routes, with complete cost and order per unit:**
- **Forward.**
  - Before the window, hold complete sets made at par by `splitOutcome` + `negateOutcome` on the fallback, at a basis of 1.
  - At time t, sell every member YES that has a bid.
  - Immediate cash = Σ bids − 1. It is closed (zero residual) only when every member, the fallback included, is sold.
  - An unsold member, usually the empty fallback, stays as a residual claim valued at 0 until observable settlement, which this capture does not observe.
- **Inverse_full.** Buy every member YES at its ask, fallback included, then `mergeQuestion`. Closed cash = 1 − Σ asks, with no residual. It is available only when every ask is present.

No route enters an inventory at zero basis. Fees are assumed zero, which is optimistic.

**Excursions.** An excursion is a maximal run of positive route cash with all three named states known, measured in server time inside the window. Each run records:
- start, end and duration;
- maximum cash, with the touch units at the maximum and the minimum units over the run;
- basis and residual coins;
- right-censoring.

A run is **qualifying** if it lasts at least 1,000 ms and starts before any target meta event. The bar is about 2.5 times this repo's measured median receipt age of 0.32–0.40 s.

**Falsifier for the reconstruction (P10).** At each `l2Book` snapshot time, the probe coin's top level must equal its reconstructed `bbo` state on both sides: price, size and count. Two consecutive mismatches falsify the reconstruction. A single mismatch is reported as possible timestamp jitter.

**Coverage.** The projection reports:
- the first time all named states are known;
- covered milliseconds;
- the maximum forward cash;
- the time with forward cash ≥ −0.001.

## Decision

- **`candidate_recorded_vector`.** Any qualifying forward or inverse_full run, provided all of these hold:
  - meta_pre unchanged;
  - every subscription acknowledged exactly once;
  - no `bbo` anomaly;
  - falsifier not falsified.

  This is a recorded-vector bound for a separately frozen timing, depth, fee and conversion review, never execution or profit. A censored prefix can still show a candidate.
- **`park_no_qualifying_excursion_in_window`.** No candidate, and none of the following reasons:
  - a censored stop;
  - either meta read changed;
  - an acknowledgement missing or duplicated;
  - any stream anomaly or target meta event;
  - fewer than 100 falsifier comparisons, or a falsified reconstruction;
  - named states unknown at the hint time;
  - server time ending more than 10 s before close.

  The scope is this one window and question only.
- **`inconclusive`.** Otherwise, with every reason listed. Runs of any length are still listed: the 50 qualifying and the 20 longest per route.

## Premises

| Premise | Meaning | How it is checked |
| --- | --- | --- |
| P1, membership | Q363 keeps its frozen structure | both REST reads plus ws meta updates |
| P3, conversions | split, negate and mergeQuestion at par, fallback included; amounts, granularity and fees unverified | assumed |
| P4, merged book | one YES book carries both sides | books-v1 mirrors consistent; not retested |
| P9, collateral | all members labelled USDC; identity unresolved | no USD claim |
| P10, `bbo` stream | change-only and lossless | falsifier |
| P11, server time | `time` is block time, shared by one block's updates | violations only shorten or split runs; 1,000 ms gate |
| P12, initial state | a `bbo` arrives at subscription | otherwise coverage starts later; park requires all named states known by the hint time |

## Not established

- takerability, fills or queue position;
- fees, conversion amounts or granularity;
- collateral identity or native units;
- kickoff or end-of-play time, or settlement;
- other matches;
- profit.

No subscription acknowledgement format, initial `bbo` push, or `outcomeMetaUpdates` channel name has been observed for outcome coins. Any deviation shows up as an anomaly, and anomalies block a park.
