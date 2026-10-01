# Unchanged Core spot/perpetual replication

Frozen c4dffae before capture. Public read-only run: 2026-10-01 15:55:47.404–16:05:47.434 UTC, 600.030 seconds. The preceding metadata timeout is separately preserved; this retry made one healthy Core connection.

**Zero entries, zero fills, zero profit or loss** in both independent $100-per-leg limit variants (1 bp and 10 bp). Each $600 cash ledger is unchanged and has no inventory. This window provides no additional profitable event.

Each variant evaluated 3,097 directions: 1,557 reference warmup rejects, 119 freshness/skew rejects, 1,411 excursions below 5 bp and ten failed cash forecasts. There were zero forecast passes. Although the unchanged hourly guard remained active, it did not reject an otherwise admissible forecast in this capture.

874 retained reference samples, four shutdown invalidations, 24,581 messages and 15,302,109 ingress bytes; retained raw archive 66,600 bytes. Offline audit passed source/plan/raw/metadata hashes, references, unchanged wallets and zero inventory. Fill and take-profit checks are vacuous because no trades occurred. All data and failed outcomes remain retained.

The preceding LIT event still shows a small positive modeled margin after a 5 bp stress allowance; this inactive replication does not establish repeatability. The follow-up broadens to the five other exact native spot/perpetual matches selected by metadata, with unchanged trading rules.
