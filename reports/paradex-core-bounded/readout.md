# Paradex/Core bounded short-term capture

Frozen plan and source: `8e31c90`. Public-only 900-second BTC/ETH capture; separate $100 and $1,000 per-leg branches. No real orders.

Both branches made **zero attempts**. This is a reference-coverage failure, not evidence of profitable or unprofitable execution. Each branch evaluated 5,020 directions: 1,206 failed timing/skew and 3,814 lacked the required reference. Of 900 one-second samples per asset, BTC had 208 valid and ETH 172. The largest valid count in any trailing 120 seconds was 45/35, below the frozen 90-observation requirement. No entry forecasts reached economic evaluation.

900.044 seconds, 33,725 messages, 21,627,556 ingress bytes, 71,608 retained compressed bytes; one connection per venue, no feed errors or early storage stop. Audit passed source/raw/metadata identity, retained reference accounting and unchanged wallets; there were no fills or funding cashflows to validate. Funding remains an estimated interpolation model; retail zero fees remain conditional on account eligibility.

The fixed one-second sampling clock plus strict 250ms cross-venue skew produced insufficient references. A future collector can sample when a synchronized observation actually arrives, with a minimum one-second spacing and the same freshness requirements. That would require a separately frozen experiment; no completed result is rewritten.
