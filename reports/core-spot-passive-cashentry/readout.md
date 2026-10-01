# LIT cash-forecast entry without a separate excursion hurdle

Protocol frozen at`d82b642`. Fresh public capture **2026-10-01 18:46:52.435287–18:56:53.210209UTC**,600.775seconds,one connection,no errors,13,464records and1,509,180compressed raw bytes. One$600USDC portfolio with$100target per leg. No orders sent.

## Result

**Eight quotes, seven no-fill closes, one partial paired close, and no wins.** Both positions ended flat; no failed hedge, unknown execution, funding payment, or unresolved quote. Seven admissions were below the old5bp hurdle, so the new entry rule was exercised.

| Item | USDC |
|---|---:|
| Spot entry notional | 67.939264 |
| Perp entry notional | 68.061344 |
| Spot cash gain | +0.001744 |
| Perp cash loss | −0.015696 |
| Cash after fees | **−0.013952** |
| Capital charge | 0.000000437309 |
| Separate5bp stress allowance | 0.034030672 |
| After capital and stress | **−0.047983109309** |
| Final actual cash | 599.986047562691 |

Actual entry values satisfy the strict$100per-leg bound. The fill was17.44LIT of a25.62LIT quote; all relevant order minima and quantity grids passed. Recorded Standard fees were zero on all four flows.

## Where the opportunity disappeared

The filled quote entered at2.513bp excursion with a+$0.019969 full-quote cash forecast. It activated behind33.53LIT at the same price. The model requested cancellation when the forecast gate failed; eligible public flow attributed the partial fill104.560ms later, still295.440ms before the modeled cancellation deadline. Cancellation did not make the resting quote disappear immediately.

The hedge completed546.885ms after the spot fill. A later independently reconstructed take-profit mark of **+$0.054711670** requested both exits; they finished498.445ms later with only0.607ms between exit legs. Cash after capital was **−$0.013952437**, a$0.068664107 deterioration from the mark. This is an accounting comparison, not a causal attribution to one venue.

Scaling original forecast components to the filled quantity gives+$0.013595529 gross forecast,−$0.003488 entry-price change, and−$0.024059529 exit-forecast miss, reconciling to−$0.013952 gross cash. This retrospective scaling is not a new smaller-order simulation. All fills occurred within one funding hour.

## Verification and limits

The independent raw-event audit reproduced8admissions,34,202reference rows,310active checks,8queue episodes,1maker flow match,3taker depth walks and1take-profit mark. Boundary checks passed8first-eligible activations and8cancellations; the conservative request bound was10per66seconds.

The original audit stopped on a tuple-versus-list depth-depletion error at its first real taker fill. It remains preserved. Separate audit-only wrapper`e4a1784` normalizes level containers; a complete tuple-shaped synthetic cycle passed before the raw audit rerun passed. Replay summary and fill trace hashes did not change. The repair and original failure are retained in `audit-repair.json`.

Public-flow attribution is conditional on queue, clock and acknowledgment assumptions; no private fills are authenticated. This sample shows a fill under the relaxed entry rule, but no profitable outcome. It uses the separate500ms pair-skew assumption and does not pass as a250ms study.

The next planned asset test is ETH under the same cash rule. Its earlier sealed spot sample contained38ordinary prints, median$143.07 and none below$10, compared with much smaller typical LIT prints. That motivates a prospective asset comparison; it does not establish fill probability or profitability. All evidence, including this loss, is retained.
