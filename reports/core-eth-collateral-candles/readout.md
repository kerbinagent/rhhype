# ETH collateral candle screen: exploratory lead

September 2026, fixed ~$1,000 spot plus 10% cash, same-quantity short:

| Period | Inferred funding | Candle basis P&L | Residual* |
|---|---:|---:|---:|
| Sep 1–7 | $1.85 | $0.92 | $1.21 |
| Sep 8–14 | $1.45 | -$0.86 | -$0.96 |
| Sep 15–21 | $1.05 | $0.78 | $0.27 |
| Sep 22–28 | $1.92 | $0.56 | $0.93 |
| Sep 29–30 | $0.56 | -$0.84 | -$1.08 |
| Full month** | $7.20 | $0.56 | $2.74 |

*After 5% annual cost on spot plus cash, and 5 bp allowance. Zero Standard
trading fees. **Overlaps weekly rows; do not add. Rounded for display.

All 90 daily candles arrived. Raw hashes, Decimal funding and basis sums
were rechecked separately. No actual P&L: trade candles are not fills,
funding-value units are inferred, debit charges remain unknown. Current
collateral rules are not proof of historical availability. Positive daily
spot-low/mark-high margin proxies do not establish liquidation safety:
spot trade price is not the collateral oracle and cash debits were omitted.

Next: bound observable execution costs before designing prospective capture.
The retrospective result cannot satisfy the live strategy stopping rule.
