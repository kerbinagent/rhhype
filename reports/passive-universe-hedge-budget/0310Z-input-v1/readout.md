# Offline optimistic static hedge-cost budget

**Zero fees and zero hedge spread do not produce a positive eligible median at any tested size.** The same 17 assets meet the original minimum three valid $1,000 rounds, and every eligible median is negative. This supplies no reason to launch a broader Core screen solely to save hedge fees under the same static cycle, $0.10 target and 5 bp stress. It does not rule out future trading profit or policies with different prices or economics.

The diagnostic reuses only the completed 03:11–03:15 UTC screen. All 420 original size rows are preserved; 320 remain valid, while 100 stale source/receipt rows are disclosed and excluded. The underlying universe stays 26 routes / 21 retained assets. There were no network calls or changes to frozen screen files.

`optimistic budget = q × (RH ask − RH bid) − $0.10 − 0.0005 × q × RH bid`

Quantity is the exact original common-lot quantity. The hedge has no fee or spread/impact, RH has no fee, and stress uses RH opening notional as its minimum possible base. The original larger-opening-leg stress can only reduce this budget. A positive budget is a necessary condition for positive margin in this unchanged-book setup before nonnegative hedge costs. It does not model whether either RH maker order fills, price drift, funding, financing or conversion.

| RH size | Valid / original | Missing | Positive observations | Maximum budget | Median across valid observations | Best eligible asset median | Positive eligible medians |
|---:|---:|---:|---:|---:|---:|---:|---:|
| $100 | 80/105 | 25 | 0 | $-0.0711 | $-0.1257 | LIT $-0.1024 | 0/17 |
| $250 | 80/105 | 25 | 0 | $-0.0267 | $-0.1643 | LIT $-0.1061 | 0/17 |
| $500 | 80/105 | 25 | 1 | $+0.0466 | $-0.2287 | LIT $-0.1121 | 0/17 |
| $1,000 | 80/105 | 25 | 1 | $+0.1933 | $-0.3574 | LIT $-0.1242 | 0/17 |

The pooled observation median is descriptive; candidate eligibility and selection use each asset’s own median and original $1,000 coverage. All four coverage-ineligible assets also have negative descriptive medians.

Only LIT at round index 2 (the third quote round), with RH bid 3.7783 / ask 3.7813, has individual positive budgets. Its 7.9401 bp RH spread can leave $0.0466 at $500 or $0.1933 at $1,000 in the zero-cost scenario. Retaining the original modeled fee amounts of $0.4489 / $0.8979 makes those budgets −$0.4023 / −$0.7046, even while still deleting hedge spread and keeping the optimistic stress base. Zero of the 320 fee-retained sensitivity observations is positive. These are two sizes of one isolated market/round, not independent evidence or positive asset medians.

| Asset | Valid $1,000 rounds | Eligible | Median zero-cost budget | Median with original fees retained |
|:---|---:|:---|---:|---:|
| LIT | 5/5 | yes | $-0.1242 | $-1.0234 |
| NEAR | 5/5 | yes | $-0.1767 | $-1.0761 |
| AMD | 3/5 | yes | $-0.2048 | $-0.3845 |
| XAG | 4/5 | yes | $-0.2508 | $-0.4305 |
| INTC | 5/5 | yes | $-0.2556 | $-0.4353 |
| MU | 3/5 | yes | $-0.2917 | $-0.4715 |
| SNDK | 5/5 | yes | $-0.3154 | $-0.4952 |
| ZEC | 4/5 | yes | $-0.3215 | $-1.2111 |
| MSFT | 3/5 | yes | $-0.3252 | $-0.5050 |
| AAPL | 4/5 | yes | $-0.3574 | $-0.5372 |
| GOOGL | 3/5 | yes | $-0.3655 | $-0.5452 |
| XRP | 4/5 | yes | $-0.3657 | $-1.2654 |
| NVDA | 5/5 | yes | $-0.3808 | $-0.5606 |
| SOL | 5/5 | yes | $-0.4157 | $-1.3148 |
| HYPE | 5/5 | yes | $-0.4375 | $-1.3370 |
| ETH | 5/5 | yes | $-0.4427 | $-1.3430 |
| BTC | 5/5 | yes | $-0.5325 | $-1.4321 |
| CRCL | 2/5 | no | $-0.1233 | $-0.3031 |
| META | 2/5 | no | $-0.3834 | $-0.5631 |
| TSLA | 2/5 | no | $-0.4022 | $-0.5821 |
| AMZN | 1/5 | no | $-0.4380 | $-0.6178 |

The fee-retained sensitivity holds each original public-scenario modeled fee amount on its recorded fill notionals fixed. It is neither a measured account fee nor a new frictionless hedge quote. All retained fee amounts are nonnegative, original HL spread/impact is nonpositive, and original stress is no smaller than RH minimum stress; the runner reconciles original RH notionals and the stressed margin, then verifies both derived budgets are at least that original margin.

Original quote SHA-256: `13d909ef8d4f16f2c796420b8b01e3fce52b00a9ac26fa3ec55a975045b66d0b`. The [manifest](manifest.json) records hashes for every read input, including original universe/summary/manifest/freeze and diagnostic method/source/tests. All original frozen input hashes verified, and every read input was unchanged after analysis. Five offline tests passed: exact arithmetic/minimum stress, strict positivity, failed-row preservation, invalid upper-budget assumptions and saved math, and original coverage plus median rather than a single peak.

All asset medians at all four sizes are in [summary.json](summary.json); all 420 rows, including failures, are in [observations.jsonl](observations.jsonl). The [method](method.md), [runner](source.py), and [tests](tests.py) are copied into this bounded derived directory.
