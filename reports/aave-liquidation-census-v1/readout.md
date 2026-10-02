# Aave liquidation sample: the missing state transition

The fixed 7,200-block Ethereum window returned **three Aave V3 liquidation
events in three transactions, involving two borrowers**. All had LINK
collateral; two repaid USDC and one repaid USDT. All three borrowers had health
factors above 1 at the end of the preceding block. The observations establish
historical cases, but do not yet support a profitable strategy.

| Event block | Transaction index | Preceding-block health factor | Whole transaction fee, ETH |
|---|---:|---:|---:|
| 26,103,141 | 1 | 1.000279249870886769 | 0.000070531199709728 |
| 26,106,270 | 1 | 1.000363658276977087 | 0.000182913681543750 |
| 26,106,490 | 21 | 1.025051001998054214 | 0.007860938120124570 |

These are complete transaction fees, potentially shared with swaps and other
actions. They are not standalone liquidation costs. Neither seized collateral
nor the liquidation bonus is cash profit. Token resale, financing, native ETH
payments, and ownership of any recipient remain to be reconciled.

The window spans blocks 26,100,263–26,107,462, with 86,748 seconds between
its first and last block timestamps. Sixteen disjoint 450-block log queries
all completed. The rule selected the first eight chronological events without
outcome filtering; only three existed, so all three were examined. Their
receipts, historical health calls, linked block headers, and the final anchor
reread were available. The 37-call run took 6.60 seconds and retained 298,608
raw bytes. An independent decoder reproduced every result.

A liquidation requires an unhealthy position under the applicable protocol
rules. A successful event after a healthy preceding-block snapshot therefore
needs an intervening state or context change. These data alone do not show
whether that was an oracle update, borrower action, accrued debt, or another
condition. A plain simulation against the preceding snapshot would omit that
transition. [Aave Pool interface](https://aave.com/docs/aave-v3/smart-contracts/pool)

The next case is the first chronological event, which is transaction 1 in its
block. It has only one preceding transaction. An ordered replay can test
whether those two historical calls reproduce the retained receipts and expose
their native ETH transfers. Ethereum documents that capability through
`eth_simulateV1`; availability on this public endpoint is untested.
[Execution API specification](https://ethereum.github.io/execution-apis/docs/ethsimulatev1-notes/)

This is a provider-reported historical sample, not a complete liquidation
population or proof of future access, execution, inclusion, or closed cash.
The [frozen plan](plan.json), [raw result](run-v1/projection.json), and
[independent reconciliation](root-review.json) preserve the exact scope.
