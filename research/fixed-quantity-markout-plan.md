# Prospective fixed-quantity quote markouts

## Question and scope

The v2 horizon pilot compares future closing-spread **bps** forecasts, but its
future quote can use a different quantity and denominator from its anchor.
A separate prospective observer can ask a narrower economic question: **at the
quantity available at an entry decision, did the first eligible 12–16-second
closing quote show enough convergence to cover four taker fees?** It cannot
tell whether both entry orders would have filled, at what prices, or whether a
delayed exit would have filled. Treat the result as an optimistic
zero-entry-latency quote screen, not realized or paper P&L.

This is a design for a new, separately versioned read-only pilot. It must not
reinterpret the v1/v2 archives or change the running v2 model or entry gates.

## Anchor and outcome, fixed before the pilot

For each directed route `asset|buy venue:market|sell venue:market`, use the
same prospective paired-book eligibility as the v2 observer: both books valid;
source and receipt ages at most two seconds; source and receipt skew at most
one second; known source timestamps, sequence tokens, and generations; both
source tokens advance from the previous accepted pair. Apply the same lot,
minimum-notional, and approximately $1,000 notional rules at the anchor.
Require the buy ask walk and sell bid walk at the **same lot-matched quantity**
`q0`. Store scalar entry quotes `A0 = buy asks(q0)` and `B0 = sell bids(q0)`,
the four relevant venue taker fee rates, the immediate close walks at `q0`
for the frozen prediction screen, both source/receipt times and tokens, and
the v2 forecasts frozen at that anchor. Do not store books long term or later
recalculate `q0`.

At least 12 seconds apart, make one anchor per route. A future pair can resolve
an anchor only if it is the **first** pair with both source timestamps at least
12 seconds newer than the corresponding anchor sources, received 12–16
seconds after the anchor decision, within the same generations, and meeting
the same two-second age and one-second pair-skew limits. If that first
time/source-eligible pair lacks bid depth on the buy venue or ask depth on the
sell venue for the **original `q0`**, censor it as `future_exit_depth`; do not
reduce quantity or wait for a later, better quote. If there is no eligible
pair by 16 seconds, censor as `outcome_missing`. Record invalidation from a
stream reset/generation change or a feed gap separately. A stale, skewed, or
nonadvancing pair is not an outcome; continue waiting only until the fixed
deadline. At process stop, censor remaining pending anchors as
`stopped_pending` before stream shutdown callbacks can label them feed gaps.
Explicit counters should separate source-age, skew, depth, reset,
gap, missing, and stopped-pending outcomes.

At a matched future pair, walk **buy bids** for `q0` to get long liquidation
`L12`, and **sell asks** for `q0` to get short buyback `S12`. Freeze the first
eligible outcome, even if a later quote is better. Require positive finite
prices and **nonnegative finite** fee rates, known metadata age, and unchanged
market identity; otherwise censor with a separate reason. Use the frozen
Standard fee assumption from discovery metadata for both entry and exit;
do not claim those rates update live or substitute a more favorable tier.

## Quote arithmetic

The **gross quoted capture** is `B0 − A0 + L12 − S12`. Four taker fees are
computed on their own quote notionals:

`F = A0 × f_buy_entry + B0 × f_sell_entry + L12 × f_buy_exit + S12 × f_sell_exit`,

where each `f` is a decimal rate (bps divided by 10,000). The primary
fixed-quantity outcome is `gross quoted capture − F` in dollars, also divided
by `A0` for bps. Report gross capture and each of the four fees separately.
This uses the actual **observed entry quote values**, not inferred entry
fills. As a secondary, separately named screen, subtract the pilot's frozen
`extra_cost_bps` reserve on `max(A0,B0)` and a capital-time estimate using
the **actual anchor-to-outcome elapsed seconds**;
never mix those reserves into the four-fee field. Freeze fee schedules and
cost parameters at the start of a new pilot and label their version. Standard
fees include any published venue floor. Funding, queue position, market
impact after quote capture, and partial or one-leg fills are unmeasured.

## Conditional evaluation, declared before outcomes

Collect every eligible anchor regardless of current opening edge or v2
prediction. Report all anchors, v2-warm anchors, matched, each censor reason,
and export truncation. The primary descriptive statistic is the fraction of
**matched, v2-scored** anchors with a positive four-fee fixed-quantity quote
outcome, alongside median/p10/p90 dollars, mean dollars, and the fraction
positive after the separately reported cost reserve. Show the matched fraction
of all v2-scored anchors and the same outcome summary for all matched anchors;
do not classify censored anchors as gains or losses. Break results out by
directed route and five-minute anchor-time block. The live snapshot retains
**all-run counts, sums, and means** for the overall/scored/selected groups.
An offline analyzer computes median/p10/p90 and route/block tables from at
most 5,000 terminal rows. If that export drops old rows, label those
statistics **retained-row only** and never blend their denominator with
all-run aggregates.

At each v2-scored anchor, freeze a **prediction screen** for each of the four
v2 models. Let `L0` and `S0` be the immediately available close walks at `q0`.
For forecast closing spread `C_hat` in bps, use

`screen = B0 − A0 − (C_hat / 10,000) × A0 − A0 f_buy_entry − B0 f_sell_entry − L0 f_buy_exit_at_anchor − S0 f_sell_exit_at_anchor`.

Thus the unknown future exit-fee notionals are estimated from **anchor-time**
close walks, which must be saved at decision time. Report
the predeclared subsets whose conditional-linear screen exceeds **$0** and
**$0.25** as the primary forecast-conditioned diagnostic. Apply the same
two thresholds to persistence as a reference, and historical median and
horizon delta as secondary controls. These cohorts overlap and are not
independent returns. Report each cohort's anchor, matched, censored, and
pending counts, including the censor fraction. Evaluate
the actual fixed-quantity outcome only after the later pair arrives. Do not
retune thresholds, forecast conversion, horizon, or censor rules using this
pilot's results. On the common matched v2-scored anchors, also report each
model's fixed-quantity quote-dollar forecast error; selected subsets differ,
so compare models on the common set rather than claiming a winner from their
different selections. Forecasts in v2 were trained on variable-quantity bps:
this conversion is a diagnostic, not a calibrated fixed-quantity prediction.

This can reveal whether any **observed** short-horizon quote convergence clears
four fees among forecast-selected anchors and how often a usable outcome is
missing. It cannot establish an executable strategy edge: entry is assumed
instantaneous at the observed quote, later quotes are not fills, and censoring
can bias the matched subset. Opposite route directions share books, while
anchors 12 seconds apart can have overlapping 12–16-second outcomes. Report
descriptive counts and time/route breakdowns; make no independent-sample
significance or profit claim.

## Minimal bounded module interface

Standalone `FixedQuantityMarkoutObserver` (new module, no order endpoints):

- `on_pair(route, now, buy_book, sell_book)`: validates a paired book and
  resolves pending original-quantity outcomes **before** new adaptive anchor
  sizing. A paired quote may resolve an older anchor even when no new entry
  quote can be sized.
- `anchor(route, now, quote, buy_fee_bps, sell_fee_bps,
  frozen_forecasts_bps)`: freezes the original quantity, entry/close quote
  values, costs, and forecasts supplied by the v2 anchor callback. The v2
  model freezes that prediction before the current quote matures its own old
  anchors; the fixed model does not train it or fetch a later snapshot.
- `invalidate(route, now, reason)`: censor pending anchors on a feed reset,
  generation change, route removal, or gap.
- `finish(now)`: records remaining pending anchors as `stopped_pending`
  before stream cancellation can create artificial feed-gap censures.
- `snapshot(now)`: bounded global and per-route counters, pending ages, and
  at most 5,000 recent terminal scalar rows. Include `model_version`, fee/cost
  configuration, censor reason, forecast-screen flags, timestamps/tokens,
  `q0`, the four quote notionals, four fees, and export-drop count.

Use at most 2,000 routes, two pending anchors per route, a 900-second active
window, and a 5,000-row terminal export. Do not retain full books, and censor
evicted pending anchors. Launch into a new output directory only after the API
and fee/cost specification are reviewed. The current v2 observer API returns
only an acceptance flag; a later integration would need an explicit frozen
anchor-forecast event. It must preserve the v2 rule that a current future
quote cannot train its own prediction.

## Regression checks before launch

1. Unequal entry and future prices plus asymmetric venue rates produce the
   exact four fee notionals and the correct long/short signs; the future depth
   walk uses `q0`, even when a fresh adaptive quote would choose a smaller
   quantity.
2. The first eligible 12–16-second future pair with too little exit depth
   censors the anchor; a later profitable pair cannot replace it. Stale,
   skewed, or one-source-unchanged books cannot resolve it.
3. Generation changes, feed gaps, metadata changes, missing outcomes,
   pending cap, route eviction, and process stop produce distinct bounded
   accounting with no anchor counted both matched and censored.
4. A current outcome may mature an older anchor, but cannot alter the current
   anchor's frozen v2 forecast, fee schedule, quantity, or screen classification.
   Run a fixture where including that outcome would flip a screen flag.
5. Threshold cohorts use only anchor-time fields. Tests verify no future fee,
   exit value, or censor status leaks into selection, and that all-model error
   comparisons use identical matched anchors.
