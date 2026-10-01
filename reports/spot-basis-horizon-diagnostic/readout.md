# LIT basis forecast horizons on the sealed 500 ms study

Post-outcome diagnostic of the18:26–18:36UTC capture, specified at`ae8564b` and run with the adapter setup correction`a51702a`. This is a basis-price forecast diagnostic, without trade execution or cash P&L. The active cash-entry experiment was already frozen and remains unchanged.

**Coverage is too sparse for a firm horizon conclusion.** Of35preselected origins at10second grid spacing,29matched fresh pairs and6were missing. Future matching produced23,24and26complete pairs at10,30and60seconds respectively. Every origin and missing target is retained. The more widely spaced principal grid had only3,3and1complete observations out of6origins; its estimates are not reliable validation.

| Horizon | All matched origins | Median forecast RMSE | No-change RMSE | Positive-excursion origins | Predicted contraction | Realized contraction |
|---|---:|---:|---:|---:|---:|---:|
| 10s | 23 | 1.619bp | 2.151bp | 17 | 1.341bp | 0.770bp |
| 30s | 24 | 1.464bp | 1.577bp | 18 | 1.348bp | 0.495bp |
| 60s | 26 | 2.083bp | 2.424bp | 18 | 1.420bp | 1.184bp |

RMSE columns use all matched origins. Contraction columns use only the explicit positive-excursion subset, relevant to long spot/short perp. Forecast contraction is current basis minus the past median; realized contraction is current minus future basis. Different horizons have different matched samples. The30/60second samples overlap, and all observations share a market and historical training data. Lower pooled RMSE does not establish profitable entry forecasts; on the30second positive-excursion subset the median forecast actually had worse RMSE than no change.

The10second positive-excursion subset moved in the desired direction12/17times, but average contraction was about0.57bp below forecast. Neither that average nor the gross basis movement includes spreads, fees, delayed fills, adverse selection, or hedge failure. This cannot be converted into expected trading profit or used to select a preferred horizon.

Matching used the first fresh callback at or after each target within250ms, with the study's500ms pair-skew and2second absolute-age bounds. Missing freshness matches were retained, not replaced with later favorable observations. References were sampled from the preceding122–2seconds with at least60observations and89seconds of span. Any generation break invalidated the comparison. The raw manifest and end marker were verified.

The first run failed before raw event iteration because the standalone adapter retained the default market selection. A separately preserved wrapper configured the existing LIT-only adapter; forecast logic, origins, horizons, and original sources stayed unchanged. Diagnostic result SHA256: `ca275837fd353e468f83625187414ef6126df1a430b9f0a8b445ecd4e7b258e7`.
