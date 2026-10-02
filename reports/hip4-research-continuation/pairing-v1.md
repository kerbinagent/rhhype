# HIP-4 continuation: forward and inverse pairing, causal timed accounting (source and math review v1, revised)

This review uses existing metadata, documents and the books-v1 bundle only. It makes no data query, adds no code and is a proposal only. It applies root's reviews of 2 October 2026, through 16:57 UTC. The funded policy, its audit and its counterexamples are in the [specification](pairing-spec-v1.md), revision 4; revision 1 is archived at `20b192a`. The staged 14:34 draft is preserved in the session scratchpad.

**Scope.** One question with fallback F and named members N1…Nk. The 11 frozen match questions each have k = 3. Every member carries venue `out`, `deployerFeeScale` `"1.0"` and the quote label `USDC` (frozen raw `5a84b598…`). Each member's YES book is merged with its NO book, with touch bid bᵢ and ask aᵢ. All 18 fallback books were empty in books-v1. Claim letters refer to the [closure ledger](closure-proofs-v1.md).

## 1. Units and costs

- **Units.** "Split `X` quote tokens into `X` Yes and `X` No shares" (exchange endpoint). One unit is one token, and prices are quote per token in the question's own quote token. Identity is unbound (I), so no USD claim is made.
- **Sizes.** Books-v1 sizes were integral and prices had at most 5 decimals. These are observations, not lot rules (M).
- **Trading fees.**
  - f = base × (s + max(s, 1)), which is 2·base for `out`.
  - Fees are charged "when closing or settling, not when opening".
  - The base rate is unstated (H), and the formula comes from a testnet-only page (L).
- **Conversion fees.** c_split, c_neg and c_merge are undocumented.
- **Settlement.** Settlement pays `settleFraction` per YES and `1 - settleFraction` per NO (A).

## 2. Ledger, closure and residuals

| Time | Action | Cash | Inventory after |
| --- | --- | --- | --- |
| t₀ | `splitOutcome`(F, m), then `negateOutcome`(F, m) | −m(1 + c_split + c_neg) | m·YES_F, m·YES_Ni |
| t_E | sell qᵢ ≤ m of each YES_Ni at the bids (closing) | +Σ qᵢbᵢ(1 − f) | m·YES_F, (m − qᵢ)·YES_Ni |
| t_C > t_E | buy qᵢ at the asks (opening), then `mergeQuestion`(m) | −Σ qᵢaᵢ + m(1 − c_merge) | none |

- **Closure.** Inventory is zero only if every sold quantity is bought back and every set is merged. Otherwise the residual YES_F and the unsold YES_Ni are valued at 0 until settlement is observed (A, F).
- **Forward only.** Immediate cash is a candidate bound only; with full legs it breaks even at Σb > (1 + c_split + c_neg)/(1 − f).
- **Closed pair.** Σ qᵢ(bᵢ(t_E)(1 − f) − aᵢ(t_C)) − m(c_split + c_neg + c_merge). It is a timed round trip of the named basket, never a static certificate.
- **Contingent closure.** Against holding the residual at 0, a full buy-back adds m(1 − c_merge) − Σ qᵢaᵢ(t_C). It is dominated whenever that is negative, provided settleFraction ≥ 0 (range unstated). At zero fees a forward-first pair is therefore Σb > 1 followed, in the same window, by Σa < 1.
- **Inverse first.** A YES_F comes from a forward leg, from a fallback ask (none observed), or from `splitOutcome`(F), which also leaves a NO_F. The [exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) states:
  - `mergeOutcome`: "Merge `X` Yes and `X` No shares into `X` quote tokens";
  - `negateOutcome`: "Convert `X` No shares from an outcome associated with a question into `X` Yes shares of every other outcome associated with the question".

  NO_F is a residual asset, not a debt, valued at 0 until it is negated and sold, merged, or settled to `1 - settleFraction`.
- **Static cycle at one instant.** This needs fallback quotes, and none was observed.
- **Membership change.** "Holders of the question's fallback YES token receive an equal balance of the new outcome's YES token" (deployer page, testnet-only per L). A later `mergeQuestion` then needs YES_new as well.

## 3. Required margins at observed depth (books-v1, 13:16 UTC on 2 October, pre-match, all 11)

The forward margin is 1 − Σb(q) and the inverse margin is Σa(q) − 1. Each uses size-weighted average prices over the displayed 20 levels for q units of every named member, at zero fees. The swing is their sum: with the displayed spread unchanged, the basket mid must rise and then fall by at least this much for a forward-first pair.

| Q | fwd, q = 1 | fwd, q = 100 | fwd, q = 500 | inv, q = 1 | inv, q = 100 | inv, q = 500 | swing, q = 1 | swing, q = 500 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 357 | 0.00024 | 0.00027 | 0.00129 | 0.00141 | 0.00170 | 0.00445 | 0.00165 | 0.00574 |
| 358 | 0.00265 | 0.00344 | 0.00749 | 0.00372 | 0.00380 | 0.00473 | 0.00637 | 0.01222 |
| 359 | 0.00743 | 0.00785 | 0.00793 | 0.00365 | 0.00369 | 0.00377 | 0.01108 | 0.01170 |
| 361 | 0.00292 | 0.00313 | 0.00990 | 0.01156 | 0.01174 | 0.01910 | 0.01448 | 0.02900 |
| 362 | 0.00636 | 0.00636 | 0.00716 | 0.00258 | 0.00258 | 0.00270 | 0.00894 | 0.00986 |
| 363 | 0.00017 | 0.00018 | 0.00019 | 0.00417 | 0.00590 | 0.00690 | 0.00434 | 0.00709 |
| 366 | 0.00530 | 0.00531 | 0.00534 | 0.00613 | 0.00614 | 0.00656 | 0.01143 | 0.01190 |
| 367 | 0.00220 | 0.00220 | 0.00273 | 0.01601 | 0.01602 | 0.01605 | 0.01821 | 0.01878 |
| 368 | 0.00151 | 0.00151 | 0.00152 | 0.00473 | 0.00509 | 0.39315 | 0.00624 | 0.39467 |
| 369 | 0.00301 | 0.00301 | 0.00361 | 0.00648 | 0.00652 | 0.00781 | 0.00949 | 0.01142 |
| 370 | 0.00116 | 0.00141 | 0.00285 | 0.00961 | 0.00961 | 0.00996 | 0.01077 | 0.01281 |

- Every entry was rechecked against the frozen bundle.
- All 66 margins are positive.
- The q = 1 swings are exact; the q = 500 swings are good to ±0.00001.
- Fees add f/(1 − f) to the forward margin.
- This is one static snapshot, and no executable size is inferred.
- Root froze a live run on Q357 (`d2050ce`): launch at 18:22 UTC, observation 18:35–20:50 UTC on 2 October. Q357 has the smallest swing at both depths, though this is a static ranking only.

## 4. Conclusion

On existing data, no forward route, inverse route or same-instant pair is positive for any match question at any shown depth. Any future statistic measures displayed, causally reachable states, not fills. It stays conditional on fees (H, L), granularity (D, M), settlement handling (A, B, C, E, F) and quote identity (I).
