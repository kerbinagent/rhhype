# HIP-4 continuation: near-expiry BTC dominance and settlement semantics v1 (design, revised after root review)

This design is separate from the book gate v1, whose result is frozen and unchanged. This revision fixes the semantics and retention defects root found at 13:40 UTC on 2 October 2026. It authorizes no request; root freezes a plan first. The instruments are fixed by the snapshot whose protocol was frozen in `9fac381` and whose result was committed in `341ee58` (raw `5a84b598…`):

| Role | Outcome | Frozen description |
| --- | --- | --- |
| B (standalone) | 7544 | `class:priceBinary\|underlying:BTC\|expiry:20261003-0600\|targetPrice:85971\|period:1d` |
| Question 371 | fallback 7550, named 7551–7553 | `class:priceBucket\|underlying:BTC\|expiry:20261003-0600\|priceThresholds:84251,87690\|period:1d` |
| Control (long-dated, unsettled) | 1473 | question 198 member |

## Questions answered

1. **H2.** Near expiry, are the YES books valuation-infeasible in the agnostic six-state model or the F=0 semantic model? These are the same exact-arithmetic closed forms as the reviewed book gate, validated against exhaustive search. The relations are H ≤ B ≤ 1−L in the agnostic model, and H ≤ B ≤ M+H with F=0 in the semantic model. Q371's conversion certificate is also reported at each snapshot.
2. **P6 at the observed price.** After settlement, do the bound `settleFraction` values of 7550–7553 and 7544 match `index:0/1/2` = `<84251`, `[84251, 87690)`, `≥87690`, F = 0 and `B = 1{X ≥ 85971}` at the one realized X, taken from `details: "price:X"`? One price can falsify the proposed mapping but cannot identify it: the two buckets that do not contain X could be swapped without changing the observation.
3. **Settlement observation bounds.** By the receipt of which `settledOutcome` read, scheduled near 06:01 and 06:10, was a valid bound object first observed? Both reads keep their send and receive times and response shapes. No protocol settlement lower bound is derived, because a null response is not proof of an unsettled state.
4. **Active-state semantics.** Are settled outcomes and the settled question absent from a strictly parsed final `outcomeMeta`?
5. **Undocumented response.** What does `settledOutcome` return for an unsettled outcome (1473)?

Questions 2–5 close source gaps from the review with direct observation. They use only `outcomeMeta` and `settledOutcome` responses, and `settledOutcome` carries the settlement price in `details`. Question 1 uses the 15 YES `l2Book` snapshots. The proposed collection as a whole therefore includes L2 order-book prices and is not metadata-only.

**Power note from the books-v1 run (13:16 UTC, bundle `b5b6e244…`).** The M and H bucket books (7552, 7553) each showed only a bid of 0.00021 and an ask of 0.99979. The L bucket (7551) was 0.00021/0.08415, and B (7544) was 0.715/0.73021. At those quotes no H2 relation can bind. Question 1 therefore has low expected power unless bucket liquidity appears near expiry.

## Schedule (UTC, 3 October 2026)

| Time | Requests |
| --- | --- |
| launch window | 05:00:00 ≤ start < 05:38:00, else refused (no late or partial schedule) |
| 05:40:00 | `outcomeMeta` (bracket start) |
| 05:40:05, 05:50:00, 05:57:00 | snapshot: YES `l2Book` for 7550, 7551, 7552, 7553, 7544 |
| 05:57:10 | `outcomeMeta` (bracket end) |
| 06:01:00 | `settledOutcome` for 7544, 7550, 7551, 7552, 7553, 1473 |
| 06:10:00 | the same six, then `outcomeMeta` |

Totals: 30 requests, weight 330, spread over about 30 minutes. Each of the 7 scheduled groups uses one keep-alive connection via the reused book-gate fetch, so 7 connections are expected; every open is counted.
- No retry, redirect or proxy.
- The first transport or HTTP failure stops the run.
- 10 s per request.
- The process deadline is 06:12:30.

## Retention

Each record becomes one gzip member, holding a framed header (with its group and scheduled time) and the exact body. The bundle has an exact cap of 49,152 bytes.

**Incremental persistence.** Each member is written and fsynced to `responses.members.gz.pending` before the next request. At the end, the pending file is hard-linked to the final name, so both names share one inode, and then unlinked. If the supervisor kills the worker, the fsynced prefix stays in the pending file and the run is not conclusion-eligible.

**Fail-closed admission.** A request is sent only if a worst-case empty record still fits. That bound, `EMPTY_BOUND` = 771 bytes, is the stored (level 0) member of a header with the longest form of every field.

**Truncation.** If a received record's level 9 member does not fit, the record keeps a bounded body prefix encoded as a stored member. The prefix is not proven maximal, because the header's digit count can change. A stored member's size never shrinks by less than the number of bytes removed, so cutting the measured excess always fits. Because the admission bound guarantees the empty record fits, this never fails silently. The record is flagged `truncated_from`, collection stops, the run is a resource failure, and no projection is accepted. Binary search over level 9 sizes is not used, because gzip length is not monotone in prefix length.

Expected size is about 31 KB. The three metadata bodies are 84,207 bytes raw and about 5,900 bytes each at level 9 (measured on the 13:16 UTC books-v1 reads). Books and settlement records add a few hundred bytes each.

**Allocation.** Root confirmed that the existing continuation raw headroom (131,072 bytes after the books-v1 suballocation) covers 49,152 bytes. Derived outputs: projection at most 24,576 bytes; receipts 12,288.

## Analysis

**Per snapshot.** Tops for the five instruments, under the same gates as the book gate: server spread at most 2,000 ms, book age between −250 ms and +5,000 ms, and a local request window of at most 2,000 ms. Q371's certificate and H2 in both models are computed in the exact decimal context, with named relations.

A snapshot is usable only if all of the following hold:
- the Q371 projected structure equals the frozen projection at both bracket ends;
- the 7544 spec is byte-identical in canonical JSON at both ends;
- all five books parse.

**Settlement binding.** A `settledOutcome` response counts as a valid settlement only if all of the following hold:
- it is an object whose `spec.outcome` is the requested id;
- the whole spec equals the frozen canonical spec in canonical JSON (from the pinned projection's member specs; 7544 from the frozen baseline);
- `settleFraction` is a decimal in [0, 1].

Anything else is retained with its issues: null, invalid JSON, a wrong spec, a missing or out-of-range fraction.

**Price-detail premise (P8, per role).** B, L, M and H must each carry `details: "price:X"`, and all observed X must agree. F may omit `details` or carry the empty string, the form the deployer page documents for deployer settlements. A present F detail must parse as `price:X` and agree. Each of these is a premise failure and never counts as agreement:
- a missing required price;
- any present but unparsable detail, for example `price:-1`, `price:abc` or a number;
- prices that disagree.

A route's settlement validity for ex-post values is separate from P8. Observed prices are retained unchanged.

**P6 at the observed price.** With every premise satisfied, each role is compared at the one X: L = 1 iff X < 84251; M = 1 iff 84251 ≤ X < 87690; H = 1 iff X ≥ 87690; F = 0; B = 1 iff X ≥ 85971. Fractions must be 0 or 1. The projection keeps each role's fraction, price, expected value and match flag.

**Settlement observation bounds.** These use observed times only, not the schedule:
- each read keeps its send and receive times and response shape;
- `valid_object_observed_by_ms` is the receive time of the first read returning a valid bound object, also given relative to 06:00:00;
- `protocol_settlement_lower_bound` is always `unavailable`;
- a valid object followed by null is flagged `null_after_valid_object`.

A valid object proves only that the record existed by that receipt. It is not the exact settlement time. Null is recorded as a response shape, not as proof of an unsettled state.

**Removal.** The final `outcomeMeta` must parse strictly: `outcomes` and `questions` lists, integer ids and no duplicates. It must also contain the long-dated control as a built-in witness: question 198 must match its frozen structure under the book-gate meta check, and control outcome 1473 must be listed. Only then is each id and Q371 classified as `listed` or `absent`; otherwise the result is `unavailable`. Each of these is therefore unavailable, not a removal:
- `{}`;
- `{"outcomes":[],"questions":[]}`;
- a response missing or altering the control.

**Conditional zero-fee ex-post accounting.** For each true named relation at a usable snapshot, take one unit at the touch, held to settlement. A route carries a value only if every role it uses has a valid bound settlement. Otherwise it lists its premise failures and has no value. This claims no fills. Settlement converts every token to quote, so terminal inventory is zero.
- `B_ask<H_bid`: buy B YES; split H; sell H YES; hold B YES and H NO.
- `B_bid>M_ask+H_ask+F_ask` (agnostic) or `B_bid>M_ask+H_ask` (F=0 semantic only): split B; sell B YES; buy the M, H (and F) YES.
- `B_bid+L_bid>1`: split B and L; sell both YES; hold both NO.

The fees at sale and settlement are unknown, so the result is an upper bound. Any other infeasible combination is reported without a route.

## Decisions

- **H2 at this expiry.**
  - `no_violation` if every usable snapshot is feasible in the agnostic six-state model.
  - `candidate` if any usable snapshot is infeasible; this needs a separate fee, settlement-latency and depth review.
  - `inconclusive` if no snapshot is usable.
  - One expiry gives no repeatability. The F=0 semantic model is conditional and reported separately. Infeasibility authorizes no naked short; construction, collateral and settlement gates remain future work.
- **P6.**
  - `consistent_at_observed_price` if every role matches at the observed X. This is not universal verification: the mapping at unobserved prices stays conditional.
  - `falsified_at_observed_price` on any mismatch.
  - `unavailable`, with every premise failure listed, otherwise.
- **Removal semantics.** Each of the six ids and Q371 is classified as `listed` or `absent` from the strictly parsed final read with an intact control witness (question 198 and outcome 1473), or as `unavailable`. Absence is a listing observation, not proof of settlement; settlement evidence comes only from bound `settledOutcome` objects.
- **Reproduction.** The supervisor re-parses the members and validates, for each of the 30 records:
  - plan identity and the scheduled time;
  - sending no earlier than the schedule, and the first record of each group within 5 s;
  - receipt before the next group's start;
  - integer, monotone clocks, caps and declared lengths.

  It then reproduces the projection exactly.
- **Unsettled response.** The shape of the 1473 response (null or object) is recorded without interpretation.

None of these establishes fills, fees, quote identity or profit.
