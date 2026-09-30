# Offline batch-cost sensitivity

[scenario-groups.csv](scenario-groups.csv) contains 1,152 scenario groups: 4 assets × 4 sizes × 2 RH directions × 2 hedge venues × 2 quote stages × 9 hypothetical batch-cost cases. The [source hash and assumptions](summary.json) tie this table to the stopped [matched quote rows](../passive-hedge-venues/matched-rows.csv). Run `python scripts/analyze_passive_cost_buffer.py` to reproduce it. No route was quoted or executed. The [research note](../../research/passive-cost-buffer-followup.md) explains the calculation and its limits.
