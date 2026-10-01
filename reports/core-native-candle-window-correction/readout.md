# Native spot/perpetual candle proxies

September historical development, not executable or realized P&L. All seven assets and all six fixed intervals are retained; the full month overlaps the four weekly blocks and two-day tail. Source freeze `c61bf22`; offline leading-date correction `719660f`.

The initial strict validator rejected six assets because the API returned August31 plus all30September dates. The original results and12raw responses remain intact. The separately frozen offline correction removed exactly August31; no in-window row was removed and no new request was made.

Fixed ~$1,000 spot and equal cash reserve, same-quantity short, shared archived lot grid and minima. Inferred funding-value cashflows exclude both boundary payments. Zero Standard trading fees;5% annual cost on twice principal plus5bp stress. No margin-solvency or historical listing/rule claim.

| Asset | Funding proxy | Basis proxy | Monthly residual | Median daily spot volume |
|---|---:|---:|---:|---:|
| ETH | $7.20 | $0.56 | $-0.96 | $426,247.30 |
| LIT | $7.02 | $-1.68 | $-3.38 | $9,271,012.37 |
| UNI | $23.51 | $-10.87 | $3.92 | $4,329.76 |
| LINK | $2.93 | $8.12 | $2.33 | $4,746.36 |
| LDO | $14.70 | $-17.12 | $-11.14 | $1,079.19 |
| SKY | $11.33 | $-1.50 | $1.11 | $565.45 |
| AAVE | $10.29 | $-3.65 | $-2.08 | $1,780.91 |

| Asset | Week1 | Week2 | Week3 | Week4 | 2-day tail |
|---|---:|---:|---:|---:|---:|
| ETH | $+0.35 | $-1.82 | $-0.59 | $+0.06 | $-1.33 |
| LIT | $-3.02 | $-2.17 | $+0.84 | $-1.79 | $-0.41 |
| UNI | $+28.01 | $+0.97 | $-51.24 | $+24.64 | $-4.39 |
| LINK | $-2.31 | $+9.08 | $-20.48 | $+10.05 | $+0.51 |
| LDO | $-10.37 | $-44.46 | $+62.73 | $-15.42 | $+3.47 |
| SKY | $+35.79 | $+18.16 | $-7.59 | $-3.81 | $+0.55 |
| AAVE | $-8.62 | $+23.04 | $-25.48 | $+6.02 | $-0.86 |

UNI/LINK/SKY monthly positives are tiny budgets for execution, with mixed weekly results. LDO/SKY/AAVE each have one zero-volume spot day. A daily open can represent a much later trade on a thin market; spot/perp candle opens need not be simultaneous or executable. These issues are not solved by complete timestamp coverage. Funding-value units remain inferred.

The archived ETH collateral experiment used1.1x capital; this full-universe comparison fixes2x for every asset. The different ETH residual is therefore expected.

Verified42quantity/funding/basis/net identities separately with exact decimal parsing and all input pins. Next: bounded current displayed cost diagnostic across this same full universe. Comparing new costs with historical residuals is a sensitivity, not a reconstructed trade or future-profit forecast.
