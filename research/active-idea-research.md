# Active idea research — 1 October 2026

## Working change

The user explicitly asked the primary agent to research ideas and a cheap
model to monitor. A `gpt-6-luna` agent now owns scheduled report preservation
and collection-health alerts. The root agent owns hypotheses, accounting and
experiment decisions. Repeating healthy collection checks is not research
progress. The fresh BTC dated-carry study continues unchanged to its frozen
endpoint, 4 October 00:30 UTC, with no interim economic inspection.

## First new calculation: absolute funding versus a funding difference

The old funding screen primarily compared two perpetuals. Funded spot plus
a short perpetual receives the short's absolute funding rate instead. Those
are different return streams: replacing a long perp that receives negative
funding with spot can actually reduce carry.

[Reproducible exploratory arithmetic](../scripts/spot_perp_idea_screen.py)
uses the existing 27–29 September archive and cross-checks HL totals against
the old hourly CSV. This is reused historical evidence, not new validation.
Amounts are rate basis points, not fixed-quantity dollar cashflows.

| Candidate | Second observed day, funding bp | Required daily bp for illustrative 7-day cost recovery |
| --- | ---: | ---: |
| Spot + short HL BTC | 1.429 | 4.740 |
| Spot + short HL ETH | 3.000 | 4.740 |
| Spot + short HL SOL | 2.390 | 4.740 |
| Spot + short HL HYPE | 2.712 | 4.740 |
| Core ETH spot + short Core ETH perp | 2.880 | 3.454 |
| Short Core / long RH SOL | 3.210 | 3.454 |
| Short Core / long RH BTC | 0.960 | 3.454 |
| Short Core / long RH ETH | 0.000 | 3.454 |

The hurdle uses 5% annual opportunity cost on twice one-leg notional,
plus a separate 5 bp stress. HL adds 9 bp for its two taker fills and
optimistically forgives every spot trading fee; Core Standard assumes zero
trading fees. Spread, impact, basis, conversion and changing settlement
notional are omitted. The 7-day calculation is a constant-rate sensitivity,
not a seven-day observed return or a forecast. Capital cost is an opportunity
cost assumption, not an exchange debit. None clears this simple hurdle.
Full inputs and negative results are in the
[summary](../reports/spot-perp-idea-screen/summary.json).

## Ranked ideas to investigate

### 1. Same-venue spot/perpetual carry with a justified collateral buffer

Core Lighter's official fee page confirms zero Standard spot and perp
trading fees. Our archived inventory contains active ETH/USDC spot (2048)
and ETH perp (0). This avoids the second perpetual's funding liability and
an RH USDG/USDC venue conversion. It still has spot spread, two non-atomic
fills, spot/perp basis, withdrawal economics and a margin path.
[Lighter fees](https://docs.lighter.xyz/trading/trading-fees).

**Completed discriminating test:** the bounded September history returned
720/720 hourly slots. All four fixed weekly blocks fail the current capital
plus stress hurdle before spread/basis costs.
[Full readout](../reports/core-eth-funding-history/202609-v1/readout.md).
ETH was selected before this pull; no automatic asset search or extension.
The simple always-on version does not advance. Collateral efficiency and
selective entry remain distinct hypotheses requiring their own evidence.

**New collateral evidence:** Core's public metadata enables ETH at 70% LTV
and 85% liquidation threshold; the official multi-asset margin page explicitly
describes spot ETH collateral against an ETH short. A separate fixed 1.1x
capital [September candle screen](../reports/core-eth-collateral-candles/readout.md)
leaves $2.74 on ~$1,100 for the full month; three weekly blocks positive,
one negative. This is an exploratory lead, with inferred funding units and
non-executable candle prices. Next check actual spread/impact costs.

### 2. Portfolio-margin carry on Hyperliquid

Current official documentation explicitly supports spot holdings offsetting
short perps and automatic borrowing against eligible collateral. This can
reduce idle collateral and manual transfers. It adds utilization-dependent
interest, eligibility, supply/borrow caps and liquidation mechanics. The
current account gate is >$5m weighted master volume or >$10k account value;
small research notionals do not establish eligibility. Caps can force extra
settlement-asset funding. No account action or borrowing is authorized here.
[Portfolio margin](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-margin).

**Next test:** derive a cashflow and margin stress envelope including interest
on initial margin and on adverse price moves. Compare on total committed
capital, with the same cash benchmark. Do not double-count borrowed capital
as both free equity and a new return. The weak archived absolute funding
rates make ordinary BTC carry a low-priority execution experiment unless
cost/rate evidence changes.

### 3. Core/RH multi-day funding difference

The full reused 24-hour SOL difference is 3.21 bp with a direction selected
on the preceding day, versus the 3.454 bp/day seven-day illustrative hurdle.
It is closer than the HL routes, but remains below the hurdle before basis
and conversion. A longer paired history could distinguish a persistent
funding opportunity from a brief RH imbalance. Prioritize after the simpler
same-venue ETH test; no third collector is launched automatically.

## New documentation discrepancy to track

Both current Core Lighter pages now list Standard maker latency as 0 ms,
with 300 ms taker and cancel/modify latency. The API page reports an update
about seven hours ago. Earlier archived maker scenarios used a different
published delay. Preserve those historical assumptions; verify the effective
change time before a future maker model. Faster acceptance alone does not
remove queue uncertainty or rescue the completed negative quote paths.
[Current account types](https://apidocs.lighter.xyz/docs/account-types).

## Literature implication

Krestenko et al. study spot/perp carry as a collateral-control problem.
Their execution and backtest results motivate testing margin needs and
transaction costs jointly, rather than repeatedly adjusting entry spreads.
Their venue/data/model assumptions are not validation of our route.
[Paper](https://arxiv.org/abs/2605.05089).

## Resource and evidence limits

This first calculation and memo have a 32,768-byte allocation inside the
existing 33 MB diagnostic allowance; overall reservation stays 836,777,216
bytes. It adds no raw archive or market request. Any subsequent history
pull has its own bounded request/output allocation. Frozen carry sources,
samples and wallets are unchanged. No strategy is promoted by this memo.
