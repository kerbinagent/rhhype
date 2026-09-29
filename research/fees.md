# Fee and capital assumptions

As observed 2026-09-29 UTC. These are public tier assumptions, not a user's authenticated fee quote. No staking, referral or volume discounts are assumed. Maker fills/rebates are not assumed.

| Venue / product | Standard taker per execution | Sensitivity / qualification |
|---|---:|---|
| Hyperliquid native perp | 4.5 bp | Tier 0; actual account may pay less. |
| Hyperliquid spot | 7 bp | Tier 0; no token/staking discounts modeled. |
| Hyperliquid HIP-3 | `4.5 × scale × growth` bp | `scale = 1+d` if deployer fee scale `d<1`, else `2d`; `growth=0.1` if explicitly enabled, else 1. Read per-asset settings. Typical sampled xyz equity/index/silver: 0.9 bp; xyz gold: 9 bp. |
| Lighter Core | 0 bp Standard | Plus 0.5 bp; Premium base 2.8 bp. |
| Lighter on Robinhood Chain | 0 bp Standard | Plus 0.5 bp; Premium base **3.5 bp**, different from Core. Applies to tested spot/perp fee scenarios; instrument restrictions and actual account still matter. |
| Aster USDT perp | 4 bp | USD1 contracts have a separate schedule; they are not the sampled contracts. |
| dYdX | 5 bp | Verified public on-chain lowest volume tier, 500 ppm. Account discounts can differ. |
| Robinhood Uniswap pools | Read pool fee | Common tested v3: 5 or 30 bp; common v4: 30 bp; COIN v4: 100 bp. Quoter amounts already include this fee and price impact: **do not deduct pool fees twice**. |

Sources: [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Core Lighter fees](https://docs.lighter.xyz/trading/trading-fees), [Robinhood Lighter account types](https://apidocs.rh.lighter.xyz/docs/account-types), [Aster fees](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees), [dYdX on-chain fee tiers](https://dydx-ops-rest.kingnodes.com/dydxprotocol/v4/feetiers/perpetual_fee_params). Archived per-asset Hyperliquid metadata and read-only Uniswap contract calls supply market settings.

For equal economic quantity `q`, let `B` be total buy cost through the ask book and `S` total proceeds through the bid book. Opening-price edge after trading fees, in basis points of buy notional:

`10,000 × (S − B − B × f_buy − S × f_sell) / B`.

Perp entry prices create positions; this number is not received cash profit. For an eventual unwind, also sell the long at its future bid, buy back the short at its future ask, and charge both closing fees on their own notionals. The observed 5/10/15-minute unwind scenarios do this and avoid crossing funding boundaries where funding would be unknown. Scenarios overlap and must never be added as portfolio profits.

Historical analysis includes actual timestamped signed funding events. Funding dollars are estimated using the preceding closed-hour price because exact event-time oracle/index prices were not collected; they are not ledger cash flows. The final ten-day model charges each entry and exit price its own fee rather than using a flat opening notional. Historic account fee settings may differ from today's schedule; this is a current-fee counterfactual, not reconstructed realized P&L.

Additional explicit sensitivities:

- Live CLOB results subtract another 5 or 10 bp for nontrading costs/adverse movement. Premium results change only Lighter's fee, preserving all other assumptions; Plus costs lie between Standard and Premium.
- Robinhood AMM results show $1 gas and $5 total-cost scenarios. These are assumed budgets, not measured total transaction fees. The RPC gas price alone does not determine a full swap/bridge cost.
- USDC/USDT/USDG are assumed at dollar parity in the base model. A 10 bp relative depeg can erase an apparent 10 bp spread. Pair conversion direction matters. No guaranteed cross-chain stablecoin conversion quote is assumed.
- The historical capital example uses 5% annual opportunity cost on 40% combined collateral for two perps, or 120% for fully funded spot plus perp margin. Over 10 days this costs 5.48 bp and 16.44 bp of matched notional, respectively. These are illustrative capital budgets, not maximum leverage recommendations or measured borrowing rates.
- Reverse spot/perp trades require pre-owned spot inventory or a verified borrow facility and borrow fee. No free stock-token shorting is assumed. Eligible redemption after the promotional period can add an issuer fee and delay; no instant open primary-market conversion is modeled.

Future funding, withdrawal/redemption charges, bridging costs, and close-out liquidity cannot be locked from this dataset. Profits must be reported after those terms are established for an implementable strategy.
