# BTC dated carry: contract preflight

Reviewed 30 September 2026 using official documentation and saved inventory in `reports/dated-carry/20260930-v1/metadata`. No instrument requests, quotes or orders were made in this review. It supports [the broader proposal](broader-carry-research-proposal.md), without establishing profit or account eligibility.

## Recommendation

Proceed with a **conditional public quote feasibility study**, fixing BTC_USDC spot and the nearest eligible dated future at activation. Public fees, sizing, routing, expiry and Standard Margin rules support declared scenarios. Missing optional fields do not establish infeasibility. Keep delivery charges, fee debit currency, underlying quote age, permissions and terminal mismatch unresolved: these prevent executable-profit certification but preserve observable quote arithmetic.

## 1. Effective fees: resolved base rates, unresolved future cash charges

Deribit's official announcement explicitly makes the new fee schedule effective **1 August 2026**. Spot fees were waived only until connection to Coinbase liquidity. Thus the current fee page's “upcoming” wording does not justify postponing the schedule. The announcement also ends differentiated daily/weekly futures trading fees. [Official effective-date announcement](https://insights.deribit.com/exchange-updates/new-fee-schedule-on-deribit/).

The current Standard rates are futures taker **3.5 bp**, futures maker 1.5 bp; routed spot taker **5 bp**, maker 2 bp. The fee page lists USDC BTC/ETH futures delivery at **2.5 bp**, while also describing weekly futures as exempt. This leaves the selected weekly linear future's actual delivery charge ambiguous. Retain a 2.5 bp delivery-rate scenario; do not assert either a zero charge or an authenticated instrument-specific maximum. Trading discounts do not reduce delivery fees. No VIP tier, fee credits, rebates or broker-specific charge has been assumed. [Current fee schedule](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).

Saved inventory corroborates the entry commissions: future `0.00035`, routed spot `0.0005`. These do not verify account-specific charges or future rates.

For declared quote scenarios, charge each fee against its own quantity and selected price/reference, preserving the reference choice. For example, a trade-price notional scenario held to delivery uses spot entry 5 bp, future entry 3.5 bp, spot liquidation 5 bp and delivery 2.5 bp, each on its own notional; their equal-notional sum is 16 bp. Early close instead has future buyback 3.5 bp and spot sale 5 bp (equal-notional four-trade total 17 bp). These sums are illustrations, not a universal $B-based fee formula.

Inspected pages do not uniquely establish routed spot/delivery fee debit currency and reference price. An execution ledger must use trade `fee` and `fee_currency`: BTC debits can reduce net acquired inventory; USDC debits require extra settled cash. Equal gross order quantities alone do not certify a hedge. [Trade fee schema; no private call made](https://docs.deribit.com/api-reference/trading/private-buy).

Likewise, delivery costs cannot be bounded in dollars merely by multiplying 2.5 bp by today's entry notional: the eventual delivery reference can differ. If the study uses today's index as a proxy, label it as such. A complete conservative headroom gate needs an explicit future reference-price/mismatch allowance; absence leaves that gate unknown.

## 2. Public inventory and exact sizing

Already saved production responses:

| Item | Dated future | Spot |
| --- | --- | --- |
| Native name | BTC_USDC-9OCT26 | BTC_USDC |
| Instrument ID | 701307 | 254613 |
| Kind / type | future / linear | spot / linear |
| Base / quote | BTC / USDC | BTC / USDC |
| Settlement currency | USDC | Spot balances, not a futures settlement position |
| Expiry milliseconds | 1791532800000 (9 October 2026, 08:00 UTC) | Far-future placeholder; not dated |
| Active / state | true / open | true / open |
| `min_trade_amount` | 0.0001 BTC | 0.00000001 BTC |
| `contract_size` | 0.0001 BTC | 0.00000001 BTC |
| Tick / tick steps | 2.5 USDC / empty | 0.01 USDC / empty |
| Routed flag | Absent | `is_cbe_routed=true`, `is_csr=true` |
| Settlement period | week | Not applicable |

Saved inventory receipts are approximately 12:16:10 UTC. Future decoded body: 158,145 bytes, 174 instruments, SHA256 `b8850f7e04f9bd154ad8e8ead4a34567e062e25347b4edd2de34262902215af7`; gzip SHA256 `c9a42515862434bd61fad02119806c731abff6d7b78bb3c714c31821efb3ba79`. Spot body: 2,962 bytes, four instruments, SHA256 `43d6bb09ec911fa7d60521820a9b93253b86a43a7f2ed7059fef68f67397544d`; gzip SHA256 `8ee2f896109b7fc658a46217facf1ce2181c7320b56ddd0339f797ee0b65aeb1`. Adjacent provenance records request parameters and receipts. These inventory facts do not supply prices or economics.

Current JSON-RPC documentation defines `min_trade_amount` as the **minimum and order quantity increment**. `contract_size` converts amount to contract count; it is not generally interchangeable with that increment. Linear futures and spots use base-coin amounts. Expiry fields also occur on perpetuals, so a nonzero expiry is insufficient to identify a dated contract. The documented optional extended fields include `maker_max_commission`, `taker_max_commission`, `settlement_max_commission`, `liquidation_max_commission` and futures `margin_params`; absent optional fields carry no zero/unlimited implication. [Public instrument schema](https://docs.deribit.com/api-reference/market-data/public-get_instruments).

The saved future's `lot_size=1` is **not a one-BTC trading constraint**: current guidance says `lot_size` is reserved for future use and does not affect matching or minimum order quantity. [Instrument size field guidance](https://support.deribit.com/hc/en-us/articles/38507223482781-API-guidance).

Use exact decimal/rational quantities. For the saved pair, the common quantity increment is `LCM(0.0001,0.00000001)=0.0001 BTC`. The proposal's budget rule is

`q = floor(B / max(spot_ask, future_bid) / common_increment) * common_increment`.

Require q positive, both native minima/increments passed, sufficient selected-side depth for q, all relevant price ticks/tick steps passed, and explicit order/position constraints accounted for. The common increment follows **min_trade_amount**, even when today's contract sizes happen to coincide. Fees and rounded net inventory remain separate checks. Freeze q for each anchor; do not increase it after seeing later prices.

At activation select among active, open, BTC-base, USDC-quoted, USDC-settled, linear outright dated futures with exact remaining time in [7,30] days. Exclude perpetuals, combos, options and other underlyings. Select the earliest expiry, break any native-name/ID tie deterministically, then keep it fixed. The saved 9 October contract is an inventory candidate; the frozen activation time must still establish its eligibility.

## 3. Optional margin fields: absent, but published scenario available

Both saved requests used `extended=true`, yet the selected entries do not contain extended maximum commissions or `margin_params`. Record their absence. Do not fabricate the documentation's `i_inc`, `m_fee`, `m_inc`, `m_init`, `m_pow` values or translate them into an unverified old margin model.

The current Standard Margin specification supplies a usable **published Standard Margin scenario**: dated BTC is tier 4, C1=25, C2=4, C3=0.03, C4=0.35; initial margin fraction is 1/L(N), maintenance fraction two-thirds of initial. N is underlying BTC position size, including the account position rather than just an isolated new order. Published BTC linear-future NMax is 885 BTC, effective 24 September 2026 at 09:00 UTC. For N <= 26.55 BTC the stated tier has L=25, so IM=4%, MM=2⅔%. Account mode, other exposure and valuation remain conditional. [Current Standard Margin model](https://support.deribit.com/hc/en-us/articles/25944811528477-Standard-Margin), [current futures position limit](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures).

The current contract document also confirms BTC future tick 2.5 USDC and 0.0001 BTC minimum; amounts are BTC. Futures are cash settled in USDC with only P&L transferred, daily settlement at 08:00 UTC and final index TWAP from 07:30–08:00 UTC. Critically, BTC-USDC delivery/settlement assumes USD=USDC by pegging its index to BTC-USD. [Current linear futures mechanics](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures).

The separate dollar-for-dollar reserve exceeds isolated small-position initial margin. It does **not** guarantee survival of adverse paths or replenishment liquidity. Fully funded spot does not authorize collateral reuse or short-future notional as financing.

Published default account limits include USDC Standard Margin aggregate future position $10m, spot maximum open orders 100 per instrument, spot buy-side USDC quantity 2.5m USDC and BTC-side quantity 100 BTC. These account limits coexist with newer instrument limits; use both conservatively, and do not assume private overrides or other account orders absent. [Default account order/size limits](https://support.deribit.com/hc/en-us/articles/31424960796061-Account-order-and-size-limits-default).

## 4. Routed spot and cash availability

BTC_USDC now uses Coinbase Exchange liquidity through Deribit. Its published spot minimum is 1e-8 BTC and tick 0.01 USDC. Routed pairs incur the spot fee column; native Deribit spot books' zero fees must not be imported. Spot requires full funding, only settled funds are usable, and unsettled session profits become available after 08:00 UTC settlement. BTC and USDC are supported for both native and CBBM wallet groups, but individual account instruments can differ after login. [Current spot specifications and availability](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments).

Deribit serves full Coinbase books, without a complete public trade tape. Routed fills are asynchronous; acceptance acknowledgment is not a fill. Paired depth supports quote arithmetic, not execution or an inventory hedge. Pin routing flags and classify changes. [Routed spot API mechanics](https://docs.deribit.com/articles/spot-trading-venues), [18 August API notice](https://support.deribit.com/hc/en-us/articles/38375233938205-18-August-2026).

## 5. Timestamp semantics and causal observation

`public/get_order_book` documents `result.timestamp` as Unix **milliseconds**, supplies price/amount levels and instrument state, and exposes futures `min_price`/`max_price`. Require open state, identified instruments, bounded numeric levels, sufficient depth and allowed-price consistency. The inspected schema does not specify whether a routed spot timestamp is Coinbase's original event time, Deribit's publication time or snapshot generation time. Never replace a missing native timestamp with local receipt and label it as native. [Order-book schema](https://docs.deribit.com/api-reference/market-data/public-get_order_book).

Freeze the study's 2-second age and 250-ms skew checks as **reported API timestamp checks** unless stronger semantics are established. Also preserve request start, receipt UTC and monotonic clocks, RPC errors, timeouts, missing/late snapshots and callback dispatch failures. A response timestamp passing these checks does not prove its underlying Coinbase book changed recently or remains executable. No continuous update coverage follows from five-minute REST samples. Cross-instrument feeds are asynchronous even when per-instrument event ordering is maintained. [Market data architecture](https://docs.deribit.com/articles/market-data-collection-best-practices).

## 6. Cashflow identity and remaining unknowns

For perfectly matched net BTC q, trade-price entry future F, spot entry cost A, final index I and actual spot exit price S, cumulative futures P&L is `q(F-I)`; spot P&L is `q(S-A)`. Their sum is

`q(F-A) + q(S-I)`.

Daily realized settlements telescope into this cumulative future amount; adding them again double counts. Daily settlement is distinct from final delivery; session P&L is not immediately withdrawable/transferable. [Settlement lifecycle](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement).

The residual `q(S-I)` includes spread, timing/TWAP and USD/USDC mismatch; today's observation does not bound its future value. USDC quote arithmetic does not certify conversion to spendable USD. Trading available balance need not be withdrawable in that currency. [Withdrawal balance definitions](https://support.deribit.com/hc/en-us/articles/25944635205021-Withdrawals).

Thus the first stage may report entry premium and conditional headroom under predeclared fees, full remaining-maturity capital, stress and an explicitly named mismatch/conversion allowance. If that allowance is unknown, the corresponding conservative-headroom/pass gate remains unknown. Do not mark all quote rows invalid solely because a future settlement is unobserved; do not call assumed terminal parity verified either. Report distinct quote-valid, scenario-positive and fully verified executable counts (the last stays zero here).

## 7. Freeze gates

| Gate | Current preflight result | Required handling |
| --- | --- | --- |
| Base entry fee schedule effective | Resolved; official August effective date and saved commissions agree | Pin 3.5/5 bp Standard scenario; no user discount |
| Native amount/quantity grids | Resolved for saved pair | min_trade_amount common increment; preserve contract_size separately |
| Dated contract availability | Candidate present/open | Recheck exact fixed T0 eligibility; no favorable replacement |
| Published Standard Margin/max position | Resolved public scenario | Account mode/exposure conditional; independent reserve, no leverage financing |
| Weekly linear delivery fee | Ambiguous | 2.5 bp rate proxy; actual/reference amount unknown |
| Spot fee debit currency/net BTC inventory | Unresolved from inspected public evidence | Separate assumed scenario; no verified inventory hedge |
| Underlying Coinbase timestamp age | Unresolved | API timestamp proxy with underlying-age unknown |
| Terminal spot/index/FX mismatch and replenishment | Unobserved | Explicit allowance or unknown gate; no parity-profit claim |
| User account/region/permissions | Unverified | No execution authorization/certification; public research can proceed |

Deribit's official announcement states it is unavailable in the United States and other restricted countries. Timezone alone does not establish residence or eligibility; any eventual trading recommendation must resolve the user's actual permitted account route. This preflight makes no private request and does not change the existing monitor. [Official availability statement](https://insights.deribit.com/exchange-updates/new-fee-schedule-on-deribit/).
