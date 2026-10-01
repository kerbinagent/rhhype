# Deribit USDC option boxes: displayed four-leg route fails

Three fixed30-second rounds, ETHprimary/BTCcontrol, fourcashbudgets; all24 outcomes retained.21eligible price bounds are negative before any fees. ThreeBTC$100rows are below minimum quantity and remain unknown/unavailable, not zero profit. The records are displayed prices, not trades.

| Underlying / budget | Base quantity | Face USDC | Gross deficit range | Optimistic residual range* |
|---|---:|---:|---:|---:|
| ETH / $100 | 0.1 | 60.00 | $-2.32 to $-2.30 | $-2.92 to $-2.90 |
| ETH / $250 | 0.3 | 180.00 | $-6.96 to $-6.90 | $-8.77 to $-8.71 |
| ETH / $500 | 0.7 | 420.00 | $-16.24 to $-16.10 | $-20.47 to $-20.33 |
| ETH / $1000 | 1.5 | 900.00 | $-34.80 to $-34.50 | $-43.86 to $-43.55 |
| BTC / $100 | Below minimum | — | Unknown | Unknown |
| BTC / $250 | 0.01 | 180.00 | $-5.10 to $-5.10 | $-6.94 to $-6.94 |
| BTC / $500 | 0.02 | 360.00 | $-10.20 to $-10.20 | $-13.88 to $-13.88 |
| BTC / $1000 | 0.05 | 900.00 | $-25.50 to $-25.50 | $-34.69 to $-34.69 |

*Full ordinary four-leg entry fees,5%annual capital cost on minimum net debit+fees,5bpface stress; zero deliveryfee andzeroextra margincapital, deliberately optimistic. Extra margin, peak executioncash, deliverycosts andactualfills are unresolved. All computed minimum netdebit+fees fit their cashbudgets, which does not establish margin feasibility. No combo discount is applied to separate fills.

Gross payoff equals strike width times basequantity for contracts held through common settlement. Linear option delivery into a future does not add a second fee on that generated future; optiondeliveryfees remain terminalprice-dependent. The unconditionally fixedgrosspayoff is not a fixednetprofit.

The large adverse displayed box pricing alone rejects this sampled four-leg route; no expanded collector or execution study follows. An atomiccombo is a different order book and was not observed, so this screen is not evidence about its price or feasibility.

Sourcefreeze `a7406c0`. Rechecked3raw archive hashes and21depth/fee/net identities, preserving3belowminimum cases. The previously frozen payoff/fee/depth synthetic checks passed.

[Metadata and contract documentation](../deribit-linear-box-preflight/readout.md).
