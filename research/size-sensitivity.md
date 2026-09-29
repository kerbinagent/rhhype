# Exploratory NVDA/XAG all-taker size sensitivity

The [method was frozen](../reports/size-sensitivity-v1/frozen-method.md) before running this offline replay, but the **choice to run a size screen was made after inspecting the earlier NVDA/XAG maker capture**. This is a post hoc diagnostic on the same 2026-09-29 20:22–20:29 UTC post-market archive, not a new holdout. It uses no real orders or fills. The [machine-readable summary](../reports/size-sensitivity-v1/derived/summary.json) and [all candidate cases](../reports/size-sensitivity-v1/derived/cases.json) preserve missing and shallow outcomes.

## Fixed method

For each of 83 five-second UTC anchors, two assets, four directed HL↔Core/RH routes, and $100/$250/$1,000 buy-side target sizes, the replay fixes one common-lot quantity `q` from the fresh buy-venue ask. Thus each size has **664 candidate route/anchor observations** (1,992 total); the observations share market frames and are correlated. Anchor quotes must pass the prior 1-second receipt, 2-second source, and 0.5-second cross-venue source/receipt skew rules. The buy-side anchor notional is at most the target; the sell-side anchor notional could be slightly larger. Its largest observed excess was about **0.085% of target**, and every case records both actual notionals.

Each taker leg independently selects its **first** source- and receipt-eligible top quote after the venue delay: HL +100 ms, Core/RH Standard +400 ms. The quote must appear within 1 second, support the unchanged `q`, and meet that venue's minimum and maximum. A shallow first quote is unresolved; the replay cannot wait for a later fuller book. After both entry legs pass, exit quotes are sought 5 seconds after the later entry receipt, with the same venue delays, 1-second waits, and a hard anchor+10-second deadline. Any one-leg result remains explicitly unresolved. The 5% annual capital illustration charges 100% of each own entry notional for its observed entry-to-exit quote interval; four taker fees use each own leg notional, and a separate 5 bp reserve uses the larger entry notional. RH USDG/USDC arithmetic assumes parity conditionally and omits executable conversion. There is no funding payment imputation across a UTC hour boundary.

## Coverage and conditional quote arithmetic

| Target | All candidates | Stale decision | Decision skew | Anchor-ready | One entry leg unresolved | Both entry legs unresolved | Both entries pass | One exit leg unresolved | Both exit legs unresolved | Complete paths |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| $100 | 664 | 452 | 64 | 148 | 86 | 22 | 40 | 20 | 4 | 16 |
| $250 | 664 | 452 | 64 | 148 | 89 | 24 | 35 | 18 | 5 | 12 |
| $1,000 | 664 | 452 | 64 | 148 | 88 | 30 | 30 | 16 | 5 | 9 |

The anchor-ready 148 observations at each size had no minimum/lot exclusion. The decision coverage is identical across sizes because all share the same quote timestamps; later first-quote depth and minimum tests account for size-dependent differences. Across the three sizes, 37 complete conditional quote paths were observed; **none had positive displayed gross or after-four-fee arithmetic**. No missing, shallow, or one-leg outcome is assigned zero return. One exit candidate per size encountered capture-end truncation; these remain within the unresolved exit counts. No complete path crossed a UTC funding hour.

| Target | Complete paths | Median displayed gross, bp | Median after four fees, bp | Median after fees + 5 bp reserve + capital, bp | Range of final conditional arithmetic, bp | Positive final |
|---|---:|---:|---:|---:|---:|---:|
| $100 | 16 | about −0.88 | −2.68 | −7.68 | −8.85 to −7.06 | 0 |
| $250 | 12 | about −0.96 | −2.76 | −7.76 | −8.85 to −7.13 | 0 |
| $1,000 | 9 | about −1.03 | −2.83 | −7.83 | −8.85 to −7.13 | 0 |

The gross medians above are approximate because each path's displayed gross is converted using its **own buy entry notional**. The fee and reserve medians are computed from per-leg prices, not a flat fixed-notional shortcut. The 5% annual capital illustration contributes about **0.0002 bp** over these few-second paths; it is included but does not explain the result. The 5 bp reserve is a stress allowance, not a measured conversion or slippage charge. Even before that allowance, the selected complete paths had negative displayed gross and negative after-fee arithmetic.

| Directed route | $100 complete | $250 complete | $1,000 complete |
|---|---:|---:|---:|
| NVDA buy HL / sell Core | 1 | 1 | 0 |
| NVDA buy Core / sell HL | 1 | 1 | 1 |
| NVDA buy HL / sell RH | 0 | 0 | 0 |
| NVDA buy RH / sell HL | 0 | 0 | 0 |
| XAG buy HL / sell Core | 7 | 5 | 5 |
| XAG buy Core / sell HL | 7 | 5 | 3 |
| XAG buy HL / sell RH | 0 | 0 | 0 |
| XAG buy RH / sell HL | 0 | 0 | 0 |

## Paired size comparison

Only **nine exact asset/route/anchor keys** reached a complete conditional quote path at **all three sizes**: five XAG buy-HL/sell-Core, three XAG buy-Core/sell-HL, and one NVDA buy-Core/sell-HL. On this matched intersection, the median after-fee/reserve/capital quote arithmetic was about **−7.83 bp at each size**, with zero positive paths. This matched comparison avoids mistaking the broader $100 coverage (16 paths) for a like-for-like return advantage over $1,000 (9 paths). It still consists of repeated observations from one short post-market capture and contains no actual fills.

The key distinction is evidentiary: reducing the requested quantity raised the count of complete **public-top-quote paths** from 9 to 16, while neither the matched nor size-specific complete paths showed positive displayed gross in this archive. This does not establish that a smaller order would have filled, that a losing displayed path would necessarily lose in execution, or that missing larger-size paths were unprofitable. The study cannot estimate regular-hours behavior, actual slippage, processing variation, funding, stablecoin conversion, or one-leg loss exposure. The [frozen 2026-09-29 maker result](maker-equity-results.md) remains separate and unchanged.
