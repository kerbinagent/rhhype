# HIP-4 continuation: forward and inverse pairing, causal timed accounting (source and math review v1, revised)

This review uses existing metadata, documents and the books-v1 bundle only; it makes no data query and adds no code. It is a proposal only. The revision applies root's review of 14:48 UTC on 2 October 2026:
- causal entry after qualification;
- full-cohort denominators;
- depth reported only as observed;
- inverse-first with its NO_F residual, which root's 14:50 correction says is an asset claim, not a debt.

Later additions:
- contingent closure (section 2);
- the round-trip swing (section 3);
- section 4 now points to the [pre-registered specification](pairing-spec-v1.md).

The staged 14:34 draft is preserved in the session scratchpad.

**Scope.** One question with fallback F and named members N1…Nk. The 11 frozen match questions each have k = 3. Every member carries venue `out`, `deployerFeeScale` `"1.0"` and the quote label `USDC` (frozen raw `5a84b598…`). Each member's YES book is merged with its NO book, with touch bid bᵢ and ask aᵢ. All 18 fallback books were empty in books-v1. Claim letters refer to the [closure ledger](closure-proofs-v1.md).

## 1. Units, costs and quote-unit assumptions

- **Units.** "Split `X` quote tokens into `X` Yes and `X` No shares" (exchange endpoint). One unit is one token. Prices are quote per token, and all legs use the question's own quote token. Identity is unbound (I), so no USD claim is made.
- **Sizes.** Books-v1 sizes were integral and prices had at most 5 decimals. These are observations, not lot rules (M).
- **Trading fees.**
  - The user rate is f = base × (s + max(s, 1)). For `out`, s = 1, so f = 2·base.
  - Fees are charged "when closing or settling, not when opening".
  - The base rate is unstated (H), and the formula comes from a testnet-only page (L).
- **Conversion fees.** c_conv = c_split + c_neg per set and c_merge (per `mergeQuestion` unit) are undocumented. Settlement pays `settleFraction` per YES and `1 - settleFraction` per NO (A); a settlement fee f is assumed on the payout.

## 2. Timed ledger and residuals

| Time | Action | Cash | Inventory after |
| --- | --- | --- | --- |
| t₀ | `splitOutcome`(F, n), then `negateOutcome`(F, n) | −n(1 + c_conv) | n·YES_F, n·YES_Ni |
| t_E | sell qᵢ ≤ m of each YES_Ni at the bid levels (closing) | +Σ qᵢ·bᵢ·(1 − f) | n·YES_F, (n − qᵢ)·YES_Ni |
| t_C > t_E | buy qᵢ of each YES_Ni at the ask levels (opening), then `mergeQuestion`(m) | −Σ qᵢ·aᵢ + m(1 − c_merge) | (n − m)·YES_F, (n − m)·YES_Ni |
| before T | `mergeQuestion`(n − m) on the unused sets | +(n − m)(1 − c_merge) | none |
| T | otherwise, each held token settles | + settleFraction × (1 − f) per token | none |

**Closure.** Inventory is zero before T only if every sold quantity is bought back, m sets are merged and the unused sets are merged. Otherwise these stay open, valued at 0 until settlement is observed (A, F):
- m·YES_F;
- the unsold remainders (m − qᵢ)·YES_Ni.

**Forward only.**
- Immediate cash = Σ qᵢbᵢ(1 − f) − m(1 + c_conv), with residuals open: a candidate bound only.
- With full legs (qᵢ = m), the break-even is Σb > (1 + c_conv)/(1 − f).

**Closed pair.** Σ qᵢ(bᵢ(t_E)(1 − f) − aᵢ(t_C)) − m(c_conv + c_merge). It needs later asks below earlier net bids, so it is a timed round trip of the named basket (worth 1 − settle_F), never a static certificate.

**Contingent closure.** Take m sets already made at t₀. Compare each step with a no-trade baseline that merges every set back at window end for 1 − c_merge, with residuals valued at 0:

| Step | Increment over baseline | Value-adding iff (full legs) |
| --- | --- | --- |
| forward entry at t_E | Σ qᵢbᵢ(t_E)(1 − f) − m(1 − c_merge) | Σb(t_E)(1 − f) > 1 − c_merge |
| closure at t_C | m(1 − c_merge) − Σ qᵢaᵢ(t_C) | Σa(t_C) < 1 − c_merge |

- The baseline −m(c_conv + c_merge) plus the two increments gives the closed-pair total. The closure row also holds with partial legs, because the merge recovers the unsold (m − qᵢ)·YES_Ni that were valued at 0.
- A closure with Σ qᵢaᵢ(t_C) > m(1 − c_merge) is dominated. It pays cash now to give up m·YES_F, which settles to `settleFraction` quote tokens (A) and so is worth at least 0, provided settleFraction ≥ 0 (its range is not stated).
- The earlier trigger, "pair total ≥ θ", admitted such dominated closures. The [specification](pairing-spec-v1.md) uses the closure row as the trigger.
- At zero fees the two tests are Σb > 1 and then Σa < 1. A forward-first pair is therefore a forward excursion followed, in the same window, by an inverse excursion that uses the held YES_F.

**Inverse first.** The documented paths to a YES_F are:
- a forward leg;
- a fallback ask (none observed);
- `splitOutcome`(F), which also leaves a NO_F.

The [exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) states the semantics:
- split: "Split `X` quote tokens into `X` Yes and `X` No shares";
- `mergeOutcome`: "Merge `X` Yes and `X` No shares into `X` quote tokens";
- `negateOutcome`: "Convert `X` No shares from an outcome associated with a question into `X` Yes shares of every other outcome associated with the question".

Inverse-first, per set (`mergeQuestion` needs m of every named leg):

| Time | Action | Cash | Inventory after |
| --- | --- | --- | --- |
| t₀ | `splitOutcome`(F, m) | −m(1 + c_split) | m·YES_F, m·NO_F |
| t₁ | buy m of each YES_Ni at the asks, then `mergeQuestion`(m) | −m·Σaᵢ(t₁) + m(1 − c_merge) | m·NO_F |
| t₂ > t₁ | `negateOutcome`(F, m), then sell qᵢ ≤ m of each YES_Ni at the bids | −m·c_neg + Σ qᵢ·bᵢ(t₂)·(1 − f) | (m − qᵢ)·YES_Ni |

- **NO_F is a residual asset claim, not a debt.** Its acquisition basis is m(Σa(t₁) + c_split + c_merge). Until it is disposed of, it is valued at 0. At settlement it converts to `1 - settleFraction` quote tokens (A), with timing unknown (F).
- **Disposal paths:**
  - `negateOutcome` and a sale, as in the table;
  - `mergeOutcome` with a separately acquired YES_F, whose basis also counts;
  - holding to observed settlement.
- **Closed inverse-first pair** (all qᵢ = m): m(Σb(t₂)(1 − f) − Σa(t₁)) − m(c_conv + c_merge). This is the forward pair with its time order reversed. It is not a free flat basis, and it is equally a timed round trip.

**Static zero-inventory cycle at one instant.** Needs fallback quotes (the books-v1 certificate); none was observed.

**Membership change.** A named addition ("Holders of the question's fallback YES token receive an equal balance of the new outcome's YES token", deployer page, testnet-only per L) splits each held YES_F into YES_F′ plus YES_new. Both stay residual, and a later `mergeQuestion` needs YES_new as well.

**Program break-even and capital.**
- Orders and conversions are separate actions, so sets are made before any signal.
- n sets made that way cost n(c_conv + c_merge) if they are merged, whether or not they trade.
- One full-leg decision that uses m = u·n sets, without closure, breaks even only if Σb(t_E)(1 − f) − 1 + c_merge > (c_conv + c_merge)/u. At u = 1 this is the fresh-set test above.
- Each unsold set ties up 1 quote from t₀. A full forward entry returns about m in cash but leaves m·YES_F until settlement (timing F).
- Without H, no fee-inclusive threshold is numeric.

## 3. Required margins at observed depth (books-v1, 13:16 UTC on 2 October, pre-match, all 11)

The forward margin is 1 − Σb(q) and the inverse margin is Σa(q) − 1. Each is computed from size-weighted average prices over the displayed 20 levels for q units of every named member, at zero fees. This is the amount the basket must move, at that depth, before either route becomes positive.

| Q | fwd, q = 1 | fwd, q = 100 | fwd, q = 500 | inv, q = 1 | inv, q = 100 | inv, q = 500 |
| --- | --- | --- | --- | --- | --- | --- |
| 357 | 0.00024 | 0.00027 | 0.00129 | 0.00141 | 0.00170 | 0.00445 |
| 358 | 0.00265 | 0.00344 | 0.00749 | 0.00372 | 0.00380 | 0.00473 |
| 359 | 0.00743 | 0.00785 | 0.00793 | 0.00365 | 0.00369 | 0.00377 |
| 361 | 0.00292 | 0.00313 | 0.00990 | 0.01156 | 0.01174 | 0.01910 |
| 362 | 0.00636 | 0.00636 | 0.00716 | 0.00258 | 0.00258 | 0.00270 |
| 363 | 0.00017 | 0.00018 | 0.00019 | 0.00417 | 0.00590 | 0.00690 |
| 366 | 0.00530 | 0.00531 | 0.00534 | 0.00613 | 0.00614 | 0.00656 |
| 367 | 0.00220 | 0.00220 | 0.00273 | 0.01601 | 0.01602 | 0.01605 |
| 368 | 0.00151 | 0.00151 | 0.00152 | 0.00473 | 0.00509 | 0.39315 |
| 369 | 0.00301 | 0.00301 | 0.00361 | 0.00648 | 0.00652 | 0.00781 |
| 370 | 0.00116 | 0.00141 | 0.00285 | 0.00961 | 0.00961 | 0.00996 |

- All 66 margins are positive, so neither route was positive at any shown depth.
- A same-instant pair needs the sum of the forward and inverse margins: at least 0.00165 per unit at q = 1 (Q357).
- Fees add f/(1 − f) to the forward margin.
- This is one static snapshot. Depth during a future excursion is unknown, so no executable size is inferred.

**Round-trip swing.** At zero fees, a forward-first pair needs Σb to rise through 1 and then, later in the same window, Σa to fall through 1. With the displayed spread unchanged, the basket mid must therefore rise and then fall by at least the sum of the two margins:

| Q | q = 1 | q = 500 |
| --- | --- | --- |
| 357 | 0.00165 | 0.00574 |
| 358 | 0.00637 | 0.01222 |
| 359 | 0.01108 | 0.01170 |
| 361 | 0.01448 | 0.02900 |
| 362 | 0.00894 | 0.00986 |
| 363 | 0.00434 | 0.00709 |
| 366 | 0.01143 | 0.01190 |
| 367 | 0.01821 | 0.01878 |
| 368 | 0.00624 | 0.39467 |
| 369 | 0.00949 | 0.01142 |
| 370 | 0.01077 | 0.01281 |

- The q = 1 sums are exact touch sums. The q = 500 sums add rounded entries, so they are good to ±0.00001.
- Q357 and Q358 have schedule hints of 18:45 UTC on 2 October, and no live run is authorized.
- Of the other nine, Q363 needs the smallest swing at both depths, which is consistent with proposing it in live-v1. This is a static ranking only.

## 4. Statistic and open assumptions

The proposal formerly in this section is superseded by the pre-registered [supported-path pairing specification](pairing-spec-v1.md). That specification fixes:
- decisions, displayed conditional evaluation at r_Q + 500 ms, and partial closure;
- classes, bounds and denominators, for forward-first and inverse-first separately;
- one counterexample per unresolved settlement assumption.

The specification is unimplemented.

**Conclusion on existing data.** No forward route, inverse route or same-instant pair is positive for any match question at any shown depth. Any future statistic measures displayed, causally reachable states, not fills. It stays conditional on fees (H, L), granularity (D, M), settlement handling (A, B, C, E, F) and quote identity (I).
