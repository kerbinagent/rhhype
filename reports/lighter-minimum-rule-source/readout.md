# Minimum sizes depend on order type in the published validator

Official `elliottech/lighter-prover` commit
`28ae613d9c264192e7a36b42f15dda5df3f7103f`, retrieved 1 October 2026. Six
public GETs retained: commit, tree, and four source files. No downloaded
source was executed. Every file's Git blob hash matches the pinned tree.

The [shared validator](https://github.com/elliottech/lighter-prover/blob/28ae613d9c264192e7a36b42f15dda5df3f7103f/circuit/src/types/tx_state.rs#L191-L246)
rejects a below-minimum base or quote amount only when the order is neither
TWAP nor IOC. The maximum quote check still applies. This exemption is based
on order type, not solely on the reduce-only flag. The
[create-order path](https://github.com/elliottech/lighter-prover/blob/28ae613d9c264192e7a36b42f15dda5df3f7103f/circuit/src/transactions/l2_create_order.rs#L580-L609)
passes the IOC flag into that validator; separate checks govern reduce-only
direction.

**Model implication:** applying ordinary resting-order minima to all IOC
hedges/exits can strand simulated small partial fills unnecessarily. A
separate source-consistent scenario should keep maker minima, positive
quantity, lot/price precision, maximum amount, freshness, delay, depth and
partial-fill accounting, while exempting only IOC minimum checks.

This is source-level evidence. The currently deployed circuit, offchain API
admission checks, and equivalence of Core and RH deployments have not been
proven. It is not an execution test or permission to submit an order. Earlier
sealed results stay as originally reported. Applying the exemption to an
already examined capture is an exploratory model sensitivity, not a fresh
validation or evidence of actual profit.
