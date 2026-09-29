# Robinhood Chain × Hyperliquid arbitrage survey

**Start with [the research report](reports/REPORT.md).** This September 29, 2026 survey combines canonical token/contract verification, 30 days of historical data, consecutive live orderbooks, read-only AMM swap simulations, and explicit entry/exit costs.

The main distinction is between Robinhood Uniswap stock tokens, Robinhood's separate Lighter spot/perp markets, and Lighter Core. Fees and liquidity differ. Positive opening spreads on perpetuals are basis exposures; the report tests subsequent unwinds and historical funding before drawing conclusions. No trades, wallet access or credentials were used.

**Follow-up:** [Overnight monitor audit](reports/monitor-audit/REPORT.md)—the dollar tally, signal duration, fee tiers, and exit-cost findings.

## Continuous monitor with simple TUI

```bash
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python scripts/monitor.py
```

Shows the best-ever top 10 and a persistent $1,000-per-positive-episode paper tally after fees. Concurrent public collection covers Hyperliquid versus Robinhood Lighter, Lighter Core and Aster. Old observations expire; records and totals survive restarts. See [monitor instructions](research/monitor.md) for background launch, the detachable `--watch` TUI, costs and retention settings. These are hypothetical entry edges, not completed-trade profits.

## Reproduce the frozen analysis

Python 3.13 was used. All analysis is ordinary Python/CSV/JSON; research memory is Markdown.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
tar -xzf data/evidence/public-market-evidence.tar.gz
.venv/bin/python scripts/rebuild.py
.venv/bin/python -m unittest discover -s tests -v
```

`requirements.txt` states compatible dependencies; `requirements-lock.txt` pins the environment used. The committed compressed evidence and SHA-256 manifest allow offline inspection and rebuilding. Generated timestamps will change, while calculations from the frozen observations remain reproducible. No credentials are required.

## Refresh public observations

These commands access public read-only APIs and may need network permission in a sandbox. Each live collection takes its configured wall-clock duration. Respect combined public API quotas; do not start overlapping collectors against the same endpoint at their full quotas.

```bash
.venv/bin/python scripts/hyperliquid_collect.py --census-only
.venv/bin/python scripts/robinhood_probe.py --all-pools
.venv/bin/python scripts/robinhood_probe.py
.venv/bin/python scripts/comparators_collect.py
.venv/bin/python scripts/live_collect.py --rounds 35 --interval 60 --lighter-max 30
.venv/bin/python scripts/robinhood_live.py --rounds 70 --interval 30
.venv/bin/python scripts/robinhood_universe_live.py --rounds 20 --interval 60
.venv/bin/python scripts/robinhood_lighter_collect.py --rounds 20 --interval 60
```

The supplemental market plan and historical defaults describe this frozen experiment. A new study must refresh its census, history window, canonical registry, corporate actions and fee metadata together; do not silently pair a new live run with old history. Public Lighter access is limited to 60 requests per minute, and HTTP 405 can indicate rate limiting. No VPN was needed for this dataset. If future data requires the authored Japan proxy, follow [its skill](skills/nordvpn-japan-proxy/SKILL.md); do not change host routing.

## Files

| File | Purpose |
|---|---|
| [Report](reports/REPORT.md) | Findings, ranked research candidates, fee/size sensitivity and limitations |
| [Journal](research/00-journal.md) | Research memory and decisions |
| [Methodology](research/01-methodology.md) | Comparability, timing, depth and inference rules |
| [Fee model](research/fees.md) | Per-account fees, gas/conversion reserves, funding and capital cost |
| [Robinhood notebook](research/robinhood.md) | Canonical assets, AMM contracts, multiplier events and historical source checks |
| [Hyperliquid notebook](research/hyperliquid.md) | Full market census and API mechanics |
| [Comparator notebook](research/comparators.md) | Core and Robinhood Lighter, Aster, dYdX, GMX and other venues |
| [Historical study](research/history-analysis.md) | 20-day direction selection / 10-day holdout, funding, cash carry and RH basis |
| [Audit](research/audit.md) | Independent calculation checks and lot-size issues |
| [Data guide](data/README.md) | Raw evidence, checksums and derived CSVs |
| [Figures](reports/figures/) | PNG and SVG research charts |

Raw API observations and hypothetical book walks are not actual fills. Source timestamps, errors, rejected books and missing coverage remain part of the evidence.
