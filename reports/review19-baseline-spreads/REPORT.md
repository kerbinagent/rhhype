# Review 19 baseline spread decomposition

**Window:** 2026-09-29 22:06:33.116829–22:26:31.021678 UTC, using `settled_at > start` and `settled_at <= end`. **Portfolio:** `shadow_baseline` only. The [review checkpoint](../../data/strategy-reviews/review-20260929T222631.021678Z.json) expects 91 completed trades, and all 91 are retained, exact `CLOSED`, fully paired, and pass independent fill, four-fee, reserve, capital, and net arithmetic checks to $0.0000001 per trade. There are no missing or truncated rows in this completion cohort. One separate aborted trade is outside this closed-trade decomposition.

| USD across 91 trades | Amount | Per trade |
| --- | ---: | ---: |
| Actual entry spread: short sale less long purchase | +100.603025 | +1.105528 |
| Closing liability: short repurchase less long sale | −132.361190 | −1.454519 |
| **Gross price P&L** | **−31.758165** | **−0.348991** |
| Long entry fee | −6.107264 | |
| Short entry fee | −10.228992 | |
| Long exit fee | −6.106731 | |
| Short exit fee | −10.232286 | |
| **All four fees** | **−32.675273** | **−0.359069** |
| Reserve charge | −45.448411 | −0.499433 |
| Capital charge | −0.003240 | −0.000036 |
| Funding | 0 | 0 |
| **Net** | **−109.885089** | **−1.207528** |

For each trade, `gross = (short entry value − long entry value) − (short exit value − long exit value)`; `net = gross − four fees − reserve − capital + funding`. Each exit value and exit fee is reconstructed from the recorded exit fills. The 91 stored net values sum to −$109.885089333513, matching the review's ledger net delta of −$109.885089333515 within rounding.

The signal-book entry spread summed to +$101.659674. Actual entry spread was $1.056649 lower, an aggregate deterioration of $0.011612 per trade; 35 of 91 individual entries deteriorated. Holding the **recorded exits fixed**, the signal entry spread would still be $30.701516 below the closing liability. This is an arithmetic comparison of recorded quotes and exits, not an achievable alternate execution or a causal estimate of latency. The actual gross price result was already negative before fees and reserve: only one trade had positive gross price P&L, and none had positive net P&L. All 91 had a positive actual entry spread, but their later closing liability exceeded it in aggregate.

AVAX contributed 22 trades, −$13.827006 gross and −$44.598047 net; CRCL contributed 32 trades, −$7.461209 gross and −$29.193199 net. Together these two assets account for 54 of 91 trades and −$73.791246 of net loss. This cohort is concentrated and is not 91 independent market experiments.

The review ledger's **fee counter delta** is $32.675245338, $0.000027760 below the $32.675273098 sum of fees on these settled trades. The engine increments its fee counter when fills occur, whereas this cohort is selected by settlement time; component deltas across those two clocks need not match. The per-trade four-fee values and final net reconcile. Reserve and capital component sums match the review deltas within rounding.

## Reproduce

The [frozen evidence](evidence.json.gz) is 50,668 bytes (SHA-256 `ddebefcde231e9ddfa127e7d025e10c5dbfedae94dccd168036d96b3ecb4cdb7`) and contains only this window's 91 trade payloads, config, and review fingerprint. The [machine-readable summary](summary.json) includes route and asset totals and the analyzer source SHA-256 `8e04c49ae409b319c001d6c1ac5d86ecaf17ccf3caf019745a879d2600d4cc34`. Replay without reading the production database:

```bash
.venv/bin/python scripts/analyze_review_spreads.py \
  --sample reports/review19-baseline-spreads/evidence.json.gz
```

The script opens the production SQLite database with `mode=ro`, `query_only`, and a short transaction when making a new freeze. This is paper-model fill arithmetic, not observed private orders or proof that the public-book entries and exits were executable. The config used to recalculate reserve and capital was read from the durable engine checkpoint at 22:31:08 UTC, after the review window; that time is retained in the evidence. Alternative fee portfolios are not pooled here.
