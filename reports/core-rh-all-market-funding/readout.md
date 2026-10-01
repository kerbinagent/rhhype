# Funding differences across the full shared unit-perp universe

Frozen `0209712`, fetched 1 October 2026. The universe contains all 42 shared
active unit-multiplier perpetual symbols in the pinned 14:07 UTC metadata;
frozen/reduce-only markets and nonmatching symbols are explicitly listed.
No asset was chosen using the new rates. All 84 public history requests
succeeded, with complete 24-hour coverage from 30 September 15:00 UTC through
1 October 14:00 UTC. Retained raw compressed bytes: 37,098; wire bytes: 173,796.

This is **rate arithmetic, not trading P&L**. A positive rate means longs pay
shorts. An absolute rate gap gives the favorable hindsight credit assuming
equal settlement reference notionals. Actual price cashflows, settlement
references, funding ownership, account fees and collateral conversion were
not joined. No actual trade was placed.

| Market | Largest hourly absolute gap |
|---|---:|
| AI | 7.54 bp |
| SHEIN | 4.57 bp |
| CASHCAT | 1.72 bp |
| LIT | 0.96 bp |
| PONS | 0.89 bp |

Across **1,008 joined asset-hours, only one exceeded 5 bp**, and the same one
exceeded the 6 bp screen (5 bp allowance plus 1 bp margin). AI had Core long
payers at 8.79 bp versus RH at 1.25 bp for the 09:00 UTC settlement. On an
assumed equal $100 reference notional, that hindsight differential is $0.0754,
leaving $0.0254 after the allowance before unmeasured trading costs.

The predeclared next-hour rule required the previous gap to be at least 6 bp
and kept its direction. It selected only AI at 10:00 UTC, whose credit was
0.45 bp: $0.0045 per assumed $100, or −$0.0455 after the 5 bp allowance before
trading costs. That simple persistence rule did not cover the allowance.
The single hindsight spike does not provide advance evidence of eligibility
for a future settlement.

Independent audit rebuilt all 42 market joins, hashes for every response,
all 2,016 individual venue-hour rates, payer signs, 1,008 gaps, both threshold
counts and the previous-hour-only rule. All passed. All markets and all hourly
rows remain in the compressed summary; the CSV provides the complete per-
market screen. This expands the earlier eight-market check without claiming
that every possible predictor or price-plus-funding strategy is ruled out.
