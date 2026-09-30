# Future hypothesis: admit only a contemporaneous rare spread

**Design note only; no implementation, capture, nomination or promotion.**
Current evidence does not justify spending the one remaining raw-study slot.
The proposed hypothesis is that an infrequent, already wide RH bid/ask spread
can cover a real hedge roundtrip before an entry is admitted. It requires fresh
evidence of that event and a later lifecycle test.

## Evidence and missing information

The [completed universe screen](../reports/passive-universe-screen/20260930T0310Z/readout.md)
had 320 valid size observations and 100 stale exclusions across 21 assets;
no actual HL-cost observation cleared fees, the $0.10 target and 5 bp stress.
All 17 eligible asset medians failed. Five minute-spaced rounds cannot exclude
rare opportunities between samples, but this sampling limitation supplies no
positive evidence for them.

The [zero-cost bound](../reports/passive-universe-hedge-budget/0310Z-input-v1/readout.md)
found only one LIT market/round with positive budgets, at $500 and $1,000;
retaining its observed HL fee amounts erased both. That shows RH spread varies
enough to motivate a *question* about tails. It does not nominate LIT, estimate
recurrence or establish a real Core hedge opportunity. The earlier
[matched hedge-venue diagnostic](passive-hedge-venue-followup.md) also had zero
positive stressed observations on its covered assets. The fresh broad screen
contains no matched Core books.

Before allocating the [128,000,000-byte raw slot](experiment-storage.md), the
minimum missing evidence is repeated actual-cost gate-positive episodes in
already retained, simultaneous RH/Core/HL books: verified common units/lots,
own venue fees, exact depth and source/receipt timing, plus enough public RH
flow and book continuity to assess whether those episodes survive a plausible
entry activation. First evaluate existing three-venue evidence at fixed times
with the rule below and preserve its coverage denominator. Require at least
three separated positive episodes across two fixed ten-minute windows, rather
than many frames from one spread excursion. Count one episode until a valid
nonpositive anchor rearms it; a coverage gap cannot manufacture a new episode.
This is a prospective feasibility
threshold, not a profitability threshold; historical reuse remains exploratory,
not an independent confirmation. If the existing evidence cannot
supply those inputs or has zero valid positives, stop the proposal. A new
stored “preflight” is still an archive and cannot bypass the scarce-slot budget.
The present evidence does not meet this prerequisite.

## Admission and matched comparison

Freeze the exposure-audited universe, IDs, fresh metadata/volume exclusions,
sizes $100/$250/$500/$1,000, sampling schedule and session strata before any
future observation. Do not select an asset from the LIT peak. On every fixed
decision anchor, use only already-received RH, Core and HL books with source
and receipt ages/skews <=2 seconds, valid continuity, grids and sufficient
depth. Missing Core or HL coverage is missing paired coverage, never a later
substitute book. Use one unchanged q rounded down on the common three-venue
lot; preserve minimum/maximum notional failures.

For hedge venue v, compute its displayed sell proceeds S_v and buyback cost
B_v at that q. Require **strictly positive**:

`q*(RH ask-RH bid) + S_v-B_v - all four own-notional public fees`

`- $0.10 - 0.0005*max(q*RH bid, S_v)`.

Core Standard's zero public fees must be freshly verified; its bid/ask spread,
depth and processing delay remain costs/assumptions. HL uses its exact fresh
native/HIP-3 public schedule. USDG/USDC parity remains conditional. Evaluate
both routes on the same received books, prices and q before either admission.
Report neither/Core-only/HL-only/both passing. Route-specific gate portfolios
have separate admission histories. Compare execution outcomes causally only
on the both-passing intersection with identical RH entry episodes; report
that intersection and route-only coverage explicitly. Never subtract unequal
portfolios or sum correlated branches.

## Denominators, lifecycle and stopping

Record every frozen asset × size × scheduled time, including metadata
exclusions, stale/missing books, depth/lot failures, valid nonpositives, valid
positives, occupancy-blocked attempts and actual paper admissions. Report
eligible time, missing time and independent positive excursions by asset and
session, not only favorable samples. A fixed feasibility endpoint with zero
valid positives stops the study; it does not trigger extra time, broader
routes, relaxed freshness, a smaller target or lower stress.

For a later separately frozen lifecycle test, fix RH entry at the gate bid and
exit at the gate ask; quote validity and activation remain conditional. Use a
five-second entry rest and ten-second exit horizon, with a separately reported
sixty-second sensitivity on the same entries. Freeze acknowledgment/cancel
assumptions, venue hedge delays, rescue deadlines and terminal reconciliation
before holdout. Public flow is conditional queue evidence, not a private fill.
Report gate pass, quote request, attributed fill, hedge and completed exit
denominators separately; conditional filled-cycle results cannot replace the
all-admission ledger.
Include no-flow attempts, partial fills, failed/late hedges, post-only failures,
rescues, funding/capital costs and unresolved obligations in every admitted
ledger. Unknown execution is not zero P&L. No repricing, route choice, quote
ceiling, horizon or delay tuning from holdout; no extension until a favorable
result. Calibration and confirmation windows remain separate.

Any later launch must freeze wall-clock windows and sampling cadence and cap
the complete archive at 128,000,000 bytes, including metadata and manifest.
Neither routes nor time/byte caps may expand after observing holdout outcomes.

## Why this hypothesis needs its own evidence

The [rejected-target reach diagnostic](../reports/rejected-target-public-reach/final-analysis.json)
records observed nonreach for all 150 reconstructed targets that exceeded the
old 5 bp ask ceiling, including the preliminary result. Incomplete public tape
and assumed activation prevent an absolute no-fill claim; reaching a print
would not establish queue priority either. Increasing that ceiling would post
farther exit asks *after* exposure and rely on later price/flow to reach them.
This hypothesis filters *before* exposure and requires economics at the
already-observed best bid/ask; it does not rescue rejected exit targets.

Rare spreads may accompany stale prices, thin depth, disappearing quotes or
adverse selection. Even repeated fresh positives might fail entry/exit queue
or lifecycle checks. Until recurrence and activation coverage are established,
another capture can consume the scarce slot without a plausible admission.
Retain this note as a conditional research option, not a launch decision.

## Appendix: bounded retained-evidence inventory

**No inspected archive establishes all prerequisites, including two complete
ten-minute windows.** This inventory read the seven-study
[retention inventory](../reports/experiment-storage/inventory-eight-20260930T0351Z.json),
capture manifests, frozen plans/metadata provenance and existing summaries;
it did not open raw gzip, book JSONL or trade payload files. Durations below
are manifest wall-clock spans, not assertions of continuous valid coverage.

Paths in the first table are under `data/raw/`; links open their manifests.
All three maker captures record RH/Core order-book and RH trade channels plus
HL L2, UTC/monotonic receipt stamps, exchange source-time annotations and
connection generations. These are candidate inputs for an eventual frame
audit, not proof that every contemporaneous anchor passes freshness.

| Retained archive | Declared span | Inputs and blocking requirements |
|:---|---:|:---|
| [maker-capture/20260929T1823Z](../data/raw/maker-capture/20260929T1823Z/manifest.json) | 394.141748 s | BTC/ETH, three venues; size-cap truncation. Simultaneous socket overlap at most 394.044527 s. No copied plan in directory; manifest's mutable monitor-plan hash differs from the present file. Insufficient duration and incomplete frozen metadata provenance. |
| [maker-capture/20260929T1939Z](../data/raw/maker-capture/20260929T1939Z/manifest.json) | 420.131403 s | BTC/ETH, three venues, untruncated; socket overlap at most 420.117862 s. Frozen lot/fee plan exists; no ten-minute window. |
| [maker-capture/20260929T2022Z](../data/raw/maker-capture/20260929T2022Z/manifest.json) | 420.037339 s | NVDA/XAG, three venues, untruncated; socket overlap at most 420.029302 s. Frozen plan plus fee/unit responses exist; no ten-minute window. |
| [rh-small-maker/20260929T212132Z](../data/raw/rh-small-maker/20260929T212132Z/manifest.json) | 3000.192830 s | Four assets, RH/HL depth, RH flow and copied normalized metadata; no Core. RH reconnect also requires coverage treatment. |
| [rh-passive-exit-preflight/20260930T0222Z](../data/raw/rh-passive-exit-preflight/20260930T0222Z/manifest.json) | 30.147511 s | Four assets, RH/HL depth/flow/metadata; no Core and insufficient duration. |
| `rh-passive-exit-v1/20260930T0227Z` | Actual span unverified | Interrupted RH/HL capture with copied metadata, no final manifest and no Core. Intended 3000 s cannot substitute for observed duration. |
| [rh-passive-exit-v1/20260930T0252Z](../data/raw/rh-passive-exit-v1/20260930T0252Z/manifest.json) | 3000.103043 s | Four assets, RH/HL depth/flow/timing and copied normalized metadata; no Core. |

For 19:39, the copied
[market plan](../data/raw/maker-capture/20260929T1939Z/market-plan.json)
matches its manifest hash and declares common BTC/ETH lots 0.00001/0.0001,
minimums and public fees. Full fresh exchange-response provenance is not
established by that plan alone. For 20:22, the
[plan](../reports/maker-equity-v2/market-plan.json) matches its manifest hash;
[unit provenance](../reports/maker-equity-v2/unit-provenance.json) and
[fee inputs](../reports/maker-equity-v2/fee-inputs.json) retain 20:19 market
details/HL context and support common NVDA/XAG lots 0.001/0.01. No short
archives are stitched into longer windows, and none covers LIT or the full
21-asset hypothesis universe. The `rh-maker-symmetric-v1` and
`passive-three-venue` raw roots contain no archive in the reviewed inventory.

Other retained artifacts do not fill the gap:

- `reports/passive-universe-screen/20260930T0310Z`: 247.046922 s, five
  RH-ticker/HL-depth rounds with source/receipt times, frozen metadata and RH
  flow; no Core, no RH depth beyond BBO, and insufficient duration. Its first
  attempt at `20260930T0303Z` lasted 123.497411 s and stopped on disconnect.
- `data/raw/live/20260929T035450Z`: 34 min 9.380077 s of HL/Core REST sampling;
  `data/raw/comparators/rh_lighter/20260929T040726Z`: 19 min 1.792664 s of RH/HL
  REST sampling. Their wall-clock overlap is only the latter interval;
  RH REST depth lacks an explicit book-source timestamp and no RH public
  trade stream is declared. These cannot establish two matched windows.
- Other inspected legacy manifests describe shorter HL/Core runs, Aster/dYdX
  comparison, HL metadata/history, or Robinhood canonical-token AMM quotes.
  They do not supply the missing RH/Core/HL perpetual depth-and-flow panel.

Thus existing manifests can support narrower exploratory diagnostics, but
cannot satisfy the proposed recurrence/activation prerequisite. No raw scan,
window shortening, missing-venue substitution or new collection follows from
this inventory.
