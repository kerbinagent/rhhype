# HIP-4 continuation: recurring settlement window v1 (design, offline draft)

Root gave the go at 13:57 UTC on 2 October 2026 for bounded offline source, math and tests only. There is no live or raw grant. This revision replaces the [proposal](settle-ws-v1-proposal.md) and applies root's corrections:
- `activeAssetCtx` has no source timestamp, and the 0.5 s cadence statement belongs to `WsBook`.
- A first changed mark received after the expiry is neither the adjacent mark pair nor a lower bound on determination.
- The knowable winner before the record stays unavailable without timestamped adjacent-pair provenance.
- Ex-post labels are never trade signals.
- Silence is not a halt.
- `outcomeSettled` carries only an id, so its receipt bounds observation, not settlement time.

Code: `scripts/hip4_continuation_settle.py`, with offline tests in `tests/test_hip4_continuation_settle.py` (10 tests, no network).

## What can be decided, and what cannot

| Question | Evidence | Status |
| --- | --- | --- |
| Does a book still display a winner gap after a bound settlement record is in hand? | A `settledOutcome` object bound to the requested id and the frozen spec with fraction 0 or 1 (expiry-v1 binding), then an `l2Book` sent after that response is received, compared on the local monotonic clock only | **decisive** |
| Is the winner knowable between determination and the record? | Needs timestamped mark updates adjacent to the expiry; no documented source provides them | **unavailable**, always |
| Did the book change after the expiry? | `bbo` changes with server time after the expiry | descriptive; silence proves nothing |
| What would perfect hindsight have paid? | `bbo` touches after the expiry against the bound fraction | **ex-post bound**, reported separately, never decisive or causal |

The resolution rule is formal ([contract specifications](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications#recurring-outcomes)): YES iff the linear interpolation of the mark updates immediately before and after the settlement timestamp is at or above the target. Protocol recurring outcomes are "automatically deployed and settled by the protocol".

## Instruments and schedule

The draft uses the 2026-10-03 06:00 UTC instances from the frozen snapshot (raw `5a84b598…`, file `84c66367…`), for offline tests:
- the four `priceBinary` outcomes 7544, 7545, 7546 and 7549;
- the Q371 members 7550–7553.

**Plan-pinned instruments.** The plan pins the snapshot by file and raw sha and lists the instruments. Code accepts an instrument only if all of the following hold:
- its entry appears exactly once with exactly the five spec keys;
- a binary carries `class:priceBinary` with this expiry;
- a bucket member belongs to the named question, which carries `class:priceBucket` with this expiry.

The spec says these description fields specify recurring instances. Expiry-v1 already covers 3 October, so a run needs a fresh pinned snapshot for a later expiry.

**Window.** Expiry − 2 min to expiry + 8 min (05:58–06:08 UTC). `outcomeMeta` is read at 05:57. Launch is allowed between 05:43 and 05:56.

**Requests.**
- **Websocket.** One public connection without reconnect, compression or proxy:
  - `bbo` for the 8 YES coins;
  - `outcomeMetaUpdates`;
  - a ping every 30 s and a liveness stop after 90 s of silence.
- **Follow-up.** On the first `outcomeSettled` for an instrument, or `questionSettled` for its question, the collector reads `settledOutcome` (weight 20). It then reads that coin's `l2Book` (weight 2), sent after the first response is received and recorded. Requests are sequential, at least 50 ms apart, with no retry or redirect, a 10 s timeout and an 8,192-byte body cap.
- **Sweep.** After the window, one more pair runs only for instruments without a valid bound record. There are at most two pairs per instrument; maximum REST weight is 372.

**Retention.** Every frame and REST body is retained raw:
- progressive fsynced gzip members;
- a hard cap of 2,097,152 bytes;
- a reserve of 786,432 bytes, covering the worst pending websocket data, all queued and sweep pairs, and the stop event.

The storage request is 2,146,304 bytes, as a separate allocation that has not been granted. No compression ratio is assumed.

## Classification per instrument

1. **Record.** The first `settledOutcome` object that binds to the id and spec with fraction exactly 0 or 1. Null, wrong-id, wrong-spec and bad-fraction responses are listed with their issues.
2. **Post-record book.** The first `l2Book` whose send time on the monotonic clock follows the record's receipt. A book read before the record is never used; a test makes a gap-displaying pre-record book and confirms it is ignored. The classes are:
   - `winner_gap_displayed`: the winner YES ask is below 1, or the loser YES bid is above 0. This is a conditional recorded display only, for three reasons:
     - once a valid record exists, tokens may already be retired, and post-settlement purchases, splits and redemption are unproven;
     - a pre-split inventory may already have become cash, leaving no loser to sell;
     - the book read may be a stale display.

     The gaps 1 − a and b are therefore never called closed cash, executable or profit.
   - `no_winner_gap_display`: no gap is displayed; a bid on the winner or an ask on the loser does not count.
   - `no_book_after_record`: the response is `null`.
   - `unavailable`: transport or HTTP failure, or an unparsable book.
3. **Promptness.** The book must be sent within 5 s of the record. A record reached only by the sweep is not prompt evidence.

## Decision and exact failure states

- **`candidate_post_record_display_conditional`.** Any instrument with `winner_gap_displayed`. It is a conditional recorded display after an official record, not proof that trading, splitting or redemption remained available.
- **`park_no_post_record_winner_gap_display`.** Every instrument meets all of the following:
  - it has a record from the event-driven follow-up;
  - its post-record book was sent within 5 s;
  - that book displays no winner gap, or is null.

  The scope is these check times only. The pre-record gap stays unavailable.
- **`inconclusive`.** Otherwise. The failure states listed are:
  - no bound record;
  - record only from the sweep;
  - late or missing post-record book;
  - unparsable book;
  - subscriptions not acknowledged exactly once;
  - stream anomalies;
  - stream censored by the cap, a close, liveness, a connect failure or a transport failure.

  A censored stream does not void the REST causality, but it removes the event trigger, so its instruments fall to the sweep.

## Not established

- determination time;
- takerability or fills;
- fees (charged "when closing or settling", per [fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees); zero is optimistic);
- collateral identity;
- other days;
- whether trading, splitting or redemption remains available after a record, so whether any displayed post-record quote is executable;
- native quote-token identity (`USDC` label in our snapshot; secondary sources say USDH; see source notes).
