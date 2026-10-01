# Derive option-box preflight

Eight frozen requests completed at 03:14 UTC on 1 October 2026. Source and
budget were committed as `b8da229`. These are official documentation and
mainnet metadata; no option quotes, account reads, RFQs or orders.

## Findings

The former v2 documentation URLs return 404. Current official documentation
uses v3 routes and explicitly lists `https://api.derive.xyz/v3` as production.
The three mainnet public POST requests succeeded. Testnet was not queried.

ETH options are linear USDC-quoted instruments, attached to the PRIME risk
universe (1). The option asset address in currency metadata agrees with
the instrument records. Current ETH reference spot is $2,686.041716.
The metadata reports Standard manager 1 and Portfolio manager 5 for PRIME;
no account eligibility or margin requirement was inferred from those IDs.

The fee documentation separately recognizes four-leg same-expiry boxes and
quotes a 0.5% annualized fee on their fixed payoff, plus $0.50 for the taker.
That applies to recognized box execution; four independent orderbook fills
must use their own fees. Current instrument metadata has a $0.50 base fee,
0.03% taker rate, and 12.5% option-premium fee cap per option order.
[Fee specification](https://docs.derive.xyz/integrators/trading/trading-fees).

For low strike K1 and high strike K2, equal quantities of long call K1,
short call K2, long put K2 and short put K1 have terminal value q*(K2-K1).
This algebra assumes identical contract units, expiry and settlement price.
Derive describes a shared expiry TWAP and settlement into the universe's
cash asset. Contract identity, local margin, execution and all required
costs must still be verified; the fixed payoff is not a profit claim.
[Settlement specification](https://docs.derive.xyz/settlement).

## Incomplete catalogue

The frozen one-page metadata request returned 1,000 instruments, while
pagination reports 1,010 across two pages. Therefore **this preflight is
incomplete for catalogue-wide selection** despite successful HTTP responses.
Its `completed_metadata_only` terminal label means only that all eight
requests finished, not that this gate passed. No expiry or strike was chosen
and no quote economics was computed.

A separately bounded second-page completion can resolve the ten missing
records while preserving this original result. A subsequent quote study
must freeze maturity, strike and size rules before reading option prices.
Public orderbook prices would assess a different execution route from a
private atomic RFQ; public quotes cannot prove an available RFQ price.

## Storage

Source, five documentation pages, three raw metadata responses and provenance
are retained within the 256 KiB preflight reservation. The active research
pool has 622,592 bytes reserved of 4 MiB; the overall budget is unchanged.
