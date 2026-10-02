# HIP-4 continuation: supported-path pairing specification v1 (pre-registered, unimplemented)

This is a specification only, with no code and no data. It was written on 2 October 2026 before the frozen Q357 live window opens at 18:35 UTC (final plan `982619f2…`). No live quote or result informed any rule.

An implementation would replay a completed live-v1 bundle offline. Derivations are in [pairing-v1](pairing-v1.md) and claim letters refer to the [closure ledger](closure-proofs-v1.md).

## 1. Inputs, clock and support

- **State.** State comes from the live-v1 causal replay, unchanged:
  - marks in receipt order;
  - frozen source-clock gates;
  - support needs acknowledgements so far and liveness, and ends at invalidation;
  - probe and unattributable-frame suspensions apply.

  K(r) is the mark in force at receipt r, meaning the last mark at or before r.
- **Usable leg.** A member leg j is usable at r if its coin is in K(r)'s supported view and K(r) is live, acknowledged and not invalidated. Its touch on each side is (px, sz).
- **Clock.** There is one anchored monotonic clock, and every interval is half-open. Invalidation, stop and window close win ties.
- **Frozen parameters:**
  - qualification at 1,000 ms, strictly before the interval ends;
  - evaluation delay δ = 500 ms of receipt time;
  - θ = 0.
- **Fees.** The primary output uses zero fees: f = c_split = c_neg = c_merge = 0. Gross components are reported, so any fee schedule can be applied later without a rerun.
- **Displayed conditional evaluation.** Every entry and attempt is evaluated only on K at its evaluation instant. The displayed touch is taken in full up to its size, with no backfill, queue, latency beyond δ, or depth beyond the touch. This is not a fill.

## 2. Forward-first (FF)

1. **Decision.** Each qualifying live-v1 forward run, in either disposition, gives one decision at its r_Q. K(r_Q) fixes:
   - the sold set S (the run key);
   - the limits bⱼᴰ;
   - m = min over j ∈ S of the bid size.
2. **Entry at r_E = r_Q + δ.**
   - For j ∈ S: qⱼ = min(m, bid size) if j is usable with a bid ≥ bⱼᴰ, else 0. For j ∉ S: qⱼ = 0.
   - Holdings start at hⱼ = m − qⱼ for every member, and the outstanding sets at T = m.
   - The entry increment is E = Σ qⱼbⱼ(1 − f) − m(1 − c_merge).
3. **To buy.** oⱼ = T − hⱼ.
4. **Closure trigger.** Take an interval from max(r_E, the previous r_A) onward; a state change at r_A starts a new interval. It must be one on which both hold:
   - every j with oⱼ > 0 is usable with an ask;
   - Σ oⱼaⱼ ≤ T(1 − c_merge − θ).

   It qualifies at start + 1,000 ms, strictly before its end, at r_Q′. Each qualifying interval gives one attempt.
5. **Attempt at r_A = r_Q′ + δ.**
   - Buy pⱼ = min(oⱼ, ask size) if j is usable with an ask ≤ its ask at r_Q′, else 0.
   - Merge M = min over j of (hⱼ + pⱼ).
   - The increment is C = M(1 − c_merge) − Σ pⱼaⱼ.
   - Update hⱼ ← hⱼ + pⱼ − M and T ← T − M. Since pⱼ ≤ oⱼ, no hⱼ ever exceeds T.
   - Bought but unmerged legs stay residual at 0. An attempt with no purchase is a miss.
6. **Closed** when T = 0, at which point every hⱼ is 0.

## 3. Inverse-first (IF), reported separately and never pooled

1. **Decision.** Take a supported interval on which every named leg is usable with an ask and Σ_named a < 1 − c_split − c_merge − θ. It qualifies at start + 1,000 ms. m is the minimum named ask size, and the limits are aⱼᴰ.
2. **Entry at r_E.**
   - Buy pⱼ = min(m, ask size) if usable with an ask ≤ aⱼᴰ, else 0.
   - Then `splitOutcome`(F, M) and `mergeQuestion`(M), with M = min over j of pⱼ.
   - The cash is −Σ pⱼaⱼ − M(c_split + c_merge). This leaves M·NO_F and (pⱼ − M)·YES_Nj, all valued at 0.
   - The amount to sell is kⱼ = pⱼ, using `negateOutcome`(M), which costs M·c_neg at the first attempt.
3. **Trigger.** Take an interval from max(r_E, the previous attempt) onward on which every j with kⱼ > 0 is usable with a bid and Σ kⱼ(bⱼ(1 − f) − aⱼᴱ) ≥ θ. It qualifies at start + 1,000 ms.
4. **Attempt at r_Q′ + δ.**
   - Sell sⱼ = min(kⱼ, bid size) if the bid is at least its bid at r_Q′.
   - The increment is Σ sⱼbⱼ(1 − f), and the update is kⱼ ← kⱼ − sⱼ.
   - Closed when every kⱼ = 0.

## 4. Classes, values and denominators (each route)

- **Classes:**
  - `entry_censored`: a stop at or before r_E;
  - `entry_unfilled`: every qⱼ (FF) or pⱼ (IF) is 0, so v = 0. It is never counted as closed;
  - `invalidated`: invalidation at or before r_E, or before closure;
  - `closed`;
  - `open_at_window_end`;
  - `censored_open`.
- **Value.** v = entry increment + Σ attempt increments, with residuals at 0.
- **Bounds:**
  - `censored_open`: [v, v + T(1 − c_merge)] for FF, and [v, v + Σ kⱼ] for IF (bids are at most 1);
  - `invalidated`: a lower bound v only;
  - `open_at_window_end`: report v and the residual (T or k).
- **Report, per route:**
  - decisions, and admitted = decisions − entry_censored;
  - class counts;
  - closed / admitted, with the bound [closed / admitted, (closed + censored_open + invalidated) / admitted];
  - the complete-case rate, labelled conditional;
  - attempts, partial attempts and misses;
  - Σv, the minimum and maximum of v, and the count with v > 0;
  - the gross components Σqb, Σpa, ΣM and Σm;
  - decisions per supported hour, using live-v1 forward coverage, since both routes need every named leg.
- **Rules:**
  - Each decision has its own notional inventory; the maximum concurrent Σm is descriptive only.
  - No survival estimator is used, because censoring can track repricing.

## 5. One counterexample per unresolved assumption

| Assumption (claim) | Counterexample | Guard here |
| --- | --- | --- |
| Trading stays open in play until settlement (C) | Books halt at kickoff while bbo frames keep the last touches, or fall silent. A displayed minute-30 excursion is then counted though nothing can trade. | None in data. Every in-play result is conditional on C, and a halted book looks like a quiet carry. |
| Conversions stay available while any member is unsettled (E; D is proven only before settlement) | A named member settles early, and `mergeQuestion` then rejects or covers only unsettled members, so the M sets in an FF closure cannot merge. | Any update that touches a member invalidates from its receipt, and open positions keep lower bound v. |
| Conversion timing matches the push and the display (A timing, F) | Conversion happens in block t, the books still display, and `outcomeSettled` arrives seconds later. An attempt in between buys an already-converted YES. | Invalidation starts at the push receipt. Results just before a settlement push are conditional. |
| 0 ≤ settleFraction ≤ 1 (A gives the conversion, not the range) | settleFraction = −0.1 on F makes a held YES_F a liability, so 0-valued FF residuals overstate and closure dominance fails. | None. The zero-valued lower bound assumes the range. |
| A question's fractions sum to 1 | A void match settles every member at 0. NO_F then pays 1 while the named basket pays 0, which breaks IF's NO_F ≡ basket equivalence, and unmerged sets return 0. | Closed decisions merge before settlement, and residuals are already 0. |
| A membership addition credits fallback holders (L, testnet-only page) | Mainnet adds a named outcome without crediting YES_F, so every open set needs a YES_new no holder has, and none can merge. | `questionUpdated` for the question invalidates. |
| Orders are cancelled at settlement (B) | Not used: only immediate takes at r_E and r_A are modelled. A resting-order variant could fill a stale order after a halt. | No resting orders. |
| Unit granularity (D, M) | A lot of 10 makes q = min(m, 7) = 7 untradeable, and a split or merge of 7 may be rejected. | None. Quantities are conditional; observed sizes were integral. |
| Zero fees (H, L) | With base 0.0005 and f = 2·base = 0.001, a displayed Σb = 1.0005 gives Σb(1 − f) = 0.9994995 < 1. | Gross components are reported. |
| Quote identity (I) | If `USDC` here names a token at 0.99 USD, a closed pair of 0.002 quote is worth 0.00198 USD. | Values are in quote units only. |
