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
The separate cross-asset OFI draft will reuse the
[frozen own-market tables](../reports/experiment-storage/single-venue-queue-ofi-v1.json).
The [immutable input export](../data/evidence/rolling-exploratory-000001-000003-v1-inventory.json)
contains only chunks 1–3, 45 verified members, 55,818,240 tar bytes through Git LFS.
Its [64 MiB reservation](../reports/experiment-storage/rolling-exploratory-peer-export-v1.json)
comes from existing headroom. Rolling and reserved data retain their rules.
