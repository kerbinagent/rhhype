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
3. **Changing order flow:** establish whether live trade grouping and book
   replenishment can be measured, then test continuation or exhaustion with
   explicit controls. A large individual print does not establish that a larger
   trading program has finished.

Liquidation events are a possible separate mechanism. The ordinary adapter
counts and excludes `liquidation_trades`; the raw capture retains the field.
The two completed broad windows contained zero live liquidation rows on either
venue, so they do not test forced-flow recovery. The official Core
[WebSocket schema](https://apidocs.lighter.xyz/docs/websocket-reference)
defines separate ordinary and liquidation arrays; RH availability requires its
own observed evidence.

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
