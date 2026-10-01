# Immediate versus confirmed PONS/CASHCAT entries

Prospective capture frozen at `60efe16`, 1 October 2026,
14:59:19–15:14:19 UTC. Independent $100-per-leg portfolios, $600 prefunded
each; 400 ms modeled orders, 10 bp entry limits, 60-second hold and 1 bp
forecast/profit hurdle. No actual orders.

| Entry rule | Paired closes | Cash wins | Cash after fees | After capital + 5 bp stress |
|---|---:|---:|---:|---:|
| Immediate | 2 | 0 | −$0.239578 | −$0.339469411 |
| Two-second confirmation | 1 | 0 | −$0.084437 | −$0.134385330 |

All three were RH-long/Core-short PONS trades. No CASHCAT entries, partial
fills, rescues, aborted attempts, below-minimum exits or unresolved positions.
The confirmed trade overlapped the second immediate trade; these arms are
separate counterfactual portfolios and cannot be pooled as independent trades.
Neither branch demonstrated profit in this capture.

Each branch had seven positive forecasts. Immediate entry admitted two,
rejected three by cooldown and one after the entry window; another positive
forecast did not generate a new attempt. Confirmation rejected five, accepted
two, and cooldown rejected one of those. Both evaluated 12,030 directions,
with 4,656 warmup, 106 clock/skew, 6,938 excursion and 323 forecast exclusions.

## Execution diagnosis

The first immediate trade requested a profit exit at an independently
reconstructed cash mark of +$0.010890. The delayed fills finished 0.599 seconds
later at −$0.082798: $0.093688 of adverse change after the request. Its entry
spread had not deteriorated. The other two trades reached their hold limit;
entry changes were −$0.048882 and −$0.062214, and the subsequent exit component
also underperformed its forecast. Full accounting identities are retained in
`execution-decomposition.json`; this is descriptive, not a causal estimate.

## Verification and retained qualifications

The fixed 900.030-second endpoint completed without errors or reconnections.
Both feeds used one connection; 27,848 messages / 13,818,358 inbound bytes.
The 131,662-byte compressed archive has 1,470 reference samples, three
admissions, 87 pending-order book callbacks, 12 fills, three exit requests,
three terminal positions and four shutdown invalidations. The independent
audit passed all 12 fills, reference provenance and forecast arithmetic,
first eligible book and 400 ms delay checks, depth, lots, cash, capital,
same-hour inventory and venue wallet identities.

An erratum frozen at `116e6e0`, before the 90-second reference warmup could
permit entry, corrected inherited plan prose: immediate is the focal arm,
raw admission soft cap 160,000 bytes and hard cap 262,144 bytes. Original plan,
erratum and running code remain unchanged. Both arms are reported fully.

Zero Standard fees and timing are now also supported by a fresh RH account
documentation excerpt (`reports/rh-account-doc-refresh/evidence.json.gz`).
The assumed 100 ms network allowance, private execution and USDG/USDC parity
remain unverified. Full wire traffic and idle full-depth books were not saved;
callback completeness depends on the frozen collector. These are paper results.
