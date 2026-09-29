# Take-profit estimate versus completed paper exit

Frozen checkpoint: 2026-09-29T20:09:07.633377+00:00. Retained settled trades: 4989.

| Independent portfolio | Triggered exits | Positive final net | Median request → flat | Median trigger / final net USD |
|---|---:|---:|---:|---:|
| cooldown | 2 | 0 | 1.575s | 0.471 / -1.436 |
| plus | 2 | 0 | 1.243s | 0.317 / -1.932 |
| premium | 2 | 0 | 1.420s | 1.050 / -3.013 |
| shadow_baseline | 3 | 0 | 1.432s | 0.230 / -0.809 |
| standard | 2 | 0 | 1.296s | 0.169 / -0.933 |

- Triggered liquidation estimates are quotes; completed outcomes are paper fills.
- Strategy portfolios share signals and prices; never add their returns.
- Retained settled sample omits pending exits and evicted older records.
- Request-to-flat time is not continuous opportunity duration or a latency threshold.
- Final minus trigger includes all model changes, not solely price slippage.

The $0.10 exit target requests an unwind when the current estimate qualifies. It does not lock in ten cents: each delayed leg uses a later eligible book. These records do not reveal exactly when the estimate changed sign between request and completion, so they cannot establish a millisecond speed requirement.

Reproduce: `.venv/bin/python scripts/analyze_profit_exits.py --evidence reports/exit-trigger-survival/evidence.json`.
