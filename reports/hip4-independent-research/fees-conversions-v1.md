# HIP-4 pairing: fee and conversion assumptions against the official text (queue item 4, v1)

Written 2 October 2026, about 18:30 UTC. It uses only the official pages retained at 14:17 UTC, listed in the [closure ledger](../hip4-research-continuation/closure-proofs-v1.md), and the published books-v1 margin table ([pairing review](../hip4-research-continuation/pairing-v1.md), section 3). It makes no new fetch, reads no data and changes no sealed plan. Section 2 is a predeclared retrospective transform of that static table. It is never pooled with the prospective Q357 results.

## 1. Fee placement in the model versus the documents

Sources:
- [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), "Outcome tokens" section, `.md` sha256/16 `75e55504b1b887a8`;
- [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets), `087859f228fc6d64`;
- [Exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), `6df658a502e587db`;
- [HIP-4 deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions), `1030b37bffd5e69e`, headed "Testnet-only".

Verbatim:
- "Outcome trading only charges fees when closing or settling, not when opening outcome positions." The page then lists "6 cases for outcome trades which are special cases of this logic":
  - minting ("no one pays fee");
  - normal trades (one side or no side pays);
  - burning (both sides, or only the taker, pay);
  - "4. Settlement: each user gets `settle_fraction * sz`".
- "Outcome trading does not support rebates. Users who would receive rebates for spot and perp trading pay zero fees on maker orders." (Fees)
- "Fees are currently zero for outcome markets for initial testing." (HIP-4, undated)
- "Users trading the outcome's markets pay the base outcome trading fee rate times `scale + max(scale, 1)`" (deployer page). The base rate is not stated anywhere.

| Model action | Position effect | Documented fee | Model |
| --- | --- | --- | --- |
| Forward-first (FF) sell of a held named YES, at the bid | closing | charged | f |
| FF buy-back of a sold named YES, at the ask | opening | not charged | 0 |
| Inverse-first (IF) buy of named YES, at the ask | opening | not charged | 0 |
| IF sell after negation, at the bid | closing | charged | f |
| Residual settlement (open-class envelope) | settling | charged | W(1 − f) |
| `splitOutcome`, `negateOutcome`, `mergeOutcome`, `mergeQuestion` | conversion | **absent from the six cases**; no fee statement | c_split, c_neg, c_merge (sensitivity only) |

- **Trades and settlement.** The model's placement of f matches the documented rule for trades and settlement.
- **Maker orders.** Only taker execution at the touch is modelled. The zero maker fee for rebate-tier users is irrelevant to it.
- **Conversions.** They are neither shown to be free nor shown to be charged. A merge redeems positions much as settlement does, so "merge charged as closing" (c_merge = f) is plausible but undocumented. The sealed sensitivity points do not include it, and it was not added after sealing.
- **Amounts.** Conversion amounts are decimal strings: `splitOutcome` `amount: String (e.g., "123.0")`; `mergeOutcome` and `mergeQuestion` `amount: String | null (null means max)`; `negateOutcome` `amount: String`. No lot rule is stated. The model's whole-token floor is therefore a stricter premise, not a documented rule (ledger claim M). Books-v1 sizes were all integral.

## 2. Retrospective: fee-adjusted required swing at the 13:16 UTC books-v1 snapshot (predeclared scenarios)

A forward-first pair needs two things:
- an entry with Σb(1 − f) > 1 + c_split + c_neg;
- a full buy-back closure with Σa ≤ 1 − c_merge.

Relative to the snapshot, the required swing is therefore the zero-fee swing (forward plus inverse margin) plus a constant:

[(1 + c_split + c_neg)/(1 − f) − 1] + c_merge

The constant is the same for every question, so the zero-fee ranking is unchanged. The scenarios were fixed before computing:
- S1–S3 are the sealed sensitivity points;
- S4–S5 are "merge charged as closing".

| Scenario | Added to the swing | Q357, q = 1 | Q357, q = 500 | Smallest q = 1 swing, any question | Largest q = 1 swing |
| --- | --- | --- | --- | --- | --- |
| S0: zero fees | 0 | 0.00165 | 0.00574 | 0.00165 (Q357) | 0.01821 (Q367) |
| S1: f = 0.001 | 0.001001 | 0.00265 | 0.00674 | 0.00265 | 0.01921 |
| S2: f = 0.005 | 0.005025 | 0.00668 | 0.01077 | 0.00668 | 0.02324 |
| S3: conversions 0.0005 each | 0.0015 | 0.00315 | 0.00724 | 0.00315 | 0.01971 |
| S4: f = c_merge = 0.001 | 0.002001 | 0.00365 | 0.00774 | 0.00365 | 0.02021 |
| S5: f = c_merge = 0.005 | 0.010025 | 0.01168 | 0.01577 | 0.01168 | 0.02824 |

- **Inputs.** The margins are those already published (q = 1 exact; q = 500 good to ±0.00001). Sums were computed with exact fractions and rounded only for display.
- **Effect of fees.** At f = 0.005, Q357's one-unit required swing is about 4× its zero-fee value. If merges are also charged, it is about 7×.
- **Status.** This is one static snapshot. It is not a prediction of the Q357 window, and it is never pooled with it.

## 3. Consequences

- **Zero fees.** The zero-fee primary is the documented current state ("currently zero … for initial testing"), but that statement is undated, so it stays labelled optimistic.
- **Next prospective study.** If one is authorized, it should predeclare a merge-as-closing sensitivity (S4, S5) alongside the trading-fee points.
- **Unchanged open items.** These still stand: base rate (claim H), conversion fees (D), settlement timing and cancellation (A, B, C, E), and quote identity (I). No retained official page closes them, and the docs index retained at 14:29 UTC lists no other HIP-4 page. The four-page fetch allowance stays unused.
