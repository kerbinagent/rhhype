# The first liquidation depends on its preceding transaction

Removing the sole preceding transaction made the selected liquidation revert
in the public provider's historical simulation. The target's sender, nonce,
call data, gas limit, fees, access list, parent state and target block context
were otherwise identical to the successful ordered replay.

| Historical simulation | Target status | Target gas used | Target regular logs |
| --- | --- | ---: | ---: |
| Original prefix, then original liquidation | Success; real receipt matched | 790,304 | 30 |
| Original liquidation without prefix | Reverted | 631,437 | 0 |

This supports dependence on the preceding transaction's state changes under
the provider's model. Both variants used the same target timestamp, so merely
advancing from the parent timestamp does not reproduce the successful case.
It does not identify which internal state change or check caused the difference.

The failed call's `returnData` was `0x`. A separate raw `call.error` contained
code 3, message `execution reverted`, and data **`0x57a5829c`**. The projection's
null ABI string refers only to `returnData`; the diagnostic error bytes are
preserved in [the raw response](run-v1/raw/03.body). We have not attributed
that selector to the deployed executor. It differs from the selector
`0x930bb771` derived from Aave's published `HealthFactorNotBelowThreshold()`
error, so calling this a directly decoded health-factor rejection would be
unsupported. [Aave error definitions](https://github.com/aave-dao/aave-v3-origin/blob/main/src/contracts/protocol/libraries/helpers/Errors.sol)

The control was chosen after the positive reproduction, before this control's
outcome. It used five RPCs, finished in 697 ms, and retained 52,596 body bytes
and 59,389 total raw-file bytes. All parent and target header rechecks matched.
An independent decoder verified the exact single deletion from the successful
request, all 20 raw files, all source/input pins and the outcome. Nine offline
tests passed before collection. The simulated gas was not actually spent.

The [positive case](../aave-ordered-replay-v1/readout.md) already showed that
99.8301% of unwrapped ETH went directly to the fee recipient, leaving only
0.000004203244671887 ETH after gas under an unverified sender/executor grouping.
This control explains why an earlier state snapshot alone cannot reproduce
that case. It adds no evidence of our access to the ordering or repeatable
profit. The next material questions are feed/executor attribution and obtainable
ordering with complete account cash, rather than fee tuning on this one trade.

Evidence: [frozen plan](plan.json), [projection](run-v1/projection.json),
[independent reconciliation](root-review.json).
