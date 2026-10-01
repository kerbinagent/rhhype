# Confirmed entries with 1 bp versus 6 bp margins

Frozen `0aa19e6`; 1 October 2026, 13:44:53–13:54:32 UTC. Same ten crypto
assets and independent $100-per-leg / $600-prefunded portfolios. Both arms
required two-second confirmation. One used a 1 bp forecast hurdle and profit
exit; the other required 6 bp for both. All other economics stayed fixed:
400 ms order delays, 10 bp entry limits, 60-second maximum hold, zero fees
conditional on fresh Standard metadata, and separate 5 bp stress reporting.

**Neither arm entered a trade.** The 1 bp arm had six positive forecasts,
all rejected by confirmation; the 6 bp arm had none. Each evaluated 54,708
directions: 8,852 warmup and 244 clock/skew exclusions, 45,292 below-5-bp
excursions. Forecast failures were 314 versus 320. No cash change, fees,
funding, rescues or open obligations. No return estimate or policy-performance
ranking can be obtained from zero trades.

Collection ended at the predeclared 128 MB ingress cap after 578.544 seconds,
not the planned 900. It received 128,002,343 bytes / 185,830 messages using
one continuous connection per venue. The 491,034-byte retained archive has
5,625 reference samples and 20 terminal invalidations. No runtime errors.
The mandatory endpoint was respected without extending or restarting it.

Independent checks passed source/plan/raw/metadata hashes, sample freshness,
spacing and basis values, no missing admission/fill/position records, and
unchanged branch wallets. Fill/forecast-admission checks in the auditor had
zero observations in this run; this does not constitute an execution test.
The pre-run synthetic test separately exercised hurdle differences, required
confirmation, delayed entries and the higher profit-exit threshold.

No orders were submitted. USDG/USDC parity and eventual private execution
remain unverified; idle full-depth books and the complete wire stream were
not retained. The larger-target idea remains unvalidated.
