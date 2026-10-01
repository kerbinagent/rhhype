# LIT inside-bid spot entry / native perpetual hedge

Protocol frozen at `b77e161`. Capture 2026-10-01 **17:44:01.080654–17:54:01.923796 UTC**, 600.843 seconds, one connection, no feed errors, 12,243 records and 1,327,080 compressed raw bytes. One independent $600 USDC portfolio, $100 target per leg. No orders were sent.

## Result

Two inside-bid quotes activated; neither received an eligible public sell print before its modeled cancellation. **No attributed fills, no P&L, no capital/funding charge, no unresolved inventory; final cash $600.** This is a completed no-fill result.

The independent main audit passed two admissions, 188 reference rows, two active checks and two queue episodes. The boundary audit passed both first-eligible activations and cancellations; actual entry values were zero. The conservative request-count bound was two per 66 seconds, below both published limits. Fill, exit and cash-reconciliation checks are vacuous where no fills exist.

## Cancellation diagnostic

| Quote | Activation delay | Excursion at activation | Original-price cash forecast at activation | Displayed queue |
|---|---:|---:|---:|---|
| 1 | 196.158 ms | 4.2377 bp | +$0.024568 | 612.28 LIT at better prices; zero at quote |
| 2 | 247.881 ms | 4.3029 bp | +$0.002428 | 613.37 LIT at quote |

Both canceled immediately after activation because excursion fell below 5 bp. The first quote still exceeded the one-cent forecast threshold; the second did not. The independent diagnostic retains the original quote price and quantity and recomputes the forecast on activation books. It does not attribute alternate fills or claim alternate profits.

There were 287 ordinary live LIT prints totaling $4,971.63; subscription backlogs were excluded. No eligible sell prints reached either quote in its original active interval. A longer hypothetical resting interval was not replayed.

## Next prospective hypothesis

Keep the existing 5 bp admission gate, but evaluate an already admitted quote by its actual original-price cash forecast: retain only while forecast after capital is at least $0.01, with unchanged freshness, reference, depth, post-only, five-second resting, first-fill cancellation, ten-second hold and 400 ms cancel/taker rules. This changes active-quote cancellation and requires a fresh capture. No profit is inferred from this diagnostic.

## Limits

Public-flow attribution remains conditional on observed books, displayed queue and assumed delays. It cannot prove private acknowledgments or actual fills. The raw capture, metadata, original protocol, all sources and all outcomes are retained. Replay and audits ran at nice +10.
