# Public queue uncertainty after the stopped RH maker pilot

**Research proposal for a future paper replay; no change to the running passive-exit study.** The evidence below comes only from the stopped 21:21–22:11 UTC maker pilot and its [queue diagnostic](rh-entry-queue-followup.md). No hypothetical RH order was submitted, so none of its fills or cancellations can be verified from a private order update.

## What stopped Standard BTC and ETH

At $1,000 fixed-best, Standard BTC had 25 activated quotes, 37.925 seconds of known active queue time, and zero attributed fills before `trade_cancel_order_ambiguous` at about 96 seconds. Standard ETH had 33 activations, 46.460 seconds, and zero attributed fills before `eligible_flow_before_queue_snapshot` at about 124 seconds. Their observed sell prints during quote intervals were only two and seven, respectively. The first unresolved obligation halts the branch. Premium's later fills therefore cannot be compared with Standard's zero as a clean latency effect; the [stopped diagnostic](../reports/rh-entry-queue-followup/diagnostics.json) separates the common-time and post-censor periods.

These two censor reasons have different immediate causes in [the frozen engine](../scripts/rh_maker_engine.py):

| Reason | Current rule | What the public record establishes |
| --- | --- | --- |
| `eligible_flow_before_queue_snapshot` | A modeled activation is due, but the first RH book whose **source and receipt** are both after due has not established `ahead_same`; an eligible sell print arrives before that book's source time. | The print could reach the price, but neither the hypothetical order's insertion nor its queue position is observed. The requirement for a later book to initialize one exact `ahead_same` is an engine choice that widens the unresolved window. |
| `trade_cancel_order_ambiguous` | A cancel is requested and its deterministic delay has elapsed, but no later source-advanced RH book has been used as the cancel confirmation; an eligible sell print arrives. | The print/cancel ordering of a **hypothetical private order** is not identified. Treating a public book as confirmation is only a timing proxy; it is not an exchange cancel ACK. |

Thus the short Standard runs are partly a conservative simulator stop rule, while the underlying order-acknowledgement and queue uncertainty is real. A later public book cannot reveal the identity or queue position of an order that was never placed. The [venue's public SDK](https://github.com/elliottech/lighter-python/blob/main/lighter/ws_client.py) distinguishes public `order_book` subscriptions from account updates; its [order API](https://github.com/elliottech/lighter-python/blob/main/lighter/api/order_api.py) also distinguishes book orders from account orders. Even richer public order-level data would help reconstruct displayed queues, but would not create the missing private ACK for our counterfactual order. Market-by-price queue ambiguity from additions and anonymous cancellations is also described in [Dixon's execution-model paper](https://doi.org/10.1002/hf2.10016); that general observation is motivation, not a venue-specific fill rule.

## Proposed future finite-state paper method

Use the **same frozen decision, quote price and quantity, fees, latency assumptions, post-only check, valid-book rules, and full hedge/exit economics** as strict v1. For each quote, retain the last valid pre-due RH book, every RH book and eligible aggressor print from modeled activation due through cancel resolution, source and receipt times, feed generation, and any missing-data flag. The model advances on receipt time; source time gates only events that could have occurred after a modeled due. A receipt arriving late with an old source remains relevant to the old quote, even after a new quote is considered.

1. `PENDING_ACTIVATION`: from decision to modeled activation due. A source-advanced book may establish a clean activation. If eligible flow occurs between due and the first such book, branch the **possible fill status** instead of either claiming a fill or halting the whole study. A clean quote requires a known passive price and valid generation; crossing or missing books stays unresolved.
2. `ACTIVE`: track remaining original quantity and same-price displayed queue ahead. At/through aggressor prints can consume same-price ahead and then the hypothetical order; no cancellation credit is inferred from aggregate depth decreases. Trade volume caps any modeled increment. Better-priced demand is not subtracted again from a print already at/through the quote.
3. `CANCEL_PENDING`: preserve the quote and all possible remaining quantities from cancel request until the first valid source-advanced book after modeled cancel due, or a fixed confirmation timeout. For every eligible print whose source lies in this interval, retain both timing possibilities: cancel effective before the print, or print while the quote could still rest. An equal-time endpoint and any late-arriving old-source print remain ambiguous. A quote is not declared harmless merely because the engine has already opened another quote.
4. `RESOLVED` or `UNKNOWN`: only a branch with known fill quantity, matched hedge/exit outcomes, no pending cancel/late-flow window, and reconciled funding can produce completed net. Feed gaps, invalid clock order, generation changes, depth failure, open inventory, or a state-count cap yield an explicit unknown obligation; they never contribute zero P&L.

At each ambiguous print, keep a bounded **set of causal states** over remaining maker quantity, queue-ahead possibility, cancel status, inventory, and resulting hedge/exit intents. Merge states only when those economic variables and future obligations match. For initial queue position, the last pre-due and first post-due books are evidence, **not** a guaranteed interval: aggregate depth may gain new orders or lose ahead/behind orders between them. Without a complete sequenced order-level event stream or a declared queue-allocation assumption, use the honest coarse limits of zero certain fill and no more than original quantity or observed eligible print volume as possible fill; if the feed is incomplete, even the latter bound is unavailable. This prevents the first post-due snapshot from being mislabeled an exact activation queue.

For a practical, finite sensitivity report, predeclare two fully specified interpretations of unresolved ordering: **early-live** (eligible due-to-snapshot flow may interact with the quote; cancel may remain live to the first eligible book) and **late-live** (no fill before the first eligible book; cancel effective at modeled due). Simulate all attributed partial fills at the **own quote price**, then the actual original-size/partial hedge and unwind schedule on first eligible books, including every own-notional fee, reserve, capital, funding boundary, depth shortfall, and late-print obligation. These are *assumption scenarios*, not observed executions or guaranteed P&L bounds. If either path cannot be flattened from the captured data, its net stays unknown.

Do not call “fill” the optimistic profit case: an early maker fill may be the losing path. If an outcome interval is reported, take the minimum and maximum completed net across **all retained causal states**, including no-fill and partial-fill paths, and label it conditional on the stated feed-completeness and timing assumptions. If the state set is truncated or a path has unresolved inventory, report an open interval/unknown rather than a finite lower bound. An all-path positive lower bound would be a meaningful paper robustness finding; a positive single scenario would not.

## Comparison and decision rule

First, replay the **stopped** capture as a diagnostic with both strict v1 and the new method on identical opportunity IDs; do not retrofit v1's published outcomes. Then freeze the method and run a fresh prospective stream. Keep separate Standard/Premium and fixed-best/inside-spread ledgers. The paired table should show all admissions, clean activations, clean no-flow, known partial/full fills, ambiguous activation, ambiguous cancel, late-flow ambiguity, invalid-feed cases, known complete cycles, unresolved obligations, and net only for known complete cycles. Also report active-queue seconds, source/receipt gap distributions, ambiguity-window widths, and the number of episodes for which both scenario paths finish with a narrow net range. Stop rules and state caps must be identical and predeclared across policies.

The useful criterion is **coverage plus robustness**, not a lower censor count alone: a policy with more possible fills but wide unresolved loss exposure has not demonstrated a profitable edge. Keep the all-admission denominator and show whether any conditional lower net bound remains positive after complete costs. Never add no-fill zeroes to unknown economic states, compare a short strict-v1 branch with another branch's later fills, or promote historical prints to private fill claims.

## Independent implementation reference, 30 September 03:00 UTC

[HftBacktest's own fill and queue documentation](https://hftbacktest.readthedocs.io/en/latest/order_fill.html)
provides a useful implementation comparison. Its market-by-price queue models
estimate queue position; its risk-averse model advances the queue from trades
without granting cancellation credit. That resembles our chosen queue rule,
but does not validate our assumed insertion or cancel time. Its documentation
also warns that replayed orders cannot alter subsequent market data. Our
within-event depth depletion prevents duplicate consumption in one callback;
it does not model how an actual order would change future books. Small size
reduces that concern only when supported by the observed market depth and flow.

The new review also identified a separate implementation boundary to test:
an entry quote can retire during processing of the very trade that should
invalidate its completed episode. This is an event-ordering correctness issue,
not a reason to grant additional fills. A separate correction must mark such
an episode unknown and retain its economic evidence. The frozen v1 source
remains preserved so any corrected replay is explicitly distinguishable.
