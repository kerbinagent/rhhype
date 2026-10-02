# HIP-4 continuation: funded supported-path pairing specification (revision 4, final draft, unimplemented)

This is a specification only, with no code, data or live quotes.
- Revision 1 was archived unaccepted at `20b192a`.
- Revision 3 (`b56e8164`) was reconciled by root and Sol at 16:57 UTC on 2 October 2026.
- This revision adds root's five clarifications and an adversarial audit (section 8).

It was written before the frozen Q357 window opened (launch 18:22 UTC, observation 18:35–20:50 UTC, plan `982619f2…`). Derivations are in [pairing-v1](pairing-v1.md) and claim letters refer to the [closure ledger](closure-proofs-v1.md).

## 1. Conditioning, gates, ties and fees

- **Supported path.** State is the live-v1 causal replay, unchanged, and K(x) is the last mark at or before x. Frames received at x are applied before any evaluation at x.
  - Leg j is usable at x if its coin is in K(x)'s supported view, K(x) is acknowledged and not invalidated, x < K(x).live, and its needed side shows a size above 0.
  - **Liveness** in the frozen live-v1 replay is the last application message, on any channel, + 35,000 ms. There is no per-touch age cap: other messages can keep a quiet coin's touch usable through the whole window. Source-clock gates run only at receipt. This carry is an unverified change-feed premise, kept as is.
  - A future implementation must report each leg's touch age at every evaluation.
  - An unusable leg fills 0, and that is reported as an unsupported outcome.
- **Gate intervals.** A predicate is a key, a support condition and an economic test. It is evaluated at every frame, at every liveness expiry and at every state change of its own episode.
  - Its interval is the maximal half-open stretch on which it is continuously true. Frames that keep it true do not restart it.
  - It qualifies at q = start + 1,000 ms, but only if q is strictly before the interval's end. Limits and m are read from K(q).
  - **One evaluation per maximal interval,** at q + δ, with δ = 500 ms, on K only. This is a displayed conditional evaluation: each touch is taken up to its finite size at the evaluation price, with no backfill.
  - **State changes.** A change of holdings or conversion state at an evaluation ends the old interval. If the predicate is true at that instant, after the change, a fresh interval starts exactly there; it never starts earlier.
  - **Misses.** An attempt that misses everything and changes nothing cannot retry until its predicate is first false and then true again.
- **Episodes.** Key, quantities, gate state and capital belong to one episode. Overlapping FF and IF episodes share nothing, and each FF decision interval opens exactly one episode.
- **Ties.** Let e = min(s, i, c), where:
  - s is a censoring stop (any stop except `window_closed`);
  - i is the invalidation receipt;
  - c is window close.

  An evaluation at x runs only if x < e. Classification uses e. Censored, then invalidated, then window end is used only to break exactly equal timestamps.
- **Fees.** A run fixes one schedule φ = (f, c_split, c_neg, c_merge), with 0 ≤ f ≤ 1 and each c ≥ 0. φ enters every gate, so decisions depend on it. The primary run uses φ = 0, which is optimistic (H). Repricing a φ = 0 path is a sensitivity only.
- **Conditional assumptions.** Conversions execute at the instant of the orders and in the order listed (D). Amounts are unit-granular (M). Trading is open (C). A conversion with amount 0 is skipped, at no cost.

## 2. Funded forward-first (FF)

| Instant | Action, in order | Cash | Holdings after |
| --- | --- | --- | --- |
| r_Q | qualify g = Σ_{j∈S} bⱼ(1 − f) − (1 + c_split + c_neg) > 0, with key S = the usable members that have a bid; fix bⱼᴰ and m = the minimum bid size over S | 0 | none |
| r_E | `splitOutcome` + `negateOutcome` on m sets | −m(1 + c_split + c_neg) | m of each member |
| r_E | sell qⱼ = min(m, bid size) of each j ∈ S that is usable with a bid ≥ bⱼᴰ (else 0) | +Σ qⱼbⱼ(1 − f) | hⱼ = m − qⱼ |
| r_E | `mergeQuestion`(U), with U = minⱼ hⱼ | +U(1 − c_merge) | hⱼ −= U; T = maxⱼ hⱼ |
| r_A | buy pⱼ = min(oⱼ, ask size), where oⱼ = T − hⱼ, if usable with an ask ≤ its ask at qualification (else 0) | −Σ pⱼaⱼ | hⱼ += pⱼ |
| r_A | `mergeQuestion`(M), with M = minⱼ hⱼ | +M(1 − c_merge) | hⱼ −= M; T = maxⱼ hⱼ |

- **Closure gate.** Every j with oⱼ > 0 must be usable with an ask, and T(1 − c_merge) − Σ oⱼaⱼ ≥ 0.
- **Entry outcomes.**
  - T = 0 at r_E with Σq > 0 is `entry_closed`. It requires every member, the fallback included, to sell an equal qⱼ.
  - Σq = 0 is `entry_unfilled`, with v = −m(c_split + c_neg + c_merge).
- **Zero fees.** At φ = 0, g matches the live-v1 forward run.

## 3. Funded inverse-first (IF), never pooled with FF

| Instant | Action, in order | Cash | Holdings after |
| --- | --- | --- | --- |
| r_Q | qualify g = 1 − c_split − c_merge − Σ_named aⱼ > 0, with every named leg usable with an ask; fix aⱼᴰ and m = the minimum ask size | 0 | none |
| r_E | buy pⱼ = min(m, ask size) if usable with an ask ≤ aⱼᴰ (else 0) | −Σ pⱼaⱼ | pⱼ of each named |
| r_E | `splitOutcome`(F, M), then `mergeQuestion`(M), with M = minⱼ pⱼ | −M(1 + c_split), then +M(1 − c_merge) | M NO_F; nⱼ = pⱼ − M |
| first r_A | `negateOutcome`(F, M); a state change even if every sale misses | −M·c_neg | NO_F 0; kⱼ = nⱼ + M |
| each r_A | sell sⱼ = min(kⱼ, bid size) if usable with a bid ≥ its bid at qualification (else 0) | +Σ sⱼbⱼ(1 − f) | kⱼ −= sⱼ |

- **Basis and recovery.** The basis is B = Σ pⱼaⱼ + M(c_split + c_merge). R is the sale proceeds minus any c_neg paid.
- **Gate.** Every leg to sell must be usable with a bid, and Σ kⱼbⱼ(1 − f) − N·c_neg ≥ B − R.
  - Before the first attempt, the kⱼ are the post-negation amounts and N = M; afterwards N = 0.
- **NO_F before negation** is a residual asset valued at 0 (claim A).
- **Outcomes.** All pⱼ = 0 gives `entry_unfilled` with v = 0. The episode is closed when NO_F = 0 and every kⱼ = 0.

## 4. Invariants and capital

- **FF.**
  - 0 ≤ hⱼ ≤ T = maxⱼ hⱼ, and minⱼ hⱼ = 0 after every merge.
  - T = 0 exactly when inventory is zero.
  - v = −m(1 + c_split + c_neg) + Σ qb(1 − f) − Σ pa + (U + ΣM)(1 − c_merge).
- **IF.**
  - kⱼ ≥ 0 and NO_F ≥ 0.
  - v = −B − (M·c_neg if negated) + Σ sb(1 − f).
- **Capital.** Required capital is the negative of the chronological minimum of the cash prefix over every action, in the order listed. It is reported as conditional required capital per episode, assuming unlimited prefunding, and never as portfolio capital.

## 5. Classes, envelope and reporting

- **Classes.**
  - If e ≤ r_E: `entry_censored`, `entry_invalidated` or `entry_after_close`, according to e.
  - Otherwise, after entry: `entry_unfilled` or `entry_closed`.
  - Then `closed` at some r_A < e.
  - Otherwise, according to e: `censored_open`, `invalidated_open` or `open_at_window_end`.
- **Rates.**
  - filled = entry_closed + closed + the three open classes.
  - The decision-to-fill rate is filled / (decisions − entry_censored). It counts entry_invalidated and entry_after_close as failures.
  - Closure within the observed window is (entry_closed + closed) / filled. Its upper bound adds censored_open and invalidated_open; it says nothing about eventual closure.
  - The complete-case rate is labelled conditional.
  - Any rate with a zero denominator is reported as unavailable.
  - Zeroed fills are counted separately by cause: not usable, limit, or size.
- **Envelope.** This is formal, never statistical, and holds only under three assumptions:
  - A1: 0 ≤ settleFraction ≤ 1;
  - A2: a question's fractions sum to 1;
  - A3: no cost beyond the settlement fee f.

  An open episode then ends in [v, v + W]:
  - FF: W = T(1 − f);
  - IF: W = maxⱼ (xⱼ + NO_F)(1 − f), where xⱼ is the named YES held.

  Without A1 and A2, no envelope is claimed.
- **Episode sums.** Σv is an overlapping-event statistic, never portfolio cash. No survival estimator is used.

## 6. Class fixtures and invariant audit (φ = 0; m = 10; legs F, A, D, B2; F unsold unless stated)

| # | Class | Fixture | End state (audited) |
| --- | --- | --- | --- |
| 1 | entry_censored | a stop at r_Q + 300 ms | v = 0 |
| 2 | entry_invalidated | `questionSettled` received exactly at r_E | the evaluation is not run; v = 0 |
| 3 | entry_after_close | r_Q = c − 200 ms | v = 0 |
| 4 | entry_unfilled | every bid below its limit at r_E | U = 10, T = 0, v = 0; capital 10 |
| 5 | entry_closed | S includes F (bid 0.02); all four sell 10 at 0.02, 0.31, 0.26, 0.45 | T = 0, v = 0.40; capital 10 |
| 6 | closed | sells 10 at 0.31, 0.26, 0.45 (v 0.20, T 10); a gate that holds 999 ms gives no attempt; a later gate buys 10 at 0.30, 0.25, 0.44 and merges 10 | T = 0, v = 0.30 |
| 7 | closed, loss | only A sells, 10 at 0.01 (v −9.90); the gate passes; A is bought at 0.99 | the prefix reaches −19.80 before the merge; v = −9.80; capital 19.80 |
| 8 | open_at_window_end | as 6, but D's ask size is 3: buys 10, 3, 10 and merges 3 | h = (7, 7, 0, 7), T = 7, v = −4.95, envelope [−4.95, 2.05] |
| 9 | censored_open | A sells 10 at 0.31, D sells 4 at 0.26, B2 not usable; then a stop | T = 10, v = −5.86, envelope [−5.86, 4.14] |
| 10 | invalidated_open | as 6 to entry; a member update arrives before any gate qualifies | T = 10, v = 0.20, envelope [0.20, 10.20] |
| 11 | IF closed, M = 0 | buys A 10 at 0.30 and B2 10 at 0.44; D misses its limit, so no conversions; later sells both at 0.31 and 0.45 | v = 0.20 |
| 12 | IF censored_open | buys 10 each at 0.30, 0.25, 0.44 (M = 10); negates and misses; a fresh gate sells 10, 10, 4 at 0.31, 0.26, 0.45; then a stop | k = (0, 0, 6), v = −2.40, envelope [−2.40, 3.60] |

## 7. One counterexample per unresolved assumption

| Assumption (claim) | Counterexample | Guard |
| --- | --- | --- |
| Trading open in play (C) | Books halt at kickoff but keep displaying, so a counted excursion cannot trade | none; every result is conditional |
| Conversions while a member is unsettled (E) | A member settles early and merges fail | member updates invalidate |
| Conversion timing matches the push (A, F) | A YES is bought after conversion but before the push | invalidation starts at the push |
| 0 ≤ settleFraction ≤ 1 | settleFraction −0.1 makes v not a lower bound | A1 is stated |
| Fractions sum to 1 | A void pays NO_F 1 and the basket 0 | A2 is stated |
| Addition credits the fallback (L) | No open set can merge | `questionUpdated` invalidates |
| Order cancellation (B) | Unused: there are no resting orders | none needed |
| Granularity (D, M) | A lot of 10 makes q = 7 untradeable | conditional |
| Zero fees (H, L) | f = 0.001 turns Σb = 1.0005 into 0.9994995: no decision | φ is a run parameter |
| Quote identity (I) | 0.002 quote at 0.99 USD is 0.00198 USD | quote units only |

## 8. Adversarial audit of this policy

1. **All-miss retry.** Asks can rise above their qualification limits while the gate stays true. The attempt then misses, and the one-evaluation rule blocks any retry until the gate turns false and true again. Closure is therefore starved, never inflated, and the episode ends open. A starved episode is reported as an all-miss attempt, not as a closure failure caused by the market.
2. **Partial-fill restart.** Each state-changing attempt restarts the gate at r_A, so the next evaluation comes at least 1.5 s later. Every such attempt lowers Σ oⱼ (FF) or Σ kⱼ (IF) by at least one unit, so FF has at most Σ oⱼ of them and IF at most Σ kⱼ + 1, counting the negation. The gate prices a full closure, but a partial attempt realizes only part of it. Bought legs that are not merged sit at 0, so v can fall below its entry value (fixture 8).
3. **IF first-negation miss.** Negation is a state change, so a fresh interval starts at r_A. The gate margin is unchanged by negation: before it, Σkb − Mc_neg ≥ B; after it, Σkb ≥ B + Mc_neg (the same 0.290 margin in the check). There is no double count.
4. **Stale quiet coin under live traffic.** Probe frames or pongs keep liveness, so an unchanged D touch from hours earlier stays usable. Only the probe coin is cross-checked. A decision or fill priced on a stale non-probe leg is therefore unverifiable, and touch-age reporting is required before any economic reading.
5. **Equal all-member entry sales.** Selling an equal 4 of 10 on all four members gives U = 6, T = 0, `entry_closed` and v = 0.16. Sales of 4, 6, 6, 6 instead give U = 4 and T = 2 (h_F = 2), so the episode stays open. Because m is fixed at r_Q and sizes can shrink by r_E, all-member decisions often end open.
6. **Same-time events.** An interval cut by a stop, an invalidation or close at q cannot qualify, because q must be strictly before its end. An evaluation at x = e is not run. A frame at x is applied before an evaluation at x, but an invalidation at x still blocks it. A gate that becomes true exactly at r_E or r_A counts from that instant, never earlier.
7. **Sign control.** Gates control prices, not fills. Unequal fills make v negative even when every gate passes (fixtures 7 to 9). Required capital can exceed m(1 + c_split + c_neg), because buys are paid before the merge.
8. **Overlap.** Overlapping episodes may both draw on the same displayed size. Their sums count displayed opportunities, never jointly executable fills.
