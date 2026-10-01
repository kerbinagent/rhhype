# October Fed complete-NO basket quote screen

Frozen source `e547327`. Event606422 has five catalog outcomes, all marked negative-risk, active, accepting orders and nonaugmented. Two full public CLOB snapshots were fetched1.09seconds apart. No real or paper orders.

Both snapshots: best-ask sum **4.009** per five-NO set versus assumed conversion upper bound **4**. A $99.999998884 basket buys24.943876 sets and returns at most$99.775504 under that assumption: **−$0.224494884 before fees/gas**. The smallest admitted five-share set costs$20.045 for assumed$20return, −$0.045. All larger quantities have nonnegative additional depth cost, so no positive quote candidate at any allowed size under$100.

Independent raw audit checked hashes, token/condition mappings and sufficient first-level size. This is a quote screen, not execution P&L. Book timestamps span10.09–11.77seconds and some rare-outcome books were10–12seconds old; these are not synchronized execution samples. Onchain completeness, conversion eligibility/fee, taker fees, gas, and multi-leg execution remain unverified. They cannot turn the displayed negative gross quote into a positive executable trade without different prices.

Three HTTP200 responses,11,910 compressed raw bytes,1.338seconds, no errors. Contract reference: https://github.com/Polymarket/neg-risk-ctf-adapter/blob/main/src/NegRiskAdapter.sol ; current collateral adapter: https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/adapters/NegRiskCtfCollateralAdapter.sol .
