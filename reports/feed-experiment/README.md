# Feed pilot comparison

Run this read-only report after the synchronized depth and BBO pilots have
written checkpoints:

```bash
.venv/bin/python scripts/compare_feed_experiments.py --name first
```

The command writes `first.md` and `first.json` here. Use a different bounded
name for a later review, such as `final`; rerunning a name replaces those two
files. It does not stop or change either collector.

## Review template

1. Check that configs, economic pair metadata, and portfolio names match.
   Check both checkpoint timestamps and the common retained-trade cutoff.
2. Read each portfolio's lifetime ledger separately: exact and estimated
   closed P&L, wins/losses, aborts, entry attempts, and fees. Do not add
   correlated portfolios into one return.
3. Inspect retained trade coverage before using paired/failed-hedge counts,
   entry timing, exit delay, signal-to-entry deterioration, route, or
   crypto/RWA diagnostics. Low coverage means the rows are a selected window.
4. Check Hyperliquid fill provenance (`bbo`, `l2book`, or missing observation).
   A missing field means that diagnostic is unavailable for that trade.
5. Compare CPU, p95 loop lag, and event rate only with their separate snapshot
   timestamps shown. They are observations from two running processes.
6. Treat a pilot with fewer trades or a different route mix as an incomplete
   comparison. The script never promotes BBO automatically.

The generated Markdown gives the compact review. The JSON includes per-route
and per-category retained diagnostics, coverage fractions, source counts,
separate checkpoint and performance timestamps, and comparability flags.



## Corrected forty-minute pilot, September 29

[Final comparison](corrected-pilot-final.md) uses the two stopped
`data/paper-monitor-feed-v2-*` directories at 18:45:52 UTC. Decimal-lot execution
fix 16be742 was loaded at launch; no old one-lot residual appeared. Both pilots
disable targeted REST, unlike production. BBO improves quote observation and
paired execution coverage but does not establish profitability. Retention
removed older trades, so lifetime ledgers and retained diagnostics are separate.
Some positions remain frozen at the scheduled duration stop; the report lists
them and does not invent closing fills. The raw stopped directories are retained
locally, and can reproduce the report with:

```bash
.venv/bin/python scripts/compare_feed_experiments.py \
  --depth data/paper-monitor-feed-v2-depth \
  --bbo data/paper-monitor-feed-v2-bbo --name corrected-pilot-final
```
