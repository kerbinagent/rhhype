# Offline RH passive exit markup diagnostic

Use only the completed 0310Z screen; do not change any frozen input or collect
new data. Retain the same 420 asset/round/size rows, 320 original valid rows,
100 original stale exclusions, common-lot quantities and public fee settings.
This is a necessary static quote-distance calculation, not a fill or future
profit prediction. Its purpose is to size a later hypothesis after the current
passive replay; smallest distance alone never nominates a trading candidate.

For original quantity q, RH maker entry bid b, proposed RH maker exit x,
fixed original HL short proceeds S and buyback cost B, RH maker fee fraction
r, and HL taker fee fraction h, solve exactly:

`q*x*(1-r) - q*b*(1+r) + S-B - h*(S+B) - $0.10 - stress >= 0`.

`stress = 0.0005 * max(q*b, S)` preserves the original larger-opening-leg
base. Thus the raw required price is

`[q*b*(1+r) + B-S + h*(S+B) + $0.10 + stress] / [q*(1-r)]`.

RH exit fees depend on the proposed exit notional, not the observed ask
notional. Reconcile both original RH maker fees and both HL taker fees against
the original saved modeled fee amount. Reconcile original stress and margin.
Keep the original unchanged HL walked prices/notionals; do not simulate a
different future hedge book or recalculate quantity at the new exit price.

Use exact rational arithmetic for the price inequality and ceiling to the
frozen RH decimal tick. Required exit is at least the observed best ask. Verify
the rounded price clears target/stress, and whenever an above-ask quote is
needed, the immediately preceding tick fails. Verify RH exit quote ceiling
and minimum notional. Distance is `(rounded x - original ask)` in price units,
integer RH ticks, and bps relative to the original ask. A missing/unsupported
fee, tick or exact arithmetic input becomes an explicit pricing limitation;
do not invent it or silently change original validity.

Report all four sizes' original valid denominator, supported count,
median/maximum distance, and every asset/size median and maximum. Eligibility
uses the same >=3 valid $1,000 rounds as the original screen; report eligibility
and unsupported coverage separately. Focus the readout on XAG/BTC/ETH/NVDA.
This arithmetic cannot estimate queue position, pass-through trade flow,
execution odds, adverse selection, delayed buyback costs, funding, collateral
conversion or losses from unfilled exits. Dynamic repricing would change the
quote, queue age, cancellation race and hedge prices and requires a separately
frozen lifecycle model. No candidate is selected by minimum distance alone.

Hash the original quote/universe/summary/manifest/freeze files and this method,
runner and tests; verify original frozen input hashes and unchanged read inputs
afterward. Write a new derived directory with a 2 MB cap and no network.
