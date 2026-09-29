# Retired quote and delayed public trade audit

Discovered by independent synthetic review at approximately **22:01 UTC,
29 September 2026**, while the original RH maker holdout was collecting.
No calibration fit or capture outcome had been inspected. The original
23-file implementation freeze remains unchanged.

## Defect and scope

The frozen execution engine waits until modeled cancellation is effective
and an additional two-second grace has passed before retiring a flat quote.
If an eligible public trade then arrives with a source timestamp *before*
that modeled cancellation, the retired quote is no longer checked. A
synthetic no-flow example with cancel due at t+5.6 seconds, retirement at
t+7.7, and a trade received at t+7.8 with source t+5.5 leaves a known zero
result even though the late print could change prior queue attribution.
The same inherited behavior affects the initial sell-side implementation.

The two-second grace bounds storage and ordinary observation delay; it is
not evidence that later messages cannot describe earlier activity. A late
print need not establish an actual missed fill: same-price queue and
unobserved private execution remain uncertain. It does prevent an
unqualified claim that the affected episode was resolved as modeled.

## Treatment

- Preserve the original frozen replay and its source hashes.
- After capture and replay finish, run a separate bounded, read-only check
  against the raw public events and audit quote intervals. Flag potential
  eligible late flow for retired activated quotes with remaining quantity.
  Identify affected episodes and branches without fabricating a fill or
  corrected P&L. A branch's original complete-net value is not validated
  if this check finds an affected obligation.
- Report original results and validation side by side. Closed contributions
  from affected episodes cannot support a profitability claim. A clean
  result from this check clears only this particular synthetic defect;
  it does not verify private fills or other execution assumptions.
- Future independent bid/ask runs retain bounded retired-quote records
  throughout their study and mark affected episodes `execution_unknown`
  and branch totals unknown. Known completed contributions exclude those
  episodes. Hitting the retention bound fails closed rather than dropping
  old obligations. The prospective method and hashes must include this
  correction before any future collection starts.

This is an execution-accounting correction discovered before reading the
holdout, not a change to its economic forecast or a selection of favorable
prices. No production strategy is promoted by this audit.
