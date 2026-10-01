# Core/Paradex short-term basis, arrival-sampled reference

Frozen `f3e5d8d`, 900 seconds on 1 October 2026, approximately 12:46–13:01 UTC.
BTC, ETH and SOL; independent $100/$1,000-per-leg paper branches with $600/
$6,000 prefunded total. Zero actual orders. **Zero paper entries in both branches.**

The reference now samples eligible synchronized book arrivals, at most once
per second per asset. The previous fixed-clock collector never formed a
valid reference. Here, BTC retained 528 samples and ETH 558, with maximum
93 and 101 observations in a 120-second reference window. SOL retained 386,
maximum 72, below the frozen 90-observation requirement. These maxima are
descriptive across the archive; invalidations clear the engine's history.

Each branch evaluated 9,684 directions: 6,650 failed reference warmup and
1,896 failed freshness/skew. At $100, 1,133 excursions were below 5 bp;
the remaining five failed the forecast-profit gate after spreads, modeled
capital and the 1 bp target. At $1,000, 1,123 were below 5 bp, five failed
forecast profit, five lacked exit depth and five lacked entry size/depth.
There were no profitable forecast admissions, fills, funding allocations,
open positions or below-minimum exits. Zero ledger change is inactivity,
not an estimate of a trading strategy's expected profit.

Core reconnected once. Nine retained invalidation records include terminal
feed shutdown; they were not dropped or treated as unchanged books. The
collector processed 52,644 messages / 37,631,091 ingress bytes, retaining
138,275 compressed bytes: 1,472 reference samples, 540 funding-index rows
and nine invalidations. It completed without a terminal error.

The independent audit verified source/plan/metadata/raw hashes and all
retained reference provenance. No fills means execution and funding
reconciliation checks were vacuous. Paradex zero-fee interactive eligibility,
400 ms assumed order delay, continuous funding interpolation, and eventual
conversion/account access remain conditional. This sample supplies no trade
P&L or justification for loosening the predefined signal gate.
