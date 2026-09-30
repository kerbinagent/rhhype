# Retrospective RH/HL rare-spread fixed-anchor feasibility

Completed 0252Z archive only; no independent holdout, matched Core comparison, queue/fill inference, or realized profit. Capital, funding and collateral conversion costs are excluded.

Implementation freeze: 2026-09-30T04:51:27.266755+00:00. One canonical traversal; all 3,000 one-second anchors across five fixed ten-minute strata. Equal-receipt events are applied before evaluation; later events cannot repair an anchor.

Possible observations: 48000; valid: 47624; strictly positive after exact public fees, $0.10 and 5bp stress: 0.

| Asset | Budget | Valid / 3000 | Positive anchors | Uncensored excursions | Start strata | Median net | Max net | Primary recurrence |
|---|---:|---:|---:|---:|---|---:|---:|---|
| BTC | 100 | 2998 | 0 | 0 | [] | -0.23121766 | -0.2197123 | False |
| BTC | 250 | 2998 | 0 | 0 | [] | -0.42884455 | -0.39928075 | False |
| BTC | 500 | 2987 | 0 | 0 | [] | -0.7590019 | -0.6985615 | False |
| BTC | 1000 | 2966 | 0 | 0 | [] | -1.4195736690 | -1.2981206025 | False |
| ETH | 100 | 2999 | 0 | 0 | [] | -0.229004007 | -0.219473739 | False |
| ETH | 250 | 2999 | 0 | 0 | [] | -0.4229027175 | -0.3986843475 | False |
| ETH | 500 | 2998 | 0 | 0 | [] | -0.74605905425 | -0.697368695 | False |
| ETH | 1000 | 2998 | 0 | 0 | [] | -1.3923013125 | -1.29473739 | False |
| NVDA | 100 | 2925 | 0 | 0 | [] | -0.1504317142 | -0.1328753602 | False |
| NVDA | 250 | 2925 | 0 | 0 | [] | -0.2261243995 | -0.1821884005 | False |
| NVDA | 500 | 2925 | 0 | 0 | [] | -0.3527713983 | -0.2644518589 | False |
| NVDA | 1000 | 2925 | 0 | 0 | [] | -0.6268308805 | -0.4289037178 | False |
| XAG | 100 | 2997 | 0 | 0 | [] | -0.1414817233 | -0.1268555377 | False |
| XAG | 250 | 2996 | 0 | 0 | [] | -0.2051930896 | -0.1681481207 | False |
| XAG | 500 | 2996 | 0 | 0 | [] | -0.31213949155 | -0.2364636815 | False |
| XAG | 1000 | 2992 | 0 | 0 | [] | -0.5276837822 | -0.3730948031 | False |

Excursions are separate within each asset and budget. Only a valid nonpositive anchor rearms; gaps bridge runs and do not create independent episodes. Initial positives without a prior valid nonpositive anchor are left censored and excluded from recurrence eligibility. Primary static recurrence requires one asset at $1,000 with >=3 uncensored excursions spanning >=2 fixed strata. Smaller sizes cannot be pooled.

All 48,000 rows, including failures, are in observations.csv; row keys are k/asset/budget. Absolute anchor UTC nanoseconds = 1790736777958514000 + k*1,000,000,000; stratum=floor(k/600). timing.csv provides one source/receipt/generation reference per anchor and asset. summary.json retains five-stratum denominators, exclusion reasons, excursion starts/end anchors, missing bridges and canonical terminal counters.

The required gate uses unchanged q=floor(budget/RHask/commonlot), two RH maker prices, both recorded HL depth walks, own-leg public Standard fees and stress=max(RH bid opening notional, HL sell opening notional)*0.0005. HL snapshots have only five recorded levels; no unrecorded liquidity is imputed. Maker top size does not establish queue capacity or fill odds. Canonical decimal representations do not recover precision discarded by the frozen decoder.

Zero valid positives ends this route-specific feasibility hypothesis. Any positive recurrence only supports further analysis of conditional execution odds; it cannot justify a capture slot or promotion by itself. Dynamic repricing, price drift, queue selection, fill odds and complete public tape are not established.

Manifest records unchanged input/dependency hashes. The input gzip is hashed before/after in addition to one bounded canonical traversal; no raw copy or network call was made. Derived CSV records and all source/metadata/report/manifest files share the 16MB limit.
