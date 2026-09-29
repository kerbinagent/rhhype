# Standalone 12-second closing-spread research observer

`scripts/horizon_observer.py` is a separate read-only process. It reads an existing `markets.json` discovery plan and opens public Hyperliquid, Lighter Core, and Robinhood Lighter WebSockets through `StreamManager`. It does not use the production monitor's output directory, place orders, or make REST book requests. Aster is excluded because reconstructing its diff feed requires a REST snapshot.

Dry-run route review (opens no sockets and writes no files):

```bash
.venv/bin/python scripts/horizon_observer.py \
  --markets data/paper-monitor/markets.json \
  --out data/horizon-research --dry-run
```

Once reviewed, a 20-minute observation uses the same arguments without `--dry-run`. The default selection takes at most 12 liquid routes, preferring BTC, ETH, SOL, ZEC, COIN, XAG, CASHCAT, HYPE, XRP, XPL, NVDA, and META when available. It selects one pair per asset by the smaller leg's 24-hour volume, with a $1 million default minimum. It refuses metadata older than 24 hours. `plan.json` records the exact selection and metadata age.

For both directions of each pair, the observer sizes $1,000 of opening buys and shorts to an equal quantity on the intersection of both lot grids. It walks full published depth for the opening buy, opening short, long liquidation bid, and short buyback ask. The measured **closing spread** is `(short buyback − long liquidation) / opening buy value × 10,000` basis points. Positive values are costly to close. This is a quote-level prediction target, **not cash P&L**; fees, funding, actual execution, collateral conversion, and capital use are outside this experiment.

An observation requires both venue source timestamps and sequence/generation identifiers, source age at most two seconds, source and receipt skew at most one second, and both source tokens advanced since the previous accepted paired quote. Gaps invalidate the route and censor pending 12-second outcomes in `HorizonMarkoutObserver`. Model version 2 compares predictions with the first eligible paired quote from 12–16 seconds later and reports missing coverage separately. Outcome detection runs on every valid advancing paired quote, while historical sampling is limited to 1 Hz. Version 1 applied that sampling limit before outcome detection; its running studies remain separately labeled. Source and receipt timestamps, skew, quantity, values, and generations remain in the most recent 100 observations in `horizon_snapshot.json`.

Storage is bounded: 200 recent observations in memory, one atomically replaced snapshot, one plan file, and a rotating 2 MiB log with two backups. The model keeps bounded per-route windows/counters and at most 5,000 mature anchor/outcome records with frozen predictions. The observer uses its own output lock and refuses to write within the source monitor directory. Live v1 studies and the separate v2 pilot are recorded in [review-loop.md](review-loop.md).


## Prospective v2 run and offline analysis

Use a new directory for every model version or changed experiment:

```bash
.venv/bin/python scripts/horizon_observer.py \
  --markets data/paper-monitor/markets.json \
  --out data/horizon-research-v2-bbo-new \
  --duration 2400 --hl-bbo
.venv/bin/python scripts/analyze_horizon.py \
  data/horizon-research-v2-bbo-new/horizon_snapshot.json \
  --out reports/horizon-v2-new
```

Run analysis after the observer stops. BBO supplies one displayed level, so
insufficient top size remains missing depth. The four v2 models are historical
median, persistence, median forward change, and a linear forecast shrunk toward
persistence. Parameters and interpretation are predeclared in
[horizon-markout-plan.md](horizon-markout-plan.md) and
[horizon-analysis-plan.md](horizon-analysis-plan.md). Aggregate metrics span the
run; percentile/route/block analysis may cover only the latest retained rows.
Twelve-second anchor spacing can produce up to four seconds of overlapping
outcomes, and opposite directions share quotes. No independence or profit claim
is inferred from a lower mean quote error.
