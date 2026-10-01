# Core ETH carry and a funding swap — 1 October 2026

## Decision

Core ETH collateral gives a defensible reason to research lower capital
requirements. The September candle proxy left $2.74 on approximately $1,100
for the month. A separate five-round quote screen found a $0.47 median
immediate round-trip cost at $1,000. These are different periods and neither
establishes executable future returns.

Adding a Boros swap could hedge the funding stream, but the current small-size
cost illustration is weak: $100/$250/$500 are negative and $1,000 leaves only
$0.42 through October 30 before several unresolved costs. Do not promote
this version or launch a larger capture solely on its displayed fixed rate.
The simpler floating-funding ETH design remains a research candidate.

## Exact stream, maturity and units

The public symbol registry contains `lighter-eth`. One complete active,
UI-whitelisted market page returned 32 markets, including two exact matches:
199 (October 30) and 212 (November 27). The rule selected the earliest
maturity between 7 and 90 days, independently of the rates. Market 199 has
hourly payments, status 2 (GOOD), tokenId 2 and no configured AMM. Its
reported previous 24-hour volume was zero; this alone does not establish
absent depth. No account eligibility was tested.

The separate asset response maps tokenId 2 to Arbitrum WETH. The corrected
book at 02:55:40 UTC (received 02:55:41) showed 15 ETH of YU at the top bid
bucket. That covers the illustrative sizes, conditional on the displayed
book remaining available. Snapshot depth is not a fill.

The first book request used an invalid aggregation size and returned HTTP
400; it remains in the evidence. The official embedded OpenAPI permits
0.0001/0.001/0.01/0.1. For this endpoint, `ia × tickSize` is the aggregated
APR, and `sz / 10^18` is YU quantity. Do not apply the contract's exponential
tick formula to this already aggregated API index. The corrected top bucket
833 at 0.0001 represents approximately 8.33% APR. We use 8.32% as a one-bucket
sensitivity, not a proven executable lower bound.
[Official API schema](https://api-boros.pendle.finance/apis/docs).

## Cost illustration

Hold ETH price at $2,684.23362681 and use 694 hourly periods to maturity.
Keep total committed capital at 1.1 times spot notional, assuming the swap's
ETH collateral is allocated from that spot inventory. Additional margin
would raise the capital charge. The setup is a sensitivity, not a feasible
portfolio proven by an account simulation.

Market configuration supplies a 0.05% annualized entry fee and 0.10%
annualized settlement fee. The published 0.00027 ETH entrance amount is an
illustration; no account-specific fee was read. Funding credits must not be
counted again on top of the fixed swap return.
[Fee mechanics](https://docs.pendle.finance/boros-dev/Mechanics/Fees).

| Notional | Fixed gross | 5% capital charge | Swap + settlement | Entrance | Earlier spread median | 5 bp stress | Remainder |
|---|---:|---:|---:|---:|---:|---:|---:|
| $100 | $0.659 | $0.436 | $0.012 | $0.725 | $0.033 | $0.050 | -$0.596 |
| $250 | $1.648 | $1.089 | $0.030 | $0.725 | $0.089 | $0.125 | -$0.410 |
| $500 | $3.296 | $2.179 | $0.059 | $0.725 | $0.209 | $0.250 | -$0.126 |
| $1,000 | $6.591 | $4.357 | $0.119 | $0.725 | $0.473 | $0.500 | $0.418 |

The spread medians came from an earlier two-minute window, not concurrent
three-leg quotes. Gas, deposit/withdrawal, bridge costs, future basis and
currency rehedging are omitted. The 5 bp charge is separate from measured
spread costs. A $0.42 residual provides little room for those omissions.

## Why the fixed APR is not a fixed dollar profit

The detailed contract documentation accounts for the short swap's fixed leg
as an upfront **WETH credit**, offset by its floating-payment liability.
The user-facing description expresses the same economics as fixed versus
floating periodic returns. Do not book the upfront credit as immediate
profit or add a second periodic fixed credit.
[Contract settlement](https://docs.pendle.finance/boros-dev/Mechanics/Settlement).

For a simplified matched quantity `q`, settlement rates `r_t`, ETH prices
`P_t`, initial fixed WETH credit `q*K*T`, and no conversion until maturity,
the combined funding-related terminal dollar cash is:

```text
q*K*T*P_T + q*sum(r_t*(P_t - P_T))
```

This is an accounting illustration assuming exact reference-rate matching,
with fees removed for clarity. It is generally different from `q*P_0*K*T`.
Trading or otherwise hedging the WETH payment exposure could change that
result, but adds execution, lot-size and collateral requirements. The spot
principal and swap collateral must also be included in the total delta.

Each venue needs enough local collateral while offsets settle elsewhere.
A funding spike can pay the Core short while draining the Boros balance.
Changes in the swap's mark rate also affect its health. Same underlying
asset and matched rates do not make these accounts cross-margined.
[Boros margin](https://docs.pendle.finance/boros-dev/Mechanics/Margin).

## Evidence and checks

[Registry](../reports/boros-core-eth-markets/summary.json),
[assets and failed request](../reports/boros-eth-book-assets/terminal.json),
[corrected book provenance](../reports/boros-eth-depth-corrected/terminal.json),
[schema excerpt](../reports/boros-eth-depth-corrected/schema-excerpt.json),
[calculation](../reports/boros-eth-book-assets/fixed-rate-screen.json), and
[source](../scripts/boros_eth_fixed_rate_screen.py) are retained.
All four spread medians reconcile to the earlier quote summary; all four
residual identities were independently recomputed with Decimal in the root
session. This is not an independent-agent audit. Actual P&L remains null.

The market lookup and depth work reserve 160 KiB within a new 4 MiB active
research pool. That pool came from reducing the manual review archive cap
from 16 to 12 MiB, acknowledged and enforced by the monitoring agent. No
archived evidence was removed; the overall 836,777,216-byte reservation and
all frozen dated-carry allocations remain unchanged.
