# Lower-fee NVDA cycle: incomplete-input quotes

**Twelve unknown complete-cycle outcomes; no validated profit or loss.** The fixed screen finished 43 public reads at 05:17 UTC on 1 October 2026. Both 100- and 1,000-USDG sizes and both v3/v4 directions were retained in all three rounds.

The v3 quoter reached its terminal square-root price limit on every one of the 12 v3 legs. Its output plateaued as the requested input grew. Unlike the standard v4 quoter, the v3 exact-input quote does not itself require the entire requested input to be consumed. A terminal price limit can leave input unspent. If the affected leg is second, stock-token inventory can remain instead of a completed USDG round trip.

The frozen collector subtracted the full requested starting input without measuring such remainders. Therefore the large negative values in its original `surplus_after_pool_fees_before_gas_usdg` field are **conditional arithmetic, not valid complete-cycle losses**. The raw output and original summary are preserved as evidence of this measurement defect. They must not be added to trade P&L or treated as an economic rejection of every smaller executable amount.

## What the check establishes

The nominal 0.01% NVDA pools exist and had positive active-liquidity values, but active liquidity alone did not ensure that the v3 pool could consume these requested amounts across its available ranges. The v3 quoted gas figures reached roughly 19–33 million units while traversing to the terminal price limit. They are quoter simulation costs, not router transaction gas bills.

The [input-completion audit](input-completion-audit.json) checked the archived return values against the two terminal v3 limits. It also checked all earlier samples: none of the 36 Base multihop quotes or 48 original RH stock-token v3 legs reached those limits. The official standard v4 implementation separately verifies that the requested amount is consumed and reverts on insufficient liquidity. These checks support the earlier sampled negative-cycle accounting under the stated official-contract assumptions; transaction eligibility and gas remain unobserved.

**Decision:** this lower-fee $100/$1,000 candidate has not supplied a complete cycle. Any follow-up must verify input consumption and inventory remainders before calculating profit. Preserve all 12 unknowns; do not silently shrink the size or substitute pools in this run.

Source and selection were frozen at a376857 before requests. NVDA was selected from the prior liquidity inventory because it was the only original stock token with active 0.01% pools in both protocol versions. The input-completion correction is a post-outcome quality audit, not a retuned trading rule.

Primary implementations: [v3 QuoterV2](https://github.com/Uniswap/v3-periphery/blob/main/contracts/lens/QuoterV2.sol), [v3 swap loop](https://github.com/Uniswap/v3-core/blob/main/contracts/UniswapV3Pool.sol), and [v4 input-consumption guard](https://github.com/Uniswap/v4-periphery/blob/main/src/base/BaseV4Quoter.sol). All original [quotes](summary.json) and the [public request trace](trace.json.gz) are retained.
