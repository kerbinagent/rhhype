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
| Autonomous Parler peer | Own distinct mechanisms on an isolated branch; freeze bounded diagnostics before outcomes and coordinate shared inputs. | Continuing research within the [9 MiB allocation](../reports/experiment-storage/parler-peer-contractual-closures-and-cache-reconciliation-v1.json); updates at material decisions. |

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

## Peer primary-issuance compatibility work

The [metadata probe](../reports/peer-research/20261002-0910/root-receipt.json)
completed 20 requests and verified fixed identities, synthetic gas and parent
checks. Its [post-submit bound design](../reports/peer-research/20261002-0941/peer-primary-issuance-bound-design-v1.json)
accounts for issuance changing reserve rounding. The completed negative result
is below. Original failures, source versions and both-session copies remain
retained under the existing peer grant.

## Polymarket full-NO conversion metadata

The [calendar correction](../reports/polymarket-no-basket/metadata-readout.txt)
used the original response; the first implementation mismatch remains retained.
A separately frozen [contract successor](../reports/polymarket-no-basket/chain-metadata-v2/root-receipt.json)
passed all 55 metadata checks, covering five questions, ten positions and
wrapper permissions. Actual conversion and source equivalence remain unproved.
The [five-NO screen](../reports/polymarket-no-basket/optimistic-books-v1/readout.txt)
returned −0.009Q nominal pUSD before costs in all 15 recorded sets; none passed
the frozen timestamp checks. Park this sample without a simultaneous-liquidity
claim. The later subset extension is summarized below.

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

## HIP-4 metadata and continuing ownership

The metadata probe returned 260 outcomes and 18 complete questions with 86
members. The separately frozen [book screen](../reports/hip4-research-continuation/books-v1/readout.txt)
read 91 responses once: all 18 questions passed the timing gates and static
no-cycle certificate; both BTC cross-question constraint sets were feasible.
Root independently reconciled every response with rational arithmetic. No
positive candidate remains at these recorded quotes. The result is conditional
on conversion/payoff assumptions, not proof of simultaneous executable depth.

The local Claude session continues HIP-4 research under its
[1 MiB allocation](../reports/experiment-storage/hip4-research-continuation-allocation-v1.json).
It owns new paths and offline work; completed evidence remains read-only.
Root coordinates shared files, commits and data gates. The original 512 KiB stays
reserved, and checkpoints do not end the task.

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

## Completed news study and continuing source research

The [corrected result](../reports/single-venue-news-inventory-fix-v2/root-readout.txt)
contains 100 flat-known policies and 20 passed audits: 67 active, 48 with closes,
27 net positive and 12 positive after extra 5 bp stress. The original output
and pre-economic inventory failure remain retained. The frozen inventory repair
changed no scientific rule or raw data; both complete versions reconciled.
The correction changed which policies were positive, despite the same count.
Several winners overlap the release move; alternative ledgers cannot be added.

Core NEAR depth-follow's three closes returned +0.7371 USDC net and +0.5889
stressed. The [frozen successor](../reports/experiment-storage/news-candidate-rolling-v1.json)
keeps it and the unchanged fade comparator, plus all 100 descriptive policies.
It selects the first reserved chunk launched at or after 15:00 UTC, retaining failure
without replacement. A [pre-cutoff host startup repair](../reports/experiment-storage/news-candidate-host-startup-recovery-v1.json)
preserves the failed sandbox launch. One ordinary block tests applicability;
it does not establish news replication or repeatable profit.

The [Comet artifact check](../reports/comet-sourcify-lookup-v1/root-reconciliation.json)
matched the retained runtime, including all 70 immutable substitutions. Its
literal metadata bytes match the embedded content hash. Independent compilation
and economics remain unproved. The failed gateway request stays retained;
Clipper remains offline.
