# Offline static hedge-cost budget diagnostic

Use only the completed `reports/passive-universe-screen/20260930T0310Z`
screen. Preserve its frozen inputs and observations. This is an exploratory
arithmetic diagnostic prepared after that study, with no new network data.

For each original valid asset/round/size row, preserve the exact original
common-lot quantity q, RH bid and ask. Define the optimistic hedge-cost budget:

`q × (RH ask − RH bid) − $0.10 − 0.0005 × q × RH bid`.

Assume zero RH fees, zero hedge fees and zero hedge bid/ask spread or impact.
Use RH opening notional as the **minimum** stress base. The original larger
opening-leg stress base can only increase the charge. Thus a strictly positive
budget is a necessary margin condition for that unchanged-book RH bid-to-ask
cycle under the original target/stress, before any hedge cost. This is not a
bound on future trading profit: it assumes the same static prices and makes no
maker fill, adverse selection, latency, price drift or funding claim.

Retain each original public-scenario modeled fee amount and show a separate
budget with that amount deducted while still assuming zero hedge spread and
the minimum stress base. This is a sensitivity with the observed fee notionals
held fixed, not an account-specific charged fee or a requoted counterfactual.
Verify original fees are nonnegative, HL roundtrip spread/impact nonpositive,
and original stress no smaller than the RH minimum stress. Verify both budgets
are at least the original stressed quote margin, and reconcile original saved
RH notionals/spread with quantity and quote prices.

Use the exact original valid denominator at all four sizes: no recovery of
stale rows and no enlarged quantities. Preserve all failed rows and reasons in
the per-observation output but exclude them from arithmetic and medians.
Report valid/missing count, positive observation count, maximum and median at
each size. Report every asset's median at each size, but eligibility for the
follow-up decision requires the original >=3 valid $1,000 rounds. Preserve the
original fresh-volume tie-break after median and asset tie-break after volume.
Report positive eligible medians and the best eligible median at each size;
ineligible assets' descriptive medians cannot nominate a candidate.

Record SHA-256 hashes of the exact original quote file, universe, summary,
manifest and freeze file, plus this method, runner and tests. Validate frozen
input hashes before analysis and all read-input hashes again afterward. Output
to a new directory, refuse to overwrite an existing output, and cap derived
files at 2 MB. No network access or edits to either screen are permitted.
