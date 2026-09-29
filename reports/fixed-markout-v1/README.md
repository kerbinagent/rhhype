# Fixed-original-quantity study, completed September 29

Public quote observation ran 18:23:22–18:43:22 UTC, from observer commit
93dfc86. It covered 12 pairs / 24 directions across crypto, equities and silver.
The full stopped snapshot and frozen market/fee plan are compressed here;
`evidence-manifest.json` gives their uncompressed SHA-256 hashes.

## Result and decision

2,134 anchors produced 1,595 usable same-quantity future quotes and 539 missing
outcomes, mostly insufficient exit depth (493). Exactly one matched quote was
positive after four Standard trading fees, and none after the separately
modeled 5 bp reserve and elapsed capital cost. Mean matched four-fee outcome
was about -$0.87 per roughly $1,000 paired notional.

The primary conditional-linear screen selected zero trades. The secondary
historical-median screen selected five anchors above $0: four outcomes were
observed, all negative; one was missing. The >$0.25 subset contained one
observed outcome, also negative. These overlapping subsets are not independent.
No strategy is promoted from this sample. The zero-entry-latency quote screen
already fails economically on the measured sample, before actual entry/exit
fill uncertainty. Missing outcomes are not classified as profits or losses.

[Full report](final.md) and [machine-readable distributions](final.json) separate
all-anchor coverage, warmup/scored anchors, all four models, and route/time groups.
The primary forecast's smaller error does not establish positive expected P&L.

## Reproduce

```bash
gzip -dc reports/fixed-markout-v1/fixed_markout_snapshot.json.gz > /tmp/rhhype-fixed-snapshot.json
.venv/bin/python scripts/analyze_fixed_markout.py \
  --snapshot /tmp/rhhype-fixed-snapshot.json \
  --out /tmp/rhhype-fixed-analysis --name final
```

The observer assumed four frozen Standard taker fees and stablecoin parity.
It did not send orders, simulate acknowledged fills, or measure funding,
conversion, or future market impact. Retained coverage is complete for this
finite run; no terminal rows were dropped.
