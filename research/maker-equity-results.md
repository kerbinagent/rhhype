# NVDA and silver maker quote replay: one post-market capture

The frozen NVDA/XAG public-feed experiment produced **one hypothetical full-flow signal, one time-eligible hedge quote, and no complete exit quote pair**. It produced **no after-fee round-trip observation**. A displayed opening edge or public trade flow is not a maker fill, and a missing exit is unresolved rather than a zero return.

This is one post-market window, 2026-09-29 **20:22:56.780–20:29:56.818 UTC** (4:22–4:29 p.m. New York). It cannot compare regular, post-market, and overnight conditions. The [frozen method](maker-equity-plan.md), [raw archive](../data/raw/maker-capture/20260929T2022Z/manifest.json), [frozen inputs](../reports/maker-equity-v2/README.md), [derived summary](../data/derived/maker-equity-20260929T2022Z/summary.json), and [single case](../data/derived/maker-equity-20260929T2022Z/cases.json) preserve the exact definitions and evidence.

## Capture and primary 1-second gate accounting

The capture stopped at its 420-second duration limit, below its 25 MB compressed cap: 10,619 records, 3,755,149 gzip bytes, 3,758,827 bytes including manifest. The record count, compressed size, market-plan hash, and cap checks pass. Each of HL, Core Lighter, and RH Lighter had one continuous feed generation; there were no recorded errors, invalidations, excluded-quality events, malformed trade fields, unknown trade markets, or retained trades with source time ahead of receipt on any of six venue/asset feeds. These checks support the offline replay's input integrity; they do not certify exchange-clock synchronization or execution.

Across all 48 route/side/delay cohorts, there were **zero terminal-capture hedge or exit censors** and **zero funding-boundary-unresolved classifications**. The sole full-flow case had `hard_deadline_after_capture_end=false` and `flow_to_deadline_crosses_funding_hour=false`. No signed funding payment or financing cash flow was imputed.

The 1-second maker-arrival policy evaluated 83 five-second anchors for each of 16 asset/route/side cohorts, or **1,328 cohort anchors**. These are repeated comparisons of the same 83 instants; they are not 1,328 independent opportunities.

| Sequential gate | Count | Interpretation |
|---|---:|---|
| Anchors | 1,328 | 83 × 2 assets × 4 routes × 2 sides |
| Stale decision book | 904 | At least one side failed the frozen receipt ≤1 s or source ≤2 s rule |
| Source skew / receipt skew | 104 / 24 | Cross-venue skew exceeded 0.5 s |
| Decision depth or minimum | 48 | Original full quantity or minimum failed |
| Quote-supported decision | 248 | Passed the preceding decision gates |
| Missing post-due maker quote | 110 | No first valid maker-side observation within 1 s after assumed arrival |
| Maker price moved or crossed | 88 | Original passive price was no longer at the same uncrossed best |
| Same-price arrival | 50 | Public flow test could proceed |
| No strict full-flow signal | 49 | Qualifying trade flow did not exceed displayed queue ahead plus original quantity |
| Full-flow signal / hedge quote | 1 / 1 | Conditional public-data signals only |
| Complete exit / after-fee result | 0 / 0 | The only case lacked a due-time exit side |

Exactly 124 of the 248 quote-supported decisions belonged to the predeclared **decision-time opening-positive subset**. Within that subset, 52 lacked a post-due maker quote, 45 moved or crossed, 27 retained the price, 26 had no strict full-flow signal, and one had a full-flow signal and hedge quote but no exit. This subset was chosen at the decision quote, before later flow and exit outcomes; its opening positivity is not realized profit.

The following primary table retains all 16 cohorts. Each row has 83 anchors. “Skew” combines source and receipt skew; “same” is the same-price arrival count, and “full” is the strict flow count. The [machine-readable summary](../data/derived/maker-equity-20260929T2022Z/summary.json) splits every gate and decision-positive subset by cohort.

| Asset | Maker→hedge | Side | Stale | Skew | Depth/min | Supported | No arrival | Moved | Same | Full |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NVDA | HL→Core | buy | 70 | 6 | 4 | 3 | 2 | 1 | 0 | 0 |
| NVDA | HL→Core | sell | 70 | 6 | 3 | 4 | 3 | 0 | 1 | 0 |
| NVDA | Core→HL | buy | 70 | 6 | 0 | 7 | 4 | 3 | 0 | 0 |
| NVDA | Core→HL | sell | 70 | 6 | 0 | 7 | 4 | 0 | 3 | 0 |
| NVDA | HL→RH | buy | 69 | 3 | 4 | 7 | 4 | 2 | 1 | 0 |
| NVDA | HL→RH | sell | 69 | 3 | 7 | 4 | 3 | 0 | 1 | 0 |
| NVDA | RH→HL | buy | 69 | 3 | 0 | 11 | 10 | 0 | 1 | 0 |
| NVDA | RH→HL | sell | 69 | 3 | 1 | 10 | 9 | 1 | 0 | 0 |
| XAG | HL→Core | buy | 31 | 13 | 4 | 35 | 12 | 12 | 11 | 1 |
| XAG | HL→Core | sell | 31 | 13 | 9 | 30 | 11 | 10 | 9 | 0 |
| XAG | Core→HL | buy | 31 | 13 | 4 | 35 | 9 | 20 | 6 | 0 |
| XAG | Core→HL | sell | 31 | 13 | 1 | 38 | 9 | 20 | 9 | 0 |
| XAG | HL→RH | buy | 56 | 10 | 7 | 10 | 4 | 5 | 1 | 0 |
| XAG | HL→RH | sell | 56 | 10 | 1 | 16 | 8 | 7 | 1 | 0 |
| XAG | RH→HL | buy | 56 | 10 | 3 | 14 | 8 | 3 | 3 | 0 |
| XAG | RH→HL | sell | 56 | 10 | 0 | 17 | 10 | 4 | 3 | 0 |

The predeclared 0.5-second and 3-second arrival controls reused the same frames and each had 1,328 cohort anchors, 904 stale decisions, 248 quote-supported decisions, and **zero full-flow signals**. At 0.5 seconds, 103 lacked a due-time maker quote, 80 moved or crossed, and 65 retained the price; all 65 lacked full flow. At 3 seconds, the corresponding counts were 96, 118, and 34; all 34 lacked full flow. These controls are correlated with the primary and must not be summed into a portfolio P&L.

| Arrival control | Asset | Cohort anchors | Stale | Supported | No arrival | Moved | Same / no full flow | Full flow |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | NVDA | 664 | 556 | 53 | 28 | 10 | 15 | 0 |
| 0.5 s | XAG | 664 | 348 | 195 | 75 | 70 | 50 | 0 |
| 3 s | NVDA | 664 | 556 | 53 | 33 | 11 | 9 | 0 |
| 3 s | XAG | 664 | 348 | 195 | 63 | 107 | 25 | 0 |

Both controls also had the same 104 source-skew, 24 receipt-skew, and 48 depth/minimum exclusions as the primary because their decisions shared the identical anchor quotes. Every exact route/side/control gate remains in the derived summary.

## The single conditional flow case

At the **20:28:20 UTC** anchor, the primary policy considered buying `xyz:SILVER` passively on HL and selling XAG on Core Lighter. The frozen quantity was **16.28 troy ounces**, about **$999.62** at the HL decision price of **$61.402/oz**. Displayed queue ahead at the assumed maker activation was **6.01 oz**. Public qualifying opposite-aggressor flow reached **165 oz**, beyond `6.01 + 16.28 = 22.29 oz`, at **20:28:22.314 receipt UTC** (exchange source time **20:28:21.991**). This is only a hypothetical full-flow signal: the archive has no hypothetical order acknowledgement, actual queue position, fill, or cancellation ordering.

The predeclared opening quote allowance was **+2.139 bp after an approximate four-fee hurdle**. That allowance uses the *decision* hedge quote and does not price a realized exit. The first time-eligible Core hedge quote arrived **20:28:22.939 UTC**, after the **20:28:22.714** due time incorporating 100 ms baseline plus 300 ms Standard processing. A source- and receipt-valid exit pair did not appear in the frozen search window after its two venue-specific due times (HL **20:28:28.039**, Core **20:28:28.339**). The case is `missing_due_exit_side`; its 10-second hard deadline **20:28:32.314** preceded capture end. Neither terminal truncation nor a funding-hour boundary explains the missing exit. No net, reserve-adjusted net, or funding result is assigned.

**Post hoc exit-coverage diagnostic, outside the frozen one-second search:** Core's first individually time-valid quote was received **20:28:28.415** (source **20:28:28.349**), but its exit ask showed only **3.45 oz**, below `q=16.28`. HL's **20:28:28.403** BBO receipt had a source time **20:28:28.004**, before its **20:28:28.039** due time, so the first individually time-valid HL BBO was not until **20:28:29.934** (source **20:28:29.605**), after HL's frozen **20:28:29.039** search cutoff. The first source- and receipt-synchronized pair before the hard deadline was at **20:28:29.934**; Core's most recent ask still showed **3.45 oz**. A later matched pair at **20:28:31.842** displayed at least `q` on both exit sides, but it followed the first shallow pair and both one-second search cutoffs. It is excluded by the frozen first-eligible and deadline rules. This audit distinguishes a stage-window miss from the broader ten-second hard deadline; it is not a revised result or a backfilled execution.

## Post hoc quote coverage diagnostic

This diagnostic reads the stopped archive with the same `archive_load` and `last_quote` validity rules as the frozen analyzer. It changes **no** threshold, case classification, or prospective result. Counts of valid anchors below refer to the 83 *unique* UTC anchors, before route/side duplication. “Frame” means a valid parsed HL BBO or Lighter ticker quote; it is not a matched executable fill.

| Public quote feed | Quote frames | Book frames | Trade frames | Valid anchors / 83 | Median quote gap | 90th-percentile gap | Longest gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| HL NVDA BBO | 252 | 79 L2 | 55 | 19 | 0.497 s | 4.827 s | 14.367 s |
| Core NVDA ticker | 715 | 1,141 | 8 | 42 | 0.049 s | 1.073 s | 15.047 s |
| RH NVDA ticker | 327 | 1,039 | 77 | 38 | 0.360 s | 3.264 s | 34.448 s |
| HL silver BBO | 951 | 79 L2 | 49 | 59 | 0.201 s | 0.940 s | 8.662 s |
| Core XAG ticker | 1,922 | 2,356 | 23 | 71 | 0.046 s | 0.585 s | 6.969 s |
| RH XAG ticker | 343 | 1,170 | 10 | 32 | 0.078 s | 2.861 s | 21.677 s |

| Pair at unique anchors | Both valid | Only HL valid | Only other valid | Neither valid | Stale pair |
|---|---:|---:|---:|---:|---:|
| NVDA HL–Core | 13 | 6 | 29 | 35 | 70 |
| NVDA HL–RH | 14 | 5 | 24 | 40 | 69 |
| XAG HL–Core | 52 | 7 | 19 | 5 | 31 |
| XAG HL–RH | 27 | 32 | 5 | 19 | 56 |

For example, NVDA HL–Core had only 13 simultaneous fresh-anchor observations. In 29 more anchors Core alone was fresh; in 6 HL alone was fresh; in 35 neither was fresh. This explains the 70 stale decisions on each side of that route. The 904 stale count across cohorts comes from those pair-level absences repeated over buy/sell routes, not from 904 separate feed failures. At invalid individual anchors, receipt age above 1 second was common; source age above 2 seconds often overlapped it. The median receipt-minus-source age **of frames that did arrive** was about 0.31 s on HL and 0.06–0.07 s on Core/RH, but those differences are **not calibrated network latency**.

[Hyperliquid's WebSocket specification](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) says BBO updates are sent only when the best bid or offer changes on a block; it describes L2 as a separate snapshot feed. Thus a quiet BBO can leave the last BBO timestamp old even while a connection is healthy. The capture also contained 79 HL L2 frames per asset, but the frozen experiment used BBO/ticker observations for its one-level depth and did not retroactively merge older/deeper L2 data or refresh a quiet BBO timestamp. A quiet period does **not** prove that the prior size was still available, that it was executable, or that an order would fill. We cannot infer a general change-only guarantee for Lighter ticker from this archive alone; its observed gaps are reported empirically.

The single-window result supports a narrow conclusion: under this frozen freshness, flow, processing-delay, depth, and exit policy, the post-market capture provided **no complete conditional round trip to evaluate**. It gives no positive or negative estimate of executable maker P&L, fill probability, regular-hours behavior, or the value of changing freshness thresholds. Funding, financing, collateral conversion, oracle/reference divergence, and actual order processing beyond the quoted delay model remain unobserved. The RH comparisons use conditional USDG/USDC parity arithmetic and omit executable conversion cost.
