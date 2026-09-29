# Paper monitor funding accounting

The monitor sums **settled** funding records for every closed leg. Positive signed rates mean longs pay shorts. A simulated leg owns an event when `entry_time < event_time <= exit_time` in Unix seconds. This deterministic convention is needed for public market data, which does not reveal the exact position/funding transaction ordering at the same instant. Aster documents that charging can lag the nominal funding time by 15 seconds; a leg starting or ending within 15 seconds of its event is marked incomplete because ownership of that payment is ambiguous.

| Venue | Public settlement history | Rate and dollar conversion | Schedule |
| --- | --- | --- | --- |
| Hyperliquid | [`fundingHistory`](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals) on `POST /info` | Signed fraction per hour. [Funding formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding): quantity × settlement oracle × rate. A positive rate costs a long. Historical rows omit the settlement oracle; a timestamped `metaAndAssetCtxs.oraclePx` sample within 90 seconds is used as an **estimated** reference. | Every UTC hour. Missing expected hour is incomplete. |
| Lighter Core and Robinhood Lighter | Official [SDK `/fundings` endpoint](https://github.com/elliottech/lighter-python/blob/main/docs/CandlestickApi.md) | `rate` is percent per hour; `direction=long` means positive long-pays. Historical `value` appears to be a positive settled amount per base unit, so quantity × value supplies a cash estimate without candle prices. The per-unit interpretation is independently checked against saved BTC rows: `0.937308 / (0.0012/100) = 78,109`, matching a BTC index price. The [official schema](https://github.com/elliottech/lighter-python/blob/main/docs/Funding.md) lists `timestamp`, `value`, `rate`, and `direction` but does not specify units; the monitor marks this cash conversion **estimated**, records source, and keeps the raw rate. | Every UTC hour. Missing expected hour is incomplete. |
| Aster | Official [V3 `/fundingRate`](https://asterdex.github.io/aster-api-website/futures-v3/market-data/) with inclusive time bounds and pagination | Signed **fraction per event**. The [funding formula](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/funding-rate) is quantity × settlement mark × rate. History omits the mark; sampled V3 `premiumIndex.markPrice` near settlement is **estimated**. | Variable: [funding configuration](https://asterdex.github.io/aster-api-website/futures-v3/market-data/) reports current intervals, but Aster can change them without announcement. The service queries settled events over the actual holding window. An empty response across an hour boundary is incomplete unless a pre-boundary `premiumIndex.nextFundingTime` sample proves the next event falls after the exit. It never projects the current interval backward. |

Aster's V3 public paths are requested on `https://fapi.asterdex.com/fapi/v3`. On 2026-09-29 the documented `fapi3.asterdex.com` host returned HTTP 403 in this workspace, while both `fundingRate?symbol=BTCUSDT&limit=1` and `premiumIndex?symbol=BTCUSDT` on the established futures host returned HTTP 200 with the documented V3 response fields. The unsymbolized batch `premiumIndex` endpoint also returned HTTP 200.

`FundingService.cashflows(position)` returns `complete`, `cashflow_usd`, `estimated`, `events`, and `missing`. A missing rate, inaccessible history, absent bounded reference, malformed record, unverified empty Aster hour, or Aster sequencing ambiguity gives `complete=false` and `cashflow_usd=null`; it never contributes a false zero. An empty window is zero only when hourly schedule proves no crossing, or Aster history is fetched successfully and every crossed hour has pre-boundary schedule proof. Individual events preserve signed rate, reference source, sampling skew, and exact/estimated quality. A zero settled rate needs no price estimate.

`sample_references(markets)` batches native and `xyz` Hyperliquid context requests, a single Lighter `orderBookDetails` request per instance, and one Aster `premiumIndex` request. All requests are public and read-only. Lighter extra requests are paced to at most ten per minute **per FundingService instance** to leave headroom under the Standard shared IP limit. The caller should schedule references near funding boundaries and persist `dump_state()` in its checkpoint. Reference retention keeps the closest sample to each UTC hour per market, so frequent sampling cannot evict the useful near-boundary value immediately. Funding history requests align to settlement windows for Hyperliquid/Lighter and UTC hour windows for Aster, allowing multiple position segments on the same market to reuse one response. Aster's cached response is never reused for a later as-of time than its fetch, because new events may have settled meanwhile. Recent responses expire after 30 seconds to allow late event posting; response, reference, and Aster schedule caches have bounded row counts. These limits do not replace a shared process-wide Lighter limiter if several processes run under the same IP.

All USD totals assume USDC, USDG, and USDT at par. `cashflow_usd` is therefore a paper comparison unit; conversion costs or depegs require separate treatment. A sampled clearing reference is always labelled estimated, including one sampled very close to the event. Past Aster or Hyperliquid settlements without a near-event reference remain incomplete.


## Closed positions waiting for accounting

A trade with no remaining quantity may stay in the engine as
`AWAITING_FUNDING` when its funding cannot be assigned reliably. This status
is not market exposure. It is also not necessarily a data-fetch delay: public
history cannot resolve an ambiguous fill/funding ordering inside Aster's
settlement window merely by waiting longer.

At 18:33 UTC on September 29, two XAG records that the display had shown as
8,000+ seconds old had actually held exposure for 12.1267s and 11.7846s.
Both legs of both records were zero. Their Aster funding ownership around
16:00 remained uncertain. The 10-second policy requests an exit; subsequent
eligible book updates and fills explain actual holding times beyond ten seconds.

Commit 1297815 separates flat records into snapshot `pending_settlements`.
`positions` holds entries/exposure; each row also provides `has_exposure`,
`holding_seconds`, and (where relevant) `funding_wait_seconds`. The UI reports
"Closed, funding unresolved" separately. Unknown funding remains null and the
existing venue-specific accounting reservation stays in place. This change
neither manufactures a funding value nor finalizes these two trades' net P&L.
