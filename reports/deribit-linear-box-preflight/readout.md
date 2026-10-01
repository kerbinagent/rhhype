# Deribit linear-box preflight

Complete returned USDC-option catalogue: 3,292 instruments. Three public requests succeeded; no option prices were inspected. Deterministic metadata selection:

| Underlying | Expiry | Strikes | Face per base unit | Minimum base quantity |
|---|---|---|---:|---:|
| ETH | 30 Oct 2026 08:00 UTC | 2,400 / 3,000 | 600 USDC | 0.1 ETH |
| BTC | 30 Oct 2026 08:00 UTC | 75,000 / 93,000 | 18,000 USDC | 0.01 BTC |

All eight selected instruments are open, active, linear USDC-quoted/settled, with contract_size1 and matching price index within each asset. API taker_commission0.0003 agrees with the standard3bp schedule. Extended maximum-commission fields were not returned; use the official documented12.5%premium cap, explicitly a public tier scenario.

Buy lower-strike call and higher-strike put; sell higher-strike call and lower-strike put. Before fees, their joint maturity payoff is the strike difference times base quantity. ITM options settle through a corresponding future into USDC, with no second fee on the generated future. Option delivery fees still depend on terminal index/intrinsic value; the net payoff is not fixed after fees. No execution or margin feasibility has been shown.

Next diagnostic: displayed four-leg prices, zero-delivery/zero-extra-margin optimistic bound plus capital/stress, full individual trading fees. No combo discount applies to separate leg fills. No RFQ or account calls.

[Official linear contract terms](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options), [fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees), [instrument endpoint](https://docs.deribit.com/api-reference/market-data/public-get_instruments). All3raw hashes verified.
