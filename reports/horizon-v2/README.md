# Completed horizon v2 forecast pilot

The public BBO-plus-depth quote observer ran 18:05:21–18:45:22 UTC on
September 29, with the v2 implementation in 3c293da. It used 12 physical pairs
and 24 directions, with a 12–16-second forward quote window.

## Result

The four models were scored on the same 2,797 anchors. Conditional-linear
closing-spread MAE was 0.927 bp versus persistence 1.094 bp, an improvement
of 0.167 bp (about 15%). It improved descriptive MAE on all 20 scored directed
routes; CASHCAT and XPL had no scored route rows. Most five-minute blocks
improved, except the final partial block with only 18 scored anchors.

This is forecasting accuracy, not a profit or fill result. Quotes can change
quantity between anchor and outcome; the separate
[fixed-original-quantity study](../fixed-markout-v1/README.md) measures fee-inclusive
quote economics and did not validate a profitable strategy.

Of 4,325 anchors, 3,744 matched and 581 were censored. The 22 `other` censures
include pending anchors invalidated at shutdown; do not interpret them as
market disconnects. All 3,744 mature rows are retained, with no export drops.
Opposite directions and nearby outcomes are correlated.

## Evidence and reproduction

[Report](report.md), [JSON](analysis.json), compressed stopped snapshot and plan,
and uncompressed SHA-256 hashes in `evidence-manifest.json` are saved here.

```bash
gzip -dc reports/horizon-v2/horizon_snapshot.json.gz > /tmp/rhhype-horizon-v2.json
.venv/bin/python scripts/analyze_horizon.py /tmp/rhhype-horizon-v2.json \
  --out /tmp/rhhype-horizon-v2-analysis
```
