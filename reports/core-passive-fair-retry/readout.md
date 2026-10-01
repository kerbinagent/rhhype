# Exploratory closing-basis maker pricing

Same already observed Core/RH LIT capture, 14:07:04–14:17:04 UTC on
1 October 2026. This is exploratory reuse after fixed-offset outcomes
were seen, not a prospective replication. One independent $100-per-leg,
$400-prefunded portfolio; no real orders.

The quote cap uses current executable RH sell depth and the past median
executable closing spread. References require a 120-second window,
2-second embargo and at least 90 observations spanning 89 seconds.
Quotes must leave a forecast 6 bp margin, and are canceled if that price
cap deteriorates below the resting quote. Existing queue, delay, partial
fill, rescue and funding-boundary rules remain in effect.

There were 97 quotes, 96 no-flow episodes, and one failed-hedge rescue.
That rescue lost $0.013222 cash; capital and the separate 5 bp stress charge
bring the result to −$0.063141680. There were no paired closes, wins,
unknown episodes or remaining inventory. The RH hedge filled zero at its
first eligible book under the fixed 10 bp limit. Core inventory was then
liquidated. The favorable forecast was not secured as a paired entry.

Independent audits passed the maker-flow match, rescue depth walk, cash,
inventory and capital arithmetic, all 97 forecast formulas and quote caps,
and 458 unique reference values reconstructed from original raw depth.
Model-driven cancellations were not independently replayed by the auditor;
their lifecycle is covered by the frozen synthetic tests.

The first attempt stopped at its audit cap. That incomplete run remains
preserved separately. Retry `51376ec` changed only trace compression and
its reserved capacity, retaining every record with continuous lossless gzip;
no economic parameter, market capture or admission window was changed.
Its full audit trace is 84,037 bytes. This negative exploratory result does
not justify treating the forecast margin as executable profit. Public-flow
fills, latency, deployed IOC rules, fees and collateral parity are conditional.
