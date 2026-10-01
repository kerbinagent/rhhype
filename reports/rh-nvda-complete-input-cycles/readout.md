# NVDA: all four active lower-fee pools, complete-input screen

Fixed plan frozen at `f5c9374`; 3 rounds, all 12 ordered distinct-pool routes, 100 USDG primary and 1,000 USDG control. Completed 2026-10-01 05:25:51 UTC with 102 public requests.

- 72 planned outcomes: **39 complete-input quote cycles; 33 unknown because a v3 leg reached its terminal price limit**. Unknown cases are excluded from both win and loss counts.
- **0 positive complete-input cycles before gas.** Best 100 USDG result: **−0.014920 USDG**. Best 1,000 USDG result: **−0.512669 USDG**. Pool fees already included; gas would reduce these further.
- Independent audit reconciled all outcomes to cached raw request calldata and response integers, verified ordered route coverage, exact first-output/second-input identity, v3 price-limit rejection, and matching before/after block hashes.
- The standard no-hook v4 Quoter enforces full input consumption; that documented deployment assumption remains. No actual trade, wallet transfer, approval, or router simulation occurred. Actual and after-gas P&L remain unset.

Lower fees substantially narrowed the gap at 100 USDG, but this fixed screen produced no profitable complete cycle. No retry or policy retuning on these observations.
