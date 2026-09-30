# Delayed taker quotes: completed negative feasibility result

**Completed 30 September 2026 at 06:52:04 UTC.** Source `92f74a7` was
committed before the third, separately authorized traversal. It finished in
904.45 seconds, within the fixed 1,200-second limit, publishing 2,530,132 bytes.
The first output-sublimit failure and second timeout remain preserved.
The independent checker (`c5645f5`) passed, and root rehashed all 33 actual
inputs plus all nine manifest-covered outputs unchanged.

## Results

Both directions, BTC/ETH/NVDA/XAG and $100/$250/$500/$1,000 were retained.
There are **7,200 candidates and 28,800 horizon outcomes**. All **26,395
complete quotes are negative after trading fees alone**, before adding the
5 bp stress allowance and capital. None meets the $0.10 target. Funding-
inclusive returns remain unknown for every row, as predeclared.

| Requested hold | Original outcomes | Complete quotes | Incomplete | Positive after fees | Positive after fees, stress and capital |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 s | 7,200 | 6,810 | 390 | 0 | 0 |
| 30 s | 7,200 | 6,768 | 432 | 0 | 0 |
| 60 s | 7,200 | 6,682 | 518 | 0 | 0 |
| 300 s | 7,200 | 6,135 | 1,065 | 0 | 0 |

The primary $1,000 grid has one anchor every five seconds; the smaller
sizes have one every thirty seconds. Each primary asset/direction/horizon
has 600 original outcomes. This unequal sampling is intentional; sizes and
horizons are not pooled into a portfolio or treated as independent trials.

Best observed primary-size quotes across both directions and all four
horizons are shown below as an optimistic descriptive maximum, not a
selectable execution or future forecast. Column maxima need not be the same row.

| Asset | Maximum gross | Maximum after fees | Maximum after fees, stress and capital |
| --- | ---: | ---: | ---: |
| BTC | +$0.2247 | −$0.6744 | −$1.1742 |
| ETH | +$0.2531 | −$0.6467 | −$1.1468 |
| NVDA | −$0.0438 | −$0.2236 | −$0.7242 |
| XAG | −$0.0245 | −$0.2046 | −$0.7053 |

On jointly complete primary-size candidates, the median difference between
30/60/300-second net quotes and their own 10-second control ranges from
−$0.00666 to +$0.00893 across the 24 asset/direction/horizon groups. Matched
coverage differs and remains in the published contrast tables. These small
median changes do not overcome the quoted round-trip costs.

## Coverage and uncertainty

6,905 candidates reached a delayed complete entry quote. Candidate failures
were: 114 cross-venue skew, 12 anchor depth, 32 missing anchor book, 50 stale
anchor, three delayed-entry depth and 84 missing delayed entries.

The 2,405 incomplete horizon outcomes comprise 1,180 inherited initial/entry
failures, 938 end-of-file exits, 266 missing exits and 21 insufficient-depth
exits. They have no fabricated economics. The hour-boundary counts among
complete quotes are 38/68/147/690 at 10/30/60/300 seconds. These flags are
not verified funding calendars, and no funding cash is imputed.

The independent verifier checks exported endpoint clocks, generation,
quantity rules, four own-notional fees, stress, elapsed capital, shared entry,
all group counts/medians, and unchanged publication hashes. Exported rows
cannot independently reconstruct the full book walks, first-eligible
selection, anchor quantity floor, or unexported instant opposite walks;
those remain supported by the frozen implementation and synthetic fixtures.

## Supplemental fee-reduction bound

A post-result diagnostic preserves each complete row's actual gross,
quantity, timestamps, stress and capital, but forgives all four nonnegative
trading fees. **Zero of 26,395 complete rows becomes positive.** Best primary
$1,000 values are BTC −$0.2751, ETH −$0.2470, NVDA −$0.5442 and XAG −$0.5253.
This bounds fee reductions at unchanged observed quotes only. It does not
assume zero fees are available, model another venue's prices, or bound maker
fills, missing outcomes, funding, other timestamps or future regimes.

## Decision

Extending the tested taker hold from ten seconds to five minutes does not
supply a positive ex-funding quote in this archive. There is no observed
positive outcome for a predictor to select on this covered grid, and fee
reductions alone cannot clear its existing stress scenario. Do not fit a
selector, relax thresholds, promote a strategy, or launch another capture
based on these results. A different execution mechanism, venue price path
or market regime needs separate evidence and a frozen future test.

This is exploratory post-capture quote feasibility, not actual fills or
paper portfolio P&L. The 50-minute overnight window, four assets, frozen
sizes and quantities, public Standard fees and USDG/USDC parity delimit the
finding. No private acknowledgement, price-limit rejection, partial fills,
hedge rescue or conversion execution was modeled.

## Artifacts

- [Original published report](0252Z-v3/readout.md), [manifest](0252Z-v3/manifest.json), [frozen method](0252Z-v3/method.md).
- [Independent verification](0252Z-v3-verification.json) and [root input/output hash attestation](0252Z-v3-audit.json).
- [Supplemental zero-fee bound](0252Z-v3-zero-fee-bound.json).
- Preserved [first failure](0252Z-v1.building/failure.json) and [second failure](0252Z-v2.building/failure.json).
- [Storage reconciliation](../experiment-storage/delayed-taker-completion-reconciliation-v3.json): completed bytes replace the 4 MB reservation; a separate 100 KB derived-analysis/audit allowance keeps the shared projected maximum at 31,110,904 of 33,000,000 bytes. No new raw archive or canonical traversal.
