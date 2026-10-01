# Hyperliquid portfolio margin: September funding budget

## Result

The fixed 28-day screen leaves **5.5523 basis points for HYPE and 1.9894 basis points for BTC** after the assumed capital charge, ordinary trading fees, and stress allowance. These are funding-rate budgets before borrowing, basis changes, and spreads. Actual profit is unknown. All eight weekly rows are negative under the same opening and closing fee assumptions.

| Asset | Full-period funding, bp | Residual, bp | Weekly residuals, bp |
| --- | ---: | ---: | --- |
| HYPE | 71.9085 | +5.5523 | −20.1008, −29.0997, −10.4592, −18.8538 |
| BTC | 68.3456 | +1.9894 | −20.0374, −26.2530, −15.8894, −19.9903 |

The full period overlaps the four weeks; these are not five independent observations. Weekly rows assume a separate round trip each week. They should not be added to reproduce the monthly result.

## Frozen method and checks

Source and allocation were committed in `9246c83` before the offline calculation. HYPE was the primary asset and BTC the control. The window is September 1–28, 2026, inclusive. All 744 archived hourly funding buckets per asset must be present and unique; reported timestamps may lag the nominal hour by at most one second. Entry and exit boundary payments are excluded, giving 671 payments for the full period and 167 per week.

The optimistic model commits capital equal to spot principal, charges 5% annual opportunity cost, 23 bp for two ordinary spot taker fills and two perpetual taker fills, and 5 bp stress. Borrowing is set to zero. Funding rates are summed without reconstructing a fixed-quantity cashflow or changing oracle prices. No staking income is included.

An independent Decimal recalculation checked all ten payment counts, funding sums, and residual identities. All four archived input hashes match the frozen plan. No new market requests were made. Full results, including every negative row, are in [summary.json](summary.json).

## Eligibility and borrowing matter

Current documentation lists HYPE and BTC collateral loan-to-value ratios of 0.65 and 0.50. Portfolio margin requires account value above $10,000 or more than $5 million of weighted master-account volume, and account value below $25 million. A hypothetical $1,000 position does not establish access. Any later analysis must charge for all capital required to meet the access gate. Supply and borrowing caps can also require additional funded margin. [Portfolio margin documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-margin).

The documented stablecoin borrowing APY starts at 5% and increases above 80% utilization. For scale only, a constant loan equal to 10% of spot principal charged at 5% simple annual interest costs 3.8356 bp over 28 days. Subtracting that illustrative amount leaves HYPE 1.7167 bp and BTC −1.8462 bp. The actual loan balance and interest index are path dependent; this illustration is not a borrowing forecast or an exact implementation of the documented compounding.

Ordinary tier-zero taker fees used here are 7 bp per spot fill and 4.5 bp per perpetual fill. Discounts and deployer-specific changes are not assumed. [Fee documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees).

## Decision

No expanded collector is justified by this screen. The optimistic residual is too small to establish a useful advantage before material omitted costs and eligibility requirements. This is historical development evidence, not validation or an executable profit claim.
