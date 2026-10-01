# Robinhood lower-fee pool inventory

The fixed inventory completed 50 public reads at one block, with a matching block-hash recheck. All 16 planned pool/version/fee rows were retained. This is an existence and active-liquidity check, not a quote or profit result.

| Token | v3 0.01% | v4 0.01% | v3 0.05% | v4 0.05% |
|---|---|---|---|---|
| NVDA | Active liquidity | Active liquidity | Active liquidity | Active liquidity |
| AAPL | Absent/uninitialized | Absent/uninitialized | Active liquidity | Initialized; zero active liquidity |
| MSFT | Initialized; zero active liquidity | Absent/uninitialized | Initialized; zero active liquidity | Initialized; zero active liquidity |
| TSLA | Initialized; zero active liquidity | Absent/uninitialized | Active liquidity | Initialized; zero active liquidity |

NVDA has active liquidity in both 0.01% pools, as well as both 0.05% pools. The lower-fee v3/v4 pair is a structurally cheaper candidate than the prior highest-liquidity v3/v4 selection. A separate fixed quote screen can test those two pools without choosing by observed quote profit.

Zero current active liquidity is not proof that every swap is impossible: a swap may cross to another initialized range. Liquidity integers also cannot be compared directly as dollar depth across tokens. No absent or inactive row is labeled an economic loss.

The audit checked the 16 rows against archived onchain responses, reconstructed every v4 PoolKey hash, checked v3 fee/liquidity values and final block identity, and verified the summary hash. Addresses were reused from the immediately preceding verified canonical-token study, as declared before collection. V4 slot0 includes protocol-fee state; any future quoter output includes the actual swap charges, so nominal LP fee is not assumed to be the entire fee.

Frozen source and allocation: db9ecd5. See [all rows](summary.json) and [public trace](trace.json.gz). Primary references: [Uniswap deployments](https://developers.uniswap.org/docs/protocols/v4/deployments) and [StateView implementation](https://github.com/Uniswap/v4-periphery/blob/main/src/lens/StateView.sol).
