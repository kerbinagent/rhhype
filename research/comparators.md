# Public DEX comparators for Hyperliquid arbitrage

Observed 2026-09-29 03:50–03:55 UTC. Raw responses and request URLs: `data/raw/comparators/20260929T035055Z/manifest.json`. Run `python scripts/comparators_collect.py` to refresh inventories, books, and 30-day representative history. A second run with `--live-rounds 60 --live-interval 30` samples Aster and dYdX books. These are observations, not executable quotes; no account credentials or orders were used.

## Directly measurable perpetuals

| Venue | Public read path | Market and execution caveat |
| --- | --- | --- |
| Lighter | [`/orderBookDetails`, `/orderBookOrders`, `/candles`, `/fundings`](https://github.com/elliottech/lighter-python) | CLOB. `orderBookDetails` has separate perp and spot arrays. `orderBookOrders` returns individual orders, with `remaining_base_amount` and `price`; aggregate equal prices before walking a book. API `maker_fee`/`taker_fee` of `0.0000` corresponds to **Standard**, not Premium. |
| Aster | [Futures V3 API](https://github.com/asterdex/api-docs/blob/master/V3%28Recommended%29/EN/aster-finance-futures-api-v3.md) | CLOB. `exchangeInfo`, `depth`, `klines`, `fundingRate`, and `ticker/24hr` work without authentication on `https://fapi.asterdex.com/fapi/v3`. Distinguish USDT and USD1 contracts and user-specific VIP fees. |
| dYdX | [Indexer API](https://indexer.dydx.trade/docs/) | CLOB. `/v4/perpetualMarkets`, `/orderbooks/perpetualMarket/{ticker}`, `/candles/perpetualMarkets/{ticker}`, and `/historicalFunding/{ticker}` work publicly. Its book can be far thinner than its daily turnover suggests. |
| GMX | [API integration guide](https://docs.gmx.io/docs/api/integration-guide/) | Oracle/pool model, **no resting order book**. `https://arbitrum.gmxapi.io/v1/markets/tickers` gives directional `capacityLong`/`capacityShort` in 30-decimal USD integers; capacity is indicative until order preparation, and pool/JIT, price impact, borrowing, funding and execution fees all matter. `https://arbitrum-api.gmxinfra.io/markets/info` supplies near-live pool state. |

Live inventory at collection: 235 Lighter perp records (filter `status=active` for usable count), 611 Aster futures symbol records (filter `TRADING` and `PERPETUAL`), 296 dYdX markets (filter `ACTIVE`), and 126 GMX Arbitrum ticker rows (multiple collateral pools can reference one underlying). Archive contains full records, not only these counts.

The following one-shot 10 bp depth is **the smaller of buy and sell notional within 10 bp of the local book mid**, rounded to nearest $1,000. It is an upper bound on immediate book size at that tolerance, not a fill guarantee. Lighter books were capped at 250 orders per side, Aster at 500 levels per side, dYdX at 100 levels per side. Timestamps are not simultaneous.

| Underlying | Lighter | Aster | dYdX | Practical reading |
| --- | ---: | ---: | ---: | --- |
| BTC | $10.23m | $10.38m | $0.00004m | Lighter/Aster strong; dYdX best quotes highly sparse in this snapshot. |
| ETH | $6.95m | $3.02m | $0.020m | Lighter/Aster strong. |
| SOL | $1.09m | $1.06m | $0.017m | Lighter/Aster plausible at modest size. |
| HYPE | $0.617m | $0.502m | $0 | dYdX spread about 224 bp in snapshot. |
| XAU | $0.847m | $0.613m | — | Two plausible gold perp books. dYdX `XAUT-USD` is a token contract, not the same XAU reference. |
| SPY | $0.143m | $0.020m | — | Aster 24h quote volume only about $60k despite displayed depth; verify repeatedly. |
| NVDA | $0.364m | $0.056m | — | Lighter deeper in this snapshot. |
| AAPL | $0.205m | $0.001m | — | Aster book not useful for meaningful size. |
| Brent oil | $0.552m | — | — | Lighter offers a direct perp, GMX offers oracle/pool oil markets. |

The archive also includes BNB, XRP, DOGE, SUI, QQQ, and TSLA books where available. An asset is only a fair arbitrage match after checking **index composition, contract multiplier, margin currency, trading hours, settlement, and token issuer**. Similar ticker strings are insufficient, especially stock tokens versus stock index perps.

## Funding and fees

- Lighter `/fundings` timestamps are **seconds**, while its candle `t` is **milliseconds**. Historical `rate` is a **percentage per one-hour event**: `0.0012` means 0.0012%, or 0.000012 of notional. The `direction` field identifies the payer: `long` makes longs pay shorts; `short` makes shorts pay longs. Its `value` field cross-checks this scale (`~$0.938` on one BTC at ~$78,140). Do not mix this with `/funding-rates` without independent scaling; that endpoint also includes other venues' rows. Lighter first capped hourly candles at 500; an older window was fetched and the stored series merged to 720 hours.
- Aster `fundingRate` is a signed **fraction per settlement event** with `fundingTime` in milliseconds. In these 30 days BTC/ETH/SOL/SPY had about 90 events (8-hour cadence), HYPE/XAU about 180 (4-hour cadence), and NVDA 94 (variable). Normalize to cash flows at actual event times; do not blindly multiply an event rate by 3 or 8.
- dYdX historical `rate` is a signed **fraction per hourly event**, `effectiveAt` is ISO time. The public endpoint returned 730 latest rows for a 730-row request. Restrict to the same 720-hour window as other venues before comparing.
- [Lighter account types](https://apidocs.lighter.xyz/docs/account-types): Standard default is 0% maker/taker, Plus 0.005% both, Premium at 0 LIT is 0.0040% maker / 0.0280% taker, with stake discounts. Premium differs in latency and quotas. [Aster current public schedule](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees): USDT perps 0% maker / 0.04% taker; USD1 perps 0% / 0.005%, before VIP/ASTER discounts. The authenticated `commissionRate` endpoint is needed to know a particular account's actual fee. [GMX fees](https://docs.gmx.io/docs/trading/fees/) include side-dependent position fees, price impact, borrowing, funding, UI and network fees; gold and oil have different on/off-hours fee schedules.
- [Aster collateral modes](https://docs.asterdex.com/trading/perpetuals/single-asset-mode-and-multi-asset-mode) allow USDT-only single-asset margin or multi-asset cross margin with collateral haircuts; the quote symbol alone does not reveal the actual collateral funding or conversion cost. GMX market labels encode index and pool collateral separately, for example `ETH/USD [WETH-USDC]`.
- [dYdX trading fees](https://help.dydx.trade/en/articles/166995-trading-fees-on-dydx) depend on trailing 30-day account volume and can change through governance. No account-specific rate was available from public market data, so the archive leaves this fee unknown rather than inserting an unsupported flat rate. [dYdX funding documentation](https://help.dydx.trade/en/articles/166992-default-funding-rates-on-dydx) confirms hourly settlement and payer direction.
- [Lighter API limits](https://apidocs.lighter.xyz/docs/rate-limits) are 60 public requests per rolling minute for Standard/unauthenticated use; HTTP 405 **can mean rate limited** as well as HTTP 429. A firewall cooldown can last 60 seconds. Plan broad universes with market rotation and leave headroom for metadata rather than assuming unlimited books.

For a pair, gross executable entry edge should be computed from **same-time, size-matched** bid on the short venue and ask on the long venue. Deduct taker/maker fees on entry and exit, expected exit spread/impact, one-time transfer or bridge costs if relevant, and the signed funding/borrowing cash flows for the chosen holding period. Report each leg's margin currency and USD conversion separately. A 24h trade-volume figure cannot substitute for executable size; resting depth can disappear before either leg fills.

## Other popular venues and Robinhood stock tokens

- [Drift](https://github.com/drift-labs/dlob-server) has a DLOB plus AMM/JIT execution and on-chain market state, so DLOB size alone misses other available execution. The previously documented `data.api.drift.trade` and `dlob.drift.trade` hosts failed DNS from this workspace on 2026-09-29, so no live Drift depth or history is in this archive. Its `/stats/markets` and `/l2?marketIndex=...&marketType=perp` paths should be revalidated before incorporating it.
- [Jupiter Perps' JLP pool](https://jup.ag/perps/jlp-earn) is the counterparty to leveraged positions. [Jupiter support](https://support.jup.ag/hc/en-us/articles/22630581630492-How-are-Recurring-orders-closed) lists a 0.06% base open/close fee, size-sensitive price impact, and hourly borrowing fees. This is structurally different from a long/short funding transfer; quote the particular size and holding time instead of comparing a displayed funding percentage.
- [Uniswap on Robinhood Chain](https://blog.uniswap.org/robinhood-chain-is-live) explicitly supports Robinhood Stock Tokens through UniswapX and AMM routes. Its [quote API](https://developers.uniswap.org/docs/api-reference/aggregator_quote) needs token contract addresses, chain IDs, size and a swapper, and may use intents rather than a simple pool book. [Uniswap's tokenized-stock notice](https://support.uniswap.org/hc/en-us/articles/46577159640589-Tokenized-Stocks) explains that issuer rights and backing vary. Do not equate one stock token with an equity perp solely by ticker.
- [PancakeSwap X RWAs](https://docs.pancakeswap.finance/trade/pancakeswap-x/rwas) includes Ondo tokenized stocks and ETFs on BNB Chain; [its FAQ](https://docs.pancakeswap.finance/trade/pancakeswap-x/faqs) says active fillers supply those swaps and fills can fail. Treat a stock-token quote as an executable spot/RFQ candidate only after exact issuer/token/chain and size-specific quote checks. It has no perpetual funding payment. PancakeSwap's separate perpetuals V2 route uses an Aster-backed pool model, per [its docs](https://docs.pancakeswap.finance/trade/perpetual-trading/perpetual-trading-v2), and should not be counted as independent order-book liquidity from Aster.

### What the archive supports

It supports an initial screen, not a backtested arbitrage profit claim. The 30-day candle/funding panels can test basis/funding behavior; the live JSONL panels can test spread/depth persistence. A credible realized-profit estimate still needs entry and exit order-book walks at synchronized timestamps, fee tier, partial-fill and hedge-delay assumptions, contract matching, borrowing/funding, and the ability to trade in each relevant jurisdiction and account. The collector does not trade or touch balances.
