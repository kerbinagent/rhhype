# Horizon v2 offline analysis plan

This plan is fixed before examining a live v2 pilot. Run `scripts/analyze_horizon.py`
only on a stopped `horizon_snapshot.json` with `model.model_version == 2`:

```bash
python scripts/analyze_horizon.py /path/to/stopped/horizon_snapshot.json --out /path/to/report-directory
```

The CLI writes `analysis.json` and `report.md` without network access. It reads
frozen forecasts from mature anchor rows and never refits the model.

## Predeclared comparison

The primary descriptive ranking sorts the four models by **all-run mean absolute
error in closing-spread basis points**, ascending, only when all four all-run
scored counts equal the reported scored-anchor count. Ties use all-run RMSE and
then this fixed order: historical median, persistence, horizon delta,
conditional linear. A positive MAE difference versus persistence means lower
absolute quote error. If counts differ or no anchors were scored, no ranking is
issued. This ranking is descriptive, not a significance test or trading rule.

For every retained scored anchor, compare all four frozen predictions with the
same later observed quote. Report paired MAE differences versus persistence,
mean signed error, MAE, RMSE, and p50/p90 absolute error. Percentiles use linear
interpolation at `(n − 1) × percentile`. Break these retained-row metrics out by
directed route and by five-minute UTC block of **anchor time**. The Markdown
table shows at most 100 routes and 100 blocks; the bounded JSON contains all
retained groups. Route direction is part of the route key.

## Coverage and limits

Report all-run anchors, matched, scored, warmup, censored, pending-at-stop, and
censor reasons. Show retained mature/scored rows against all-run totals, and
flag any dropped or missing mature export rows. All-run error aggregates cover
the whole pilot; retained-row percentiles and route/block tables may cover only
the newest 5,000 mature rows. Never merge these denominators or imply the
retained subset represents the full run. The CLI accepts at most a 32 MB
snapshot and 5,000 retained rows, and caps each output file at 20 MB. All-run
matched/scored counts by route are copied separately when retained in the
snapshot; the model may evict old route summaries. The snapshot does not retain
anchor-time censor records, so five-minute censor coverage cannot be recovered.

Closing-spread bps use each observation's own executable quantity and entry
value. They do not measure original-quantity fill outcomes, cash P&L, or
strategy profit. Opposite directions of a market share quotes; neighboring
12-second anchors can have outcomes up to 16 seconds after anchoring. Those
rows can be correlated. No independent-sample p-values or significance claims
are reported.
