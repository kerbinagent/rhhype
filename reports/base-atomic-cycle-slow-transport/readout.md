# Base atomic USDC/WETH cycles

The fixed public quote screen completed on 1 October 2026 at 04:58 UTC. All 36 pool-fee-inclusive cycles were negative before gas: 18 at $100 and 18 at $1,000. Actual P&L remains unknown; no trade was sent.

| USDC input | Quotes | Positive before gas | Best surplus | Worst surplus |
|---:|---:|---:|---:|---:|
| 100 | 18 | 0 | -0.042124 | -0.525438 |
| 1000 | 18 | 0 | -0.668181 | -5.266913 |

Three fixed rounds covered every ordered pair of distinct 0.01%, 0.05%, and 0.30% Uniswap v3 fee pools. Each cycle starts with USDC, receives WETH in one pool, and returns to USDC through another pool. Distinct pools avoid reusing state reverted by the Quoter. Token decimals, deployed code, pool token identity, and fees were checked. All quotes in each round use one block number, followed by a matching block-hash recheck.

The first attempt stopped on HTTP 429 before any economic quote. It is preserved in [the original failure record](../base-atomic-cycle-screen/readout.md). The separate transport correction was frozen at a21b3e4 and imposed a five-second minimum interval before each read. These are retrospective same-block simulations by the time the sequential requests finish, not simultaneous executable quotes. No quotes were dropped or selected by profitability.

Gas is not subtracted, and the Quoter gas estimate is not a router transaction gas bill. Because every gross cycle is already negative after pool fees, adding a nonnegative gas expense cannot make any of these sampled cycles profitable. This does not establish that all future cycles or other pools are unprofitable. No further sample expansion is justified by this screen.

The independent audit rebuilt all 36 amounts and path fee tiers from RPC calldata and response words, checked block identity and exact Decimal arithmetic, and verified source, plan, and summary hashes. See [audit](audit.json), [all outcomes](summary.json), and [archived request/response trace](trace.json.gz).

Primary references: [Uniswap Base deployments](https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments), [QuoterV2 interface](https://github.com/Uniswap/v3-periphery/blob/main/contracts/interfaces/IQuoterV2.sol), [Circle USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses), and [Base network details](https://docs.base.org/get-started/connect-to-base).
