# Pendle $100 principal-token investigation: access unresolved

The proposed mechanism is purchase of discounted principal tokens followed by redemption at maturity. It avoids assuming a future exchange buyer for the principal token. The exact accounting asset, underlying redemption restrictions, depeg risk, gas, and conversion cost still matter. This is a different return source from two-perpetual convergence, not evidence that the previous strategy works.

Official documentation states that swap fees scale with time to maturity and that matured PT redemption has no protocol fee, while network gas remains payable. The public SDK can provide preview outputs without a funded wallet; these previews do not establish execution. [Fees](https://docs.pendle.finance/pendle-v2/ProtocolMechanics/Mechanisms/Fees), [API overview](https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview).

The frozen preflight selects Arbitrum and Base for a small-position investigation, retains all active catalogue rows, and requires a complete chain catalogue. The prospective shortlist requires explicit nonvolatile status and 7–90 days to maturity, ranked by distance to 30 days and then liquidity, without ranking yields. Accounting assets must be verified before a quote study.

Both documentation requests returned HTTP 403, preserved separately in `reports/pendle-doc-preflight`. The official repository then supplied the current public catalogue schema. The two distinct catalogue requests also returned HTTP 403, before any market metadata or prices were received. No retry, authenticated endpoint, wallet, order, or transaction was used. The error alone does not identify whether the cause is geographical, network, or server policy.

**Result: unknown, not an economic rejection.** There is no selected market, $100 quote, estimated return, or profit claim. The request manifest and both failures are retained in [terminal.json](terminal.json); no missing result is treated as zero yield.
