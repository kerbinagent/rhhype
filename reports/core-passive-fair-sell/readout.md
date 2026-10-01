# Fair-value maker sell — exploratory replay

Frozen runner and auditors: 01c9180. Same completed LIT input used for earlier maker tests; no fresh or independent sample claim. The strategy quotes Core asks against RH buys, setting its floor from a past-only 120-second closing-basis median, 2-second embargo, 90 observations over at least 89 seconds, fees, capital and a 6 bp forecast margin. Current planned maker and hedge values each fit $100. Cash-only take-profit threshold is $0.06; the separate 5 bp stress is reported only.

**96 quotes, 96 no-flow episodes, zero fills, zero profit or loss.** No hedge, rescue, unknown or remaining position. The tighter fair-price rule avoided the earlier losing maker executions but did not demonstrate an executable profit opportunity in this capture.

The independent reference audit passed 461 raw reference values and all 96 quote floors, including source freshness/skew, historical timing, median, quantity iteration, price rounding, budget and forecast. The fill/cash audit passed with zero fills (execution checks are vacuous). Model-driven cancellation decisions were not separately reconstructed from raw books; synthetic tests cover the raised-floor cancel. Public queue and private fill/ACK assumptions remain unverified.

No parameter sweep or further replay of this input is justified by this result. The positive prospective same-venue spot/perpetual event and its fresh replication are the current research priority.
