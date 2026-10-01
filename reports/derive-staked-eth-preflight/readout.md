# Staked-ETH collateral preflight

## Decision

The present simulated portfolio can open an ETH short against wstETH plus
a 10% USDC reserve. This establishes a current margin prerequisite, not
profitability or future solvency. The captured ETH perpetual funding rate
was zero; Lido's current seven-day staking APR was 2.261%. This does not
pay the 5% capital assumption on 1.1 times spot principal before fees.
No historical funding result or executable trade is established.

## Public evidence

The fixed preflight (`caf0be6`) collected documentation, ETH/wstETH currency
metadata, ETH-PERP specifications, a September funding-history request and
Lido's seven-day APR response. All market calls used Derive's documented
production v3 API; no account identifier, authentication, RFQ or order.

wstETH metadata maps its underlying to Lido's Ethereum token
`0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0`. The reference prices were
$2,685.876459/ETH and $3,343.047812/wstETH. The target rounded down to
0.372 ETH short and about 0.298872794828 wstETH, representing $999.146043
at those prices. This hedge uses their current price ratio; it does not
verify the on-chain stETH-per-token rate or eliminate discount risk.
Staking grows the ETH claim over time, requiring hedge/rebalancing accounting.
[Lido token mechanics](https://docs.lido.fi/guides/lido-tokens-integration-guide/).

The ETH-PERP minimum order is 0.1 ETH, approximately $268.59 at this
reference price. The $100/$250 target notionals cannot open that minimum
hedge. The $1,000 primary can; its size increment is 0.001 ETH.

The September hourly funding-history response contains **zero rows out of
720 requested hours**. This is missing coverage, not zero historical funding.
The API history is funding-rate OHLC, not settled account payments.
Current metadata separately reports `funding_rate = 0`; its configured
hourly cap differs from the generic documentation, so generic caps should
not override captured instrument settings.

Lido's response contained seven daily APRs averaging 2.261%, for September
24–30. That describes a recent staking rate, not a locked future return.
[Official APR API](https://docs.lido.fi/integrations/api/).

## Margin correction and full matrix

All eight original simulations returned a parameter error: at most 12
fractional digits are accepted. They are preserved. Their original terminal
label means requests completed; it does not mean margin calculations succeeded.
The separately frozen correction (`f19f5a5`) rounds wstETH down to 12 decimals
and USDC down to six, retaining the same quantities and economic scenarios.
All eight corrected requests returned simulated results at 03:35 UTC.

| Margin model | Extra cash / principal | Net initial margin after short | Net maintenance margin | Can add short now? |
| --- | ---: | ---: | ---: | --- |
| SM | 0% | -65.96 | 749.65 | No |
| SM | 10% | 33.95 | 849.56 | Yes |
| SM | 25% | 183.82 | 999.42 | Yes |
| SM | 50% | 433.61 | 1,249.21 | Yes |
| PM2 | 0% | 384.58 | 905.87 | Yes |
| PM2 | 10% | 484.49 | 1,005.78 | Yes |
| PM2 | 25% | 634.36 | 1,155.65 | Yes |
| PM2 | 50% | 884.14 | 1,405.43 | Yes |

These are margin headroom amounts, not account equity or trading profits.
The calls are sequential and marks can move. SM collateral credit and PM2
risk haircuts have different meanings; the public calculation resolves the
current result without interpreting their raw discount numbers identically.
Future price moves, wstETH discounts, cash debits/borrowing, collateral caps
and withdrawal conditions remain untested. No actual account eligibility is
implied. [Portfolio margin](https://docs.derive.xyz/portfolio-margin).

## Thirty-day cost sensitivity

Hold prices and the current staking APR constant for illustration, with
zero funding as captured. On $999.146043 principal plus 10% cash, staking
would add about $1.86 while capital costs $4.52, two perp taker fees cost
$0.62 and stress is $0.50: approximately **-$3.78** before spot execution,
bridges, transfers, basis and rebalancing. Perpetual funding would need to
average approximately **4.60% annualized** just to cover this partial hurdle.
That is a required rate, not a forecast. Funding uses an hourly continuous
rate; no rate-history sum has been presented as actual cashflow.

[Exact sensitivity](cost-sensitivity.json),
[corrected public simulations](../derive-margin-precision-correction/summary.json),
[Derive funding mechanics](https://docs.derive.xyz/perp-funding).

## Verification and resources

All 24 retained raw response hashes reconciled, corrected precision was
checked, and the empty funding history was verified. Arithmetic is Decimal.
This was root-session verification, not an independent-agent audit. The
original preflight reserves 128 KiB and the explicit correction 40 KiB
inside the existing 4 MiB active research pool. Actual P&L is null.
