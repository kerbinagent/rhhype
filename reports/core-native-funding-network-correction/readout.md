# Native spot/perpetual funding screen

Historical development screen; no executable P&L. Source frozen in `94b0446`, transport correction in `9831a1a`. All six new histories contain exactly720 hourly observations; ETH reused its pinned720-hour history. The first attempt failed DNS for all six requests; its unknown results are preserved separately.

All active native crypto spot/perpetual pairs in the archived catalogue were included. This current-survivor universe does not prove September availability. Fixed long spot/short perp; zero Standard trading-fee scenario,5% annual capital on2x principal,5bp stress. Entry/exit boundary payments excluded. Rates interpreted as percentages from prior cross-checks; changing notional and actual dollar settlement are absent.

| Asset | Sep full month | Week1 | Week2 | Week3 | Week4 | 2-day tail |
|---|---:|---:|---:|---:|---:|---:|
| ETH | -18.59 | -5.68 | -9.72 | -14.29 | -4.38 | -4.91 |
| LIT | -34.27 | -24.13 | -15.01 | +8.52 | -15.45 | -8.13 |
| UNI | +61.71 | -1.57 | -3.32 | +24.15 | +25.82 | -4.84 |
| LINK | -63.82 | -19.27 | -36.61 | -18.46 | -4.61 | -4.97 |
| LDO | +40.39 | -1.87 | -4.14 | -2.64 | +30.35 | -2.12 |
| SKY | +20.62 | -4.16 | -4.14 | -4.17 | +7.03 | +5.57 |
| AAVE | +6.13 | -4.14 | -4.14 | -3.34 | +2.10 | -4.84 |

Numbers are residual basis points, **not dollars or returns**. Full month overlaps the weekly/tail rows. Four monthly positives; all42 rows remain in summary; no aggregate portfolio formed. No asset passes every week. LIT has a positive third week despite a negative month.

UNI/LDO/SKY/AAVE monthly positives are research leads only. Basis, spread, lot sizes, price-dependent dollar funding and collateral remain unresolved. Next justified step: same seven-asset universe with daily spot/perp candles; no winner-only replay.

Verified all7 raw hashes and42 independent timestamp/sign/cost identities. Synthetic checks reject a missing hour and check sign/boundary arithmetic. Retained new raw28968bytes.

Official sources: [funding endpoint](https://apidocs.lighter.xyz/reference/fundings) and [funding payments](https://docs.lighter.xyz/trading/funding).
