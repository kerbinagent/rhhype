# ETH spot cash-entry sample: unresolved cancellation

Protocol frozen at`43cfa17`. Fresh public capture **2026-10-01 19:11:41.025209–19:21:41.828669UTC**,600.803seconds,one connection,no errors,11,402records and1,486,651compressed raw bytes. One$600USDC portfolio,$100target per leg; no orders sent.

**One quote, zero attributed fills, zero completed episodes, and an unresolved cancellation.** The recorded ledger has zero inventory and$600cash, but `cancel_confirmation_book_timeout` remains an open execution uncertainty. This is not a validated zero-P&L completed portfolio.

There were **no ordinary live trade updates** on the ETH spot channel. Its only trade frame was the subscription response containing50historical prints; those were excluded. The earlier38-print ETH sample did not predict activity in this new interval.

At19:19:16.787093 the model requested0.0370ETH at2701.80, with1.444bp excursion and+$0.010365723 forecast cash after capital. Activation was first eligible at19:19:17.485545,698.453ms after decision, behind0.5949ETH of better-priced bids and no same-price queue. By activation, the cash forecast had fallen to−$0.000457768, so cancellation was requested immediately, with modeled deadline19:19:17.885545.

The next spot callback arrived19:19:17.985343, but its source timestamp19:19:17.878029 was7.516ms earlier than the deadline and did not qualify. The next eligible annotated callback was19:19:21.883079,3.998seconds after the deadline. The branch had already declared the prescribed timeout at19:19:19.891694. Later public data does not retroactively remove that uncertainty or authenticate a private cancel acknowledgment.

Independent audits passed1admission,151reference rows,1active check,1queue episode and1first-eligible activation. There was no confirmed cancellation or fill to audit. Request bounds passed at2per66seconds. The previously repaired tuple-safe audit was configured from the outset. Capture, original unknown outcome, all audits, trade-channel evidence and cancellation clocks are retained.

The sample used the separate500ms pair-skew assumption,2second age/confirmation bounds,100ms minimum maker delay and400ms cancel/taker delays. It ran at a different time from LIT and does not isolate an asset effect. Passive perp short with contingent spot purchase is being prepared as a separate execution-order hypothesis; this ETH outcome is unchanged.
