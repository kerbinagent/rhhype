# Historical health crossing after the original prefix

The same borrower crossed necessary liquidation eligibility in the paired
simulation at block 26,103,141. Both branches use the parent state and the
target block's timestamp and supported context. The with-prefix branch first
reproduces the original preceding transaction's gas and all receipt logs.

| Measurement | Without prefix | With prefix |
| --- | ---: | ---: |
| Health factor | 1.000279233106508735 | 0.992131850556653093 |
| LINK oracle price, base units / 1e8 | 14.42772000 | 14.31020466 |
| Debt, raw base units | 391768966072 | 391768966072 |
| Liquidation threshold, raw | 7100 | 7100 |

The price change is −0.8145108167%. Health starts 0.0279233107% above one
and ends 0.7868149443% below one. The earlier parent-block health observation
had a different timestamp; this paired comparison holds target time fixed.

At the parent hash, Aave's oracle is
`0x54586be62e3c3580375ae3723c145253060ca0c2` and LINK source is
`0xc7e9b623ed51f033b32ae7f1282b1ad62c28c183`. The source reports LINK/USD,
8 decimals, and aggregator `0x64c67984a458513c6bab23a815916b1b1075cf3a`,
matching the preceding transaction's AnswerUpdated emitter. Parent round
answer equals the without-prefix price; the update answer equals the
with-prefix price.

The post-hoc [nested ABI decoder](interpretation.py) parses the retained
forward call and its `transmitSecondary` payload. All 31 observations are
sorted; median 1431020466 matches the update and post-prefix price. This
matches the interface described in the [Chainlink searcher guide](https://docs.chain.link/data-feeds/svr-feeds/searcher-onboarding-ethereum).
It does not verify historical bytecode identity or establish which auction
carried the transaction. [Derived arithmetic](interpretation.json) is separate
from the frozen projection.

The [previous positive replay](../aave-ordered-replay-v1/readout.md) and
[omission control](../aave-ordered-control-v1/readout.md) establish the same
executor's dependence on this prefix in the provider's model. These new views
show a health crossing, but do not identify the executor's custom error.
Post-prefix oracle wiring was not re-read, and the selected price's exclusive
causal role is unproved. Neither diagnostic sender is an account we control.

Execution competition remains decisive: the prior conditional cash ledger
left only 0.000004203244671887 ETH after direct fee-recipient payment and gas,
under its account-grouping assumptions. This is not verified operator profit.
The next question is whether this exact update was available to searchers
before inclusion; a historical hint match would still not establish our live
latency, winning bid, fills or repeatability.

The fixed run completed 13 requests in 1,475ms, retaining 61,914 response-body
bytes and 82,046 raw-file bytes. All 12 offline tests passed. Exact offline
replay and an independent decoder verified all 10 pins, 52 raw files, request
identities, hashes, call arguments, context and reported measurements. The
independent audit read 262,742 bytes and found no discrepancy.

[Frozen plan](plan.json), [projection](run-v1/projection.json),
[terminal](run-v1/terminal.json), [independent review](root-review.json).
