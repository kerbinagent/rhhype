# Paradex public schema preflight

Completed 12 public reads with 0 errors after retaining the original 12 sandbox DNS failures. BTC/ETH/SOL metadata confirms zero interactive maker/taker fees, USDC settlement, and explicit lot/minimum/maximum rules. Ordinary API metadata gives 2bp taker while official general documentation gives 4.5bp base: use the higher rate in a Pro control until resolved.

Only 3 of 9 public books had source timestamps within 2 seconds of receipt. RTT was 0.61–0.68 seconds. Stale books cannot qualify as fresh executions under the current research gate; polling faster does not change their source age. SOL returned 14 asks; requested depth is a maximum, and all returned levels are preserved. Paradex funding accrues continuously by funding-index delta, even for short holds. No trades or profit estimates made in this preflight.

Sources: [order classification](https://docs.paradex.trade/trading/trader-profiles), [fees](https://docs.paradex.trade/trading/trading-fees), [funding mechanism](https://docs.paradex.trade/risk/funding-mechanism).
