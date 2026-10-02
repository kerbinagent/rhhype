# Parallel collection and research — 2 October 2026

The user requested broader exploration alongside deeper Sol analysis and
allocated 2 GB for rolling captures. Two hours was an illustrative working
window, not a limit on how long an idea may be studied.

## Responsibilities

| Lane | Work | Deliverable |
| --- | --- | --- |
| Public collector and routine monitor | Reuse a fixed ten-asset Core/RH cohort; publish sealed ten-minute chunks independently of research. Monitor coverage, gaps and storage. | Verified raw chunks and operational metadata, without trading decisions. |
| Root researcher | Read prior evidence and relevant primary research, prioritize distinct mechanisms, define falsifiers and controls, decide advance/park/inconclusive. | A short current [decision register](research-decision-register.md), not a new collector per idea. |
| Two Sol analysis assignments | Answer bounded questions on explicitly assigned completed chunks; reuse existing quote/replay components. | Full denominators, cost-aware comparisons, missing outcomes and a decision recommendation. |
| Autonomous Parler peer | Own cross-asset propagation and other distinct mechanisms on an isolated branch; freeze bounded diagnostics before outcomes and coordinate shared inputs. | Continuing research, implementation and falsification within the [8 MiB allocation](../reports/experiment-storage/parler-peer-research-v1.json); updates at material decisions. |

## Shared data and retention

The new store is `data/rolling/market-research-v1`. Its hard ceiling is
**2,000,000,000 bytes**, including raw frames, metadata, seals, index and
controller files. Each independent capture has a 64 MiB raw cap and a
ten-minute target. Fresh metadata and reconnection boundaries create measurable
gaps; adjacent chunks must not be described as gap-free observations.

Retain chunks as long as the store has room. Under space pressure, expire the
oldest eligible unpinned chunks, retaining each for at least two hours after
sealing. Readers pin completed chunks before opening them and unpin only after
closing them. Keep pins on data required by active experiments or promoted
results. If pins and recent data leave insufficient space, report
`storage_blocked`; do not erase pinned evidence or exceed the cap. Automatic
expiry applies only to this new store's recognized chunks.

The controller has a 48-hour runtime bound and an explicit stop command. Root
reviews continuation under the ongoing research instruction. This is an
operational bound, not a two-day profitability claim.

The v1 coverage field `invalid_frames` counts all qualities other than
`wire_ok`, including valid initial books tagged `wire_ok_snapshot`. It is not
a count of malformed frames. The first chunk's 20 such market frames were
all valid initial snapshots; downstream analysis uses the adapter's actual
quality checks. The frozen collector continues with this field documented.

Its `live_trade_prints` field counts rows in `trades[]`, which can include
liquidations also listed in `liquidation_trades[]`. Use explicit subtype and
deduplication checks for ordinary-flow counts; do not sum the arrays as distinct
events. The initial inventory run exposed the old adapter's rejection of these
known mixed types. Preserve that [coverage-limited result](../reports/single-venue-research/inventory-context-batch1-readout.txt)
and repair the adapter under the [separate allocation](../reports/experiment-storage/ordinary-feed-adapter-repair-v1.json)
before interpreting the full cohort. The corrected reruns use the same frozen
methods and separate outputs under `reports/single-venue-research/ordinary-feed-fix-v1`.
Original raw frames remain intact.

## Exploration and validation

Assign roles before collection: three exploratory chunks followed by three
reserved chunks, repeating. A reserved role grants no validation claim by
itself. A prospective test must identify its rule, comparator, costs and decision
criterion before the designated data begin. Data whose outcomes influenced a
rule are exploratory for that rule, even if reloaded in a fresh process.

Sol tasks receive named chunks and an analysis/output budget. Pin those inputs,
respect their roles, and report all selected groups and failures. Do not inspect
reserved economics while choosing the model. Do not treat adjacent chunks or
correlated assets as independent market regimes. The separately frozen news
and carry studies retain their own analysis boundaries and ownership.

## Current research queue

1. **Local shock recovery:** the old ordinary-window control check is sparse
   and inconclusive. Two local quote gains coincided with larger favorable
   reference moves. Keep its fixed matching rule and seek more distinct events.
2. **Delayed directional response:** the fixed diagnostic now tests this
   directly. Its 26 selected episodes and nine cost-plausible episodes were
   negative on average in both old windows. Park this version; no group passed
   its replication criterion. See the [readout](../reports/single-venue-research/directional-response-readout.txt).
3. **Changing order flow:** the corrected [feature preflight](../reports/experiment-storage/single-venue-flow-recovery-ordinary-feed-fix-v1.json)
   measures continued trade flow and restoration of depth in the original
   price band. It uses exploratory chunks 1–3 and 7–9; the reserved chunks stay
   unopened. Establish support for both flow states before an outcome study.
   The [completed preflight](../reports/single-venue-research/ordinary-feed-fix-v1/flow-recovery-batch2-readout.txt)
   contains 17/14 selected episodes, with 5/3 slow states and zero persistent
   states. The fixed measurement gate fails; park this version. A large print
   or subsequent quiet does not establish parent-order completion.
4. **Inventory context of aggressive flow:** the economics-free
   [field audit](../reports/single-venue-research/inventory-field-availability.txt)
   found explicit pre-fill positions on all 14,138 ordinary trades in the two
   old captures. Chronologically ordered within-message position changes
   reconcile. The signed, per-fill interpretation remains a stated empirical
   assumption. The corrected [inventory protocol](../reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json)
   compares delayed fade quotes after reducing versus adding flow, using earlier
   controls matched on entry cost and recent return/flow. It uses chunks 1–3 and
   7–9 and retains all 1,140 scheduled anchors per batch. Any conditional
   improvement must also survive absolute costs before an execution study.
   The corrected [two-block result](../reports/single-venue-research/ordinary-feed-fix-v1/inventory-context-batch2-readout.txt)
   processes 25,720 and 26,565 ordinary prints. No group meets the fixed gate
   in both blocks. BTC/Core has only four/two pairs and negative absolute
   reducing quote means in both. Park this version without tuning calipers.
   RH/BTC also exceeded the frozen 5,000-level decoder state bound in chunks
   8 and 9; 22 anchors have unusable books and one adding profile lacks a close.
   These failures remain explicit, including missing reference contributions.
5. **Observed queue OFI:** the [fixed linear comparison](../reports/single-venue-research/queue-ofi-publication-fix-v1/readout.txt)
   fits 13 of 20 cells; seven lack 40 training labels. None of 60 cell/size
   policies meets the three-chunk forecast, support and cash gate. Park this
   version. A publication-only successor increased the file allowance and
   reused the first table exactly; scientific rules stayed frozen.
6. **Passive PERP strict-through:** the [fixed screen](../reports/single-venue-research/passive-through-v1/readout.txt)
   evaluated all 120 market/side/size alternatives. None passed the initial
   three-block gate; later blocks stayed unopened. The 610 full-witness profiles
   include 557 complete conditional values and 53 retained unknown closes.
   Public witnesses remain conditional on accepted/live placement and matching
   assumptions. Park this version without an execution branch or tuning.

The [corrected news companion](../reports/experiment-storage/single-venue-news-ordinary-feed-fix-v1.json)
is separately frozen and armed for the original October 2 capture. It applies
the same ordinary-subtype correction to both families, then uses the existing
independent signal/cash auditors. Original capture, helper, methods and outputs
remain intact. Capture and corrected analysis hashes have separate roles.

Liquidation events are a possible separate mechanism. The ordinary adapter
counts and excludes `liquidation_trades`; the raw capture retains the field.
The two old broad windows contained zero live liquidation rows. The first three
rolling chunks contain 0, 3 and 61 rows in those arrays before deduplication.
A [schema and clock audit](../reports/single-venue-research/liquidation-field-availability.txt)
found 64 unique liquidations but only 11 asset episodes at 30-second spacing;
these episodes are still dependent. The official Core
[WebSocket schema](https://apidocs.lighter.xyz/docs/websocket-reference)
defines separate ordinary and liquidation arrays; RH availability requires its
own observed evidence.

Lighter documents partial liquidations as IOC orders, while full liquidation
and deleveraging involve position takeovers or matched transfers. This motivates
checking row subtypes and order identities before interpreting them as book
pressure. The public API serialization boundary remains a separate question.
[Liquidation mechanism](https://docs.lighter.xyz/trading/liquidations-and-llp-insurance-fund).

A distinct candidate question is whether a liquidation label predicts another
same-direction liquidation from a different public taker order within two
seconds, beyond comparable ordinary position-reducing flow. This would test
forced-flow persistence before another price-recovery replay. Initial-message
fills, late clocks, missing controls and interrupted windows must remain
explicit. The [frozen observability preflight](../reports/single-venue-research/liquidation-delay-v1/readout.txt)
witnessed one different public order after 400 ms–2.4 s among 9/2 complete episodes.
Stale ordinary evidence suppresses 4,129/9,041 later frames; admitted windows
are not a full-market denominator. Adequate distinct episodes and controls
remain prerequisites for a cost-aware study. No execution branch is justified.

The separately frozen [coverage successor](../reports/single-venue-research/liquidation-coverage-v2/readout.txt)
retains valid stale identities and applies a brief quarantine. Its six fixed
exploratory blocks include 16 complete chunks and 2 unavailable captures.
They contain 17 admitted episodes and one qualifying delayed order; no cell
meets the two-superblock support threshold. This version stops before controls
or prices. Different inputs prevent a paired coverage comparison with v1.

Public-data impact studies also distinguish reconstructing average impact from
identifying a tradable entry: synthetic order groupings can reproduce impact
patterns, while models can misrepresent the source of correlated order flow.
Our inference is to test observable flow conditions directly and avoid assuming
that a detected burst marks a completed parent order.
[Maitrier et al.](https://arxiv.org/abs/2503.18199),
[Naviglio et al.](https://arxiv.org/abs/2501.17096).

## Commands

```bash
.venv/bin/python scripts/rolling_research_capture.py status
.venv/bin/python scripts/rolling_research_capture.py pin --owner study_name chunk-000001
.venv/bin/python scripts/rolling_research_capture.py unpin --owner study_name chunk-000001
.venv/bin/python scripts/rolling_research_capture.py stop
```

The [budget amendment](../reports/experiment-storage/rolling-capture-budget-v1.json)
records the new grant and releases the superseded, unlaunched one-hour capture
reservation. Capture data and analysis outputs have separate funded limits.

## Peer input handoff

The [unchanged return-lag audit](../reports/peer-research/20261002-0544/decision.txt)
found one BTC episode but no target/control pairs; economics remain unevaluated.
The separate [cross-asset OFI test](../reports/peer-research/cross-asset-ofi-v1/root-receipt.json)
completed under its frozen root runtime after 12 synthetic tests and source review.
Only 4/18 cells passed training feature support; each application block had zero
common usable calendars. The run stopped before fitting or economics. This is
inconclusive, with no subset or threshold rescue. The six existing tables were
read through their [immutable inventory](../reports/peer-research/20261002-0627-shared-ofi-inputs.json);
no raw or reserved inputs were copied. The [peer review](../reports/peer-research/20261002-0714/decision.txt)
reconciled the saved support records and confirmed the inconclusive classification.
The [immutable input export](../data/evidence/rolling-exploratory-000001-000003-v1-inventory.json)
contains only chunks 1–3, 45 verified members, 55,818,240 tar bytes through Git LFS.
Its [64 MiB reservation](../reports/experiment-storage/rolling-exploratory-peer-export-v1.json)
comes from existing headroom. Rolling and reserved data retain their rules.

## Peer primary-issuance compatibility proposal

The peer's next [proposal](../reports/peer-research/20261002-0743/peer-primary-issuance-v1-proposal.json)
examines native ETH issuance through Lido followed by a sale on one fixed Curve
pool. An executable premium must cover the complete transaction, gas, residual
share disposal and capital; no premium or profit has been observed.

The [single metadata probe](../reports/peer-research/20261002-0910/root-receipt.json)
completed 20 requests in 19.36 seconds. Synthetic return/revert gas, the fixed
contract identities and the final header check passed. All four native issuance
sizes were eligible at the observed block. Root verified the saved manifest,
ABI selectors, code hashes and resource limits without further RPC. Economics
remains null: no composed route, obtainable inclusion or profit was tested.

The [budget amendment](../reports/experiment-storage/parler-peer-primary-issuance-v1.json)
reclassifies 512 KiB within the existing peer grant for both raw metadata copies;
the total ceiling is unchanged. A strict cumulative-read correction was reviewed
before the run; both original and corrected sources remain retained. The peer
has derived a post-submit quote bound for the fixed balanceOf-only sale policy.
Its [design](../reports/peer-research/20261002-0941/peer-primary-issuance-bound-design-v1.json)
allows a compiler-free necessary-condition test, conditional on the stated
runtime/source provenance. A pre-submit quote is insufficient because issuance
can change the pool's reserve rounding. Offline implementation is authorized
within the existing grant; economic collection still needs an exact freeze.

## Polymarket full-NO conversion metadata

One fixed query selected the October FOMC event by calendar and title, without
price inspection. Its UTC end-day mismatch remains an inconclusive original
result. A separately frozen offline correction used the same response and the
New York meeting date; no second query ran. The [metadata readout](../reports/polymarket-no-basket/metadata-readout.txt)
records five coherent outcome definitions, token identifiers and fee schedules.
The first contract preflight stopped on a documented implementation mismatch;
its failure remains preserved. The observed implementation also appears in
the official current deployment repository. A separately frozen successor
passed all55 metadata checks: five registered questions, all ten positions,
zero conversion fee and required wrapper bindings/permissions at one stable
block. [Root receipt](../reports/polymarket-no-basket/chain-metadata-v2/root-receipt.json).
Actual conversion and deployed-source equivalence remain unproven. The fixed
[five-NO book screen](../reports/polymarket-no-basket/optimistic-books-v1/readout.txt)
completed all15 requests. Every recorded set had a cost floor of4.009Q against
at most4Q gross conversion return, giving a conditional zero-cost margin
of−0.009Q nominal pUSD. All15 sets failed the frozen timestamp diagnostics,
so no simultaneous all-slot conclusion is available. Park this displayed-taker
candidate at these recorded quotes; larger equal size cannot improve the bound.
There is no depth/execution branch or profit claim, and no conclusion about
other events or later periods. Root reconciled all15 raw responses and kept
the original timing gates.

## Rolling collector recovery, 2 October 11:39 UTC

The controller stopped when duplicated coverage tables filled its 1 MiB index.
Chunk 52 had already sealed successfully. A separately reviewed and frozen
[recovery](../reports/experiment-storage/rolling-research-capture-recovery-v1.json)
verified the existing seal and file hashes, adopted that completion and replaced
duplicate index tables with references to unchanged seals. The original capture
source, role schedule, pins, 2 GB ceiling and 48-hour deadline remain fixed.
The resumed chunk 53 sealed complete; the actual handoff gap was
1,151.452925 seconds. No reserved raw data was decoded. The
[recovery receipt](../reports/rolling-capture-recovery-v1/handoff-receipt.json)
records this missing interval explicitly.

## HIP-4 preparation and shared-host ownership

The local Claude collaborator owns only the four HIP-4 source/review paths in
the committed [allocation](../reports/experiment-storage/hip4-outcome-research-allocation-v1.json).
Root owns shared logs, storage ledgers, the git index, commits and data launches.
The first assignment covers official schemas, conversion arithmetic and an
offline metadata-probe package. Its 512 KiB reservation comes from existing
headroom. No market API request is authorized until the package is reviewed
and a concrete request manifest is frozen.

## Conversion price screens, 2 October 12:02 UTC

The independently reviewed [issuance screen](../reports/primary-issuance-bound-local-v1/readout.txt)
ran once after frozen commit c439df1. All four sizes passed metadata/domain
and final-parent checks but returned negative optimistic bounds: approximately
−6.08 to −6.09 basis points before gas. Root reconciled all 19 saved responses,
request payloads and integer share/balance arithmetic. Park this fixed model
and sample; no composed route, inclusion, source equivalence or profit was proved.

The [Polymarket extension](../reports/polymarket-no-basket/subset-conversion-books-v1/readout.txt)
fixed all 30 proper NO subsets, the full-NO reference and one full-YES
creation/resale route before quotes. All 480 route-slots were field-valid and
nonpositive: 320 at −0.009Q and 160 at −0.019Q nominal pUSD before costs. Only one
of 15 sets passed the frozen timing diagnostics; all 32 routes in that set were
negative. The other 14 support recorded-quote bounds only. Root independently
reconciled all raw bodies and route arithmetic. This family is parked at the
sampled prices, with no entire-interval or executable-liquidity claim.

Both runs retained their full denominators and evidence. The Polymarket source
category received 98,304 bytes from its unused derived category before collection,
including the retained preparation draft; the overall 2 MiB reservation did not
change. The issuance run used its separate preallocated 512 KiB envelope.
