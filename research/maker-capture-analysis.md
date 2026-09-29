# Public maker-feed capture: stopped-archive analysis

This analysis replays the frozen [18:23 UTC archive](../data/raw/maker-capture/20260929T1823Z/manifest.json) with [`scripts/analyze_maker_capture.py`](../scripts/analyze_maker_capture.py). It evaluates **conditional public quote economics and displayed-book markouts**, not fills or trading P&L. No order was sent.

## Archive and feed quality

The capture ran 2026-09-29 18:23:22–18:29:56 UTC (394 seconds). Its 25 MB compressed hard cap ended it before the configured 10 minutes: 68,229 complete NDJSON records, one complete frame dropped at the cap, and `truncated=true`. The gzip SHA-256 is `dd1693a4b248f14f7c2bbb111590df24d67acb6ea28f3a677ce4cc05e54a2bf7`; all members decoded and record and compressed-size counts match the manifest. There was one connection generation per venue, six subscription acknowledgements per venue, no recorded errors, no sequence or timestamp invalidations, no rejected trade fields, and no unknown-market HL trades. The market-plan file changed after capture, so its **current** hash differs from the captured hash; the manifest freezes the BTC/ETH IDs used by this replay.

The first Hyperliquid trade frames arrived before the first BBOs and contained recent historical trades. A second-pass source-time filter removed 50 BTC and 30 ETH trades before the first quote. Lighter startup trade snapshots were also excluded. Remaining trade counts are HL BTC 1,390 / ETH 847; Core BTC 1,959 / ETH 721; RH-domain Lighter BTC 365 / ETH 139. Trade IDs are deduplicated, aggressor side and positive price/size are required, and trades cannot be reused inside a 5-second screen window.

| Feed | BTC quote frames | ETH quote frames | Median quote gap BTC / ETH | Median receipt minus source BTC / ETH |
|---|---:|---:|---:|---:|
| Hyperliquid BBO | 2,922 | 2,737 | 0.098 / 0.100 s | 0.296 / 0.299 s |
| Hyperliquid L2 | 74 | 74 | 5.386 / 5.386 s | 0.358 / 0.358 s |
| Lighter Core ticker | 11,128 | 15,157 | 0.013 / 0.012 s | 0.065 / 0.065 s |
| RH Lighter ticker | 2,766 | 3,846 | 0.044 / 0.027 s | 0.065 / 0.065 s |

The Lighter order-book channels separately had about 50 ms median receipt gaps; the manifest reports no nonce gaps. All measured receipt-minus-source ages were nonnegative. Exchange clocks and the collector clock were **not calibrated**, so these differences are observations, not network-latency measurements. HL L2 must not be merged with a newer BBO merely because both frames are structurally valid.

## Maker quote and trade-flow screen

At each non-overlapping 5-second UTC grid point, the screen considers about $1,000 of BTC or ETH, floored to its base-size lot. It requires two current one-level quotes (receipt age at most 1 second, source age at most 2 seconds, cross-venue source difference at most 0.5 second) and full displayed top size for the **hedge**. It then tests 0.5, 1, and 3 second hypothetical maker-order arrival delays. The maker-side price must still be displayed and uncrossed. The initial displayed maker size is treated as queue ahead; opposite-aggressor public trades at or through the quote are accumulated only until the next 5-second grid point. A trade-flow total above displayed size is an **optimistic hypothetical partial-execution signal**. Public data cannot reveal our actual queue place, hidden orders, cancels, ALO acceptance, or whether any hypothetical order would fill.

The quote allowance subtracts the maker entry fee, opposite-leg taker entry fee, and an **approximate** two-taker exit-fee hurdle from the opening quote difference. It does **not** include an actual closing basis, exit spread or impact, funding, financing, currency conversion, or the price at which a delayed hedge would execute. A favorable opening quote therefore cannot be called profitable. Fee assumptions are native HL tier-0 maker 1.5 bp / taker 4.5 bp and Lighter Standard maker/taker 0 bp on both the Core and RH domains. Replacing a $1,000 HL taker entry with an HL maker entry saves about **3 bp, or $0.30**, in fees if filled; any spread capture is a separate, unproven effect. See [HL fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Core Lighter account types](https://apidocs.lighter.xyz/docs/account-types), and [RH Lighter account types](https://apidocs.rh.lighter.xyz/docs/account-types).

The 1-second-arrival screen, pooling BTC buy/sell and ETH buy/sell (77 decision grids each), produced:

| Hypothetical maker → taker hedge | Top-supported opening quotes | Positive opening quote after four-fee allowance | Same maker price at arrival | Possible partial trade-flow signal | Positive opening quote **and** possible partial |
|---|---:|---:|---:|---:|---:|
| HL → Core | 199 | 26 | 157 | 12 | 0 |
| Core → HL | 242 | 0 | 25 | 8 | 0 |
| HL → RH Lighter | 169 | 48 | 138 | 13 | 3 |
| RH Lighter → HL | 227 | 5 | 43 | 4 | 0 |

All 26 HL → Core positives were ETH maker-sell openings (26 of 48 top-supported ETH sell quotes), with **zero** positive-and-partial overlap at 1 second. All 48 HL → RH Lighter positives were also ETH maker-sell openings (48 of 63), with three positive-and-partial overlaps. Of those three overlapping windows, **one** also had a fresh, same-$1,000-size hedge quote with a positive opening allowance at the first trade-flow signal. Even that conjunction establishes neither maker fill nor closing economics. At 0.5 and 3 second assumed arrival, the HL → Core positive-and-partial count was 0 and 1; HL → RH was 1 and 1. The raw [screen rows](../data/derived/maker-capture-20260929T1823Z/screen.csv) contain every side and delay. Repeated delay screens share market observations and are not independent trials.

Hyperliquid's [order rules](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types) and [public WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) provide no hypothetical order acknowledgement or queue position. The public trade-through screen therefore cannot estimate fill probability. The positive-and-partial rows warrant, at most, more offline examination; they are **not** maker P&L.

## Predeclared four-taker control: 1, 2, 5, and 10 seconds

The separate control samples at most once per second per route and uses both long/short directions of each HL pair. It fixes the same base quantity, about $1,000 of the long entry leg, through four displayed one-level taker books: long ask and short bid at entry, then long bid and short ask. Entry must meet the freshness and 0.5-second source-skew limits above. The exit uses the **first observed quotes with source time at or after** the nominated horizon, received within 1 more second; it requires 0.5-second source and receipt skew and full top size on both exits. Observed exit receipt medians were about horizon + 0.4 second. Fees are charged on each of the **four actual displayed trade notionals**. Missing or insufficient books are excluded, never counted as zero return. This is a displayed-book markout, not an assertion that four taker orders would fill at those prices.

| Pair | Horizon | Qualified entry anchors | Complete same-quantity four-book observations | Positive displayed net | Directional net-median range |
|---|---:|---:|---:|---:|---:|
| HL–Core BTC/ETH | 1 s | 879 | 485 | 0 | −10.05 to −9.56 bp |
| HL–Core BTC/ETH | 2 s | 878 | 493 | 0 | −10.23 to −9.56 bp |
| HL–Core BTC/ETH | 5 s | 870 | 498 | 0 | −10.31 to −9.68 bp |
| HL–Core BTC/ETH | 10 s | 858 | 475 | 0 | −10.32 to −9.73 bp |
| HL–RH BTC/ETH | 1 s | 734 | 397 | 0 | −11.12 to −10.31 bp |
| HL–RH BTC/ETH | 2 s | 733 | 388 | 0 | −11.16 to −10.15 bp |
| HL–RH BTC/ETH | 5 s | 727 | 382 | 0 | −11.23 to −10.74 bp |
| HL–RH BTC/ETH | 10 s | 718 | 389 | 0 | −11.38 to −10.47 bp |

For the 1-second Core control, 16 qualified entries lacked a timely future quote, 88 failed future skew, and 290 lacked full exit top size. The corresponding RH figures were 44, 69, and 224. The [full control CSV](../data/derived/maker-capture-20260929T1823Z/four_taker_control.csv) reports each BTC/ETH direction and every horizon, including missing-book reasons and actual exit receipt time. RH prices are USDG-denominated versus HL USDC; this control omits conversion and financing, making its negative result optimistic with respect to those costs.

## Decision supported by this capture

The public feeds can screen opening quote differences and later displayed-book changes. They cannot support a maker fill-rate or maker P&L estimate. The capture's conditional fee-positive HL ETH maker-sell openings do not verify a hedge at fill time or a profitable unwind. The predeclared 1–10 second four-taker observations showed **zero** positive after-fee displayed markouts among complete books, so this stopped 6.6-minute sample gives no evidence that simply shortening the holding period rescues the BTC/ETH cross-venue taker route. It does not rule out unobserved times or different conditions. A next maker study would need an explicit queue/order acknowledgement and fill model, post-flow hedge and unwind diagnostics, and a longer bounded capture; any real order experiment would require separate authorization.
