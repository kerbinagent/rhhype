# RH quote distance and public trade flow

**Scope:** exploratory, fixed ladder on two already stopped seven minute public captures. This is a diagnostic of reported aggressor flow near hypothetical RH Lighter orders. It is **not** a fill, P&L, or executable strategy backtest. No orders were sent, and the ongoing RH pilot capture was not read.

## Frozen question and method

At each valid RH full-book receipt, separated from the previous anchor by at least 12 seconds, place hypothetical bids and asks at 0, 2, 5, 10, or 20 basis points *away* from the observed same-side best, rounded outward to the RH price grid. Size each quote to no more than $100, $250, $500, or $1,000 at its own price, rounded down to the published size step and checked against minimum quantity and notional. The primary view is $1,000. The four sizes share exactly the same asset, side, distance, and anchor times.

The assumed quote activation is 300 ms after the decision. Initialize displayed **same-price** quantity ahead only at the first RH book whose source and local receipt clocks are both at or after activation. A book arriving more than two seconds after that point, or one where the quote would already cross the opposite side, censors the branch. Do not give the hypothetical order credit for later public cancellations. For a bid, count only ordinary sell-aggressor trades at or below its price; for an ask, ordinary buy-aggressor trades at or above its price. A touch is any such print. The possible attributed quantity is `min(own quantity, max(0, total eligible print quantity − initial same-price quantity ahead))`; "possible partial/full" describes that bound, not a proven private execution. At-price and through-price print volume are retained separately in [rows.csv](rows.csv).

The exposure window ends 10 seconds after decision. A print needs an exchange source time within the active window and a local receipt within two seconds thereafter; source time must never exceed receipt. An eligible print whose source or receipt precedes the first activation book makes the affected branch unknown, because the queue snapshot could have missed it. Feed invalidation, generation change, a stale book, a greater-than-two-second RH book gap, or a window cut by archive end also censors the branch. Book and trade events are deduplicated and validated by the existing [RH event adapter](../../scripts/rh_maker_events.py); subscribed trade backlog and liquidation prints are excluded. The captures are [BTC/ETH, 19:39–19:46 UTC](../../data/raw/maker-capture/20260929T1939Z/manifest.json) and [NVDA/XAG, 20:22–20:29 UTC](../../data/raw/maker-capture/20260929T2022Z/manifest.json), both stopped with `duration_limit` and no truncation. Script and raw SHA-256 hashes appear in [summary.json](summary.json).

The 300 ms activation is the paper pilot's RH Standard assumption: the archived [RH-specific official account-type page](../../data/raw/comparators/rh_lighter/20260929T040726Z/sources/account-types.md) lists **200 ms maker/cancel processing** and 300 ms taker processing, and the study adds 100 ms modeled network/receipt allowance to maker activation. The [main Lighter account-type page](https://apidocs.lighter.xyz/docs/account-types) describes a different Standard maker latency; its 0 ms figure must not be applied to the RH domain. Actual acknowledgement, order priority, hidden liquidity, matching details, and account availability are unobservable from this public archive.

## Primary $1,000 observations

Each cell is **complete windows / touched / possible partial or full / possible full**. The same anchor coverage applies to all offset rows within an asset and side, except one ETH best-quote branch that was marketable at activation.

| Asset | Side | 0 bp | 2 bp | 5 bp | 10 bp | 20 bp |
| --- | --- | --- | --- | --- | --- | --- |
| BTC | Bid | 34 / 16 / 12 / 9 | 34 / 3 / 3 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 |
| BTC | Ask | 34 / 23 / 13 / 5 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 |
| ETH | Bid | 33 / 17 / 5 / 4 | 34 / 5 / 3 / 2 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 |
| ETH | Ask | 33 / 14 / 9 / 5 | 34 / 2 / 2 / 2 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 | 34 / 0 / 0 / 0 |
| NVDA | Bid | 23 / 7 / 2 / 1 | 23 / 1 / 0 / 0 | 23 / 0 / 0 / 0 | 23 / 0 / 0 / 0 | 23 / 0 / 0 / 0 |
| NVDA | Ask | 23 / 4 / 3 / 0 | 23 / 0 / 0 / 0 | 23 / 0 / 0 / 0 | 23 / 0 / 0 / 0 | 23 / 0 / 0 / 0 |
| XAG | Bid | 30 / 2 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 |
| XAG | Ask | 30 / 1 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 | 30 / 0 / 0 / 0 |

There were 35 BTC and ETH anchors each, with one archive-end censor each; 34 NVDA anchors with ten book-gap censors plus one archive-end censor; and 34 XAG anchors with three book-gap censors plus one archive-end censor. The extra ETH best-quote censor was marketability at activation. All 160 asset × side × distance × size groups and exact censor reasons are in [summary.json](summary.json). At the best quote, possible full-flow counts generally decline as the requested size rises: for example BTC ask is 13/34 at $100 and 5/34 at $1,000. Across these brief archives, no **complete** 5, 10, or 20 bp window had an eligible at/through print on either side for any asset.

## Interpretation for the maker hypothesis

The frozen RH pilot's adverse Hyperliquid hedge calibration is conditioned on RH flow at the **best bid**. A quote 5–20 bp behind the best encounters a different event: a larger directional sweep, or no flow in a 10-second window. The best-bid adverse estimate cannot be transferred unchanged to those deeper quotes. The present archive yielded too few deeper touches to estimate their conditional HL hedge markout reliably; this report deliberately does not turn an empty conditional cell into zero adverse selection. A future joint quote-distance, trade-flow, and post-flow hedge-price study would need substantially more independent stopped data, with a rule fixed before its holdout.

These counts are descriptive of four short market intervals. The hypothetical quote remains at its initial fixed price for the window; no hedge, inventory, cancel/requote policy, own-order ACK, funding, fees, or exit is simulated. A public at/through print can be routed against other orders and does not prove our order would fill. Conversely, queue changes or unobserved execution can defeat this conservative same-price-ahead attribution. The result gives a useful constraint on the "quote far enough away to clear costs" idea over 10 seconds: in these archives, 5 bp or more of distance produced no uncensored qualifying flow, while top-of-book flow was observable but says nothing by itself about net profit.

## Reproduce

```bash
python scripts/analyze_rh_quote_distance.py
python -m unittest tests.test_analyze_rh_quote_distance -q
```

The script reads only the two named stopped captures and archived RH market metadata. It writes [rows.csv](rows.csv) and [summary.json](summary.json); it makes no network calls.
