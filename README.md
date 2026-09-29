# Robinhood Chain × Hyperliquid arbitrage survey

Research started 2026-09-29 UTC. Read-only public market research; no orders or wallet access.

## Research structure

- `research/00-journal.md`: decisions, progress, and research memory.
- `research/01-methodology.md`: economic comparability and measurement rules.
- `research/robinhood.md`, `research/hyperliquid.md`, `research/comparators.md`: sourced venue notebooks.
- `scripts/`: reproducible Python data collection and analysis.
- `data/raw/`: original timestamped API responses (local, ignored by Git).
- `data/derived/`: compact auditable tables (committed).
- `reports/`: final findings and figures.

The survey distinguishes executable two-sided quotes from last prices, historical basis from profit, and carry from risk-free arbitrage. Conclusions will be constrained by observed depth, fees, collateral, asset rights, and sampling coverage.
