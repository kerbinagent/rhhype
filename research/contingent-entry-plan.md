# Frozen: HL-first contingent-entry paper trial, version 1

The [review 12 audit](review12-hedge-failures.md) found 15/15 convergence
hedge failures after the other venue filled and HL later rejected within
the frozen 10 bp price limit. Version 1 changes **only entry sequence**:
submit HL first and submit the original-size other leg only after a full HL
fill. Public displayed books remain paper quotes, not exchange fills. This
trial does not touch the live monitor or submit orders.

## Candidate and data rules

An isolated control `PaperEngine` runs the unchanged convergence selector
and simultaneous-entry policy. A second independent `PaperEngine` receives
**the same selected candidate ID, route, original quantity, direction, and
signal**; it never independently rescans or reranks. Each policy has its
own paper capital. The candidate tap follows the control selector's
existing-position check, so contingent-only opportunities while control
occupies a route are outside the study. Capacity/admission abstentions for
either policy remain in the original-candidate denominator.

Preselect GRAM, GRASS, NEAR, SNDK, SOXL, SPCX, VVV, XPL from diagnosed
convergence failures and BTC, ETH, NVDA, XAG as controls. Choose at most
24 existing HL/Lighter Core/RH physical pairs, highest prior min-side
volume within asset/venue, requiring at least $1 million on both sides.
The current dry run finds 19 eligible pairs; GRASS is absent. Aster routes
and the baseline's SHEIN partial failures are outside this convergence
cohort. This is a selected mechanism test, not an unbiased market sample.
RH-domain USDG and HL USDC are treated at parity only under the existing
paper quote assumption. No executable conversion path, conversion cost,
or collateral transfer is modeled.

Both policies see the same public WebSocket books with `prefer_bbo=True`:
newest BBO or L2, never spliced. The trial makes **zero targeted HL REST
book requests**, because an isolated process cannot safely share the live
process's aggregate REST budget. Consequently it cannot reproduce the
production targeted-REST failure rate or timing. Default duration is
1,200 s, hard cap 2,400 s. Preserve convergence's 40-sample/120 s causal
warmup and economic gates; zero selected candidates is a valid result.

## Treatment execution

`HLFirstEngine` creates the same two-leg PaperEngine position, then pauses
the other venue's intent **before any book can fill it**. The HL intent
keeps the original quantity, normal network/processing delay, first
eligible source and receipt checks, generation, three-second post-due
timeout, and signal-frozen 10 bp directional price limit. The inherited
lot-rounded fill function determines zero, partial, or full HL entry and
charges its actual fee.

If HL fills less than the full original quantity, do not send the other
leg. Mark it `not_sent_hl_first` and use the inherited failed-hedge exit
path to flatten **all** actual HL quantity, charging actual exit fees,
price result, reserve, and exposure time. A zero HL fill has zero trading
cash and is recorded as a foregone candidate, never as a gain. Version 1
does not resize a hedge to partial HL quantity or split common lots/dust.

After a full HL fill, create the other leg's original-quantity intent at
the HL fill time. Its **signal-time 10 bp limit remains frozen**; it has
normal venue delay, source/receipt/generation checks, and three-second
post-due timeout. Require a valid other book before sending; otherwise
wait at most 2 s after the HL fill, then request HL flatten. Check the
deadline before accepting a newly healthy book. A zero or partial second
fill follows inherited flattening on every actual position. There is **no
postfill economic gate** in v1: one would change entry selection as well
as sequence. Base evidence measures peer `signal_to_receipt_seconds` from
its later send time; reports must also compute original-candidate-to-peer
receipt from the cohort record.

A full matched pair uses the inherited $0.10 all-cost take-profit request
or mandatory exit request at 10 s from opening. Actual flattening may
finish later under normal delays/timeouts. The engine charges all actual
entry/exit taker fees, 5 bp reserve, and elapsed capital cost. A position
wholly inside one UTC hour has exact zero hourly funding and is settled
locally; a boundary-crossing position remains unresolved. No zero funding
or net P&L is inferred for it.

## Implementation and evaluation

`scripts/paper_contingent.py` owns two isolated engine subclasses and
cohort links. `scripts/contingent_observer.py` owns one WS stream, frozen
metadata, and independent output. One bounded SQLite `PaperStore`
transaction persists both engines, cohort IDs, transitions, and evidence.
Selected pair fee/lot/minimum metadata and selection parameters enter the
store config hash, preventing silent resume under changed discovery.
Checkpoints run synchronously on this isolated event loop; both policies
see the same pause. Report its duration and event-loop lag.

Bound active cohort links to 128, retained cohort rows to 500, terminal
trades to 5,000, DB to 128 MB, and exported episode histories to 200 per
engine. Cumulative counters survive row eviction. Each cohort has two
terminal outcomes or remains pending/unresolved. Compare net only for
both-exactly-closed cohorts and report all selected-candidate coverage,
admissions/abstentions, HL zero/partial, second-leg failure, one-leg
seconds, foregone control matches, finalized-cohort net sums, and pending
count. Individual engine ledgers remain visible. Do not present an
abstention as profitable avoidance or an unresolved trade as zero P&L.
The exposure integral is normalized by each original candidate quantity
before summing across assets; missing/truncated fill history is unknown,
not zero. Clock one-leg seconds are reported separately.
Correlated routes/repeated HL events are not independent trials.

On stop, freeze event admission before stream teardown and checkpoint any
open exposure without a synthetic close. Restart invalidates old entry
generations and preserves actual exposure for inherited flattening.
Meaningful tests cover the same frozen candidate, HL timing, zero/partial
HL, later peer partial/rejection, missing-book timeout, price/source/
generation checks, all-cost accounting, restart/cohort identity, storage
failure rollback, and bounded state. No launch before independent audit.

## Deferred experiments

Hedging a partial HL fill at a common lot, flattening unmatched dust, or
adding a postfill economic gate would each change more than sequence and
require a separately versioned policy. They are **not** part of v1.
