# HIP-4 outcome source review v1

Collaborator lane under
[the allocation](../experiment-storage/hip4-outcome-research-allocation-v1.json)
(sha256 `1085b374…5b1982d`). Official Gitbook Markdown pages were read live on
2 October 2026, 11:55–12:10 UTC; hashes are below because the pages are not
versioned. No exchange API, RPC, websocket, price, account or order access.
Third-party material is pinned by commit and is a lead only: it is not an
economic observation or fee proof.

## 1. Decision summary

| Required input | Finding |
| --- | --- |
| Complete question membership | Officially typed only on the websocket page (`QuestionSpec`). Members are `namedOutcomes` plus `fallbackOutcome`. The REST `outcomeMeta` example omits `questions`. Membership is available only if the live snapshot carries those fields; otherwise it is unavailable. Never infer it from names, descriptions, expiry or an update stream. |
| Active status | No status field exists in any official schema. Strict screen: question listed, every member listed exactly once, and `settledNamedOutcomes` empty. "Not finally settled" is only implied by listing (the websocket documents `outcomeSettled`/`questionSettled` as changes to the outcome meta). This is a stated assumption, not proof. |
| Quote asset | `quoteToken` is a string. Officially it appears only in the `settledOutcome.spec` example. HIP-1 token names have "no uniqueness constraints", so a name join to `spotMeta` is not authoritative. Within-question equality of the unclipped string is a label check only, not asset identity; omit `spotMeta`. |
| Native precision | There is no official outcome size/price precision, minimum size or amount granularity. Unavailable. This blocks native order/fill claims, not a metadata receipt. |
| Conversion-cycle scope | Under the documented merged book, a standalone outcome cannot violate its interval at rest. Only multi-outcome questions can yield static zero-cost cash cycles (§6). If no eligible question is listed, the conversion screen has nothing to test. |

## 2. Official sources and exact schemas

| Page (`https://hyperliquid.gitbook.io/hyperliquid-docs/…`) | bytes | sha256 prefix |
| --- | ---: | --- |
| `hyperliquid-improvement-proposals-hips/hip-4-outcome-markets.md` | 3452 | `087859f228fc6d64` |
| `for-developers/api/info-endpoint/spot.md` | 13114 | `2790494f02e91dea` |
| `for-developers/api/websocket/subscriptions.md` | 18564 | `761f00c20ba21c03` |
| `for-developers/api/exchange-endpoint.md` | 119366 | `6df658a502e587db` |
| `for-developers/api/asset-ids.md` | 2265 | `eec6b95ef1bf184f` |
| `for-developers/api/hip-4-deployer-actions.md` (testnet-only) | 13905 | `1030b37bffd5e69e` |
| `trading/contract-specifications.md` | 5192 | `59ef08be4b7e3d7c` |
| `trading/fees.md` (byte-identical to `reports/fee-sensitivity/sources/hyperliquid-fees.md`) | 12174 | `75e55504b1b887a8` |
| `for-developers/api/tick-and-lot-size.md` | 1561 | `1114a12bc134c7d0` |
| `hyperliquid-improvement-proposals-hips/hip-1-native-token-standard.md` | 8423 | `db370738d60ee828` |
| `for-developers/api/rate-limits-and-user-limits.md` | 4137 | `0e94f9c44edfae68` |
| `hypercore/aligned-quote-assets.md` | 6814 | `14ebdc13e0521440` |

**REST `outcomeMeta`**
([spot#retrieve-outcome-metadata](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot#retrieve-outcome-metadata)).
Request `{"type":"outcomeMeta"}`. The full documented example is
`{"outcomes":[{"outcome":123,"name":"Recurring","description":"class:priceBinary|underlying:HYPE|expiry:20260310-1100|targetPrice:34.5|period:3m","sideSpecs":[{"name":"Yes"},{"name":"No"}]}]}`.
It has no questions, quote, status, venue, fee scale or precision fields.

**REST `settledOutcome`** (same page). Request
`{"type":"settledOutcome","outcome":<int>}`. Response
`{"spec":{outcome,name,description,sideSpecs,"quoteToken":"USDC"},"settleFraction":"0.0","details":"price:76876.9"}`.
The unsettled response is undocumented.

**Websocket `outcomeMetaUpdates`**
([subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)),
described there as "Changes to the outcome meta":

```ts
type WsOutcomeMetaUpdate = { outcomeCreated: OutcomeSpec } | { outcomeSettled: number }
  | { questionUpdated: QuestionSpec } | { questionSettled: number };
type OutcomeSpec = { outcome: number; name: string; description: string;
  sideSpecs: [OutcomeSideSpec, OutcomeSideSpec] };
type OutcomeSideSpec = { name: string };
type QuestionSpec = { question: number; name: string; description: string;
  fallbackOutcome: number; namedOutcomes: number[]; settledNamedOutcomes: number[] };
```

**User actions**
([exchange#split-outcome](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint#split-outcome)
to `#negate-outcome`). Each is `{"type":"userOutcome", …}`:
- `splitOutcome {outcome, amount: String}` turns X quote tokens into X Yes and X No.
- `mergeOutcome {outcome, amount: String|null}` turns X Yes and X No into X quote; null means max.
- `mergeQuestion {question, amount: String|null}` turns X Yes "from each outcome associated to the same question" into X quote.
- `negateOutcome {question, outcome, amount: String}` turns X No into X Yes "of every other outcome associated with the question".

No fee or amount granularity is stated for any of them.

**Asset IDs** ([asset-ids](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids)).
The encoding is `10*outcome + side`, where side is 0 or 1. It appears as coin `#<enc>`, token `+<enc>` and asset `100000000+<enc>`. The page does not say which side is Yes. The deployer page orders `sideNames` as `["<YES side name>", "<NO side name>"]`, so side 0 = first `sideSpecs` entry is a documented inference.

**Book and questions** ([HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets)):
- Yes and No books are merged. Buying Yes at `p` is equivalent to selling No at `1-p`. At the same merged level, resting sells precede resting buy duals (price-side-time priority).
- Settlement pays Yes `settleFraction` and No `1-settleFraction`.
- A question is a set of outcomes in which exactly one settles to Yes; members are linked by `negate` and `merge`.
- "Multi-outcome markets will be supported but are not part of the initial mainnet release."

**Deployer semantics**
([hip-4-deployer-actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions),
marked testnet-only):
- A question with N named outcomes registers N+1 outcomes. The fallback is automatic, named `template fallback`, with description `other` and sides `Yes`/`No`.
- Named outcomes can be added to a live question, up to 100 per question. Fallback YES holders "receive an equal balance of the new outcome's YES token".
- Question outcomes settle only to `"0"` or `"1"`. Named outcomes settle to 0 in any order. The last active one settling to 1 auto-settles the fallback to 0 and settles the question. `settleQuestion2` settles all remaining members at once.
- Standalone outcomes may settle fractionally.
- User fee = base outcome rate × (`scale + max(scale,1)`), with `deployerFeeScale` in [0,10]. A question's scale also applies to its fallback. "Per-outcome scales are returned in the `outcomeMeta` info request." `outcomeMeta` "includes non-null outcome deployers". Maker rebates are never paid.
- Limits on testnet: 10 active outcomes per deployer and 50 per day.

**Recurring classes**
([contract-specifications#recurring-outcomes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications#recurring-outcomes)):
- `class:priceBinary|underlying|expiry|targetPrice|period` settles YES iff the interpolated mark at expiry is ≥ target.
- `class:priceBucket|…|priceThresholds:P1,P2|period:15m` has buckets `<P1`, `[P1,P2)` and `≥P2`: "Exactly one of the 3 outcomes settles to 1".
- At most one series exists per `(seriesType, underlying, period)`.
- The descriptions are labels; they never establish membership.

**Fees** ([fees#outcome-tokens](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees#outcome-tokens)):
- Fees are charged only "when closing or settling, not when opening".
- There are six volume cases: minting, normal trades, burning, and settlement. In a burn both sides, or only the taker, may pay.
- There are no rebates; rebate-tier users pay zero maker fees.
- The developer fee formula has no outcome branch, so the base outcome rate is not stated.
- The HIP-4 page says fees are "currently zero … for initial testing".
- AQAv2 will be required for HIP-4 quote assets in a future upgrade ([aligned quote assets](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets)).

**Precision**:
- The [tick/lot page](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size) gives only perp and spot rules (5 significant figures; `8-szDecimals` decimals for spot).
- [HIP-1](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-1-native-token-standard) defines the lot size as `10**(weiDecimals-szDecimals)` and says token `name` has "no uniqueness constraints". Tokens are indexed by deployment hash. Spot USDC has `szDecimals = weiDecimals = 8`.
- No outcome token `szDecimals`/`weiDecimals` source exists.

**Rate limits** ([rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)):
undocumented-weight info requests (including `outcomeMeta` and `spotMeta`) have weight 20 against 1200 per minute per IP.

## 3. Conflicts and dating

These dates come from the [docs mirror](https://github.com/dzmbs/hyperliquid-docs), which syncs every 3 hours. Each date is the first sync, so it is an upper bound for the change:
- **2026-05-02 (`25a0d824c2`):** HIP-4 page created with the initial-mainnet exclusion of multi-outcome markets.
- **2026-05-07 (`87cb068256`):** contract specs add `priceBucket` without naming a network, and the HIP-4 page adds question semantics.
- **2026-05-08 (`b0675aef2b`):** the zero-fee testing sentence is added.
- **2026-09-08 (`cfc9f6650e`):** the deployer page gains the testnet-only marker.

Unresolved conflicts:
- Whether questions are live on mainnet.
- Zero fees versus the fee page and the deployer scale.
- `quoteToken`, deployers and scales: present in the `settledOutcome` example and in deployer text, absent from `OutcomeSpec` and the REST example.
- Builder fees: the HIP-4 page says sell orders only; the deployer page says buy orders as well.

## 4. Third-party leads (not evidence)

- **Official Python SDK** [`2fdb18f`](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/tree/2fdb18f95176) (latest commit, 2026-06-04): no outcome support.
- **[nktkas/hyperliquid `db80d59`](https://github.com/nktkas/hyperliquid/blob/db80d598f6e4672edc090fe69994ecec97ebc980/src/api/info/_methods/outcomeMeta.ts):**
  - Response adds `quoteToken` (2026-06-07), optional `sideSpecs[].token`, optional `deployer` (2026-08-01) and `questions[]` with the websocket fields.
  - Its live coverage test exempts `token` presence, i.e. `token` was not observed.
  - `settledOutcome` returns null when unsettled.
- **[Alchemy preview docs `101db80`](https://github.com/alchemyplatform/docs/blob/101db80c94dec6c0943808a503ff19ba09c0ba9f/content/api-reference/data/hypercore/rest/outcome-markets/outcome-meta.mdx):** observed `venue` (`out`), `deployerFeeScale` (`"1.0"`), top-level `deployers` and `feeScale`, and outcomes named `template:priceTouch`.
- **Precision defaults disagree:**
  - [ccxt `8cf4b18`](https://github.com/ccxt/ccxt/blob/8cf4b187ad7293b82ad446cbe634e92dcdbe15ae/python/ccxt/prediction/hyperliquid.py) hardcodes 4 size decimals, tick 0.0001 and prices 0.0001–0.9999.
  - [Nautilus `224f599`](https://github.com/nautechsystems/nautilus_trader/blob/224f599df710ecca2b9f4757ce07a06a86b3db70/crates/adapters/hyperliquid/src/http/parse.rs) uses 2 size and 4 price decimals "until the venue exposes per-market values". It says `outcomeMeta` "is partial today (no precision or expiry fields)", and that question members carry descriptions `other` or `index:N`.
- **[Aarymanv research `775e4aa`](https://github.com/Aarymanv/prediction-market-research/blob/775e4aae54777a541deef5b2f04c5dec67b19f05/09-profitability-lab/outcome_paired_inventory/precision_epoch_evidence.json)** (captures dated 2026-09-08):
  - `outcomeMeta` top-level keys were `outcomes`, `questions`, `deployers` and `feeScale`.
  - Body sizes: `outcomeMeta` 52,316 B and `spotMeta` 135,497 B, identity-encoded with Content-Length.
  - `spotMeta` contained zero outcome tokens.
  - Only integer sizes were seen; fractional admissibility is unverified.
  - "Merge Outcome" fill rows carried fees.
- **[lastdotnet RE notes `6b0c325`](https://github.com/lastdotnet/hyperliquid-rust-docs/blob/6b0c3255b9e53593acfa48a2a73aaaa8dcd540df/obsidian/HIP-4%20Outcomes.md)** (testnet, 2026-04, hypothesis level): error string "Cannot trade fallback token", and price bounds 0.001–0.999, which conflict with ccxt.

## 5. Unresolved; must not be inferred

1. Whether the live mainnet snapshot carries `questions[]`, which questions, and their classes.
2. Native outcome size and price precision, minimum order size or value, and amount granularity for split, merge and negate.
3. Whether settled outcomes and questions leave `outcomeMeta`, and how an unsettled status would be proved.
4. Whether `namedOutcomes` keeps settled members, and whether `mergeQuestion`/`negateOutcome` span active or all associated members (including settled ones and the fallback).
5. Fees on `userOutcome` actions, the base outcome rate, the settlement fee, and the fee scale of protocol-deployed recurring outcomes.
6. Whether the fallback token is orderable.
7. Fallback-No payoff and collateral under named-outcome association. The documented YES credit makes fallback No pay in the new outcome's state as well.
8. Settlement mechanics for recurring questions. The deployer rules are testnet-only.
9. Whether `outcomeMetaUpdates` sends an initial full snapshot. Root notes it may not; use a static snapshot.

## 6. Valuation certificate review

**Model.** A question has an active, complete, mutually exclusive set `A` (|A|≥2) and common collateral `C`. Let `Y_i=1{i}` and `N_i=1-1{i}`. The documented conversions, assumed zero cost here, are:
- `split_i: C→Y_i+N_i`
- `merge_i`, its reverse
- `mergeQ: ΣY_i→C`
- `negate_i: N_i→Σ_{j≠i}Y_j`

All four preserve each state's payoff if and only if `A` is complete and exclusive. An omitted member, such as the fallback, breaks `mergeQ` and `negate`.

**Soundness.** Take `ℓ_i=max(0,bY_i,1-aN_i)` and `u_i=min(1,aY_i,1-bN_i)`. A valuation `π` on the simplex with `ℓ_i≤π_i≤u_i` exists if and only if every `ℓ_i≤u_i` and `Σℓ≤1≤Σu`; the attainable sums of the box form the interval `[Σℓ,Σu]`.

Define `W = cash + Σ_s π_s·payoff_s(holdings)`:
- Conversions leave `W` unchanged.
- Buying Yes at a price ≥ `aY_i` ≥ `π_i`, or No at a price ≥ `aN_i` ≥ `1-π_i`, lowers `W` weakly.
- Selling at bid prices also lowers `W` weakly, by the mirrored bounds.

So any sequence that starts and ends with zero tokens has `cash_end ≤ cash_start`. Deeper book levels are worse than the touch, so the certificate covers every size. The proof needs no free-disposal assumption: the 0/1 caps only encode missing quotes and the simplex range. A standalone outcome needs only `ℓ≤u`, and fractional settlement keeps `Y+N=1`, so the same proof applies.

**Merged-book reduction and dual liquidity.** In the merged book, the No ask equals `1-bY_i` and the No bid equals `1-aY_i`; they are the same resting orders. Hence:
- `ℓ_i=max(0,bY_i)` and `u_i=min(1,aY_i)`. The No terms add no information.
- A `#<enc+1>` snapshot is a mirror. Any price or size mismatch is a timing or representation defect: the snapshot is unusable, with no result and no route.
- Depth must come from a single pool per outcome side and must never be summed across `#…0` and `#…1`.

**Local conflicts.** These are `bY>aY`, `bN>aN`, `bY+bN>1` and `aY+aN<1`, i.e. `ℓ_i>u_i`. Under merged semantics they indicate inconsistent data, never a tradable cycle; the helper returns `inconsistent_snapshot`.

**Exhaustive routes** (after `ℓ≤u`; zero cost; at the touch; no fill claim). This is the root's construction, independently checked by the Sol review:
- Split/merge make `N_i ≡ C−Y_i`, and split+negate/mergeQuestion make `ΣY ≡ C`. So a closed cycle has the same net YES-coordinate quantity λ for every member.
  - λ>0 is the inverse route.
  - λ<0 is the forward route.
  - λ=0 leaves only local round trips, which cost `a−b≥0`.
- **Inverse:** margin `1-Σ_i min(aY_i,1-bN_i)`. Let S be the members acquired by splitting and selling No. Buy Yes outside S, split `k=|S|` units, `mergeQ` once, then sell the S No tokens.
  - Every member needs an acquisition path; a missing one gives `u_i=1`, which cannot fail this side.
  - Capital `Σ_{∉S}aY+k` per unit is exact for this acquisition-first order, not a universal minimum.
- **Forward:** margin `Σ_i max(bY_i,1-aN_i)-1`. Let S be the members disposed of through No.
  - k=0: `split+negate` one member (1 C), then sell every Yes.
  - k≥1: buy each S No, negate each, merge `k−1` full Yes sets, then sell the remaining Yes. Capital is `Σ_S aN` per unit.
- **Missing disposal.** A clipped 0 is not a trade. With only `bY1=bY2=0.6` among three members, `Σℓ=1.2` but `Y3` stays as residual. Pure conversions cannot erase it, so this is a residual candidate (`candidate_forward_residual`), never cash-closed. Never mark the residual.
- **Standalone outcomes.** `[bY,aY]` is never violated at rest in a merged book, so they offer no static conversion cycle. Links between priceBinary, priceBucket and priceTouch markets are not enforced by conversions. They rely on settlement-rule equivalence, which is a separate mechanism.

**Premise breakers for later paper profit.**
- Fixed metadata at one instant. A named addition, fallback credit or settlement invalidates the valuation and the fixed question screen.
- An unorderable fallback has no quotes, so the inverse route is impossible and the forward route leaves residual.
- Legs are separate L1 actions, so a cycle is not atomic.
- A cross-book snapshot needs common or bounded book times.
- Fees: zero is optimistic only. Opening buys are documented as fee-free; merge, sale and conversion fees are unknown and must be subtracted per leg.
- Unknown native precision, minimum size and amount granularity. Discrete lots can only shrink the continuous opportunity set, so they block quantities and fills but not a conditional no-positive continuous certificate.
- Capital as above; taker-only legs; maker legs face price-side-time priority.

## 7. Implications for the metadata probe

[`draft-protocol.json`](draft-protocol.json) proposes:
- One anonymous POST of `{"type":"outcomeMeta"}`, with no `spotMeta` since name joins are not authoritative.
- Body at most 131072 bytes, so the worst-case gzip fits the 163840 raw cap.
- No retry, redirect, proxy or fallback.
- Raw kept only as gzip, plus a structural projection with no economics.

A question is a **structural candidate** only if:
- Its six `QuestionSpec` fields are present with the documented types, and its id is unique.
- It has no duplicate members and the fallback is not among the named outcomes.
- `settledNamedOutcomes` is empty.
- Every member is listed exactly once with two named sides and the same unclipped `quoteToken` label.
- No member is shared with another question.

Every projection states that active state, quote-asset identity and native precision remain unverified; the probe does not fail because of them.

Decision:
- A structural candidate may only motivate a separately reviewed book-screen design. It never makes a question eligible for price or execution work.
- A valid, empty questions list parks the conversion screen.
- Anything else is inconclusive.

The supervisor cites a status only when all of these hold:
- The worker exited cleanly.
- The terminal receipt, projection and gzip raw match.
- No publication is pending.
- The final plan and source pins verify.

Otherwise the request count stays unknown (0 or 1) when the terminal is missing.
