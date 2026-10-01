# Core spot/perp arrival-sampled trial

Frozen source/plan `488f880`;600-second public-only follow-up. Separate $100/$1,000 per-leg portfolios each start with6×budget cash. Collect synchronized observations on arrival, at least1second apart, preserving the prior freshness, median-history,5bp excursion,1bp forecast hurdle and1bp entry-limit rules. No real orders.

## Result

- **$100:** one attempt, **one failed-hedge unwind**, zero paired closes. Buy25.36LIT spot at$99.601400; perp short rejected by its price limit. Sell spot for$99.507568. Cash P&L **−$0.093832**; capital charge$0.000000078088769; after capital and separate5bp stress **−$0.1436327781**. Zero wins, no pending inventory, no below-minimum exit.
- **$1,000:** no attempts. Two positive forecasts occurred after the fixed admission window closed.
- $100 had four forecast passes total; three were after admission closed. No replay or hindsight change to the deadline.

## Coverage and audit

Arrival sampling captured481LIT and322ETH observations; maximum trailing120-second counts108 and89. This cured the LIT reference-coverage failure; ETH still did not satisfy the90-observation rule. There were23,565 messages,13,542,875 ingress bytes and67,680 compressed retained bytes, one healthy connection, no early stop.

Offline audit passed both actual modeled fills, first eligible retained callbacks, price limits, public lot/minima, spot cash/inventory identity, all retained reference samples and admission history, hashes, and unchanged$1,000 wallet. Cash, not generic derivative P&L alone, was independently reconciled. Full wire stream is not archived; candidate completeness depends on the frozen callback capture. Funding was zero because the sole inventory interval crossed no settlement.

The tight limit prevented the perp entry while leaving spot exposure; the rescue lost9.38c. This does not show a profitable same-venue policy. It motivates testing tight versus wider entry limits on the same future feed rather than inferring that smaller limits necessarily improve results.
