# Required RH passive exit markup: static quote-distance diagnostic

**At $1,000, median required markup above observed best ask is 5.08 bp for XAG, 14.46 bp for BTC, 13.85 bp for ETH and 6.13 bp for NVDA.** These are prices required to meet the declared static cost hurdle. They do not establish exit fills, execution odds, expected P&L or a preferred asset.

The calculation preserves the original 420 rows and 320 valid size observations from the completed 0310Z screen. Each size retains 80/105 valid observations and 25 stale exclusions. Exact original fee/tick inputs support repricing for all 320 valid rows; no metadata or arithmetic limitation occurred. Seventeen assets meet the original minimum three valid $1,000 rounds. The original frozen files were unchanged and no network calls were made.

## Exact price hurdle

For common quantity q, RH bid b, proposed RH exit x, original HL short proceeds S and buyback cost B, RH maker fee fraction r and HL taker fee fraction h:

`q*x*(1-r) - q*b*(1+r) + S-B - h*(S+B) >= $0.10 + 0.0005*max(q*b,S)`

This includes the RH exit fee on q*x. All frozen RH maker fee values happen to be zero, while the runner and tests support nonzero maker fees and their price dependence. Both original HL fees remain on their own unchanged walked notionals. The original larger-opening-leg stress base remains fixed. Quantities are not reduced, rerounded or increased as exit price changes.

The raw requirement is solved as an exact rational, then rounded upward to the frozen RH tick, at least at the current ask. Every rounded price clears the original fee/target/stress hurdle, and the preceding tick fails for every above-ask result. Quote ceiling and minimum notional also pass. Price/bps summaries are descriptive; the grid decision itself uses exact rational arithmetic.

## All sizes: original valid observations

| Size | Supported / original | Stale exclusions | Median distance (bp) | Maximum distance (bp) | Median ticks | Maximum ticks |
|---:|---:|---:|---:|---:|---:|---:|
| $100 | 80/105 | 25 | 16.625 | 25.938 | 105.5 | 1980 |
| $250 | 80/105 | 25 | 10.520 | 20.115 | 70.5 | 1480 |
| $500 | 80/105 | 25 | 8.686 | 18.527 | 62.5 | 1314 |
| $1,000 | 80/105 | 25 | 7.657 | 18.527 | 59.5 | 1230 |

The pooled medians include each original valid observation, including assets with insufficient median-ranking coverage. Tick counts are venue/asset grid units and cannot be compared across assets as equivalent price or execution distances.

## Focus assets

| Asset | Size | Valid rounds | Median / max bp above ask | Median / max ticks |
|:---|---:|---:|---:|---:|
| XAG | $100 | 4/5 | 13.755 / 14.501 | 841.5 / 887 |
| XAG | $250 | 4/5 | 7.968 / 8.746 | 487.5 / 535 |
| XAG | $500 | 4/5 | 6.056 / 6.850 | 370.5 / 419 |
| XAG | $1,000 | 4/5 | 5.083 / 5.902 | 311.0 / 361 |
| BTC | $100 | 5/5 | 23.460 / 23.769 | 1954 / 1980 |
| BTC | $250 | 5/5 | 17.457 / 17.766 | 1454 / 1480 |
| BTC | $500 | 5/5 | 15.452 / 15.774 | 1287 / 1314 |
| BTC | $1,000 | 5/5 | 14.455 / 14.765 | 1204 / 1230 |
| ETH | $100 | 5/5 | 22.826 / 23.086 | 610 / 617 |
| ETH | $250 | 5/5 | 16.839 / 17.099 | 450 / 457 |
| ETH | $500 | 5/5 | 14.818 / 15.079 | 396 / 403 |
| ETH | $1,000 | 5/5 | 13.845 / 14.106 | 370 / 377 |
| NVDA | $100 | 5/5 | 15.335 / 16.658 | 35 / 38 |
| NVDA | $250 | 5/5 | 9.201 / 10.521 | 21 / 24 |
| NVDA | $500 | 5/5 | 7.449 / 8.767 | 17 / 20 |
| NVDA | $1,000 | 5/5 | 6.134 / 7.452 | 14 / 17 |

At $1,000 the median price increments are approximately $0.0311/ounce for XAG (311 ticks of $0.0001), $120.40/BTC (1,204 ticks of $0.10), $3.70/ETH (370 ticks of $0.01), and $0.14/share for NVDA (14 ticks of $0.01). The prices come from static public Standard fee scenarios, not authenticated fee quotes.

## Original coverage and $1,000 distance by asset

| Asset | Valid rounds | Eligible original coverage | Median / max bp above ask | Median / max ticks |
|:---|---:|:---|---:|---:|
| BTC | 5/5 | yes | 14.455 / 14.765 | 1204 / 1230 |
| ETH | 5/5 | yes | 13.845 / 14.106 | 370 / 377 |
| LIT | 5/5 | yes | 14.810 / 18.527 | 56 / 70 |
| NVDA | 5/5 | yes | 6.134 / 7.452 | 14 / 17 |
| SOL | 5/5 | yes | 14.048 / 15.725 | 168 / 188 |
| HYPE | 5/5 | yes | 13.573 / 14.265 | 117 / 123 |
| AAPL | 4/5 | yes | 6.364 / 6.364 | 21.0 / 21 |
| XAG | 4/5 | yes | 5.083 / 5.902 | 311.0 / 361 |
| GOOGL | 3/5 | yes | 6.443 / 7.322 | 22 / 25 |
| SNDK | 5/5 | yes | 6.035 / 6.557 | 104 / 113 |
| NEAR | 5/5 | yes | 12.079 / 13.699 | 60 / 68 |
| ZEC | 4/5 | yes | 12.985 / 14.511 | 183.5 / 205 |
| XRP | 4/5 | yes | 14.039 / 14.712 | 21.0 / 22 |
| MSFT | 3/5 | yes | 5.884 / 6.276 | 30 / 32 |
| MU | 3/5 | yes | 5.694 / 6.816 | 61 / 73 |
| TSLA | 2/5 | no | 7.200 / 7.624 | 25.5 / 27 |
| META | 2/5 | no | 6.695 / 6.897 | 49.5 / 51 |
| CRCL | 2/5 | no | 3.991 / 4.646 | 33.5 / 39 |
| AMD | 3/5 | yes | 6.419 / 6.910 | 39 / 42 |
| AMZN | 1/5 | no | 7.690 / 7.690 | 19 / 19 |
| INTC | 5/5 | yes | 6.884 / 7.745 | 8 / 9 |

All asset/size medians, maxima and original coverage are in [summary.json](summary.json), and all 420 individual outcomes are in [observations.jsonl](observations.jsonl). No asset is nominated by this diagnostic.

## Implication for the next hypothesis

After the current passive lifecycle replay, this gives a cost hurdle for evaluating a fixed cost-targeted exit: can an exit at the required distance close within a predeclared horizon while all admitted outcomes—including missing flow, partials, hedge deterioration and rescue losses—remain profitable? The replay must supply the lifecycle and exit-flow evidence; choosing the smallest distance cannot answer that question. The earlier zero-cost hedge diagnostic also found no positive eligible median under the same static target/stress, so hedge fee savings alone do not remove the need for higher RH exit prices.

RH ticker supplies only the best bid/ask and their sizes. It does not reveal queue competition or a private fill at an above-ask exit level. This sparse five-round screen cannot estimate execution odds, adverse selection, fill latency or delayed HL buyback costs. The implied exit quote assumes the original HL prices remain unchanged; funding, financing and USDG/USDC conversion are not measured. A dynamic repricing policy changes price, queue priority, quote age, acknowledgement/cancel races and hedge prices; it needs a separately frozen lifecycle model and confirmation window. This diagnostic provides no such policy or price-drift prediction.

## Verification

Five offline tests passed: nonzero exit-fee dependence and minimal grid price, exact equality and sub-decimal-precision rounding, already-sufficient ask, explicit unsupported-input/quote-bound limitations, and original failures/coverage without nominations. All frozen input hashes verify, all exact original fee/stress/margin equations reconcile, and read input hashes remain unchanged. The original quote SHA-256 and all diagnostic source/method/test hashes are recorded in [manifest.json](manifest.json). Derived files are bounded by 2 MB.
