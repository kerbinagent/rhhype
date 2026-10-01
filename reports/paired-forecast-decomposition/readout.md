# What consumed the forecast margin

Retrospective diagnostics of two sealed cohorts; all numbers exclude the
separate 5 bp stress allowance. Independent alternative arms are not summed.
Only fully paired trades enter this decomposition; the four equity rescues
remain included in the parent equity report.

| Cohort / branch | Pairs | Forecast gross | Entry price change | Exit forecast miss | Actual cash |
|---|---:|---:|---:|---:|---:|
| Crypto immediate | 6 | +$0.216747 | −$0.265639 | +$0.011326 | −$0.037566 |
| Crypto two-second | 1 | +$0.011913 | +$0.026860 | +$0.007067 | +$0.045840 |
| Equity immediate | 2 | +$0.029581 | −$0.115608 | −$0.050170 | −$0.136197 |

The identity is forecast gross + entry change + exit forecast miss = actual
gross. Entry change compares the original signal's two executable entry
values with eventual filled values. Exit forecast miss compares eventual
exit cash flows with the modeled exit component, including assumed basis
reversion. It combines forecast error, elapsed market movement and execution.
These are exact accounting decompositions, not causal estimates. Fees in
these specific cohorts were zero.

In the six-trade immediate crypto cohort, adverse entry movement alone
exceeded the entire forecast gain; the aggregate exit component slightly
outperformed forecast. Tighter entries have already been tried separately:
all three 1 bp-limit attempts in the earlier tight-control study became
failed-hedge rescues. Tightening limits therefore needs a paired-fill solution.

## Exit request marks can disappear before execution

Five immediate crypto trades requested a take-profit exit. HYPE marks of
+$0.013704 and +$0.016800 became +$0.000040 and +$0.003248 in cash. One NEAR
mark of +$0.041052 became −$0.117316 after a 0.584-second request-to-flat
interval: a $0.158368 adverse change. VVV and the other NEAR close improved
during their exit delays. The confirmed VVV shares the control exit event,
so its improvement is not independent confirmation.

The exit diagnostic uses saved trigger marks with modeled accrued capital
added back. It does not independently reconstruct the trigger depth because
idle books were not retained; actual fills were audited separately. Maximum
hold exits have no saved trigger mark and are excluded from this section.
The larger-target experiment was already frozen before these diagnostics;
no active outcome, threshold or timing was changed.
