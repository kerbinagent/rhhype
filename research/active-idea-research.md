# Active idea research — updated 2 October 2026

## Current scope: short-term trading, including one venue

The user's latest instruction excludes buy-and-hold yield and maturity
strategies. Research targets trading cycles lasting seconds to minutes,
including directional paper trades on one venue. On 2 October the user clarified
that $100 was an example and larger sizes are allowed; assess their depth,
execution costs and capital use. Existing frozen tests retain their declared
sizes. The completed carry work below is historical context, not the
active plan. The already frozen BTC collector remains unchanged, with its
economic evidence unopened until its endpoint.

The [current decision register](research-decision-register.md) records which
mechanisms are parked, what the latest single-venue evidence shows, and what
would justify another experiment. The [revised method](01-methodology.md)
requires a cost-aware signal screen and explicit controls before another
execution variant. The older research below explains the path taken; it is
not the current experiment queue.

- [Fresh Core/RH paper test](../reports/core-rh-small-shortterm/readout.md):
  the primary $100-per-leg, ten-second branch closed 11 paired trades,
  zero wins, and −$0.183554 cash P&L. One-minute and five-minute controls
  were also negative. All 112 recorded fills and venue wallets passed the
  independent audit. No unresolved inventory or below-minimum exits.
- [Base atomic cycles](../reports/base-atomic-cycle-slow-transport/readout.md):
  all 36 same-block USDC/WETH round trips were negative before gas;
  best $100 surplus −$0.042124. The initial rate-limit failure is retained.
- [RH stock-token atomic cycles](../reports/rh-atomic-stock-cycle/readout.md):
  all 48 exact chained v3/v4 round trips were negative before gas;
  best 100-USDG surplus −0.087617 USDG.
- [Lower-fee NVDA complete-input screen](../reports/rh-nvda-complete-input-cycles/readout.md):
  all four active v3/v4 pools, 72 fixed outcomes. Of these, 39 complete
  quote cycles were negative before gas; 33 were unknown because a v3 leg
  reached its price limit. Best 100-USDG surplus −0.014920 USDG. The earlier
  12 low-fee quotes are also unknown after the input-completion correction,
  rather than valid full-cycle losses.
- [Paradex public preflight](../reports/paradex-public-transport/readout.md):
  12 successful metadata/book reads. Interactive orders have conditional
  zero fees and a documented 300 ms delay. Only 3 of 9 public books met the
  current two-second source-age gate. Funding accrues continuously, so a
  future short-term test needs funding-index accounting. No paper trades
  or economic results were produced by this transport/schema check.

The paper losses persist with zero Standard fees and without stress or capital
deductions. Entry worsened in 10/11 trades, with median deterioration $0.026716;
take-profit marks failed to survive delayed exits. This does not justify faster
fill assumptions or retuning. No profitable strategy is established. The decision
register tracks the completed news study and its prospective successor.

## Division of work

The user asked for parallel collection, broad root-led exploration and deeper
Sol analysis, and allocated 2 GB for rolling captures. The
[parallel workflow](parallel-research-workflow.md) separates those jobs.
The Mac mini peer owns Comet sales; local Claude Code owns Curve reward accounting
and the frozen HIP-4 schedule. Both have autonomous assignments through
3 October 08:00 UTC and report only a decisive result, hard blocker or that
checkpoint. Internal reviewers audit captures and preserve scheduled reports.
The root owns hypothesis selection and experiment decisions. Repeating healthy
collection checks is not research progress. The fresh BTC dated-carry study continues unchanged to its frozen
endpoint, 4 October 00:30 UTC, with no interim economic inspection.

## Earlier carry research: absolute funding versus a funding difference

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

## Earlier carry branches, superseded by the short-term scope

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

**Collateral follow-up:** ETH margin at 70% LTV supports a separate 1.1x
capital design. Monthly candle proxies leave $2.74 in September and
[$1.26 in August](../reports/core-eth-august-replication/readout.md), before
execution costs. Three of August's four weeks are negative. A five-round
quote screen found $0.47 median round-trip cost at $1,000. The
[funding-swap assessment](core-eth-fixed-funding-assessment.md) is also marginal.
These are research leads with inferred units and unproven execution.

**Full native crypto universe follow-up:** a separately frozen screen kept
all seven active native crypto spot/perp pairs. Four September funding-only
budgets were positive. Adding fixed-quantity candle basis and inferred dollar
funding leaves UNI +$3.92, LINK +$2.33 and SKY +$1.11 per roughly $1,000 spot
with equal cash reserve; the other four monthly proxies are negative.
All weekly blocks and the original DNS/date-validation failures remain in
the [full readout](../reports/core-native-candle-window-correction/readout.md).
Thin spot volume and unmatched candle trade times limit those proxies.
Three prospective book rounds across all seven assets and four sizes found
median $1,000 crossing costs of $2.86 UNI, $12.56 LINK and $56.89 SKY.
Only UNI leaves about $1.06 in a cross-period sensitivity, with unstable
weekly results and unresolved fills/margin. This does not justify a larger
collector. [All quote outcomes](../reports/core-native-quote-cost/readout.md).

**Staked collateral follow-up:** Derive supports simulated WSTETH collateral
and ETH shorts. The valid, precision-corrected public simulations address
current margin only. Observed Lido APR averages 2.261%; a fixed-price 30-day
sensitivity loses $3.78 per roughly $1,000 spot after capital, perp fees and
stress, before missing costs. Historical Derive funding returned no rows;
instantaneous zero funding is not a monthly forecast.
[Readout](../reports/derive-staked-eth-preflight/readout.md).

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

The [September persistence test](../reports/core-rh-monthly-funding/readout.md)
selected directions on the first week and retained all later blocks for
SOL/BTC/ETH. All 15 cost-adjusted rate proxies fail. SOL's aggregate
14.21 bp is below 68.01 bp capital plus stress; its first two evaluated
weeks lose funding before costs. The earlier favorable daily difference
was not a stable monthly advantage. No expanded collector follows.

A separate four-hour convergence rule using a prior-day median and fixed
10 bp trigger found zero signals across all 120 predefined asset/anchors.
[Readout](../reports/core-rh-four-hour-basis/readout.md). No trade P&L follows
from the absence of signals.

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
