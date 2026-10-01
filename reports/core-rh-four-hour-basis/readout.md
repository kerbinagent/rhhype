# Four-hour Core/RH basis diagnostic

**No signal at any of 120 scheduled decisions.** ETH was primary; BTC and
SOL were controls. Each had 40 eligible prior-data observations and zero
entries. No outcome is recorded as a win, loss or zero P&L.

The source and plan were frozen in commit `4c5f9ae`; the offline run completed
1 October 2026 at approximately 03:29 UTC with no market requests.

## Fixed question

Does a large price gap from its earlier median offer a reason to test
four-hour convergence? The rule used existing Core and RH hourly candles,
at six-hour decision intervals from September 19 03:00 through September 29
03:00 UTC. Define basis as 10,000*(Core close / RH close - 1). Compare the
last completed hour with the median of the preceding 24 hours; a deviation
of at least 10 bp would trigger a trade against that deviation. Planned
entry was delayed one hour, with a four-hour hold and no overlapping cycle.

All prior 25 hours had to be present with at least $1,000 recorded volume
on both venues. Future entry/exit volume would mark missing outcome quality,
never suppress a selected signal. Zero Standard fees were an optimistic
scenario; capital was 5% on $2,000 over the hold, plus $0.50 stress. Funding
value units remained inferred; adverse boundary-payment timing was explicit.

| Asset | Scheduled decisions | No signal | Max absolute median deviation | Median absolute deviation |
| --- | ---: | ---: | ---: | ---: |
| ETH, primary | 40 | 40 | 3.5048 bp | 0.6530 bp |
| BTC | 40 | 40 | 1.8142 bp | 0.7830 bp |
| SOL | 40 | 40 | 8.3615 bp | 0.9288 bp |

These are the full fixed decision set, not selected favorable hours. No
threshold reduction, horizon adjustment or new asset search follows this
result. It does not rule out every possible basis predictor; it establishes
that this prerequisite was absent in the chosen historical observations.

## Limits and checks

The archive was previously used for other research, so this is historical
development, not fresh validation. Hourly candle opens/closes are asynchronous
trade observations, not simultaneous executable prices. USDG/USDC conversion,
margin, idle capital and cash recycling are not simulated. The unused
cashflow branch would only have measured conditional cycle cost headroom.
Actual P&L remains null.

Before evaluation, synthetic checks verified prior-only signals, matched
quantity cashflows, conservative funding boundaries, and retention of
selected but unobservable outcomes. Afterward all 120 stored deviations
reconciled to the prior medians and remained below 10 bp. No separate-agent
audit is claimed. Source/input hashes, the complete decision rows and
terminal status are retained within the 128 KiB reservation in the existing
active research pool. No production strategy or wallet was modified.
