# Public-document follow-up, 30 September 2026 12:47 UTC

Bounded source-only follow-up after launch; no API requests, quotes, private
calls, orders, frozen-source edits or interim economics. No uncertainty resolved.

The [spot specification](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments)
confirms gross order amounts, routing and fees. Its purchase example omits fees,
so it does not establish net BTC received or the fee debit currency. The
[trade schema](https://docs.deribit.com/api-reference/trading/private-buy)
exposes fee and fee_currency per fill; no private call was made.

The [fee page](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees)
contains weekly-futures exemption language alongside the USDC BTC/ETH futures
2.5 bp delivery rate. [Settlement guidance](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement)
says weekly futures are typically exempt. The
[linear futures specification](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures)
discusses fee reduction/netting with option-generated positions but does not
uniquely settle this standalone weekly contract's exemption. The August trading
fee changes do not unambiguously amend delivery charges.

Retain the frozen 2.5 bp delivery proxy and actual-fee/net-inventory unknowns.
This supplement does not alter the collector, evaluator, thresholds or freeze.
