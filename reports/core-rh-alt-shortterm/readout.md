# Expanded crypto short-term basis experiment

Frozen ten-market universe, $100 primary and $1,000 control per leg, independent portfolios. Sixty-second maximum hold, one-basis-point price take profit, five-basis-point favorable excursion against the prior two-minute median, 400 ms delayed taker model. Each portfolio prefunds six times its per-leg budget across separate wallets. Capture completed its full 900 seconds without transport errors or early size stop.

| Branch | Attempts | Paired closes | Rescue closes | Cash wins | Cash P&L | After capital + 5 bp stress |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| $100 | 6 | 5 | 1 | 1 | −$0.231553 | −$0.530521 |
| $1,000 | 0 | 0 | 0 | 0 | No trades | No trades |

The LIT take-profit round trip earned $0.014838 before the $0.00000815 modeled capital charge, or $0.01482985 after capital. It is a positive hedged paper cash trade, not evidence that this policy is profitable overall. It does not survive the separate five-basis-point stress charge. All other five attempts lost money. No branch trades are pooled; the control found no eligible admission during the fixed entry window.

Trading fees were zero under verified public Standard metadata. No executed inventory interval crossed an hourly funding settlement. All six primary attempts ended flat; five paired normally and one required a losing one-leg rescue. No public exit-minimum violations were observed. USDG/USDC parity and public execution assumptions remain conditional.

The independent audit passed all 22 fills, quantity grids, minima, delayed source clocks, first eligible books among the 187 captured candidate callbacks, cash and wallet identities. The archive retains 9,000 one-second reference rows. It is not a full wire archive; callback completeness relies on the frozen collector. Raw SHA256: ae5720413f3d055ec0c1fbaf922a6b61d2c4c537cf241aaee1a5cd1faf49d097
