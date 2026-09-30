# Active experiment and research loop

## User mandate, 30 September 2026 02:10 UTC

Run the proposed passive RH inventory-exit experiment and continue collecting,
researching and improving until the user stops the work or paper P&L is
convincingly positive. Public data and paper execution only. Maintain the
twenty-minute production reviews while experiments remain separate.

## Current status, 30 September 2026 07:22 UTC

The passive-exit replays and delayed taker diagnostic have completed without
a qualifying positive result. The next prospective spread-regime prerequisite
watch is in implementation review; its method and 500 KB allocation are frozen,
and no metadata or ticker request has started. See the latest entry below and
the [research map](README.md) for completed readouts. Production reviews continue
every twenty minutes, with the next due at 07:26:33 UTC.

## Original experiment: RH passive exit v1

- Assets: XAG primary; BTC/ETH continuous crypto controls; NVDA a separately
  labeled out-of-regular-session cohort in the current UTC window.
- Sizes: $100/$250/$500/$1,000; primary $1,000. Standard public fees primary,
  Premium as a separately accounted sensitivity. Branches cannot be summed.
- Entry: RH maker buy at a valid best bid, contingent HL short after attributed
  public trade flow. The study assesses possible queue fills, not private fills.
- Four exit comparisons: ten-second taker control, best-ask passive ten-second,
  cost-targeted passive ten-second, cost-targeted passive sixty-second.
- Primary decision: XAG / $1,000 / Standard / targeted passive ten-second.
- Same-entry comparisons require identical admitted entries. A slower branch
  must not be compared with a faster branch using different trading periods
  without also reporting candidate coverage and portfolio differences.
- Fixed passive exit price in v1; no hindsight repricing. Full lifecycle includes
  delayed activation/cancel, partials, contingent HL buybacks, emergency exits,
  late prints and unresolved obligations. No reset that erases exposure.
- Calibrate the adverse HL buyback move from prior public buy-aggressor flow;
  freeze it for the holdout. Fees, capital and the 5 bp stress are separate.
- Freeze method, all implementation dependencies and fresh metadata before
  capture. Thirty minutes of calibration followed by twenty minutes holdout;
  final 80 seconds admit no new entries to permit bounded liquidation.

Engine, coordinator, metadata and independent accounting/performance reviews
completed before the source freeze at 02:27:26 UTC (commit `6886d59`). The
50-minute capture started at approximately 02:27:32 UTC, with calibration until
02:57:32 and holdout through 03:17:32. Original frozen replay files and the
production strategy remain separate. See the preserved launch manifest in
`reports/rh-passive-exit-v1/launch.json`.

## Operational success threshold

This is a research stopping threshold, not proof of executable profitability.
Require the predeclared primary policy to achieve all of:

1. At least 100 fully closed cycles over at least two fresh twenty-minute
   holdouts, with positive total stressed net in each holdout.
2. At least $10 combined net after all modeled fill fees, the declared 5 bp
   stress and capital; profit factor at least 1.5.
3. The net and profit factor include **all admitted known outcomes**, including
   failed hedges, partial/rescue losses and zero-flow attempts. They are not
   conditional on successful cycle completion alone.
4. No unresolved economic obligations, missing required funding or execution
   uncertainty in the scored portfolio. Unknowns do not count as zero profit.
5. Results and adverse tails remain visible by size, tier and asset. USDG/USDC
   parity and public queue assumptions remain explicit limitations.

Repeated research and stopping when results look favorable introduce selection
risk. A later promising policy needs its own frozen confirmation windows; a
positive branch discovered among many alternatives is exploratory evidence.

## Loop

Implement → audit → freeze → collect bounded fresh data → replay → examine
all outcomes and coverage → write notebook and commit → choose one justified
next change or replication. During collection, review production on its
twenty-minute schedule and research the next concrete hypothesis. Never alter
an in-flight experiment's frozen source or train on its holdout outcomes.

Each capture and derived output has an explicit cap. Before any repeat, check
the cumulative research footprint and retain a bounded number of raw studies;
do not create an unbounded automatic capture loop. The user may stop the active
work at any time; stop study collection gracefully and preserve terminal
inventory and manifests rather than fabricate a close.


## Connectivity preflight, 02:21 UTC

A separate 30-second public-feed check completed normally: 1,287 raw records,
855,162 bytes including frozen metadata and manifest. It is neither calibration
nor holdout and has no modeled economic outcomes. The normalized feed supplied
56 HL books per asset (median gap about 0.535 s), RH books for all four assets,
and RH trades for all four. XAG had one trade and a maximum RH book receipt gap
of 2.148 s; this short check cannot establish sustained fill opportunity or
rule out the experiment's two-second validity/confirmation failures. Exact
counts and source-age diagnostics are in
`reports/rh-passive-exit-v1/preflight.json`. This preflight preceded the long
capture described above.

## Research during collection, 02:41 UTC

The old stopped quote comparison has no complete-cycle fill evidence. Its
[cost headroom chart](../reports/passive-hedge-venues/cost-headroom.svg) shows
median $1,000 static headroom above the $0.10 target of only +0.09 bp for
RH/HL silver and +1.46 bp for RH/Core silver. Every group misses the additional
5 bp stress allowance. Smaller sizes face a larger relative $0.10 target.
The [cost sensitivity](passive-cost-buffer-followup.md) separates actual modeled
fill fees from hypothetical amortized rebalancing and the unpaid stress.
Prepared future-only modules permit a separate quote-selection allowance and
bounded three-venue capture; neither changes current v1. A broader, bounded
public universe screen is being prepared to find assets whose quoted spread
can clear the hedge costs before investing another full capture in them.

Public queue evidence remains a separate barrier. The prior Standard BTC/ETH
branches became unresolved within about two minutes; Premium's later fills
were not comparable observations. See the [common-window diagnostic](rh-entry-queue-followup.md)
and [queue uncertainty research](public-queue-uncertainty-followup.md).
Future latency/queue scenarios must be explicitly assumed, preserve every
resulting hedge and exit loss, and stay separate from the strict v1 control.


## Interruption and prospective restart, 02:53 UTC

The first capture ended without a final manifest before calibration completed;
its raw bytes and interruption evidence remain preserved. It has no scored
holdout. The unchanged method was re-frozen with fresh metadata at 02:52:37 UTC
and restarted at 02:52:57 UTC in a new directory. Current calibration ends about
03:22:58 and holdout about 03:42:58 UTC. See the live-operations restart entry
and `reports/rh-passive-exit-v1-restart/launch.json`. No outcomes from the
interrupted raw file informed the strategy. New subagents use gpt-6.1-sol high
as explicitly requested; no in-place model change was used.

## Next TUI rollout requirement, 03:07 UTC

The user requested that headline paper results show **only the latest strategy
version**, so the current policy's performance is apparent. Preserve historical
ledgers and archives; exclude their accumulated P&L from the new headline.
Display an explicit strategy version and start time. Keep current-version
counts, wins, fees and realized net durable across process restarts and rolling
trade retention. Positions admitted under an earlier version remain carryover
exposure and must not enter the new version's realized result when they close.
Available wallet balances and capital constraints remain real paper state;
versioning is not permission to replenish or reset them. Prepare this for the
next planned rollout, with focused migration/restart/carryover/resize tests.

## Screen and correction freeze, 03:23 UTC

The completed independent universe replication ran 03:11:00–03:15:07 UTC:
21 eligible markets, five rounds, 105 HL books, 320/420 valid size observations.
All 100 rejected size observations failed source/receipt freshness. None of
the valid static cycles cleared fees, $0.10 and the separate 5 bp stress;
the best eligible $1,000 median was XAG at −$0.508121. No positive-profit
candidate was nominated. The two-round connection failure remains separate,
and cumulative request use is disclosed in the [readout](../reports/passive-universe-screen/20260930T0310Z/readout.md).
An offline optimistic zero-hedge-cost budget will check whether fee savings
alone could justify another venue screen. It cannot predict future fills
or bound a price-changing cycle's eventual return.

The [retirement correction](passive-retirement-correction.md) was independently
reviewed and frozen at **03:18:43.851172 UTC**, before both the conservative
03:22:37 source-freeze-based deadline and actual holdout boundary. It fixes
late qualifying flow received on the callback that retires an entry quote:
the affected old episode becomes execution-unknown. No fill or cash is
invented. The correction is explicitly a calibration-time amendment to a
capture already in progress. Its separate wrapper pins the original 18
files plus two correction files and will publish separately from strict v1.
The one-shot supervisor is waiting to run strict v1 after capture completion;
the corrected replay will run separately against the same stopped raw file.

During holdout collection, future ACK timing scenarios and a strict/corrected
comparison utility are being prepared with synthetic tests only. None reads
the active holdout or changes its frozen strategy. A less restrictive assumed
ACK clock can improve measurable coverage; it cannot establish a real queue
position, eliminate economic costs or demonstrate executable profitability.

## Completed capture and current preparation, 03:53 UTC

The replacement capture completed normally at 03:42:58 UTC with 124,019
records and 48,931,302 total archive bytes. Strict v1 and the separately frozen
entry-retirement correction are replaying the same stopped archive, each with
a one-hour limit. Their completed readouts remain pending. The 20 original
and correction source files remain unchanged.

The current-version TUI was deployed at 03:36:13 UTC. Version
`e3e83cda71a6` has its own persistent epoch; older positions keep their
original attribution and wallet balances were preserved. See the
[rollout verification](../reports/paper-strategy-epoch-review/rollout-verification.json)
and [version display method](paper-strategy-version-display.md).

The future ACK scenario adapter is implemented in commit `8fc0365` and has
passed independent synthetic review. A possible replay on this completed
archive will be explicitly exploratory and post-capture, with its own source
hashes and outputs. It includes historical-evidence guards, duplicate-ID
handling and coverage checks as well as clock assumptions; any difference
cannot be attributed solely to latency.

Synthetic review also confirmed a separate frozen-parent limitation: after
an unrelated branch halt, a newly received old-source buy can bypass the
retired passive-ask guard. The portfolio remains unknown, but an earlier
closed episode can incorrectly retain known status. Before using episode
contributions from either frozen replay, inspect retired passive-ask counts.
Zero retained asks rules out this particular defect; retained asks with a
halt require separate historical-evidence adjudication. Keep the frozen
results intact and label any affected reported contributions provisional.

No further raw capture starts until the cumulative raw-study count is
reconciled with retention policy. Offline quote-distance arithmetic and the
storage review can proceed without collecting another archive.

## Frozen readout and next bounded diagnostic, 04:11 UTC

Both frozen replays completed at 03:58 UTC. The
[readout](../reports/rh-passive-exit-v1-restart/readout.md) has 29 known
complete independent portfolios, all negative, and 99 unknown. Primary
Standard XAG/$1,000 admitted 57 attempts and closed 56 without flow before
cancellation ambiguity; no completed primary trading cycle or paired
comparison. The entry-retirement correction changed no admissions or episode
classifications on this input. Eleven halted branches with retained passive
asks have provisional closed contributions withheld from validated inference.

Crypto targeted asks repeatedly exceeded the fixed 5 bp ceiling and were
not posted. The [static exit-distance diagnostic](../reports/passive-universe-exit-markup/0310Z-input-v1/readout.md)
confirms that cost-covering quote distances can exceed that ceiling, without
establishing any maker fill. The subsequently completed stopped-data
[flow-reach diagnostic](../reports/rejected-target-public-reach/REPORT.md)
found no eligible observed buy print reaching any of the 150 rejected targets
within its fixed window. Widening the ceiling alone is unsupported.

The base and plus200 exploratory ACK scenarios launched at 04:10:54 UTC,
each in its own process with a one-hour deadline and bounded outputs.
Their 21 dependencies are immutable through both runs. These scenarios keep
the frozen price/fee policies and expose execution-model sensitivity; a
favorable result would still need a separate prospective confirmation.

The [fixed storage amendment](experiment-storage.md) now preserves all seven
current raw archives and permits at most one additional 128 MB complete
archive, subject to separate design/freeze/preflight, under a fixed eight
archive/512 MB selected-raw limit. No new capture has launched. Next
production review after review 45 is 07:26:33 UTC.

## Completed ACK sensitivity, 04:30 UTC

Both exploratory scenarios completed with stable dependency hashes: base at
04:26:25 UTC and plus200 at 04:23:27 UTC. Base has 12 conditional complete
portfolios, all negative, and 116 unknown; plus200 has all 128 unknown.
The [comparison](../reports/rh-passive-ack-exploratory/readout.md) preserves
all four models and all six cohort alignments. The primary XAG branches
remain without a completed trading cycle. Timing-model changes combine
different clocks, coverage and historical-evidence checks; reduced losses
in partial records cannot be interpreted as improved profitability.

Next work checks the dominant coverage and late-anchor halt causes and
inventories existing evidence for a contemporaneous spread admission gate.
No further raw capture is justified by the results so far. Production review
37 remains negative; no strategy promotion or wallet reset.


## Fixed-anchor feasibility result, 04:59 UTC

The predeclared one-second scan of the completed 50-minute RH/HL archive
finished at 04:57:02 UTC, with one canonical traversal, unchanged hashes and
7,554,465 output bytes below its 16 MB cap. The
[readout](../reports/passive-rare-spread/0252Z-fixed-1s-v1/readout.md) preserves
all 48,000 scheduled asset/size/time rows: 47,624 valid, 20 initially missing,
304 stale and 52 lacking sufficient recorded HL depth. **Zero valid positives**
after four public fees, $0.10 and 5 bp stress, across every size/asset/stratum.
The best $1,000 margins are XAG−$0.373095, NVDA−$0.428904,
BTC−$1.298121 and ETH−$1.294737; all recurrence thresholds fail.

This stops the contemporaneous RH-maker/HL-taker gate on the covered fixed
anchors and quantities. It does not test Core, every market time, other assets,
price-changing cycles or future regimes. Capital/funding and actual execution
remain outside this static margin, and correlated observations are not treated
as independent trials. No new capture or strategy promotion follows.

The [reverse HL-maker/RH-taker bound](../reports/passive-rare-spread-reverse-bound/0252Z-v1/REPORT.md)
completed at 05:13:04 UTC after method/source commit `de2fdef` and nine
passing synthetic tests. All 47,624 evaluated upper bounds are nonpositive;
376 parent-invalid rows remain reverse-unadjudicated. All 48,000 identities
and 80 asset/size/stratum groups are retained. Published output is 852,744
bytes under the 2 MB allocation, with unchanged parent/source hashes and
no raw traversal or network request. This excludes only the unchanged
best-quote reverse margin at inherited q, with target and stress but excluding
funding. Other quantities, wider quotes and price-changing cycles remain
outside the bound. It supplies no reason for a new capture or promotion.


A supplemental [derived-row verification](../reports/passive-rare-spread/0252Z-fixed-1s-v1/verification.json)
was added after original publication; all manifest-covered files stayed
unchanged. Total with this 1,338-byte attestation is 7,555,803 bytes. Its
48,000 CSV rows, 12,000 timing references and all five strata reconcile.
At $1,000, 942 XAG and 69 NVDA observations clear trading fees plus $0.10,
but zero clear the additional 5 bp allowance. The greatest fee-only quoted
margins are XAG $0.226464 and NVDA $0.170798; BTC and ETH remain negative
even before target and stress. These assumed-fill quoted margins do not
establish execution or realized profit. The declared stress allowance is
separate from charged fees and has not been lowered after seeing results.

## Delayed taker quote diagnostic, 05:21 UTC

The [reviewed method](delayed-taker-fixed-quantity-plan.md), committed as
`71e4127` before implementation, tests a distinct question on the same stopped
archive: whether later basis movement can cover delayed four-taker quote
costs. It fixes 7,200 original candidates across both directions, four assets
and four sizes, each with a shared delayed entry and separate 10/30/60/300 s
outcomes. All 28,800 rows, initial failures and EOF outcomes remain visible.
Fees, stress, capital and unknown funding are separate. Paired quotes do not
model private fills, price-limit rejection, partials or hedge rescue.

Implementation and independent review completed with 31 passing synthetic
checks; source/tests were committed as `1b79060` before evaluation. One
canonical traversal launched at 05:48:25 UTC with its 33 input/dependency
hashes persisted before traversal. Output target:
`reports/delayed-taker-quotes/0252Z-v1`. An external 900-second deadline
and internal cap enforce the bound (deadline approximately 06:03:25 UTC).
The 3 MB aggregate output allocation is recorded in `d9e8124`; no raw
archive is added. The process exited with code 1 before the deadline:
the compressed outcome table exceeded its 1.85 MB sublimit. No completed
economic result was published. Preserve the 460,596-byte `.building`
directory and its [failure record](../reports/delayed-taker-quotes/0252Z-v1.building/failure.json);
all 33 input hashes were rechecked unchanged after failure.

A separate resource amendment passed root and independent review with 40
focused tests. Commit `337097a` freezes 4 MB maximum output, a larger outcome
sublimit, and bounded memoization of pure repeated level validation. Every
book's structural/grid validity and all timing rules remain enforced.
Candidate grid, economics, 900-second limit and stopped input remain fixed.
The second and final authorized traversal launched at 06:17:02 UTC into
`reports/delayed-taker-quotes/0252Z-v2`, with 33 dependency/input hashes saved
before traversal. Deadline approximately 06:32:02 UTC. Results remain pending;
no automatic retry or partial-result conclusion follows.
This is post-capture exploratory analysis with no automatic policy selection,
capture or promotion.


### Second attempt failure and separate resource amendment, 06:33 UTC

V2 ended with external timeout exit 124 at its original 900-second limit.
Its full canonical terminal was not verified and no economic results were
published. All 33 frozen inputs were rehashed unchanged; 117,265 bytes of
source/freeze/failure evidence are preserved in `0252Z-v2.building`.
An attempted early termination had been rejected by automatic approval
review and was not executed; the original timeout ended the process.

The author reproduced default-cache thrashing on synthetic 40,000-level
working sets: four cycles took about 0.8122 s cached versus 0.1866 s with
the original validator and 0.1981 s with the existing cache disabled. The
cache recorded zero hits, 160,000 misses and 152,007 evictions. This is a
synthetic diagnosis, not a measured hit ratio for the stopped archive.

Root explicitly supersedes the v2 second/final limit for one additional
resource-only revision, subject to independent review and a new commit/
freeze before launch. Inject the existing disabled-cache path; preserve
the full 7,200/28,800 grid and all economic/timing/validity criteria. Set
a fixed 1,200-second internal/external deadline, based on the first
attempt completing its canonical traversal within 900 seconds and the
limited synthetic comparison; completion is not guaranteed. Retain the
4 MB aggregate and 3.25 MB outcome limits. No automatic retry.

The v3 allocation reserves both failed attempts plus the new run and
20 KB additional documentation: 32,480,772 of 33,000,000 bytes, leaving
519,228 bytes. The 820 MB total reservation and raw archive count stay
fixed. Implementation is authorized; the traversal has not yet launched.

V3 passed root and independent review with 41 focused tests. Commit
`92f74a7` freezes the minimal uncached recovery before its one authorized
launch at 2026-09-30T06:37:00.151635+00:00. The helper saved all 33 hashes before
canonical traversal into `reports/delayed-taker-quotes/0252Z-v3.building`.
The fixed external deadline is approximately 2026-09-30T06:57:00.151635+00:00.
No other replay or raw capture is launched. Results remain pending;
no fourth attempt is authorized by this amendment.


### Delayed taker diagnostic completed, 06:52 UTC

The separately frozen v3 run completed at 06:52:04 UTC in 904.45 seconds.
All 7,200 candidates/28,800 outcomes remain, with 26,395 complete quotes
and 2,405 incomplete. **Every complete quote is negative after fees alone**
at each of 10/30/60/300 seconds, including all sizes and both directions.
All 33 actual input hashes and nine published output hashes match; the
independent derived-row verifier passed. Completed output is 2,530,132 bytes.
See the [audited readout](../reports/delayed-taker-quotes/0252Z-v3-analysis.md).

A separately labeled unchanged-quote fee-reduction bound also has zero
positives even after forgiving all trading fees while retaining original
stress/capital. It does not price another venue, maker execution or funding.
The completion reconciliation releases unused v3 output allowance and
reserves 100 KB for derived analysis/audit, giving 31,110,904 of 33,000,000
bytes. Both failed attempts remain; no new raw archive or replay follows.
These findings do not justify a selector fit, threshold relaxation,
strategy promotion or additional capture. The ongoing production review
schedule continues; the next review is 07:06:33 UTC.


### One prospective spread-regime prerequisite watch, 07:18 UTC

The old LIT optimistic peak does not justify a Core-specific static rerun:
only one of five valid rounds was positive and its median was negative.
Nonnegative hedge spread/fees can only tighten that unchanged-price bound.
No Core quote screen or full execution capture is launched.

A distinct [prospective method](rh-spread-regime-sentinel-plan.md), committed
as `f87191b` after root and independent review, asks whether NEW RH spreads
persistently pass the necessary ex-funding static cost budget across all
21 original assets. One fixed 20-minute window has 20 minute slots and
1,680 original size observations. The primary gate requires 16/20 valid,
a positive full-window median and positive medians in at least three of
four fixed five-minute blocks, each with at least four valid samples.
There is no economic readout before the endpoint or automatic repeat.

The 500 KB allocation `65fe3a0` explicitly counts new sampled public-network
evidence, including full fresh metadata, selected raw ticker messages,
source, derived rows, logs and failures. It is not a canonical flow archive
or evidence reuse. Projected shared maximum is 31,610,904 of 33,000,000 bytes.
At most three metadata requests and one RH ticker connection are permitted;
no Core/HL book calls or trade subscriptions. Receipt/sample clock guards
precede timestamp acceptance, with no clock rebaselining or stale fallback.

Implementation is authorized after method review; no new metadata or ticker
request has been made. Root will review code/tests, then separately review
fresh metadata and freeze sources before launching. Even a positive
prerequisite supplies no paired hedge, maker-fill or profitability evidence.


### Production review 46, 07:26 UTC

The complete twenty-minute review adds cooldown 50 exact closes/−$60.6943
and Premium three/−$5.1906, both zero wins. Cooldown remains −$35.7272
without the stress allowance. Current-version closed totals are −$758.7532
cooldown and −$155.3691 Premium; two cooldown positions are open in the
separate later snapshot. Four feeds remain connected. The sentinel is still
in implementation review with no collection started. Next production review:
**07:46:33 UTC**. Full accounting is in the [review journal](review-loop.md).
