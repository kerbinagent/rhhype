# Live strategy experiments — 2026-09-29

## Status and initial results

Experiments are enabled in the user's existing collector. Original Standard/Plus/Premium accounting is preserved. Four additional independent Standard-fee portfolios began at **2026-09-29T15:09:36.346189+00:00**. The frozen comparison below is at **2026-09-29T15:27:59.643161+00:00**. The live screen will advance beyond these values.

| Policy | Closed trades | Positive P&L closes | Net closed paper P&L | Failed hedge closes retained |
|---|---:|---:|---:|---:|
| shadow_baseline | 324 | 1 | $-361.18 | 11 |
| cooldown | 44 | 0 | $-54.38 | 1 |
| convergence | 4 | 3 | $+1.17 | 4 |
| conservative | 0 | 0 | $+0.00 | 0 |

Each portfolio has its own $20,000 paper capital and $1,000 target per leg; returns must not be added. Closed totals exclude open positions and unresolved funding. These are short exploratory results, not established expected returns.

**The positive median-policy total is not successful paired arbitrage.** All four `convergence` trades failed to establish both legs. Three gains came from short ZEC positions on three venues, unwound after their Hyperliquid buys were rejected; one SPCX failed hedge lost money. The ZEC gains reflect related directional exposure, not three independent successful arbitrages. No paired arbitrage profit has been demonstrated by these first forecast trades.

The cooldown policy lost less in aggregate by trading less. Its mean net result was $-1.236 per closed trade versus $-1.115 for the fresh baseline, so it did not improve per-trade profitability in this sample. The conservative policy has not traded and cannot be called profitable.

## Approaches tested

- **Fresh baseline:** the unchanged positive opening-edge rule, started alongside the experiments.
- **Cooldown:** minimum $0.25 cost-adjusted opening signal, 60 seconds between entries per directed route, and 250 ms receipt/source alignment.
- **Median (`convergence`):** minimum $0.25 opening signal and 60-second cooldown; subtract the historical median executable closing spread from the signal, then require at least $0.25 expected net. Uses the baseline's one-second alignment bound.
- **Conservative:** uses the 75th percentile closing spread, a $0.50 minimum forecast and stricter 250 ms entry alignment.

All retain actual simulated fill fees, the 5 bp additional modeled cost, financing/funding treatment, delayed entry/exit execution, the $0.10 net liquidation profit trigger and ten-second exit-request deadline. Forecast margins also cannot be below a configured profit target.

Historical closing spreads are sampled for both directions, including times when the opening signal is negative, at no more than once per second per route. Both observations must advance and pass freshness checks. Models use only prior observations: the current evaluation cannot train its own forecast. Required history is at least 40 samples spanning 120 seconds; the rolling window is 900 seconds, capped at 900 observations per route and 2,000 routes. A 30-second observation gap or changed stream generation resets the affected history.

These models assume a recent distribution is informative about future closing spreads. They do not establish ten-second convergence probabilities. Execution failure can dominate otherwise favorable forecasts, as the first four trades illustrate.

## Sampling revision, declared before forecast trades

Version 1 required both receipt and exchange-source alignment within 250 ms for training. Around 99% of attempted paired training evaluations failed the check; none of the forecast policies entered. Observed HL source-to-receipt ages around 0.68–0.71 s versus 0.07–0.11 s on other venues showed why simultaneously tight receipt and source bounds were often incompatible.

Version 2 began at **2026-09-29T15:20:40.210634+00:00**. It uses the existing baseline's maximum one-second bound for training and median-policy entry. Conservative/cooldown entries retain 250 ms. This sampling change preceded all forecast entries; migration refuses a version-1 experiment that already executed forecast entries. Prior baseline/cooldown balances and counters are preserved. Decision counters span both versions, with an explicit migration timestamp.

The revised models reached **226 ready directed routes** in the frozen snapshot. Median-policy forecast rejections reached 1822; the rule is evaluating and rejecting trades, rather than merely waiting forever for data. Models warm up again after process restart; the final performance deployment restarts that warmup without resetting accounting.

## Operations and performance

- One shared set of feeds and REST gates serves every portfolio. Additional orders may affect refresh scheduling, so these are observational comparisons, not independent randomized trials.
- A market-to-position index avoids scanning every position for every unrelated book. Liquidity arrays are initialized only for portfolios with eligible orders.
- Common lot quantities and depth walks are reused across fee tiers, while fee floors and actual execution remain scenario-specific. Regression checks compare repriced signals with independent tier calculations in both directions, including multi-level depth and market fee floors.
- A synthetic receive-only benchmark improved from 0.775 s to 0.342 s CPU time for 10,000 events (2.27x). A separate paired-quote calculation benchmark improved from 0.591 s to 0.257 s (2.30x). These are isolated component benchmarks, not end-to-end speedup claims.
- Twelve consecutive ten-second health observations are saved in `consecutive-health-samples.json`. All reported connected feeds. More intense later traffic saturated roughly one CPU core and pushed p95 loop lag above 100 ms, so Python headroom is limited at peak load. The final deployment adds shared-depth repricing; a subsequent operational sample is recorded separately. More scaling should be based on profiling, not an assumption that threads make CPU work parallel.
- An existing Aster XAG position took 52 s after its exit request to flatten following restart. The two-second-per-market snapshot queue plausibly explains that delay; exact first-book evidence had already expired. Held markets now begin their bootstrap ahead of ordinary scans, with an ordering regression test. The ten-second rule remains a request deadline, not a guaranteed flat time.
- The active SQLite budget remains 128 MiB, with existing trade/event/evidence caps and rotating logs. Model history is bounded RAM; cooldown/accounting state persists. Accepted forecast entries emit bounded historical model evidence, subject to the same evidence retention limits.

## Validation and evidence

The full suite passed 116 tests before the final shared-depth optimization; 30 relevant engine/exit/latency/strategy tests passed after that change. Prior terminal resize/Ctrl-C tests passed. At the comparison checkpoint, all seven wallet identities reconciled within $2e-11, and a separate fill reconstruction found no fee duplication or P&L sign error. SQLite quick check returned `ok`; all 13 positions saved before the sampling-revision restart subsequently closed.

- `initial-comparison.json`: strict-sampling phase, before forecast entries.
- `validated-comparison.json`: cumulative ledger comparison and retained trade diagnostics, with policy version/time markers.
- `consecutive-health-samples.json`: sequential operational observations.
- `receive-benchmark.json`, `quote-benchmark.json`: limited component benchmarks.
- `../../data/evidence/strategy-forecast-first-trades.json.gz`: the first four forecast trades plus subsequently observed trades, with recorded entry diagnostics and fill details. Their separate detailed training-history evidence was already pruned when exported; the archive records an empty model-evidence list rather than fabricating it.

To inspect live results:

```bash
.venv/bin/python scripts/monitor.py --watch
.venv/bin/python scripts/paper_report.py data/paper-monitor
```

Restart an existing viewer once to load the added rows. `Ready` means enough history for a route, not a profitable route. The collector remains running. The next substantive strategy question is execution quality: avoiding failed paired entries and measuring their expected unwind loss, rather than treating favorable failed-hedge outcomes as arbitrage wins.


## Later checkpoint after the final performance deployment

At **2026-09-29T15:32:19.726109+00:00**, results had advanced to:

| Policy | Closed | Net paper P&L | Failed hedge closes |
|---|---:|---:|---:|
| shadow_baseline | 401 | $-445.78 | 13 |
| cooldown | 52 | $-62.35 | 2 |
| convergence | 5 | $-0.17 | 5 |
| conservative | 0 | $+0.00 | 0 |

The fifth median-policy trade was another failed hedge and erased the earlier small gain. All five were failed paired entries; the earlier +$1.17 must not be treated as an established positive result. Both earlier and later checkpoints are retained to avoid selecting only the favorable moment.

The post-deployment operational sample measured 70.1% of one core, 19.8 ms p95 loop lag and 1202 book events/s, with 131.2 MiB resident memory. This is a snapshot, not a sustained capacity guarantee. All 14 positions saved before this final restart subsequently closed, and all wallet errors remained below $2e-11. Forecast history is warming again after restart; balances and counters were preserved.
