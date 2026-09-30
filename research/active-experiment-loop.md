# Active experiment and research loop

## User mandate, 30 September 2026 02:10 UTC

Run the proposed passive RH inventory-exit experiment and continue collecting,
researching and improving until the user stops the work or paper P&L is
convincingly positive. Public data and paper execution only. Maintain the
twenty-minute production reviews while experiments remain separate.

## Current experiment: RH passive exit v1

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
production review after review 38 is 05:06:33 UTC.

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

A separately bounded derived-data diagnostic is being prepared for the reverse
HL-maker/RH-taker route at inherited q. Its optimistic static upper bound uses
full recorded HL walk notionals and actual frozen maker fees; nonpositive
bounds rule out only that fixed-quote margin on covered rows. Parent-invalid
rows remain reverse-unadjudicated, and positive bounds are inconclusive.
It requires no further raw traversal or new archive.
