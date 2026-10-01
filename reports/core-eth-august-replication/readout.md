# August ETH collateral replication

Frozen source/allocation commit: `b8a7fcc`. Four public requests completed
1 October 2026 at 03:04 UTC: 744 hourly funding observations and 31 daily
candles each for spot, perpetual and mark. No retries or alternative assets.

## Result

The primary full-month candle proxy is **+$1.255659** on $999.836048 spot
principal plus a 10% cash buffer. Its components are $7.628028 inferred
funding, -$1.201984 basis change, -$4.670467 capital opportunity cost and
-$0.499918 stress. Actual P&L is null.

| Fixed window | Inferred funding | Basis change | Capital | Stress | Residual |
| --- | ---: | ---: | ---: | ---: | ---: |
| August 1–31, primary | 7.628028 | -1.201984 | 4.670467 | 0.499918 | 1.255659 |
| August 1–7 | 1.339364 | -1.615166 | 1.054622 | 0.499918 | -1.830342 |
| August 8–14 | 0.945275 | -1.093070 | 1.054637 | 0.499925 | -1.702357 |
| August 15–21 | 1.656222 | -2.252898 | 1.054754 | 0.499981 | -2.151412 |
| August 22–28 | 2.147296 | 2.911573 | 1.054555 | 0.499886 | 3.504428 |
| August 29–31 | 0.526622 | -0.090090 | 0.452006 | 0.499946 | -0.515420 |

USD figures use fixed quantity within each window. The month overlaps the
diagnostic blocks; do not add them. Each block separately rounds quantity
down to a 0.0001 ETH lot and excludes its opening-hour funding payment.
Three of four weekly diagnostics and the three-day tail are negative.

## Interpretation

The same design had a +$2.74 September monthly candle proxy. August was
previously unseen when this replication was frozen, but was chosen after
September research: this is historical replication, not prospective
validation or a chronological holdout. No week was used to retune rules.

The later five-round quote screen's $0.472528 median round-trip cost would
reduce August's residual to approximately $0.7831 if substituted. That is
only a cross-period sensitivity. Candle opens/closes are not executable
quotes; no historical fills, transfers or account eligibility are proven.
There is little absolute surplus to absorb missing costs.

Funding `value` is interpreted as USDC per ETH; the official API model
names it without defining its unit. Official trading documentation states
that payment uses quantity, index and signed rate. Exact API value semantics
remain unverified. Current ETH collateral settings were applied as a
sensitivity; historical availability is unknown.
[Funding mechanics](https://docs.lighter.xyz/trading/funding),
[official API model](https://github.com/elliottech/lighter-python/blob/main/lighter/models/funding.py).

Daily low spot/high mark stress leaves a minimum $501.37 IMR and $702.36
MMR headroom proxy in the full month. These asynchronous trade/mark extrema
are not collateral oracle history or a liquidation-safety proof. They omit
funding from the balance path. Local account operations and collateral caps
also need verification before any prospective design.

## Reconciliation and resource use

Synthetic checks covered payment boundaries, funding direction, accounting,
missing data and the budget chain before requests. After collection, all
six cashflow identities and four raw hashes reconciled using a separate
Decimal calculation in the root session. Its initial check used binary
float JSON parsing and failed an overly precise tolerance; decimal parsing
resolved that check without changing the frozen source or output. This is
not an independent-agent audit.

The 64 KiB reservation covers source 8 KiB, raw 32 KiB, output 16 KiB and
control 8 KiB, within the existing active research reserve. Raw gzip files
total 9,872 bytes. Full inputs, provenance, summary and terminal status are
retained. No production strategy or wallet changed.
