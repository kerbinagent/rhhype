# First Aave liquidation: most proceeds went to the fee recipient

The first chronological liquidation in the fixed census was reproduced by
replaying it after its sole preceding transaction. Both calls matched their
real receipts: **187,112 and 790,304 gas**, with **4 and 30 regular logs**,
respectively. The public endpoint accepted `eth_simulateV1` with validation
enabled, original transaction arguments and original block context.

The liquidation's simulated native transfers show the executor unwrapping
WETH and paying almost all of it directly to the block's fee recipient.
Assuming the transaction sender and executor share economic control:

| Component | ETH |
| --- | ---: |
| Native ETH received from WETH withdrawal | 0.043990496433453504 |
| Direct payment to block fee recipient | −0.043915761989071889 |
| Target transaction gas fee | −0.000070531199709728 |
| Conditional remainder | **0.000004203244671887** |

The direct payment alone consumed **99.8301%** of the unwrapped ETH. This is
a payment to the recorded block fee recipient; the data do not identify its
commercial arrangement or who ultimately benefits. Gas is deducted once:
the API's synthetic native-transfer logs exclude gas payments.
[Execution API notes](https://ethereum.github.io/execution-apis/docs/ethsimulatev1-notes/)

The generic Transfer-event projection shows 0.043990496433453504 WETH entering
the executor. Its real receipt also contains a `Withdrawal` for precisely
that amount. WETH9 withdrawal reduces the token balance and emits Withdrawal
without emitting a corresponding Transfer burn. Treating that incoming
Transfer as residual WETH would double-count the proceeds. After this separate
reconciliation, the selected group's LINK, USDC and WETH event deltas are all
zero. These remain event-derived deltas; account balances were not separately
queried. [Canonical WETH9 source](https://github.com/gnosis/canonical-weth/blob/master/contracts/WETH9.sol)

The preceding call emits an `AnswerUpdated(int256,uint256,uint256)`-shaped
event from `0x64c67984a458513c6bab23a815916b1b1075cf3a`, with raw answer
1,431,020,466 and round 17,262. This supplies a concrete state-transition lead.
The current experiment does not establish the feed's relationship to the
borrower or isolate the effect of that update. A separate control can replay
the same liquidation without the preceding transaction at the same timestamp.

The completed [same-event control](../aave-ordered-control-v1/readout.md) now
shows that removing only the preceding transaction causes a revert. This
supports dependence on that transaction under the provider's model; the
specific internal cause remains unidentified.

The eight-request run finished in 986 ms, retained 94,128 response-body bytes
and 109,142 framed bytes, and passed exact offline replay. An independent
decoder checked all requests, source/input pins, block context, both complete
regular-log sequences, gas and native arithmetic without importing the runner.
The positive reproduction used no state or balance overrides.

This is one historical case, selected before viewing its proceeds. It does
not demonstrate that we control either account, can obtain the same ordering,
or can repeat the trade. Private costs and intermediate state equivalence
remain unknown. The tiny conditional remainder is not verified operator
profit or a deployable strategy.

Evidence: [frozen plan](plan.json), [simulation projection](run-v1/projection.json),
[post-run unwrap reconciliation](reconciliation.json),
[independent review](root-review.json). The unwrap interpretation is explicitly
post-run analysis and does not modify the frozen collector or raw results.
