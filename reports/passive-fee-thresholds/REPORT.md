# Passive HL fee threshold screen

Each cell is median maximum HL taker bp per fill, followed by the fraction of matched rows whose $0.10 target survives at current base and published tier 6 + Diamond rates. Fee-only includes modeled capital; stress also subtracts the separate 5 bp reserve. Negative median means zero HL fee is insufficient for the median row.

| Stage | Asset | Size | RH side | n | Fee-only max bp | Fee-only base | Fee-only Diamond | Stress max bp | Stress base | Stress Diamond |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| static | BTC | 100 | buy_rh | 75 | -4.675 | 0/75 | 0/75 | -7.175 | 0/75 | 0/75 |
| static | BTC | 100 | sell_rh | 75 | -4.675 | 0/75 | 0/75 | -7.175 | 0/75 | 0/75 |
| static | BTC | 250 | buy_rh | 75 | -1.656 | 0/75 | 0/75 | -4.156 | 0/75 | 0/75 |
| static | BTC | 250 | sell_rh | 75 | -1.656 | 0/75 | 0/75 | -4.156 | 0/75 | 0/75 |
| static | BTC | 500 | buy_rh | 75 | -0.653 | 0/75 | 0/75 | -3.153 | 0/75 | 0/75 |
| static | BTC | 500 | sell_rh | 75 | -0.653 | 0/75 | 0/75 | -3.153 | 0/75 | 0/75 |
| static | BTC | 1000 | buy_rh | 75 | -0.153 | 0/75 | 0/75 | -2.653 | 0/75 | 0/75 |
| static | BTC | 1000 | sell_rh | 75 | -0.153 | 0/75 | 0/75 | -2.653 | 0/75 | 0/75 |
| static | ETH | 100 | buy_rh | 75 | -4.500 | 0/75 | 0/75 | -7.000 | 0/75 | 0/75 |
| static | ETH | 100 | sell_rh | 75 | -4.500 | 0/75 | 0/75 | -7.000 | 0/75 | 0/75 |
| static | ETH | 250 | buy_rh | 75 | -1.517 | 0/75 | 0/75 | -4.017 | 0/75 | 0/75 |
| static | ETH | 250 | sell_rh | 75 | -1.517 | 0/75 | 0/75 | -4.017 | 0/75 | 0/75 |
| static | ETH | 500 | buy_rh | 75 | -0.516 | 0/75 | 0/75 | -3.016 | 0/75 | 0/75 |
| static | ETH | 500 | sell_rh | 75 | -0.516 | 0/75 | 0/75 | -3.016 | 0/75 | 0/75 |
| static | ETH | 1000 | buy_rh | 75 | -0.017 | 0/75 | 0/75 | -2.516 | 0/75 | 0/75 |
| static | ETH | 1000 | sell_rh | 75 | -0.017 | 0/75 | 0/75 | -2.517 | 0/75 | 0/75 |
| static | NVDA | 100 | buy_rh | 56 | -4.355 | 0/56 | 0/56 | -6.857 | 0/56 | 0/56 |
| static | NVDA | 100 | sell_rh | 56 | -4.355 | 0/56 | 0/56 | -6.857 | 0/56 | 0/56 |
| static | NVDA | 250 | buy_rh | 56 | -1.345 | 0/56 | 0/56 | -3.847 | 0/56 | 0/56 |
| static | NVDA | 250 | sell_rh | 56 | -1.345 | 0/56 | 0/56 | -3.847 | 0/56 | 0/56 |
| static | NVDA | 500 | buy_rh | 56 | -0.343 | 0/56 | 0/56 | -2.845 | 0/56 | 0/56 |
| static | NVDA | 500 | sell_rh | 56 | -0.343 | 0/56 | 0/56 | -2.845 | 0/56 | 0/56 |
| static | NVDA | 1000 | buy_rh | 56 | 0.158 | 0/56 | 23/56 | -2.344 | 0/56 | 0/56 |
| static | NVDA | 1000 | sell_rh | 56 | 0.158 | 0/56 | 23/56 | -2.344 | 0/56 | 0/56 |
| static | XAG | 100 | buy_rh | 68 | -3.577 | 0/68 | 0/68 | -6.079 | 0/68 | 0/68 |
| static | XAG | 100 | sell_rh | 68 | -3.577 | 0/68 | 0/68 | -6.080 | 0/68 | 0/68 |
| static | XAG | 250 | buy_rh | 68 | -0.560 | 0/68 | 0/68 | -3.062 | 0/68 | 0/68 |
| static | XAG | 250 | sell_rh | 68 | -0.560 | 0/68 | 0/68 | -3.063 | 0/68 | 0/68 |
| static | XAG | 500 | buy_rh | 68 | 0.444 | 11/68 | 53/68 | -2.058 | 0/68 | 0/68 |
| static | XAG | 500 | sell_rh | 68 | 0.444 | 11/68 | 53/68 | -2.059 | 0/68 | 0/68 |
| static | XAG | 1000 | buy_rh | 68 | 0.945 | 38/68 | 68/68 | -1.558 | 0/68 | 0/68 |
| static | XAG | 1000 | sell_rh | 68 | 0.945 | 38/68 | 68/68 | -1.558 | 0/68 | 0/68 |
| delayed | BTC | 100 | buy_rh | 75 | -4.734 | 0/75 | 0/75 | -7.234 | 0/75 | 0/75 |
| delayed | BTC | 100 | sell_rh | 75 | -4.681 | 0/75 | 0/75 | -7.181 | 0/75 | 0/75 |
| delayed | BTC | 250 | buy_rh | 75 | -1.709 | 0/75 | 0/75 | -4.209 | 0/75 | 0/75 |
| delayed | BTC | 250 | sell_rh | 75 | -1.662 | 0/75 | 0/75 | -4.162 | 0/75 | 0/75 |
| delayed | BTC | 500 | buy_rh | 75 | -0.707 | 0/75 | 0/75 | -3.207 | 0/75 | 0/75 |
| delayed | BTC | 500 | sell_rh | 75 | -0.659 | 0/75 | 0/75 | -3.159 | 0/75 | 0/75 |
| delayed | BTC | 1000 | buy_rh | 75 | -0.207 | 0/75 | 0/75 | -2.707 | 0/75 | 0/75 |
| delayed | BTC | 1000 | sell_rh | 75 | -0.158 | 0/75 | 0/75 | -2.659 | 0/75 | 0/75 |
| delayed | ETH | 100 | buy_rh | 75 | -4.539 | 0/75 | 0/75 | -7.039 | 0/75 | 0/75 |
| delayed | ETH | 100 | sell_rh | 75 | -4.612 | 0/75 | 0/75 | -7.112 | 0/75 | 0/75 |
| delayed | ETH | 250 | buy_rh | 75 | -1.536 | 0/75 | 0/75 | -4.036 | 0/75 | 0/75 |
| delayed | ETH | 250 | sell_rh | 75 | -1.610 | 0/75 | 0/75 | -4.110 | 0/75 | 0/75 |
| delayed | ETH | 500 | buy_rh | 75 | -0.554 | 0/75 | 1/75 | -3.054 | 0/75 | 0/75 |
| delayed | ETH | 500 | sell_rh | 75 | -0.610 | 0/75 | 1/75 | -3.110 | 0/75 | 0/75 |
| delayed | ETH | 1000 | buy_rh | 75 | -0.054 | 0/75 | 1/75 | -2.554 | 0/75 | 0/75 |
| delayed | ETH | 1000 | sell_rh | 75 | -0.113 | 0/75 | 1/75 | -2.613 | 0/75 | 0/75 |
| delayed | NVDA | 100 | buy_rh | 50 | -4.355 | 0/50 | 0/50 | -6.857 | 0/50 | 0/50 |
| delayed | NVDA | 100 | sell_rh | 50 | -4.573 | 0/50 | 0/50 | -7.075 | 0/50 | 0/50 |
| delayed | NVDA | 250 | buy_rh | 50 | -1.345 | 0/50 | 0/50 | -3.847 | 0/50 | 0/50 |
| delayed | NVDA | 250 | sell_rh | 50 | -1.564 | 0/50 | 0/50 | -4.066 | 0/50 | 0/50 |
| delayed | NVDA | 500 | buy_rh | 50 | -0.343 | 0/50 | 2/50 | -2.845 | 0/50 | 0/50 |
| delayed | NVDA | 500 | sell_rh | 50 | -0.562 | 0/50 | 3/50 | -3.064 | 0/50 | 0/50 |
| delayed | NVDA | 1000 | buy_rh | 50 | 0.158 | 1/50 | 18/50 | -2.344 | 0/50 | 0/50 |
| delayed | NVDA | 1000 | sell_rh | 50 | -0.062 | 1/50 | 15/50 | -2.564 | 0/50 | 0/50 |
| delayed | XAG | 100 | buy_rh | 68 | -3.623 | 0/68 | 0/68 | -6.125 | 0/68 | 0/68 |
| delayed | XAG | 100 | sell_rh | 68 | -3.573 | 0/68 | 0/68 | -6.076 | 0/68 | 0/68 |
| delayed | XAG | 250 | buy_rh | 68 | -0.601 | 0/68 | 1/68 | -3.103 | 0/68 | 0/68 |
| delayed | XAG | 250 | sell_rh | 68 | -0.552 | 0/68 | 0/68 | -3.055 | 0/68 | 0/68 |
| delayed | XAG | 500 | buy_rh | 68 | 0.402 | 10/68 | 55/68 | -2.101 | 0/68 | 0/68 |
| delayed | XAG | 500 | sell_rh | 68 | 0.452 | 9/68 | 53/68 | -2.051 | 0/68 | 0/68 |
| delayed | XAG | 1000 | buy_rh | 68 | 0.899 | 34/68 | 68/68 | -1.603 | 0/68 | 0/68 |
| delayed | XAG | 1000 | sell_rh | 68 | 0.953 | 40/68 | 67/68 | -1.550 | 0/68 | 0/68 |

See `groups.csv` for zero-fee and volume-only counts; `threshold-rows.csv` retains every signed row threshold. These rows are conditional quote screens, not realized fills or portfolio returns.
