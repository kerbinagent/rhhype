# Robinhood Chain stock-token atomic cycles

The fixed public screen completed on 1 October 2026 at 05:06 UTC. **All 48 complete quoted cycles were negative after embedded pool fees and before gas.** No order, wallet transaction, or signature was used.

| Stock token | Input USDG | Valid cycles | Positive before gas | Best surplus, USDG | Worst surplus, USDG |
|---|---:|---:|---:|---:|---:|
| NVDA | 100 | 6 | 0 | -0.087617 | -0.713623 |
| NVDA | 1000 | 6 | 0 | -1.001515 | -7.260372 |
| AAPL | 100 | 6 | 0 | -0.093452 | -0.708077 |
| AAPL | 1000 | 6 | 0 | -1.070980 | -7.224626 |
| MSFT | 100 | 6 | 0 | -0.588207 | -0.715061 |
| MSFT | 1000 | 6 | 0 | -6.134649 | -7.402517 |
| TSLA | 100 | 6 | 0 | -0.596784 | -0.705501 |
| TSLA | 1000 | 6 | 0 | -6.175448 | -7.262471 |

NVDA at 100 USDG was the primary candidate. The other three tokens and 1,000-USDG size were controls. Each group contains three fixed rounds and both v3-to-v4 and v4-to-v3 directions. The best 100-USDG result was NVDA, buying through v4 and selling through v3, with a 0.087617-USDG loss.

The pool universe was taken from the earlier frozen four-token screen: one v3 and one v4 pool per token, originally chosen by archived indexed liquidity. This run refreshed the canonical token registry, active status, token addresses, decimals, contract deployment and pool identity. V3 fees were 0.05% for NVDA/AAPL and 0.30% for MSFT/TSLA; all four selected v4 pools were 0.30% with no hook. The quoted outputs include the contract swap charges; no extra fee was deducted from them.

Each cycle passes the exact raw stock-token output of the first simulated swap into the second swap. Both use the same block number and different pool state, followed by a block-hash recheck. It starts and ends in USDG, so there is no perpetual hedge, contract multiplier conversion, or maturity holding period. The separate quoter calls are consistent same-block arithmetic, not an executed combined router transaction. Sequential quotes are historical simulations by the time collection completes.

Gas, first-use approvals, transfer eligibility, router execution, and inclusion remain unresolved. They cannot rescue the already negative gross cycles sampled here. USDG is reported in its own units; dollar redemption or parity is not an observed cashflow. These results cover the selected pools and blocks, not every pool or future opportunity.

The audit independently decoded all 96 quote inputs and outputs, including token direction, fee, exact amount linkage, block tags and rechecked hashes, and verified source/plan/input/summary hashes. See [audit](audit.json), [all 48 outcomes](summary.json), and [archived public responses](trace.json.gz). Source and the fixed plan were committed at 10d0d5a before the 151 public reads. No error or quote was discarded.

**Decision:** these sampled complete cycles fail the necessary pre-gas profitability condition. No execution or gas-optimization follow-up is warranted for this version.

Primary references: [Robinhood network](https://docs.robinhood.com/chain/add-network-to-wallet/), [canonical stock-token API](https://docs.robinhood.com/chain/stock-token-apis/), [Uniswap v4 deployments](https://developers.uniswap.org/docs/protocols/v4/deployments), and [v4 quote interface](https://github.com/Uniswap/v4-periphery/blob/main/src/interfaces/IV4Quoter.sol). The previously cited v3 deployment page was unavailable through the browser during this follow-up; the plan discloses this and retains prior provenance plus fresh onchain factory/pool checks.
