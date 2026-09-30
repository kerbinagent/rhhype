# Proposed fixed-quantity delayed taker quote diagnostic

**Planning only, 2026-09-30.** The candidate grid and rules below are fixed for this proposal. Implementation, source freeze, synthetic review, and one supervised offline traversal require root approval. No raw frames were scanned and no code, capture, network request, production policy, parent static helper, or reverse helper was changed while preparing this plan.

## Untested question and useful limit

Does a fixed original quantity have a positive delayed, four-taker quote outcome at a predeclared 30, 60, or 300 second hold, when a 10 second control and all original candidates are retained? This measures whether observed dynamic basis movement can overcome crossed spreads, public fees, 5 bp stress, and a capital estimate. It cannot observe private fills or establish an executable strategy.

The existing [convergence follow-up](strategy-convergence-followup.md) asks for these horizons but reports only 12–16 second fixed-quantity evidence. Its 1,595 matched quotes have no reserve-adjusted +$0.10 outcome; 539 of 2,134 original anchors are censored. [Horizon v2](../reports/horizon-v2/report.md) scores variable-quantity closing-spread forecasts at 12–16 seconds. The [stopped impulse pilot](../reports/impulse-v1/final.md) confirms zero candidates, uses a five-second hold, and supplies no completed quote outcomes. The completed 0252Z [static RH-maker screen](../reports/passive-rare-spread/0252Z-fixed-1s-v1/readout.md) has zero stressed positive margins among 47,624 valid anchors, but contains no later unwind prices.

These studies do not test the proposed delayed all-taker question. The static maker result is no admission gate here: applying its zero-positive filter would create no candidates and answer nothing about dynamic basis. This diagnostic fits no predictor, chooses no horizon, estimates no half-life, and makes no performance promotion. A fifty-minute archive remains too short to validate a stable convergence process or justify multihour carry.

This is a paired-book quote-feasibility study. It omits leg-specific private order fills, limit-price execution/rejection, partial execution, and one-leg hedge/rescue paths. The 500 ms observations are explicit common quote delays, not normal-delay private execution or a limit-protected order simulator. The older convergence note proposes a broader execution study with those risks; this bounded diagnostic answers only its prior question about available delayed quotes. No executable or all-admitted execution P&L is claimed.

## Actual stopped inputs and metadata

Admit only `data/raw/rh-passive-exit-v1/20260930T0252Z`:

- `frames.jsonl.gz`: **48,680,716 bytes**, **124,019 records**, declared SHA256 `c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6`.
- `manifest.json`: complete/nontruncated, no errors, `duration_limit`; start **2026-09-30 02:52:57.958514 UTC**, end **03:42:58.061557 UTC**, configured duration 3,000 seconds.
- `metadata/normalized.json`, `market_plan.json`, and the three archived response/request pairs: `rh_order_book_details`, `hl_meta_native`, `hl_meta_xyz`. Normalized SHA256 is **34249d999bf176b73a2f9e30aa1602f3ab135a7cadc9238a080bfe060f048aba**. Response completions precede capture start by approximately 53 seconds. Validate their actual request/response hashes and selected market identities before implementation is run.
- `reports/rh-passive-exit-v1/protocol.json`: original 18-source protocol, normalized metadata SHA **15712b46e48d77fe971def33b91674173c57d649724bff66f7bcd75b95c4396d**. `reports/rh-passive-exit-v1-restart/protocol.json`: authoritative restart protocol for this capture, normalized metadata SHA **34249d999bf176b73a2f9e30aa1602f3ab135a7cadc9238a080bfe060f048aba**, matching the archived normalized file. Verify both actual protocol hashes and their unchanged 18-source inventories; compare this capture's metadata to the restart protocol, preserving the original pre-restart hash as provenance. The current restart replay freeze does not have a metadata mismatch.

| Asset | RH-domain market | HL market | RH Standard taker | HL public Standard taker |
| --- | --- | --- | ---: | ---: |
| BTC | 1 | BTC | 0 bp | 4.5 bp |
| ETH | 0 | ETH | 0 bp | 4.5 bp |
| NVDA | 15 | xyz:NVDA | 0 bp | 0.9 bp |
| XAG | 41 | xyz:SILVER | 0 bp | 0.9 bp |

Only RH-domain and HL books are present; Core/XAG93 is absent. HL depth is the recorded five-level fast-L2 snapshot. RH depth requires same-generation delta/nonce continuity. Public trades are archived but establish no private fills. Metadata supplies quantity grids, minimums and RH limits, dynamic HL price validation, and public fee assumptions. It does **not** supply account fee tiers, private processing clocks, historical funding payments/rates or verified funding schedules. Common base exposure, linear payout, and USDG/USDC parity remain inherited quote-screen assumptions, with no conversion or collateral claim.

## Exact candidate grid

Let `T=1790736777958514000` UTC nanoseconds, the actual capture start. Use both directions independently: long RH/short HL, and long HL/short RH. Include BTC, ETH, NVDA and XAG, public Standard fees only.

| Budget | Anchor offsets from T | Anchors per asset/direction | Original candidates | Four-horizon outcomes |
| --- | --- | ---: | ---: | ---: |
| $1,000, primary | `5*k` seconds, `k=0..599` | 600 | 4,800 | 19,200 |
| $100, diagnostic | `30*k` seconds, `k=0..99` | 100 | 800 | 3,200 |
| $250, diagnostic | same 30-second grid | 100 | 800 | 3,200 |
| $500, diagnostic | same 30-second grid | 100 | 800 | 3,200 |
| Total | no omitted tail anchors | — | **7,200** | **28,800** |

Each candidate has exactly four separate rows: **10 second quote control; 30, 60 and 300 second diagnostics**. All four share the same frozen quantity and single first eligible delayed entry record. Keep five fixed 600-second anchor strata, each containing 1,440 candidates/5,760 horizon rows. Production's ten-second hold stays unchanged. Smaller sizes have explicitly different sampling coverage and cannot be pooled with $1,000.

This post-capture grid spans the full original calibration and holdout periods. It does not inherit the passive replay's last-80-second admission washout or shorten admission to make future quotes available. All scheduled late anchors remain, including the final $1,000 anchor at T+2,995 seconds and each smaller-size anchor at T+2,970 seconds. It supplies no independent holdout.

At the anchor, apply all canonical events with receipt at or before it, including every event tied at that receipt. Validate both current books, then let `s` be the exact common lot (LCM of RH and HL size steps), `B` the anchor budget, and `a_long` the current long venue's best ask:

`q = floor(B / a_long / s) * s`.

Require positive q, common units, both venue quantity rules and minimums, grid-valid/noncrossed positive books, and anchor full-q entry walks. Freeze this **original q** once; never resize at delayed entry or exit. Initial missing/stale/depth/quantity/minimum/metadata failures stay in all four outcome denominators. The budget is a best-ask sizing reference: the **anchor full-depth walk may already exceed B** when q consumes multiple ask levels. Record `anchor_long_buy_notional` and `anchor_notional_exceeds_budget`, actual delayed long-buy notional, its difference from the anchor full-walk notional, and `entry_notional_exceeds_anchor_budget`. Excess over B can arise from anchor depth and subsequent price drift; keep both visible. Do not claim a strict B-funded execution, silently reject budget excess, or change q to repair it.

## First eligible paired entry and exit

All comparisons use exact UTC nanoseconds. Exchange source clocks are uncalibrated; the source-time requirements below are explicitly quote-observation assumptions, not measurements of private order arrival.

**Book eligibility:** positive `source <= receipt <= evaluation`; source and receipt ages at most two seconds; between-venue source and receipt skews at most one second; valid known generation/sequence; unchanged generation relative to the candidate's anchor. Validate exact RH grids and native dynamic HL price rules. Both venue source and receipt tokens must strictly advance from the relevant baseline, and both source and receipt timestamps must be at or after the due time.

**Entry:** request at the anchor, due at `anchor + 500 ms`, inclusive hard deadline `anchor + 2 s`. Use the first eligible paired state in that interval, with advancement from the anchor. Walk the long ask and short bid at q. Eligibility in this definition is timing/book validity, not the presence of enough size: the first eligible pair with inadequate full-q depth, minimums, or order limits terminates as `entry_depth`/`entry_minimum`/`entry_order_rule`; do not wait for a better pair. Otherwise freeze one entry receipt, both books' source/receipt/generation references, both entry notionals, and each entry fee for all horizons.

**Exit for H:** request at `first_entry_receipt + H`, due 500 ms later, inclusive hard deadline `first_entry_receipt + H + 2 s`. Use the first eligible paired state with advancement from that shared entry. Walk long bids and short asks at the same q. First eligible insufficient depth/minimum/limit terminates immediately as the explicit exit failure; no retry. Absent eligible entry/exit at a reached deadline is `entry_missing`/`exit_missing`.

Group all events sharing one receipt, apply them in canonical order, then evaluate candidates and timers. An eligible pair exactly at a hard deadline is evaluated before timeout. Fixed anchors likewise see all events tied at their timestamp. No later book repairs an earlier anchor or completed failure, and no book with a future receipt is used. Processing every intervening event permits first eligible outcomes between five-second anchors; outcomes are not sampled only on the anchor grid.

Explicit book invalidation, RH nonce gap, source regression, generation change, or connection close censors unresolved affected candidates/horizons. Trade-only invalidations do not erase quote depth. Once an explicit book gap occurs, later recovery does not repair that pending outcome. Endpoint source/receipt freshness is mandatory. A period with no book change is not automatically asserted to be tape loss: this is an endpoint quote diagnostic, not simulated inventory execution. Record whether either endpoint fails freshness; do not weaken the two-second threshold. This proposal does not claim continuously executable liquidation or known exposure throughout the hold.

Define the diagnostic's planned observation end as **T+3,000 seconds**, the completed manifest's configured duration. Apply all eligible book events through that cutoff, then settle already reached deadlines and classify still-pending rows as `entry_eof`/`exit_eof`. Continue the canonical traversal solely to verify stopped terminal/count/hash evidence; later quotes cannot improve an outcome. The archived final capture shutdown occurs after this configured cutoff. Its planned final connection-close/decoder invalidations do not convert these tail rows into unexpected feed-gap failures, and provide no liquidation quote. Genuine invalidations before the cutoff and deadlines already expired retain their original causes. A planned terminal close exactly at the cutoff has EOF priority for still-pending rows; an unexpected close before the cutoff remains an explicit gap. Preserve earlier initial failures rather than overwrite them. The 300-second tail is deliberately censored, never removed by shortening the candidate grid. Partial public depth is a quote failure, with no hypothetical partial inventory filled and no fabricated failure P&L.

## Economics and funding labels

For completed same-q quotes, let entry long-buy and short-sell notionals be `L_e,S_e`, and exit long-sell and short-buy notionals `L_x,S_x`:

`gross = S_e - L_e + L_x - S_x`.

Compute all four taker fees at their **own observed notional**, using each venue's frozen public rate. No two-times-budget substitute, private rebate or account discount. Report gross, each fee, fee-only net, stress, capital and adjusted quote net separately:

- `stress = 0.0005 * max(L_e, S_e)`, one declared pair risk allowance; it is not an exchange cash fee.
- `capital = (L_e + S_e) * 0.05 * elapsed_ns / (365 * 86400 * 1e9)`, where elapsed is actual exit receipt minus shared entry receipt. This is a frozen full-entry-notional 5% annual opportunity-cost proxy, not measured margin or financing.
- `adjusted_quote_net_ex_funding = gross - four_fees - stress - capital`.

Report exact counts `fee_only_net > 0`, `adjusted_quote_net_ex_funding > 0`, and `adjusted_quote_net_ex_funding >= $0.10` separately at each horizon. These are observed quote-feasibility counts, not trading returns. No unknown result is a known zero.

Funding-inclusive P&L is **unknown** because the archive lacks historical funding/payment data and a verified schedule. Flag whether the quoted holding interval crosses **03:00 UTC**, and separately flag an entry/exit exactly on that boundary. This top-of-hour flag is inherited conservative paper bookkeeping, not verification of either venue's actual funding calendar. Complete quotes may retain ex-funding economics while `funding_unknown=True`; a boundary-crossing quote never becomes a funding-inclusive positive. No funding credit is imputed and no multihour carry is analyzed.

Where full opposite-side depth exists on the **shared entry book**, also compute a same-q instantaneous liquidation reference `N_0` after four own-notional fees and stress, with zero elapsed capital. Its missing depth does not retrospectively reject an otherwise valid entry or later outcome. Report `N_H - N_0` and the deficit to $0.10 on their jointly observed subset. `N_0` is a zero-latency reference, not a private fill or feasible instantaneous round trip. Paired 10-versus-H contrasts require the exact same candidate/shared entry and both quotes complete; unequal coverage remains visible separately.

## Required coverage and interpretation

Conserve all 7,200 candidate IDs and 28,800 horizon IDs. Report initial failures, first-entry success/failure/missing/EOF, first-exit depth/rule/missing/EOF/gap, funding flags, quote complete coverage, and all cost columns by asset/direction/budget/H and five fixed anchor strata. Denominators are original candidates, not matched-only rows. Report matched-only economics alongside censor fractions and joint 10/H coverage; censored rows retain null economics. Do not allocate aggregate inventory exposure to quote cohorts.

The hindsight diagnostic is the count/distribution of positive **observed fixed-horizon quotes**. It does not choose the best future timestamp, the best horizon for each candidate, or an oracle execution path. Both directions, overlapping anchors, sizes and horizons share books; they are not independent trials, and no p-values or summed portfolio P&L are issued. An observed zero-positive result limits these covered delayed quote variants only. Positive quotes would support examination of a future, past-only selection hypothesis, not promotion or a new capture slot from this archive alone. No model fitting or threshold relaxation follows automatically.

## Before any approved implementation/run

Use a new helper/test/method and a new output directory; do not modify the frozen original 18/20/21 dependencies, current static/reverse helpers, their source copies, or published outcomes. Freeze the new implementation/test/method plus actual transitive decoder/adapter dependencies and all stopped input hashes before evaluation; verify them again before publication. Label the freeze post-capture exploratory, with no prospective holdout claim. The original full archive has already been inspected by other diagnostics.

One later approved canonical traversal only; no raw copy, event cache, capture or network. Require the existing gzip and manifest hashes, normalized/raw metadata hashes, complete verified nontruncated terminal, and exact 124,019 decoded records. Proposed read caps: raw gzip 50,000,000 bytes; decoded stream 128,000,000 bytes; record count 124,019; inherited bounded line/depth/trade-ID limits. Keep at most 800 unresolved candidate groups/3,200 horizon states and the eight current books; abort rather than drop candidates if a bound is exceeded.

Bound eligibility work with anchor/due/deadline heaps. Timers activate only currently due entry/exit windows; an event batch evaluates those active windows for its own asset, rather than scanning every unresolved candidate on every book. Explicit invalidation can touch unresolved states for the affected asset. Cache at most 4,096 full-q walk results keyed by exact book identity/side/q; eviction must cause recomputation, never omitted candidates or a changed first eligible time. This is needed for the 900-second budget, not an authorization to start implementation.

**Output ceiling: 3,000,000 bytes TOTAL**, including compact/compressed candidate/outcome rows, summaries, report, metadata/source freeze copies, manifest, verification and capped logs. Reserve indicative sublimits: candidate rows 450,000; horizon rows 1,850,000; summaries/report 300,000; source/metadata freeze 300,000; manifest/verification/log 100,000 bytes. Enforce sublimits and the aggregate bound before each write, including compressed bytes and staging; never silently truncate denominators. Publish staged output only after complete checks, with no overwrite or symlink replacement. A cap failure produces no completed report and triggers no automatic retry with a smaller grid.

The recorded shared allowance is 33,000,000 bytes with projected allocation 27,882,911 and headroom 5,117,089. Reserving 3,000,000 for this proposal leaves **2,117,089 bytes**. The actual static parent uses approximately 7.56 MB of its 16 MB reservation, but this plan does not spend that unallocated difference. The reservation includes this method and later copies; root must record the allocation before approving a run.

Supervise a hard **900-second wall limit**, no automatic retry, and capped logs within the same aggregate allowance. This is a maximum, not a runtime measurement. Cap/gap/timeout/incomplete verification leaves the diagnostic incomplete and supplies no economic conclusion.

Before root authorizes that traversal, synthetic fixtures must cover exact q/long-direction budget drift, four own-fee signs, shared entry across horizons, same-q future depth, first shallow pair failure without retry, advancement/source-future rejection, inclusive deadline/tied-event ordering, source regression/generation/nonce invalidation, funding boundary flags, initial failure and EOF denominator conservation, output cap before writes, and staged no-overwrite publication. This planning document alone authorizes none of those implementation or run steps.

## Resource amendment v2: retained failed first attempt

The first authorized attempt used the original reviewed source/test commit **1b79060827fa6dee6541c84ab3aa6be826f850e0**. It stopped with exit 1 before the 900-second deadline because compressed horizon rows exceeded their **1,850,000-byte category sublimit**, while the aggregate allowance was not yet exhausted. Its canonical terminal was verified before the writer failed. No completed economic summary or horizon-row file was published, so this is **no completed result** and supplies no profitability conclusion. Do not derive economics from the partial candidate CSV.

The first attempt's source/method/test copies, freeze and failure evidence remain unchanged in `reports/delayed-taker-quotes/0252Z-v1.building`; root records **460,596 retained bytes** and rechecked all 33 input/source hashes unchanged. Root has explicitly authorized this resource correction. There is no automatic retry.

For one **second and final** traversal, subject to independent synthetic code/test review, a new commit/freeze and root's explicit launch:

- Raise only the horizon-row category ceiling to **3,250,000 bytes** and the aggregate output ceiling to **4,000,000 bytes including 50,000 bytes of external logs**. The helper's internal ceiling is 3,950,000 bytes. Other category ceilings remain: candidates 450,000; summaries/report 300,000; source/metadata freeze 300,000; manifest/verification 50,000. These are individual maxima, not additional aggregate allowance; every write must satisfy both applicable limits.
- Preserve exactly **7,200 candidates/28,800 horizon rows**, horizons, first eligible timing, quantity, fees, stress, capital, funding flags, all invalid/missing/EOF statuses, and quote-only interpretation. No shorter grid, extra horizon, fee change or economic threshold change. Keep the **900-second supervised wall limit** and no automatic retry. A second failure is retained with no further traversal authorized by this amendment.
- Add a bounded **pure successful per-level validation** LRU: at most **16,384 entries** and **8 MiB conservatively accounted persistent cache bytes**. The key includes exact price/size representations and the frozen grid-validation rule fingerprint. Cached values are immutable Decimal price/size values that have passed the original positivity/finite/grid checks. Count all nested key/value objects even when shared, plus conservative dictionary/LRU/accounting overhead. An entry too large for the byte allowance is validated without being stored; eviction causes revalidation.
- Every emitted book still visits every level and eagerly checks shape, length, metadata grid, positive/finite price and size, ordering, duplicates and bid/ask crossing. Cache reuse changes computation only. Clock/source/generation/nonce/control handling remains eager; no book eligibility, quantity, fee, cashflow, outcome or timer state enters this memoization. Existing lazy Fraction materialization and the 4,096-result full-q walk cache are unchanged.
- Output cap errors must identify the category, requested/buffered bytes, current and projected category/aggregate bytes, both ceilings and violated limits before any file write. This distinguishes a category failure from an aggregate failure; it does not publish partial economics.

Required focused fixtures compare cached, disabled and forced-eviction engines on identical synthetic timelines, with exactly identical candidate/horizon statuses, quantities, timestamp references and economics. Check changed size and grid rules, nonfinite/off-grid levels, duplicate/unsorted/crossed books even when levels are cached, byte and entry caps, genuine gaps/generation changes, due/deadline/cutoff ties, first shallow failure and EOF. Separately test rich category and aggregate cap diagnostics before writes. These fixtures do not inspect the archive or failed partial economics.

Root's committed allocation **16be20f** reserves the new 4,000,000-byte report plus the preserved 460,596-byte failed attempt. The shared projected maximum is **32,343,507 of 33,000,000 bytes**, leaving **656,493 bytes**, with no increase to the 820 MB reservation and no new raw archive. The actual v2 dependencies and amended method must be frozen before root alone launches the second traversal. No speedup or v2 economic outcome is claimed from this resource amendment.
