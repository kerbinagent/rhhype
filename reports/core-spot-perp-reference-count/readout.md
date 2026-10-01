# Reference-count comparison — completed prospective result

Frozen9683e08;2026-10-01 16:34:02.172–16:44:02.213 UTC,600.042seconds. Five native Core spot/perpetual pairs, independent$100-per-leg/$600prefunded portfolios. Both use1bp entry limits. Only minimum past reference count differs; freshness, span, embargo and execution checks remain fixed.

**Both portfolios made zero entries and ended flat with unchanged cash.** Count60 improved coverage but produced no passing forecast.

| Gate | Count90 | Count60 |
|---|---:|---:|
| Evaluated directions |4850|4850|
| Clock/skew rejected |175|175|
| Reference warmup |3763|1477|
| Excursion below5bp |897|3155|
| Failed forecast |15|43|
| Passed forecast |0|0|

The raw-storage soft gate closed new admissions after90,000compressed bytes (around410seconds); no otherwise passing forecast was rejected by that gate. No stop or extension depended on economics. All1,625samples and10shutdown invalidations remain in127,003compressed bytes. One healthy connection,29,493messages,14,200,284ingress bytes. Independent source/plan/raw/metadata/reference/cash audit passed; execution checks were vacuous because no fills occurred.

## Spread diagnostic

An offline optimistic bound uses four best prices at retained fresh sample callbacks, no depth impact, no capital charge, and the smallest possible1bp forecast hurdle. Among sampled excursions>=5bp with60references, none had a positive bound. At each asset's best such sample: UNI margin<=−12.02bp with15.00bp spot spread; AAVE<=−9.82bp with11.38bp spot spread; LDO<=−17.60bp with19.08bp spot spread. LINK had no qualifying excursion at the retained eligible samples; SKY had no eligible retained sample in this diagnostic window. This does not cover every engine decision callback or calculate hypothetical realized returns.

Removing a spot crossing cost by using a passive bid could improve that arithmetic; public queue allocation, adverse selection and delayed hedging still need fresh evidence. This motivates a separately frozen passive spot-entry study, not a profitability claim or relaxed execution checks. All previous inactive and interrupted captures remain retained.
