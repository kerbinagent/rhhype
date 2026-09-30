# Reverse static best-quote route: conservative upper bound

This is a post-capture derived diagnostic from the completed `reports/passive-rare-spread/0252Z-fixed-1s-v1` report only. No raw event scan, strategy engine, new capture or network request. All 48,000 original fixed-anchor asset/budget identities remain in the denominator. Only valid parent rows have the two full HL depth walks needed for this bound. Parent-invalid rows remain **reverse unadjudicated**: insufficient HL taker-walk depth can exclude the forward route without excluding hypothetical HL makers.

## Proof

Use the unchanged parent's exact common-lot quantity `q`; RH best bid/ask `b,a`; and full HL sell/buy walk values `S,B`. Let `y=q*HLbestbid` and `x=q*HLbestask`. Valid depth implies `y>=S>0`, `x<=B`, and `x>y`. The hypothetical reverse static route buys HL as maker at its observed best bid, sells HL as maker at its observed best ask, and shorts/buys back RH with Standard takers. No queue or fill is inferred.

For HL maker fee rate `h` expressed as a fraction of own notional, with `0<=h<1`:

`HL maker gross minus fees = (1-h)*x-(1+h)*y`

`<= (1-h)*B-(1+h)*S`.

The joint monotonicity proof matters: this does **not** assert that actual maker fees are at least `h*(S+B)`. Standard RH taker fees are zero in the frozen metadata. Full RH taker sell proceeds are at most `q*b` and buyback cost at least `q*a`, so RH spread loss is at least `q*(a-b)`; missing/shallow RH depth cannot improve the ideal bound. The required stress reserve is at least `0.0005*y>=0.0005*S`.

Therefore the reverse static margin after the $0.10 target and 5 bp stress satisfies:

`margin <= U = (1-h)*B-(1+h)*S-q*(a-b)-0.10-0.0005*S`.

Frozen HL maker fees are 1.5 bp for BTC/ETH and 0.300 bp for NVDA/XAG; divide basis points by 10,000. Public base rates and growth/deployer context are inherited, with no user tier/discount/rebate assumed. Negative maker fees would invalidate this proof and are refused. Compared with the looser `B-S-2*h*S` bound, joint monotonicity reduces U by `h*(B-S)`.

All input decimals, quantity checks, bounds, comparisons to exact zero, and min/median/max use exact rational arithmetic. Display finite fractions as exact decimals; any other fraction is displayed as its exact numerator/denominator. Group medians are descriptive bounds, not P&L estimates. No P&L sum or independent-sample inference is made across overlapping anchors/budgets.

## Interpretation and excluded variants

`U<=0` conservatively rules out a **strictly positive** unchanged static best-quote reverse margin at that covered anchor and inherited q. Equality is nonpositive. `U>0` is merely an inconclusive loose bound; it supplies no candidate, actual spread, queue, execution or profit evidence.

The inherited q was sized by the forward RH ask. It may violate an HL-entry budget, and a separately sized reverse route would have another q. Neither reverse budget validity nor transfer to another q is claimed. HL quotes outside the observed best bid/ask, later repricing, longer horizons and dynamic market movements are excluded. Capital cost is nonnegative and could only lower this static margin. Funding may provide a credit and is explicitly excluded: this is **not an overall P&L bound including funding**. Common units and USDG/USDC parity remain inherited paper assumptions.

Missing/invalid anchors are not assigned a bound or known zero. An all-evaluated-row nonpositive result would exclude only this covered static variant; reverse feasibility at parent-invalid anchors and between the fixed 1s anchors remains untested.

## Completed-input and bounded-output gates

Read only the complete published parent's CSV, timing, metadata, summary, manifest and freeze/source copies. The sole optional additional file is `verification.json`, a later supplemental attestation: hash it before/after, but exclude it from the original manifest's output-hash expectation and do not claim the original freeze authenticated it. Refuse `.building`, any other missing/unexpected file, symlinks or an aggregate parent input over 16 MB. Verify all original published parent output hashes, its freeze/input consistency, complete verified nontruncated terminal, known stopped raw digest, decoder/adapter hashes and exact 124,019 decoded records. No raw path is opened to repeat these checks. Validate all 48,000 unique CSV identities, all 12,000 timing identities, all 16 routes and five 600-anchor strata, and exact parent summary/CSV valid/positive/exclusion counters. Verify inherited common-lot q and frozen HL maker/Standard RH taker rates.

Freeze new helper/method/tests and all completed parent file hashes before evaluation; verify them again before publication. No parent or frozen source is changed. Preserve all 48,000 row statuses and bounds in canonical index order (`k*16+asset_index*4+budget_index`); invalid rows have explicit status X and null bound. Group all assets/budgets/five strata into nonpositive, positive-inconclusive and parent-invalid-unadjudicated counts with min/median/max. No row subset is silently dropped.

Publish into a new report directory only after every check. New analysis, source freeze/copies, report and manifest together must fit 2,000,000 bytes before writing; refuse over-cap or existing output. There is no raw copy or storage-budget increase. The output is post-capture exploratory evidence and cannot nominate a route or authorize a capture.
