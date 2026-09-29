# RH passive bids with Hyperliquid hedges

**Status:** collecting public data. No profit result is available yet.
Started 29 September 2026 at 21:21:32 UTC. Thirty minutes of calibration
precede the 20-minute evaluation window, ending about 22:11:32 UTC.

The user's size range is **$100/$250/$500/$1,000**, with **$1,000 primary**.
BTC, ETH, NVDA and silver have separate Standard and Premium scenarios.
Each compares conditional hedge pricing, a persistence diagnostic, and
joining the RH best bid. Portfolios reuse public events and cannot be added.

- [Frozen method](method.md), committed before collection in **9054b25**.
- [Capture/source freeze](capture-freeze.json) and [verified launch](launch.json).
- [Public raw metadata and grids](metadata/normalized.json).
- [Standard policy inputs](policy-metadata-standard.json),
  [Premium policy inputs](policy-metadata-premium.json), and
  [explicit assumptions](assumptions.json).
- [Strategy rationale and sources](../../research/sota-strategy-review.md).

The raw capture at `data/raw/rh-small-maker/20260929T212132Z` is capped at
384 MB including metadata. The offline replay allows 96 MB of compressed
audit records plus 32 MB of results. It writes no reconstructed full-book
copy. Both the elapsed time and storage are bounded. Existing production
paper monitoring remains separate.

After a terminal capture manifest exists, reproduce with:

```bash
.venv/bin/python scripts/analyze_rh_maker.py \
  --capture data/raw/rh-small-maker/20260929T212132Z \
  --out data/derived/rh-small-maker-v1
```

Output must be a new directory. The coordinator verifies frozen metadata
and raw hashes, uses the fixed chronological split, reports all 96 branch
outcomes and keeps open obligations unknown. It never sends orders.
Lifecycle implementation and tests must be frozen before the holdout starts;
the method was fixed before capture. Test fixtures use synthetic data.

These are public-flow counterfactuals under stated timing assumptions.
They do not establish private queue position, actual fills, or executable
USDG–USDC conversion. The ten-second rule is an **exit request deadline**;
later partial executions and unresolved obligations remain visible.
Any combined dollar result is conditional on collateral parity. One short
holdout cannot establish durable profitability or justify production promotion.
