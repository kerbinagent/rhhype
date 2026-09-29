# Frozen holdout: fee and execution-cost sensitivity

**Result:** fee-tier changes alone do not rescue the recorded strategy. The fixed holdout lost **$624.27** across 527 closes. Removing every recorded trading fee still loses **$491.56**; removing only the modeled 5 bp pair reserve loses **$361.61**. Removing both leaves **−$228.90**, with the same fills and exits. This is an accounting counterfactual, not a new trading run.

## Frozen sample and calculation

This uses the [filter experiment's frozen evidence](../../data/evidence/research-filter-sample.json.gz) with SHA-256 `b2412d250f8ee2bf3b5e335032b046d8e3d4e9eaace309f939cd8562722f06bc` and its [published chronological split](../filter-experiments/REPORT.md). After the same 5-second route deduplication, there are 1,758 settled baseline attempts. The 70/30 boundary is **2026-09-29 17:08:49.735478 UTC**; two training outcomes crossing it were purged using `settled_at` for closes and `closed_at` for aborts. The untouched holdout has **528 attempts: 517 paired closes, 10 failed hedges, and one aborted attempt**. No filters were selected or retrained here.

Each closed attempt obeys `net = price P&L − trading fees − other costs − capital costs + funding`. Its `other_costs_usd` equals exactly **5 bp × the larger recorded entry-leg value** in all 527 closes; it is the monitor's modeled reserve, not an observed charge. The scenarios add back recorded `fees_usd`, `other_costs_usd`, or both. They leave recorded prices, quantities, fills, exits, funding, and capital charges untouched. [`scripts/fee_sensitivity.py`](../../scripts/fee_sensitivity.py) rebuilds [`summary.json`](summary.json), [`paired_attempts.csv`](paired_attempts.csv), and [`failed_hedges.csv`](failed_hedges.csv) from the frozen evidence. Five preselected filters from the original report are evaluated at their original thresholds without new selection.

| Same holdout and fills | All closed net | Paired net | Failed-hedge net | Paired wins | Additional improvement for paired break-even, bp of actual four-leg turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| Recorded costs | −$624.27 | −$602.98 | −$21.29 | 0 / 517 | 2.92 |
| All explicit trading fees set to zero | −$491.56 | −$472.96 | −$18.60 | 0 / 517 | 2.29 |
| Modeled 5 bp reserve set to zero | −$361.61 | −$344.82 | −$16.79 | 0 / 517 | 1.67 |
| Both set to zero | −$228.90 | −$214.80 | −$14.10 | 4 / 517 | 1.04 |

The 517 paired closes have **$2,064,381.40 of actual four-leg turnover** (mean $3,993.00 per paired attempt): both recorded entry values plus both recorded exit values. The required improvement for each attempt is `max(0, −scenario net USD) ÷ actual four-leg turnover × 10,000`. At recorded costs, the median paired attempt needs **2.68 bp** more across that turnover and the 90th percentile needs **3.29 bp**; after deleting both costs the median still needs **0.83 bp**. The table's aggregate basis-point figure divides the paired cohort's total loss by its total actual turnover. It is a **turnover-equivalent rebate or price improvement**, not a claim that every leg could receive a rebate or that basis would improve uniformly. A $1,000 single-leg denominator would misstate this requirement.

The 10 failed hedges are kept separate. Their recorded loss is **$21.29** and remains **$14.10** even with both cost fields removed. They did not complete a two-leg entry, so a four-leg turnover denominator and a paired basis-improvement claim do not apply.

## Original train-selected filters, unchanged

The five thresholds fixed in the [original analysis](../filter-experiments/REPORT.md) also remain negative if both cost fields are removed. These are subsets of the same holdout, with the same recorded fills.

| Frozen filter | Holdout attempts | Recorded net | Net with both cost fields zero |
| --- | ---: | ---: | ---: |
| Net entry edge ≥ $0.10 | 377 | −$452.21 | −$171.90 |
| Gross / modeled cost ≥ 1.25 | 245 | −$280.31 | −$107.27 |
| Receipt skew ≤ 500 ms | 326 | −$380.81 | −$137.46 |
| Source skew ≤ 750 ms | 233 | −$266.84 | −$94.50 |
| RWA `xyz` asset class | 506 | −$540.62 | −$174.92 |

## Published fee tiers and what they imply

The [current Hyperliquid perp schedule](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) lists **4.5 bp base taker / 1.5 bp base maker**, falling to **2.4 bp taker / 0 bp maker** at its highest volume tier, which requires over **$7 billion of weighted 14-day volume**. Its largest listed HYPE staking discount is **40%**, and the maximum published maker-volume rebate is **0.3 bp**, subject to eligibility. HIP-3 growth mode cuts protocol fees and rebates by at least 90%; actual market deployer scaling also matters. These account-dependent reductions are smaller than deleting *all* recorded fees, which still leaves a large holdout loss. A hypothetical maker order would have different fill probability, timing, and price, so this report does not reclassify any taker fill as maker.

[Lighter Core's current Standard tier](https://apidocs.lighter.xyz/docs/account-types) is **0 bp maker / 0 bp taker**. Core Plus is 0.5 bp each; base Premium is 0.4 bp maker / 2.8 bp taker, with stake discounts for Premium. [RH Lighter's separate schedule](https://apidocs.rh.lighter.xyz/docs/account-types) also has **0/0 bp Standard** and **0.5/0.5 bp Plus**; its base Premium is **1.2 bp maker / 3.5 bp taker** below $1 million trailing 14-day volume, declining with volume. Premium buys a different latency/quota service and is not a cheaper alternative to Standard here. For the Aster cohort, [RWA taker fees are fixed at 1.25 bp across VIP levels](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees); crypto schedules vary by group and VIP level. The frozen attempt already records its modeled fee dollars, and the zero-fee row removes them all, including Aster fees.

**Conclusion:** no published taker fee tier can outperform the zero-explicit-fee bound under these unchanged fills. The remaining loss comes primarily from recorded price P&L: **−$228.88** in the holdout, plus small capital costs. Better entry or exit basis, different hedge reliability, or maker execution would be a *different execution experiment* requiring new evidence. The current paper monitor and entry policy were not changed.

## Reproduce and limits

Run `python scripts/fee_sensitivity.py` and `python -m unittest discover -s tests -p test_fee_sensitivity.py -v`. The script verifies the frozen evidence hash, original split and purge count, `settled_at` availability before training cutoff, every close's P&L identity, and the 5 bp reserve formula. Current official fee pages were checked on 29 September 2026 and copied under [`sources/`](sources/).

This holdout is short and retrospective. Cost deletion does not produce executable quotes or changes in venue liquidity. The filter cohorts overlap, failed hedges remain real failures, and the turnover-equivalent break-even rates are descriptive diagnostics rather than a prospective edge estimate.
