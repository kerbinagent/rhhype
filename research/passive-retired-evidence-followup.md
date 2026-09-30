# Post-capture review: retired passive evidence after an unrelated halt

This is a **post-capture synthetic diagnosis**, recorded separately from strict v1 and the pre-holdout entry retirement correction. It changes neither frozen implementation nor either replay result. No current raw capture was read to establish the finding. The [standalone reproducer](../scripts/reproduce_passive_retired_after_halt.py) and [callback-level result](../reports/passive-retired-evidence-review/reproducer.json) provide the fixture, source hashes, and isolated existing-guard probe.

## Confirmed scope

Both `PassiveExitBranch` and `RetirementGuardPassiveExitBranch` retain this defect. `MakerBranch.process` advances the clock and then returns immediately if the branch is already unknown. The passive tombstone guard lives inside `PassiveExitBranch._on_trade`, so this return prevents a later genuinely new old-source buy from invalidating an earlier finalized episode. The entry retirement correction checks entry tombstones outside that gate; it does not move the passive guard.

The fixture uses ordinary configuration and public callbacks: admit a bid, activate it on a later RH book, fill one unit, hedge on HL, activate the passive ask, sell half, execute the corresponding HL buy, and flatten the remaining inventory through the normal hold-deadline taker fallback. A fresh second admission then halts on an RH book generation change. Finally, a new valid buy print arrives whose source lies inside the old ask's activation/cancel interval and whose price reaches the old ask.

| Class | Same late buy without prior halt | Same late buy after generation-change halt |
| --- | --- | --- |
| Frozen strict v1 | Old episode execution unknown; cohort net absent | Old episode remains known |
| Frozen entry retirement correction | Old episode execution unknown; cohort net absent | Old episode remains known |

The retained ask has remaining quantity `0.5`. Both affected fixtures retain cohort net `-0.04032725363077118214104515474` after `process`. Calling the already existing `_retired_flow_check` on the identical event in an isolated disposable branch flags that episode and makes `_complete_net` absent. Cash, fees and positions remain identical. This establishes a classification omission, not an omitted economic fill estimate or measured positive opportunity.

**Portfolio complete net is already absent because of the branch halt.** The remaining reporting risk is the closed-episode contribution: `score_cohorts` computes each episode's `_complete_net` independently of the branch's complete net. A known contribution can therefore survive the later contradictory execution evidence.

## Nonapplicability and later adjudication

For this precise defect, **zero retained passive asks in every replay branch is a sufficient nonapplicability check**, provided the replay has no truncated/missing branch retention. These tombstones persist through study end. Zero is not a fabricated unknown count or a substitute for checking the actual field `retired_passive_quote_guard_count`. Control policies without passive asks cannot encounter this path. A positive count alone does not establish affected execution or profit.

If a branch has retained passive asks, a separately labelled post-capture historical adjudication must examine the canonical raw RH trade stream, in original receipt/sequence order, against each actual tombstone and each branch's first halt receipt. The qualifying evidence requires:

- The same asset and RH venue; aggressor side `buy`.
- Valid source/receipt clocks, positive price and quantity; `source_ns <= received_ns`.
- A genuinely new native trade ID absent from that ask's `seen_ids`; exact retransmissions must not manufacture new evidence. Conflicting ID content needs explicit uncertainty treatment.
- `activation_due_ns <= source_ns <= cancel_due_ns`, `price >= ask.price`, remaining quantity greater than zero, and a quote with a recorded activation and cancel due.
- Receipt after the prior branch halt and after the old ask was retired (including the stored stable sequence order for equal receipt timestamps).

Do not discard this historical evidence solely because its source is old relative to receipt: the existing tombstone guard is specifically intended to review delayed old-source prints. A reconnect generation must not silently remove it. Retain asset/branch/episode, tombstone interval, old seen IDs, halt reason/time, raw event identity, source/receipt/generation and the matched event hash as provenance. Summary counts alone cannot provide those intervals and seen IDs; an adjudicator needs separately retained tombstone evidence or a separately labelled immutable-source replay that records it. The original strict and entry-corrected outputs remain preserved.

Adjudication withdraws the affected old episode's known net and classifies execution unknown. It must neither invent the missing fill/cash nor turn the episode into known zero. Preserve the prior branch halt reason and all original economics. Its source inventory and post-capture timing must be explicit; this finding does not amend the earlier 20-source freeze.

The independently reviewed future ACK adapter checks genuinely new validated trades against retained passive evidence even after an unrelated halt. That adapter also changes ACK/queue assumptions, so its result cannot serve as the unchanged strict replay or as a profit bound.

## Reproduce

```sh
python -m scripts.reproduce_passive_retired_after_halt > reports/passive-retired-evidence-review/reproducer.json
```

The script checks all 20 source hashes against the existing correction freeze before and after its four synthetic cases. It asserts the prior-halt defect, the no-prior-halt control, and unchanged economics in the direct diagnostic guard probe. It does not run a market request, capture, or historical replay.
