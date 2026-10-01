# Immediate collateral from selected NO baskets

Frozen code/plan `50f20c7`; five public HTTP requests completed 1 October 2026.
No account, order, approval or transaction was submitted.

**All 114 quote rows fail the optimistic immediate-cash screen.** Three
preselected liquid 2028 election events, 19 nested subsets per event, and two
snapshots. At roughly $100 input, the closest result is −$0.799456474 for
20 named Democratic nominee questions. Its NO ask sum is 19.153 against
at most 19 collateral units per equal-sized basket. Even the minimum-size
version loses $0.76541 before fees and gas. All prefix ask sums exceed their
cash return per share, so reducing size cannot make these retained quotes
positive.

The [contract documentation](https://github.com/Polymarket/neg-risk-ctf-adapter/blob/main/docs/NegRiskAdapter.md)
allows converting an m-question NO subset into immediate collateral plus
YES tokens for the other questions. Fees reduce the conversion output.
The [current collateral adapter](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/adapters/NegRiskCtfCollateralAdapter.sol)
wraps returned collateral. We optimistically assign zero conversion fee,
zero CLOB fee and zero gas, and value every leftover YES token at zero.
Thus this is a cash-recovery screen, not a completed round trip or a
resolution-date strategy. It does not test monetizing the leftover tokens.

Augmented event membership need not be complete to express the subset
identity. However, onchain question identity, conversion eligibility,
actual fees and transaction execution were not verified. The independent
audit checks public token/condition mapping, the frozen selection ordering,
all depth walks and Decimal cash arithmetic against hashed raw responses.
It finds zero positive candidates. Book ages span 0.135–74.126 seconds;
these are public displayed quote comparisons, not simultaneous executable
fills. Later adverse/favorable changes were not replayed.

218,664 raw bytes retained. Every failed prefix remains in the compressed
summary. No profitable strategy is established, and these snapshots alone
do not reject other event subsets, leftover-token sales or future quotes.
