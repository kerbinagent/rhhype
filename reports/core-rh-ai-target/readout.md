# AI: confirmed 1 bp versus 6 bp target

Frozen at `bb41a59`; public observation ran the full 900.032 seconds on
1 October 2026, 14:22:12–14:37:12 UTC. Two independent $100-per-leg,
$600-prefunded portfolios used the same two-second confirmation and
60-second maximum hold, differing only in the 1 bp versus 6 bp forecast
and take-profit thresholds. No actual orders were submitted.

Both arms had zero entries, exits, P&L or remaining obligations. Each
examined 1,132 directions: 1,112 failed reference warmup and 20 failed
freshness/skew. Neither arm reached a forecast decision. The retained
249 valid paired samples were too sparse to provide 90 observations
within the required recent window. This is a data-eligibility result;
it provides no evidence about profitable or unprofitable execution.

One connection per venue, 2,278 messages, 1,680,188 ingress bytes;
251 archived records occupy 16,618 compressed bytes. The two recorded
invalidations are terminal disconnects. The independent audit passed
source, metadata and raw hashes, observed samples, and unchanged wallet
identities. Admission and fill checks had zero observations and therefore
do not validate execution behavior in this run. Full idle wire books were
not retained, as declared before collection.

The prior all-market funding screen motivated exploratory selection of AI.
This price-basis study assumed no future funding credit. Same-symbol/index
compatibility and USDG/USDC parity remain conditional.
