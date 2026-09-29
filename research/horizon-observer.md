# Standalone 12-second closing-spread research observer

`scripts/horizon_observer.py` is a separate read-only process. It reads an existing `markets.json` discovery plan and opens public Hyperliquid, Lighter Core, and Robinhood Lighter WebSockets through `StreamManager`. It does not use the production monitor's output directory, place orders, or make REST book requests. Aster is excluded because reconstructing its diff feed requires a REST snapshot.

Dry-run route review (opens no sockets and writes no files):

```bash
.venv/bin/python scripts/horizon_observer.py \
  --markets data/paper-monitor-final-validation/markets.json \
  --out data/horizon-research --dry-run
```

Once reviewed, a 20-minute observation uses the same arguments without `--dry-run`. The default selection takes at most 12 liquid routes, preferring BTC, ETH, SOL, ZEC, COIN, XAG, CASHCAT, HYPE, XRP, XPL, NVDA, and META when available. It selects one pair per asset by the smaller leg's 24-hour volume, with a $1 million default minimum. It refuses metadata older than 24 hours. `plan.json` records the exact selection and metadata age.

For both directions of each pair, the observer sizes $1,000 of opening buys and shorts to an equal quantity on the intersection of both lot grids. It walks full published depth for the opening buy, opening short, long liquidation bid, and short buyback ask. The measured **closing spread** is `(short buyback − long liquidation) / opening buy value × 10,000` basis points. Positive values are costly to close. This is a quote-level prediction target, **not cash P&L**; fees, funding, actual execution, collateral conversion, and capital use are outside this experiment.

An observation requires both venue source timestamps and sequence/generation identifiers, source age at most two seconds, source and receipt skew at most one second, and both source tokens advanced since the previous accepted paired quote. Gaps invalidate the route and censor pending 12-second outcomes in `HorizonMarkoutObserver`. The model compares predictions with the first eligible paired quote from 12–16 seconds later and reports missing coverage separately. Source and receipt timestamps, skew, quantity, values, and generations remain in the most recent 100 observations in `horizon_snapshot.json`.

Storage is bounded: 200 recent observations in memory, one atomically replaced snapshot, one plan file, and a rotating 2 MiB log with two backups. The model keeps bounded per-route windows and counters. The observer uses its own output lock and refuses to write within the source monitor directory. It remains unlaunched until the route plan and tests are reviewed.
