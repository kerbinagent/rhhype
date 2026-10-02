# HIP-4 continuation: book-certificate gate v1 (design, successor after review)

Owner: the Claude Code continuation lane, under the
[continuation grant](../experiment-storage/hip4-research-continuation-allocation-v1.json)
(sha `5f0053c2…`). The input is the mainnet `outcomeMeta` snapshot taken at 12:34:11 UTC. The request protocol and source were frozen in `9fac381`; the result was committed in `341ee58`:
- Raw response sha `5a84b598…`.
- [Projection](../hip4-outcome-v1/metadata-v1/metadata.json), sha `66913ed2…`.

It contains 260 outcomes and 18 structurally complete questions with 86 members. All quote labels are `USDC`; there are no precision fields; every `settledNamedOutcomes` is empty. This design authorizes no request; root freezes a separate plan first.

This successor incorporates root's operational review and two independent Sol math reviews (exact arithmetic, model labels, claim scope).

## Cohort, groups and denominators

The cohort is all 18 questions, chosen from metadata only. Every question keeps a status. The projection adds deterministic group totals. The groups are fixed by question id from the frozen labels, used for reporting only, and are correlated clusters rather than independent regimes:
- **Tournament winners:** 198, 199, 200, 250.
- **Policy rate:** 289, 331 (one FOMC event).
- **Match results:** 357–370, 11 questions (one matchday).
- **Recurring BTC buckets:** 371.

## H1: zero-fee static conversion certificate (exact claim)

The data is one YES-side `l2Book` per member, coin `#<10·outcome>`. Under the documented merged book it is the only liquidity for both sides; the NO coin is never summed with it.

**Claim.** Conditional on premises P1–P5, and on reading the frozen vector of recorded quotes as one executable state: if `Σ bid ≤ 1 ≤ Σ ask` for a usable question (a missing bid counts as 0 and a missing ask as 1, in exact arithmetic), then no sequence of taker trades and documented zero-cost conversions against that state yields positive closed cash, at the touch or at depth.
- Fees, discrete lots and minimum sizes can only remove such cycles.
- The timing gates do **not** prove simultaneity. Prices that change during the request window could create routes this snapshot cannot exclude.
- A failed certificate is only a candidate.

**Premises.**
- **P1, membership.** Membership equals the frozen projection, and both `outcomeMeta` reads reproduce the question's canonical projected structure.
- **P2, active state.** Not proven; the reads bracket it only.
- **P3, conversions.** Documented split, merge, `mergeQuestion` and negate exist at zero cost in the books' quote token. The label is `USDC`; its identity is unverified.
- **P4, merged book.** Tested as described under premise falsifiers below.
- **P5, timing** (all checked):
  - member book server times within 2,000 ms;
  - each book received between 250 ms before and 5,000 ms after its server time;
  - from the first member request sent to the last received, within 2,000 ms, compared in exact nanoseconds.

  Wall-clock and monotonic times are recorded for every request. The supervisor also checks that the clocks are integers and ordered, and that declared lengths and per-kind caps match each body.

**Exact arithmetic.** Every price and size must have at most 20 integer and 30 fractional digits. Every certificate, complement, sum and dominance computation runs in a decimal context with precision 120 and `Inexact`/`Rounded` trapped. The frozen v1 certificate is reused unchanged through this wrapper. Under the default 28-digit context, `0.5000…0001 + 0.5` rounds and was falsely certified; that is now a test.

**Status precedence.** A question with any book failure is `not_attempted` or `book_unavailable`. Otherwise the first matching condition applies:
1. `metadata_changed` (changed or missing in either read);
2. `metadata_unverified` (a read unavailable);
3. `stale_or_future_book`;
4. `local_window_exceeded`;
5. `timing_unusable` (server spread);
6. `premise_failed` (P4 falsified);
7. otherwise the certificate status.

A certificate failure behind any of these gates is listed in `gated_certificate_failures`. It is never dropped.

**Decision.**
- **Park:** at least 12 of 18 questions usable, every usable question certified, and P4 not falsified.
- **Candidates:** any usable certificate failure goes to a separately frozen fee, depth, precision and timing review. Never execution, never profit.
- **Inconclusive:** otherwise. Candidates and gated failures are listed even when the result is inconclusive.

## Premise falsifiers carried by the same snapshot

- **P4.** Two NO-side mirrors (`#14721`, `#75511`) are fetched directly after their YES books. Every displayed level is compared exactly: price complement, size and order count, on both sides. Equal server times with any mismatch falsify P4, and every question becomes `premise_failed`. Unequal times give `mismatch_different_time`, a timing-limited result only.
- **Fallback books.** Displayed fallback levels are observed resting orders. They are not proof of present takerability, and an empty book is no evidence. With no fallback bid, the forward route can only be a residual candidate; with no fallback ask, the inverse route is impossible.
- **Native units.** The maximum fractional digits of `px` and `sz`, and any fractional size, are observations, not authority.

## H2: recurring BTC settlement dominance (conditional, distinct)

The instruments are binary 7544 (`targetPrice:85971`) and question 371 (`priceThresholds:84251,87690`). They share expiry `20261003-0600` and, per the official contract spec, one interpolated mark X (premise P8). The bucket index map `index:0/1/2` = L/M/H is assumed (P6).

**Collateral (P9).** B and the buckets are both labelled `USDC`. Common collateral is assumed but unresolved beyond the label, so H2 makes no USD claim.

**H2 bracket (P7).** In both reads, the 7544 entry must appear exactly once and be byte-identical in canonical JSON to the frozen baseline in the plan. A changed, missing, duplicated or unverified B blocks H2, and so does a Q371 metadata change.

**Two models, both conditional.**
- **Agnostic six-state** (no premise about B in the fallback state). States L, M1, M2, H, F0, F1 with B = M2+H+F1, so H ≤ B ≤ 1−L. A valuation exists iff:
  - every interval is consistent;
  - `aL ≤ min(bL, 1−aB)` and `aH ≤ min(bH, bB)`;
  - `aL+aM+aH+aF ≤ 1 ≤ min(bL,1−aB) + bM + min(bH,bB) + bF`; B is not in the sum.
- **F=0 semantic.** Adds "exactly one of the 3 buckets settles to 1", intersected with the F quotes: a positive F bid is a premise conflict, which is infeasible. Then B = M2+H, and a valuation exists iff `max(aM+aH, aB, 1−bL) ≤ min(bM+min(bH,bB), 1−aL)` together with `aH ≤ min(bH,bB)`.

Both closed forms match exhaustive tenths-grid search, and the reviewers' near-boundary counterexamples are tests.

**H2 is usable only if:**
- both brackets are unchanged;
- all five books are fresh;
- the local window and server spread are within 2,000 ms;
- P4 is not falsified.

**Interpretation.** Infeasibility is a hold-to-settlement candidate only. It authorizes no naked short; construction, collateral and settlement gates are future work.

## Requests, retention and supervisor

| # | Request | Weight | Body cap |
| --- | --- | --- | --- |
| 1 | `outcomeMeta` | 20 | 196,608 |
| 2–90 | 89 books: 86 member YES books; NO mirrors directly after their YES books; `#75440` after question 371 | 2 each | 8,192 |
| 91 | `outcomeMeta` | 20 | 196,608 |

**Connections and pacing.**
- Requests are sequential on one keep-alive connection.
- After any protocol-indicated close (`response.will_close` or `Connection: close`), the connection is retired. A new one opens only for the next distinct planned request; it is never a retry. Every open, including any implicit reconnect, is counted.
- At least 50 ms between requests. The deadline is checked before the spacing sleep and again immediately before sending.
- 10 s per request and 150 s per process.

**Stop handling.** Any stop or failure (transport, HTTP, cap, partial read, deadline) is a run failure. The retained prefix bundle and the terminal are published; no projection is accepted. Partial reads keep their bounded `partial` bytes. A body is never retained beyond its cap; `over_cap` is the evidence.

**Bundle.** The bundle is a deterministic gzip of framed records: a canonical JSON header with 16 fixed keys, then the exact body. It holds at most 393,216 compressed bytes. Collection refuses any request whose worst case could exceed that.

**Projection.** The worker analyzes the parsed, retained bundle, not process memory.

**Supervisor.** It always writes a receipt, including after a process start failure. It sets `conclusion_eligible` only if all of these hold:
- a clean exit;
- a valid terminal without failure, with 91 attempts;
- the bundle bytes and sha match the terminal;
- strict bundle framing with no trailing data, matching header hashes and exactly the 91 planned records in order (index, kind, coin, payload), all HTTP 200;
- an independent re-analysis that reproduces the projection exactly;
- no pending files;
- final pins verify.

Without a trusted terminal, `requests_attempted` is `unknown_0_to_91`.

## Not established

Simultaneous executable liquidity, takerability, fills, queue position, fees, quote-asset identity, active state beyond bracketing, other times, maker strategies, and any profit.
