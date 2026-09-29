# Impulse dislocation quote study

Stopped pilot. Quotes are prospective observations, not fills or cash P&L.

## Full-run gate, arm, and scenario accounting

Armed 1; confirmed candidates 0; paired entry quotes 0; complete quotes 0. Candidate scenario accounting residual 0; arm accounting residual 0.

Gate counts: confirm_basis=1, history_warmup=9176, impulse_history_short=27017, impulse_small=68484, missing_leg=29, other_moved=3, receipt_skew=65, source_age=2493, source_not_advanced=461, source_skew=6200, trigger_depth=13181.

Arm terminals: confirm_basis=1.

Censor reasons: none.

| Arrival | Candidates | Paired entry quotes | Complete | Entry depth | Exit depth | Entry missing | Exit missing | Funding unknown | Stopped pending |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1 s | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Other gate and censor reasons, including invalidation and minimum-notional failures, remain in the JSON counters.

## Retained arrival scenarios

Terminal rows retained 0; all-run export drops 0. Retained complete 0 of 0 all-run; retained censored 0 of 0 all-run. Distributions below use retained complete quoted outcomes only.

| Arrival | Retained complete | Retained censored | Four-fee net mean / p10 / median / p90 USD | Four-fee positive | After reserve and capital mean / p10 / median / p90 USD | Positive |
|---|---:|---:|---|---:|---|---:|
| 0.5 s | 0 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |
| 1 s | 0 | 0 | ? / ? / ? / ? | ? | ? / ? / ? / ? | ? |

Entry timings include retained scenarios with a paired entry quote, even if the exit was censored. Exit timings include complete quotes only. Values are median milliseconds after each scenario's due time; HL and other venue are shown separately.

| Arrival | Entry source HL / other ms | Entry receipt HL / other ms | Exit source HL / other ms | Exit receipt HL / other ms |
|---|---:|---:|---:|---:|
| 0.5 s | ? / ? | ? / ? | ? / ? | ? / ? |
| 1 s | ? / ? | ? / ? | ? / ? | ? / ? |

## Same-candidate paired comparison

Both scenarios retained for 0 candidates; both complete for 0. Retained candidates with only one scenario row: 0. Stress minus primary net quoted outcome median $? among complete pairs only. Missing or censored outcomes are never filled with zero.

## Retained breakouts

The JSON contains scenario-separated counts and full mean/p10/median/p90 distributions for gross capture, each of four fees, reserve, capital, and net quotes by pair direction and five-minute UTC trigger block, separately and jointly. Censored-only groups remain present. These are retained-row views, not full-run cohort rates.

Validation warnings: none.

## Interpretation

- Prospective quotes at a frozen quantity, not orders, paired fills, cash P&L, or realized profit.
- The 0.5 s and 1 s arrival scenarios share each confirmed candidate; their counts are correlated.
- First eligible future quote with insufficient entry or exit depth is censored, not treated as zero.
- Funding-unknown and stopped-pending outcomes stay censored, not breakeven observations.
- Source clocks across venues are not calibrated; receipt order is collector order only.
- USDG and USDC are treated at parity for this quote screen, with no conversion or collateral claim.
- There is no no-impulse control in v1; retained rows can omit older terminal scenarios.
