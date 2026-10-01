# Core/RH monthly funding persistence

Frozen source/allocation commit `e3ef8b7`; five public requests completed
1 October 2026 at 03:09 UTC. Reused the previously collected Core ETH month.
All six histories have 720 unique hourly events in September. No retries.

The first seven days independently chose each asset's funding direction.
SOL was primary and BTC/ETH controls before these requests. Directions stay
fixed throughout every later block. This is historical development research;
the earlier 48-hour screen used overlapping September 27–29 observations.
It is not an untouched or prospective validation sample.

## Results

Amounts are signed funding **rate basis points**, not fixed-quantity dollars.

| Asset | Selected short venue | Sep 8–14 | Sep 15–21 | Sep 22–28 | Sep 29–30 | Sep 8–30 aggregate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| SOL, primary | Core | -3.26 | -2.12 | 16.77 | 2.82 | 14.21 |
| BTC | Core | -1.73 | -0.70 | 4.33 | -0.19 | 1.71 |
| ETH | RH | 3.86 | 7.40 | -0.12 | -0.17 | 10.97 |

The 5% capital hurdle on twice one-leg notional is 19.1781 bp per seven-day
block, 5.4795 bp for the tail and 63.0137 bp for the aggregate. Apply a
separate 5 bp stress charge to each independently evaluated hold.
**All 15 asset/block residuals are negative**, even with zero trading fees
and before spread, basis and conversion. The aggregate overlaps the blocks;
do not add their outcomes or repeatedly charge its stress allowance.

For the primary SOL direction, the first two evaluated weeks lose funding
before costs. Its aggregate 14.21 bp leaves 9.21 bp after stress, supporting
at most 0.2923 times one-leg notional as total committed capital at the 5%
hurdle, before any execution cost. With equal wallets that is about 14.6%
per venue. This is break-even arithmetic, not evidence that such collateral
would survive the price path. BTC's aggregate does not cover stress even at
zero capital cost; ETH supports at most 0.1895 times one-leg notional.

## Decision and limits

The earlier favorable daily SOL difference did not represent a stable
month-long advantage. This fixed-direction, fully reserved funding-only
justification fails. No expanded collector or strategy promotion follows.
The complete negative outcomes and partial-period reversals remain visible.

Historical rates do not fix future payments. Venue-specific index prices,
fixed-quantity cashflows, entry/exit basis, USDG/USDC conversion and local
margin paths are absent. Current zero Standard fees are an optimistic
scenario, not verified historical/account fees. The Core fee page was
checked; RH documentation was unavailable through the browser, so archived
RH metadata/schema remain the stated assumption. Actual P&L is null.
[Core fee rules](https://docs.lighter.xyz/trading/trading-fees),
[funding mechanics](https://docs.lighter.xyz/trading/funding).

## Verification and storage

Synthetic tests before requests checked train-only sign choice, direction,
capital/stress, missing training/evaluation data and the allocation chain.
After collection, a separate Decimal calculation reconciled all 15 rate/cost
identities and all five raw response hashes in the root session. This is
not an independent-agent audit. The 128 KiB maximum is part of the existing
4 MiB active research pool; overall reservation remains unchanged.
