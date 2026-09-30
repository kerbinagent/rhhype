# Passive exit quote allowance variant (prospective only)

The frozen v1 `passive_target` ask uses the 5 bp rebalance reserve both to select a quote and to report stressed net cash. The reserve is a stress allowance, not an exchange fee. This separate module tests whether requiring that allowance **at quote selection** suppresses otherwise plausible passive asks. It does not change the frozen v1 capture, replay, or reported 5 bp stressed ledger.

`CostPolicyPassiveExitBranch` accepts `quote_reserve_bps=0` or `5`. For a matched RH long and HL short of quantity `q`, the target ask before tick rounding is

`[target - existing entry cash + HL buy walk × (1 + adverse75/10000) × (1 + HL taker fee/10000) + selected quote reserve + projected capital] / [q × (1 - RH maker fee/10000)]`.

The selected quote reserve is `max(RH entry notional, HL entry notional) × quote_reserve_bps/10000`. The target remains $0.10, the adverse allowance must be frozen before the holdout, and the ask remains capped at 5 bp above the current RH best ask. A 5 bp selection delegates to the original v1 target implementation; tests verify identical quotes, audit events, fills, fees, reserve, capital, and final ledgers. A 0 bp selection uses the same formula and book gates but can request a lower ask. Both variants still subtract the **same 5 bp reserve** and modeled capital cost from their reported stressed net. The fee-only value includes actual-notional venue fees and excludes that reserve and capital charge.

This is a **future policy preparation**, not a new result. Lowering the quote hurdle could increase modeled flow while reducing the stressed margin. It does not establish actual maker fills, a known queue position, a successful hedge, or an executable USDG/USDC conversion. Cancel races, partial fills, late prints, and unknown inventory use the inherited guarded state machine. A comparison should keep matched entry cohorts and report every unresolved branch separately. No additional capture or replay has been launched for this variant.

Implementation: `scripts/rh_passive_exit_cost_policy.py`; focused tests: `tests/test_rh_passive_exit_cost_policy.py`.
