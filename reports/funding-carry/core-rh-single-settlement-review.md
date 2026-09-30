# Core/RH single-settlement funding-rate review

30 September 2026, 10:18 UTC. Source and 12,000-byte reservation frozen in
`db99951`; one bounded offline execution completed. No new public request,
raw replay, predictor, trading-policy change or private funding evidence.

The earlier carry study compares 24-hour totals against HL-route costs.
This narrower check asks whether concentrating a ten-second Core/RH hedge
around one settlement supplies a large rate credit under equal settlement
reference notionals. It uses the already-derived `holdout_hourly.csv`, all
384 rows, joining Core and RH into 192 asset/hour pairs. Duplicate keys,
missing venues, asset/event counts and common HL reference rates are checked.
The input SHA256 is `5ddcc880253a639471d1f6292dab6f44bb2f8c8e7dec26814c1bb07d8076edbc`.

For positive-long-pays rates c and r, favorable hindsight direction gives
`abs(c-r)` when both events are owned. Allowing either, both or neither
payment gives `max(abs(c), abs(r), abs(c-r), 0)`. This generous arithmetic
scenario does not assert that unequal payment ownership can be achieved.

| Asset | Events | Max absolute differential, bp | Max favorable ownership subset, bp |
| --- | ---: | ---: | ---: |
| BTC | 24 | 0.15 | 0.20 |
| ETH | 24 | 0.00 | 0.12 |
| SOL | 24 | 0.41 | 0.41 |
| HYPE | 24 | 0.21 | 0.21 |
| ZEC | 24 | 0.08 | 0.20 |
| COIN | 24 | 0.03 | 0.07 |
| XAG | 24 | 0.30 | 0.37 |
| NVDA | 24 | 0.15 | 0.19 |

The largest rate credit is 0.41 bp, or $0.041 for an assumed $1,000
settlement reference notional. Fixed 5 bp stress plus the $0.10 target needs
15/9/7/6 bp at $100/$250/$500/$1,000, before capital and trading cashflows.
Zero of 192 events clears any size's hurdle, even under the favorable
payment-subset scenario. Public Standard trading fees are modeled as zero.

This is rate arithmetic, **not an exact cashflow or executable-return bound**:
each venue settles on its own reference; equal entry base quantities need
not imply equal settlement notionals. No simultaneous entry/exit depth,
private payment ownership, rate forecast, conversion, collateral or account
eligibility is measured. Historical values were known only after settlement.
RWA hedge equivalence retains the original study's caveats. Price-basis
movement can add or subtract cash but has not been joined to these events.
The original hourly table remains fully retained; the compact
[output](core-rh-single-settlement-review.json) has every asset's counts and
extrema. The script is `scripts/review_core_rh_single_settlement.py`.

**Decision:** existing funding rates do not support a ten-second
settlement-capture successor. This does not rule out future rate regimes or
combined price-and-funding effects. No new data collection follows.

Peer algebra review passed. Threshold comparison additionally assumes each
settlement reference notional and the stress base equal the sizing budget.
