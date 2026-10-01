# Smaller complete-input NVDA cycles within100USDG

Frozen source/plan `7f67940`; independent audit `fec2f68`. Two0.01%NVDA pools, both ordered cycles, fixed input grid0.01/0.1/1/5/10/25/50/100USDG at one pinned block. Canonical registry/token decimals/v3factory identity and no-hookv4PoolKey verified; final block hash matched.39publicreads, no transactions.

**Seven complete quote cycles, zero positive before gas; nine unknown partial-input cases.** Buying throughv3 hit its terminal input limit at all eight sizes. Buying throughv4 and selling throughv3 fully consumed both legs at0.01through50USDG;100remained partial/unknown.

| Input USDG | Complete-cycle quote surplus before gas |
|---:|---:|
| 0.01 | -0.001012 |
| 0.1 | -0.010114 |
| 1 | -0.101131 |
| 5 | -0.505736 |
| 10 | -1.011684 |
| 25 | -2.530802 |
| 50 | -5.066911 |

Unused starting cash is100minusinput, so final budget is100minusinputplusoutput. No partial-input row is counted as an economic loss. The complete direction loses about10.1%even before gas; smaller size did not uncover a positive quote in this snapshot.

Independent audit decodes raw calldata/output, verifies all16planned route/size combinations, exact first-output/second-input equality, bothv3terminal-boundary checks, same-block hash consistency, and every cash identity. Standard no-hookv4full-input guard remains a deployed-contract assumption. Quotes are not full router transaction simulations; transfer eligibility, gas, approvals and inclusion remain unverified. No actual-profit claim.
