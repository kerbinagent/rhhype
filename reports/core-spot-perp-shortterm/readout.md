# Core spot/perp short-term capture

Frozen source/plan `8d2ed91`; public-only 600.013-second ETH/LIT trial. Separate $100/$1,000 per-leg branches, cash-funded spot buys and matching perp shorts, 400ms delayed execution and 1bp entry limits.

**Neither branch attempted a trade.** Each evaluated 1,859 directions: 75 rejected on timing/skew, 1,784 on reference warmup. LIT had293/600 synchronized one-second samples and ETH96/600. Maximum valid samples in a rolling120seconds were73 and31; the frozen model required90. Thus no economic forecast was evaluated. Zero P&L is an inactive result, not an execution profitability result.

19,379 messages,10,376,773 ingress bytes,43,458 compressed retained bytes, one Core connection, no errors or cap stop. Audit passed frozen hashes and unchanged cash/inventory; no fills to validate. A separately frozen follow-up will collect samples when synchronized books are available, spaced at least one second apart, instead of polling only at fixed one-second instants. Thresholds and execution rules stay frozen per experiment.
