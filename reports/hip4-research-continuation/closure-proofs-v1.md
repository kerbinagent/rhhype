# HIP-4 continuation: closure and settlement proof ledger v1

This ledger answers root's 14:13 UTC request of 2 October 2026 for explicit proof of:
- order cancellation;
- tradability and conversion availability around settlement;
- redemption, fees and delisting;
- native quote identity.

**Method.** Official Hyperliquid GitBook pages were fetched as raw `.md` at 14:17 UTC with `curl` (documentation only, no exchange API) and searched verbatim. The WebFetch summarizer had truncated the 119 KB exchange-endpoint page and reported "NO OCCURRENCE" of outcome actions, so verbatim `.md` text is used throughout. Page hashes are the first 16 hex characters of sha256. The aligned-quote-assets hash `14ebdc13e0521440` equals the one recorded in the [v1 source review](../hip4-outcome-v1/source-review.md), so that page is unchanged since then.

| Page (`.md`) | Bytes | sha256/16 |
| --- | --- | --- |
| [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) | 3,452 | `087859f228fc6d64` |
| [HIP-4 deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions) | 13,905 | `1030b37bffd5e69e` |
| [Info endpoint, spot](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot) | 13,114 | `2790494f02e91dea` |
| [Exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) | 119,366 | `6df658a502e587db` |
| [Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) | 55,013 | `f4228fc7734af5db` |
| [Websocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) | 18,564 | `761f00c20ba21c03` |
| [Contract specifications](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications) | 5,192 | `59ef08be4b7e3d7c` |
| [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) | 12,174 | `75e55504b1b887a8` |
| [Asset IDs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids) | 2,265 | `eec6b95ef1bf184f` |
| [HIP-1](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-1-native-token-standard) | 8,423 | `db370738d60ee828` |
| [Permissionless spot quote assets](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/permissionless-spot-quote-assets) | 2,278 | `fdeddfaa9adc1c5c` |
| [Aligned quote assets](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets) | 6,814 | `14ebdc13e0521440` |
| [Tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size) | 1,561 | `1114a12bc134c7d0` |

## Ledger

| # | Claim | Official evidence (verbatim) | Status |
| --- | --- | --- | --- |
| A | Settlement redeems balances without a user action | HIP-4: "Settlement automatically converts either Yes to `settleFraction` quote tokens and No to `1 - settleFraction` quote tokens." | **Proven** that conversion is automatic. Its timing relative to a `settledOutcome` record, `outcomeSettled` push or book removal is **not stated**. |
| B | Open orders are cancelled at settlement | None. The order-status list has `delistedCanceled`, "Canceled due to asset delisting", with no outcome or settlement status, and no page links settlement to it. `WsNonUserCancel { coin; oid }` carries no reason. | **Missing proof** (official sources silent) |
| C | Trading halts at expiry, or continues until settlement | None on any page. Contract specifications define only the resolution rule and timestamp. | **Missing proof** |
| D | Split, merge and negate available before settlement | HIP-4: "users with No shares on different outcomes of the same question can redeem quote tokens before the underlying outcomes settle." The exchange endpoint documents `splitOutcome`, `mergeOutcome`, `mergeQuestion` ("Merge `X` Yes shares from each outcome associated to the same question") and `negateOutcome`, each returning only `{'status': 'ok', ...}`. | **Proven** to exist before settlement. Amount granularity, fees and error cases are **not stated**. |
| E | Split, merge, negate or trading available after settlement, or for settled question members | None. Whether "associated" outcomes include settled members or the fallback after partial settlement is **not stated**. | **Missing proof** |
| F | Settled outcomes leave `outcomeMeta` | None. The deployer page says "Settling outcomes frees capacity" (active-outcome cap), which implies settled outcomes stop counting as active but says nothing of listing. Subscriptions describe `WsOutcomeMetaUpdates` as "Changes to the outcome meta", typed as an array, `type WsOutcomeMetaUpdates = [WsOutcomeMetaUpdate]`, whose members include `{ outcomeSettled: number }` and `{ questionSettled: number }`. The websocket `OutcomeSpec` lists `outcome`, `name`, `description` and `sideSpecs`, with no `quoteToken`, venue or fee scale. | **Missing proof**; listing absence remains an observation only. Push data is an array, which live-v1 and settle-v1 already accept. The parked metastream draft's payload check would wrongly compare a 4-key websocket spec with the fuller REST entry; that draft is parked and unreviewed. |
| G | Shape of `settledOutcome` for an unsettled id | Only a settled example is documented. | **Missing proof** |
| H | Fees | HIP-4: "Fees are currently zero for outcome markets for initial testing." Fees: "Outcome trading only charges fees when closing or settling, not when opening outcome positions." Deployer page: users pay "the base outcome trading fee rate times `scale + max(scale, 1)`"; "Maker rebates are never paid on outcome markets." | Charging points and scale formula **proven**. The base rate is **not stated**. "Currently zero" is an undated statement; third-party reports of fees ([source notes v1](source-notes-v1.md)) conflict, so zero stays optimistic. |
| I | Native quote identity of `quoteToken: "USDC"` | Info endpoint example: `settledOutcome.spec.quoteToken` is the string `"USDC"`. HIP-1: token `name` has "no uniqueness constraints", and the deployment hash is the "globally unique hash by which the execution logic will index the token". The `spotMeta` example lists `"name": "USDC"`, `"index": 0`, `"tokenId": "0x6d1e7cde53ba9467b783cb7c530ce054"`, `"isCanonical": true`. No `outcomeDeploy` registration action takes a quote-token argument. Aligned quote assets: AQAv2 "will be a requirement for quote assets to be listed against HIP-4 ... on a future network upgrade". | **Missing proof.** No official source maps an outcome's `quoteToken` string to a token index or `tokenId`, and a name join to `spotMeta` is not authoritative. Secondary sources (Chainstack, GoldRush) say USDH. That label is **not adopted**: it conflicts with the official example and with our frozen snapshot, where all 260 outcomes read `USDC`. |
| J | Template semantics (direction of `binaryPrice`, sports templates) | Deployer page: "`{"type": "outcomeTemplates"}` info request returns all templates". Templates carry display text with `{keyword}` placeholders and a `semanticRestriction`, and "Markets that contradict their template's semantic restriction are considered malformed and slashable by validators." | **Source exists but has not been read.** One metadata-only request would supply the authoritative template text. |
| K | Settlement details format | Deployer `settleOutcome`: "`details` must be empty." The recurring example carries `"details": "price:76876.9"`. | **Proven** for both forms. Deployer-settled outcomes carry no price detail. |
| L | Deployer rules apply on mainnet | The deployer page is headed "Testnet-only". Yet our mainnet snapshot lists deployers and venues `out`, `skew` and `txyz`. | **Unresolved.** Every deployer-page rule (B to F, K) is at best a testnet statement for mainnet markets. |
| M | Outcome tick and lot | The tick-and-lot page gives perp and spot rules only. | **Missing proof.** Observed books-v1 prices have at most 5 decimals and sizes are integral; these are observations, not rules. |

**Official SDK cross-check.** [hyperliquid-dex/hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) was checked at commit `2fdb18f` (2026-06-04). It has zero occurrences of "outcome" in `hyperliquid/info.py`, `hyperliquid/exchange.py` and `hyperliquid/utils/types.py`, so it adds no evidence for any claim above.

## Consequences for the drafts

- **settle-v1.** Post-record books stay conditional displays (claims B, C and E are missing). No displayed gap can be called executable or closed cash. Claim A (automatic conversion) supports retiring tokens at settlement, with unstated timing.
- **expiry-v1.** Absence classification stays a listing observation behind the control witness (claim F). Null `settledOutcome` stays a shape (claim G). `details` stays role-specific (claim K).
- **live-v1.** Forward-route conversions are documented before settlement (claim D). Every route must still treat amount granularity, fees (claim H) and collateral identity (claim I) as unverified.
- **Highest-value missing proofs**, in order:
  - claim I, quote identity;
  - claims B, C and E, order and conversion handling at settlement;
  - claim J, template semantics, the only one closable by a single public read.

## Optional bounded reads for root to consider (not requested)

- **Template semantics (claim J).** `{"type": "outcomeTemplates"}`, once (documented on the deployer page; weight not documented).
- **Spot token metadata for quote identity (claim I).** `{"type": "spotMeta"}`, once (weight 20). It can show how many spot tokens are named `USDC` or `USDH`, with their `tokenId` and `isCanonical`. It would still be a name join, so at most corroboration, never proof.

Neither is needed by any current draft.
