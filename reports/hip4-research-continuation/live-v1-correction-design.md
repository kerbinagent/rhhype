# HIP-4 continuation: live-v1 causal correction design (proposal for root review)

**Status.** No source, test, plan or design edit happens until root approves. This replaces the hindsight timeline with a causal screen in receipt time.

**Trigger.** Sol's independent review of `scripts/hip4_continuation_live.py` (sha `69b3bc5b…`) found blockers, and root relayed them at 14:55 UTC on 2 October 2026.

**Library facts** were checked in the locally installed aiohttp 3.13.2:
- `_ws_connect` calls `self.request(...)` without `allow_redirects`, so `_request`'s defaults apply: `allow_redirects=True`, `max_redirects=10` (`client.py` lines 498–499 and 1076).
- A redirect awaits each trace's `send_request_redirect` before following it (`client.py` lines 807–812).
- With `autoping=True`, `receive()` consumes PING and PONG frames (`client_ws.py` lines 377–380).

## 1. Findings and fixes

| # | Finding (live line numbers) | Fix |
| --- | --- | --- |
| 1 | `timeline` (437–449) sorts every bbo by server time, so a late receipt can backdate or extend a 1,000 ms run | causal receipt-order state (§2); server time is used only by the gates |
| 2 | `falsifier` (452–473) compares each probe with bbo frames received after it | causal falsifier (§3) |
| 3 | no source age, future or order gate; `scan` (387–389) only counts a regression and still applies it | frozen gates (§2) |
| 4 | unknown named states for the first 10 minutes still pass park (560); `end_ms` (532) uses the maximum server time over all frames, probe included, while other states are carried | receipt-time coverage partition ending at the stop; no whole-window park (§4) |
| 5 | meta invalidation tests only the run start (540–541), so a run can qualify after the event | qualification must precede the first relevant meta receipt (§2) |
| 6 | `ws_connect` follows redirects despite the fixed endpoint | a trace `on_request_redirect` hook sets cause `redirect` and raises; the stop is `ws_connect_failed` with an event body `{"cause":"redirect"}` |
| 7 | the design says "every frame", but autoping hides protocol ping and pong | wording becomes "every delivered application message, every sent frame and the connection events"; protocol control frames are not retained |
| 8 | the sold-member set can change inside one forward run (499–514), mixing residual and basis from the maximum state with duration and minimum size from other states | the run key includes the sold set (§2) |
| 9 | spawn failure, kill, decompression refusal or projection overflow leaves no per-route outcome | explicit unavailable denominator (§5) |
| 10 | the parser refuses more than 64 MiB raw (59, 243), but collection stops only on gzip size; anomaly keys are unbounded strings (361, 385, 410) | raw-byte stop and a bounded projection (§5) |
| 11 | a quiet bbo may be unchanged rather than lost | carrying stays a premise; no losslessness or whole-window negative claim |
| 12 | closed and residual forward states are pooled under `forward` | separate dispositions (§4) |

## 2. Causal state, gates and runs

**Processing.** Records are processed once, in capture index order. `validate_records` already checks that `mono_ns` is monotone. Durations use `mono_ns`; window membership and source age use `wall_ms`. If consecutive records' wall and mono deltas differ by more than 50 ms, that is a `local_clock_step`: every coin becomes unsupported until its next accepted frame.

**Gates, frozen per frame.** age = `wall_ms` − `time`. Each bbo or probe frame is gated as:
- `future` if age < −250 ms;
- `stale` if age > 2,000 ms;
- `order` if `time` ≤ the previous accepted `time` for that coin (duplicate or regression).

A gated frame is never applied. Its coin is unsupported from that receipt until the coin's next accepted frame. Each class is counted.

The bars are frozen choices, not estimates. This repo's perp probe measured median ages of 0.322 s (fast) and 0.402 s (slow), and p95 ages of 0.499 s and 0.512 s ([summary](../hl-fast-probe/20260929T205147Z/summary.json)); its own freshness bar was 2 s. Outcome-coin ages are unmeasured.

**State.** K(r) applies each accepted frame at its receipt and never reorders, reapplies or backdates. A state that mixes coins from one block is a displayed state; the 1,000 ms bar filters such transients.

**Carry.** A coin's state persists until its next frame (premise P10). A carried state is supported only while the connection is live, meaning some application message was received within the last 35 s; pings go out every 30 s.

**Supported(r)** requires all of:
- every named coin is known and supported;
- the connection is live;
- the receipt is inside the window;
- it is before r_M, the first relevant meta receipt: a parsed target or member event, or any unparsed `outcomeMetaUpdates` frame;
- it is before r_F, the falsification receipt.

If meta_pre or meta_post changed and no update was located, the reason is `meta_change_unlocated`.

**Runs.**
- The key is (route, disposition, sold set).
- A run is a maximal receipt interval [r₀, r₁) on which Supported holds, cash is positive and the key is constant.
- It qualifies at r_Q = r₀ + 1,000 ms if r_Q < r₁. This is known at r_Q, because no ending frame has arrived by then.
- Decision attributes over [r₀, r_Q] are fixed at r_Q: minimum and maximum cash, minimum units, residual coins and basis.
- The extension to r₁ is descriptive only and records its end cause: frame, gap, meta, falsifier, stop or close.

## 3. Causal falsifier

At each accepted probe receipt r_p with source time s_p, take the latest accepted probe-coin bbo in K(r_p), with time s_b:
- no bbo yet: `unknown`;
- s_b > s_p: `superseded` (not compared);
- otherwise: `match` if both sides agree on px, sz and n, else `mismatch`.

Two consecutive compared mismatches mean falsification at r_p, and support ends from r_p onward. Earlier decisions are kept, but the status cannot be a candidate. A sparse probe tests consistency only; it never shows losslessness.

## 4. Coverage, dispositions and status

**Coverage.** The receipt-time partition of [open, close] is exhaustive. A test checks that the parts sum to the window length:
- `initial`: from open until the first supported state;
- `supported`;
- `gap`: support lost to a gated or unknown coin, lost liveness or a clock step;
- `invalidated`: from r_M or r_F onward;
- `censored`: after a stop other than `window_closed`.

**Dispositions**, never pooled:
- `forward_closed`: every member, the fallback included, is sold, so the residual is zero;
- `forward_residual`: unsold members are a residual valued at 0, so the cash is a candidate bound;
- `inverse_full`: closed.

**Statuses.**
- `candidate_supported_path`: at least one qualifying run, given all of:
  - meta_pre unchanged;
  - every subscription acknowledged exactly once;
  - not falsified;
  - no `meta_change_unlocated`.

  It is reported per disposition.
- `no_qualifying_supported_path`: the same gates hold and nothing qualified. Its scope is the supported milliseconds only; it is never a negative for the whole window or for losslessness.
- `inconclusive`: anything else, with every reason listed.

**Removed:** `park_no_qualifying_excursion_in_window`, the 100-comparison park rule, the hint-time gate and the server-time `end_ms`.

## 5. Failure denominators and stop cases

**Unavailable denominator.** On any of the following, the supervisor publishes `{question: Q, routes: {forward_closed, forward_residual, inverse_full}: "unavailable", counts: null, cause}`:
- start failure;
- deadline kill;
- worker exit without a valid terminal;
- a bundle parse or decompression refusal;
- a projection over its cap.

The counts are unknown, never zero.

**New stop `raw_reserve_reached`.** Capture counts raw framed bytes and stops reading at RAW_LIMIT − 1,048,576. That remainder holds pending data, one 256 KiB frame, the stop event and the 196,608-byte meta_post.

**Bounded projection.** Anomalies come from a fixed enumeration plus `other`, and every list keeps its cap. A test builds the worst case and checks it against PROJECTION_CAP, so overflow cannot happen by construction. If it ever did, the unavailable denominator would apply.

**Settle-v1 isolation.** Settle imports `lv.STOPS`, `lv.Capture` and the parsers, and repeats the same `ws_connect` call (settle line 318). Live gets its own `LIVE_STOPS`, and the raw counter goes in a live-only subclass. Settle's bytes and behaviour stay unchanged, and its redirect and autoping issues are listed for a separate decision.

## 6. Cost and order

**Estimated growth:**
- live source about +6 KB;
- tests about +6 KB, covering:
  - backdating;
  - superseded and mismatch probes;
  - each gate;
  - meta after a run start;
  - a sold-set split;
  - the coverage sum;
  - unavailable denominators;
  - the raw stop;
  - the projection bound;
  - the redirect hook;
- design rewrite and plan regeneration about ±1 KB.

**Budget.** This proposal and pairing-v1 already use about 19.3 KB of the 32,768 B, leaving about 13.4 KB. The edit, at about 13 KB, would use nearly all of that, so it needs a separate root allocation before it starts if the pairing work is to continue.

**Order after approval:**
1. Edit.
2. Run the live and settle suites.
3. Regenerate the draft plan.
4. Report pins.

Expiry and the books files stay untouched.
