# Fixed-quantity delayed taker quote diagnostic

Completed post-capture paired-book quotes only; no private fills, limit-price execution, partial execution, hedge rescue or funding-inclusive profit. Production policies unchanged.

All 7,200 candidates and 28,800 outcomes retained. See compressed CSV and summary groups for initial failures, gaps, deadlines, EOF and jointly observed 10/H quote contrasts.

| Asset | Long venue | Budget | H | Original | Complete quotes | Positive ex funding | >= $0.10 ex funding |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC | hyperliquid | 1000 | 10 | 600 | 589 | 0 | 0 |
| BTC | hyperliquid | 1000 | 30 | 600 | 585 | 0 | 0 |
| BTC | hyperliquid | 1000 | 60 | 600 | 578 | 0 | 0 |
| BTC | hyperliquid | 1000 | 300 | 600 | 530 | 0 | 0 |
| BTC | rh_lighter | 1000 | 10 | 600 | 582 | 0 | 0 |
| BTC | rh_lighter | 1000 | 30 | 600 | 579 | 0 | 0 |
| BTC | rh_lighter | 1000 | 60 | 600 | 573 | 0 | 0 |
| BTC | rh_lighter | 1000 | 300 | 600 | 526 | 0 | 0 |
| ETH | hyperliquid | 1000 | 10 | 600 | 594 | 0 | 0 |
| ETH | hyperliquid | 1000 | 30 | 600 | 591 | 0 | 0 |
| ETH | hyperliquid | 1000 | 60 | 600 | 585 | 0 | 0 |
| ETH | hyperliquid | 1000 | 300 | 600 | 536 | 0 | 0 |
| ETH | rh_lighter | 1000 | 10 | 600 | 593 | 0 | 0 |
| ETH | rh_lighter | 1000 | 30 | 600 | 590 | 0 | 0 |
| ETH | rh_lighter | 1000 | 60 | 600 | 584 | 0 | 0 |
| ETH | rh_lighter | 1000 | 300 | 600 | 535 | 0 | 0 |
| NVDA | hyperliquid | 1000 | 10 | 600 | 500 | 0 | 0 |
| NVDA | hyperliquid | 1000 | 30 | 600 | 494 | 0 | 0 |
| NVDA | hyperliquid | 1000 | 60 | 600 | 485 | 0 | 0 |
| NVDA | hyperliquid | 1000 | 300 | 600 | 453 | 0 | 0 |
| NVDA | rh_lighter | 1000 | 10 | 600 | 500 | 0 | 0 |
| NVDA | rh_lighter | 1000 | 30 | 600 | 494 | 0 | 0 |
| NVDA | rh_lighter | 1000 | 60 | 600 | 485 | 0 | 0 |
| NVDA | rh_lighter | 1000 | 300 | 600 | 453 | 0 | 0 |
| XAG | hyperliquid | 1000 | 10 | 600 | 586 | 0 | 0 |
| XAG | hyperliquid | 1000 | 30 | 600 | 584 | 0 | 0 |
| XAG | hyperliquid | 1000 | 60 | 600 | 577 | 0 | 0 |
| XAG | hyperliquid | 1000 | 300 | 600 | 528 | 0 | 0 |
| XAG | rh_lighter | 1000 | 10 | 600 | 586 | 0 | 0 |
| XAG | rh_lighter | 1000 | 30 | 600 | 583 | 0 | 0 |
| XAG | rh_lighter | 1000 | 60 | 600 | 577 | 0 | 0 |
| XAG | rh_lighter | 1000 | 300 | 600 | 528 | 0 | 0 |

All funding-inclusive totals unknown. Matched quote economics do not resolve censored outcomes; correlated branches are not summed.
