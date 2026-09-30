# Passive-exit v1: completed holdout readout

Both frozen replays completed at about 03:58 UTC on 30 September 2026,
without replay errors. **No profitable complete branch was found.** Of 128
independent asset/size/tier/policy ledgers, 29 have known complete net and
all 29 are negative; the other 99 remain unknown. Do not sum these correlated
counterfactual ledgers.

## Primary result

Standard XAG / $1,000 / targeted passive ten-second exit admitted 57
attempts. It closed 56 without attributed entry flow, then halted on
`trade_cancel_order_ambiguous`, 449.727 seconds after its first quote.
The control has the same coverage. There are **zero completed trading
cycles and zero complete same-entry primary pairs**. Complete portfolio net
is unknown; the closed no-flow attempts are not profitable trades.

The adverse-exit calibration was ready: 30 resolved XAG flow observations
out of 33 admitted, with frozen p75 adverse HL buyback move 0.163682 bp.
All 32 asset/size/tier adverse models were ready. The primary failure was
execution coverage, not an unavailable calibration model.

## Standard $1,000 crypto controls

| Asset | Policy | Admitted / closed attempts | Closed with entry flow | Complete stressed net |
|---|---|---:|---:|---:|
| BTC | Taker 10s | 83 / 83 | 10 | −$5.328019 |
| BTC | Best-ask passive 10s | 83 / 83 | 10 | −$5.221381 |
| BTC | Targeted passive 10s | 83 / 83 | 10 | −$5.318364 |
| BTC | Targeted passive 60s | 83 / 83 | 10 | −$5.146465 |
| ETH | Taker 10s | 87 / 87 | 10 | −$7.048746 |
| ETH | Best-ask passive 10s | 87 / 87 | 10 | −$7.115488 |
| ETH | Targeted passive 10s | 87 / 87 | 10 | −$7.048751 |
| ETH | Targeted passive 60s | 87 / 87 | 10 | −$6.835761 |

These totals retain failed/partial and no-flow outcomes. Closed with entry
flow does not imply a fully hedged successful cycle. Each same-entry crypto
comparison has nine eligible complete pairs. For targeted 10s versus taker
10s their paired net difference is zero for both assets; differences in the
whole-ledger totals must not be presented as the paired effect.

All 29 complete branches remain negative even when their recorded fees,
5 bp reserve and capital charges are added back on the same fixed paths:
gross cash ranges from −$0.479812 to −$0.019638. This arithmetic sensitivity
does not simulate a different fee schedule or different trading decisions.

The targeted policies issued no passive ask on these Standard $1,000 crypto
paths. Each recorded nine target-price abstentions because the required exit
exceeded v1's fixed ceiling of five basis points above best ask. They then
used their declared fallback. Thus this sample does not test fills at the
higher cost-covering target. The separate stopped quote-screen diagnostic
finds median required $1,000 static markups of 14.46 bp for BTC, 13.85 bp for
ETH, 5.08 bp for XAG and 6.13 bp for NVDA; these are cost hurdles, not fill
forecasts. See [the full quote-distance readout](../passive-universe-exit-markup/0310Z-input-v1/readout.md).

## Correction and historical-evidence checks

The strict replay and the separately frozen entry-retirement correction
have identical admission histories and zero changed episode execution
classifications in this sample. Their economic results agree. This does not
disprove the independently reproduced boundary defect or establish equivalence
on other inputs.

The [128-branch comparison](../../data/derived/rh-passive-exit-v1-restart-comparison/REPORT.md)
verified complete stopped-capture provenance, both source inventories and
cohort scores. It found 112 branches with no retained passive asks, five
with retained asks and no recorded halt, and **11 with retained asks plus a
halt**. Closed contributions from those 11 remain provisional because of
the separate [post-halt historical-evidence defect](../../research/passive-retired-evidence-followup.md).
Their validated contributions and related paired inferences are withheld.
They already have unknown whole-portfolio net; none is counted among the
29 known negative portfolios. No historical fill or cash was invented.

## Provenance and decision

- Capture: 02:52:57.958514–03:42:58.061557 UTC, duration limit, untruncated,
  124,019 raw records, 48,931,302 total archive bytes.
- Calibration: first 30 minutes; holdout: final 20 minutes, including
  80 seconds with no new admissions. There were 1,298 retained shared cohort
  decisions across independent groups, not 1,298 independent profit samples.
- Strict replay: 917.609 seconds; corrected replay: 879.671 seconds.
- Raw gzip SHA-256: `c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6`.
- Full artifacts: [strict analysis](../../data/derived/rh-passive-exit-v1-restart/analysis.json),
  [corrected analysis](../../data/derived/rh-passive-exit-v1-restart-corrected/analysis.json),
  [comparison](../../data/derived/rh-passive-exit-v1-restart-comparison/comparison.json).

No strategy is promoted. The separately labelled post-capture ACK sensitivity
also found no positive complete portfolio; see its
[readout](../rh-passive-ack-exploratory/readout.md).
The completed [target-reach diagnostic](../rejected-target-public-reach/REPORT.md)
reconstructed all 150 targets rejected above the five-basis-point ceiling.
None was reached by an eligible observed RH buy print within its fixed window,
including qualifying source times received late. Public-tape completeness is
unproven, so this is observed nonreach rather than an absolute no-fill bound.
Widening the ceiling alone is unsupported by these observations. Repeating
the unchanged target policy is also unsupported. A different entry gate needs
its own feasibility evidence before another capture.
