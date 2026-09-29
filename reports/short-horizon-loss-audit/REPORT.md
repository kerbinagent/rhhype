# Ten-second paper strategy: loss audit

Frozen checkpoint: **2026-09-29 14:54:38 UTC (10:54:38 EDT)**. First retained entry: 14:33:06 UTC. All 978 completed trades are retained and match the lifetime closed counters. Open positions are excluded from the closed totals below. The collector continues running, so its screen will show later numbers.

## Results

| Independent fee scenario | Closed | Profitable | Price P&L | Trading fees | Extra cost allowance | Net P&L |
|---|---:|---:|---:|---:|---:|---:|
| Standard | 377 | 0 | −$198.50 | $132.47 | $188.16 | **−$519.14** |
| Plus | 376 | 0 | −$219.17 | $180.95 | $187.75 | **−$587.88** |
| Premium | 225 | 0 | −$194.16 | $214.72 | $112.24 | **−$521.13** |

These are alternative portfolios with different fees and processing delays: do not add their returns. Financing adds $0.0130, $0.0127 and $0.0062 respectively. Funding is zero in this sample, which does not cross an hourly boundary. Each trade targets $1,000 per leg, with actual size rounded to common venue lots.

The additional 5 bp allowance is an assumed expense, approximately $0.50 per trade, not an observed exchange charge. Removing it leaves Standard at **−$330.98**, Plus at **−$400.13**, and Premium at **−$408.89**. Only two of 978 trades would be profitable after trading fees before this allowance. Removing a cost from recorded results is an accounting sensitivity, not a rerun with altered entry decisions.

## Why the strategy loses

The entry test uses the opening cross-venue price difference, subtracting estimated opening and closing fees plus the allowance. It does **not** estimate the opposite-book spread at the eventual exit. A positive signal therefore depends on sufficient future convergence. Buying one perpetual and shorting another does not immediately realize their price difference.

For matched quantities:

```
price P&L = (short entry proceeds − long entry cost)
          − (short buyback cost − long exit proceeds)
net P&L   = price P&L − all fill fees − extra costs − financing + funding
```

If the price difference persists, the second term consumes the first, and spreads and fees leave a loss. In this sample **868 exits hit the time limit**, **109 unwound an entry failure**, and only **one** requested a profit exit. Median holding time including exit execution was 11.2–11.4 seconds. Re-entry is allowed as soon as the prior position finishes; persistent differences can thus cause repeated losing round trips. The implementation currently treats any positive entry signal as sufficient: 331 of the completed trades even had an entry signal below the chosen $0.10 profit target. Raising this threshold alone would not validate convergence.

Crypto was included: Standard XPL lost $133.02 across 50 trades and ARB $72.72 across 34. Equity and commodity routes also lost: Standard NVDA/Robinhood Lighter lost $63.60 across 62 trades; silver/Robinhood Lighter lost $61.80 across 59. Per-route details are in [summary.json](summary.json).

## Timing and profit triggers

For the 869 trades that fully entered, median signal-to-both-entry-fills was **1.371 seconds**; median exit-request-to-flat was **1.391 seconds**. These combine configured processing delays with fresh-book observation and scheduling. They are paper observation times, not measured exchange order acknowledgements.

The sole profit trigger was SPCX, Premium: estimated net liquidation +$0.2023 at the exit request, but actual modeled exit fills finished 0.801 seconds later at **−$1.1539**. A $0.10 trigger requests delayed orders; it cannot guarantee a positive fill outcome.

Operational inspection around this audit found all four feeds connected, snapshot age under two seconds, approximately 61% of one CPU core and 26 ms p95 event-loop lag. Core Lighter had no reconnects after the keepalive fix; Robinhood Lighter still had sequence gaps that triggered resynchronization. Healthy connections do not establish continuously synchronized executable quotes. Feed freshness and execution observation are larger limitations here than the measured event-loop scheduling delay.

## Accounting checks

A separate audit script reconstructs long and short price P&L from entry/exit values, fees from each fill's recorded rate, the cost allowance from configured basis points, financing from filled notional and elapsed time, and each portfolio's cash identity including active positions. It checks quantities fully close and exit fills sum to stored exit values.

All checks pass. Maximum trade-net discrepancy: **$2.28e−13**; maximum wallet reconciliation discrepancy: **$7.28e−12**. No sign error or duplicate fee/allowance charge was found. An independent code review reached the same conclusion. This validates recorded accounting, not actual fill attainability or external fee schedules.

## Next strategy work

The present entry rule is too permissive to establish profitable short-horizon arbitrage. A shorter exit deadline bounds exposure; it does not create convergence.

The next experiment should evaluate a bounded rolling distribution of executable closing spreads by route, require expected convergence within the actual measured holding/execution window to cover all costs, and report out-of-sample results. Add one-entry-per-episode/cooldown controls to measure how much repeated churn contributes, and separately report paired trades versus failed hedges. Compare those changes in shadow portfolios against this preserved baseline; neither a cooldown nor a revised threshold guarantees profit. The user's running policy and balances were preserved during this audit.

## Reproduce

```bash
# Frozen evidence, exactly the sample in this report:
.venv/bin/python scripts/paper_loss_audit.py data/evidence/short-horizon-loss-audit.json.gz

# Current collector, short read-only SQLite transaction:
.venv/bin/python scripts/paper_loss_audit.py data/paper-monitor
```

The frozen compressed evidence is about 302 KiB. The audit adds no background logger and changes no retention settings. Future audits may cover only the retained trade window; lifetime counts are reported separately.
