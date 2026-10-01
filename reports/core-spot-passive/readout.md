# Core spot passive entry / perpetual hedge — five alts

Frozen protocol `c7ccd78`; public read-only capture **2026-10-01 17:02:14.557045–17:12:15.339904 UTC** (600.783 s), one connection, no feed errors. Retained 28,010 records / 2,815,877 compressed bytes. Five independent $600 USDC portfolios, $100 target per leg; no spot borrowing. These portfolios cannot be combined into a $600 total-capital result.

## Results

| Asset | Quotes | Attributed fills | Cash / stress P&L | Final inventory |
|---|---:|---:|---:|---|
| SKY | 0 | 0 | $0 / $0 | Flat |
| UNI | 2 | 0 | $0 / $0 | Flat |
| AAVE | 4 | 0 | $0 / $0 | Flat |
| LINK | 0 | 0 | $0 / $0 | Flat |
| LDO | 0 | 0 | $0 / $0 | Flat |

Every quote was canceled for best-bid change on the activation callback. No positive or negative filled-trade outcome occurred. All portfolios retain $600 cash; no funding, capital charge, rescue or unresolved inventory. The six passing entry forecasts ranged from $0.01144 to $0.06207; they were forecasts, not realized gains.

## Audit and preserved adapter failure

The initial adapter retained an old schema identifier and rejected this archive **before any observations or economic events were processed**. Its source and failed output remain under `result/`. Commit `bf5e172` froze a schema-literal/error-text-only copied adapter and a wrapper targeting `corrected-result/`; all original trading source pins remain unchanged. Real archive hashes/metadata and the first connection control were checked before replay. The correction did not change trading rules or data.

The corrected replay completed without error. Independent audit verified all six admissions, 493 reference rows, and six queue episodes. Supplemental audit verified the first eligible activation and cancellation for all six quotes. Actual entry notional was zero. Fill, capital and exit checks are vacuous here; the separate synthetic test exercised one positive complete cycle and is not market evidence. Public flow would support conditional queue attribution, not private ACK/fill proof.

## Trade-flow finding and next hypothesis

All five spot trade subscriptions supplied backlogs, but there were **zero live ordinary trade frames in the entire ten-minute capture**. The newest backlog ages at start were SKY 5.31 h, LINK 2.21 h, AAVE 2.88 h, UNI 1.44 h and LDO 1.20 h. Historical backlogs were correctly excluded from fills. Extending quote lifetimes cannot supply a missing live trade in this window.

The archived fresh metadata reports daily spot quote volume about **$3.64m LIT** and **$304k ETH**, versus $121–$8,978 for these five alts. AAVE's 2,236 daily trades totaled only $809; trade count alone would be misleading. `flow-diagnostic.json` preserves all spot-market activity and backlog ages. The next prospective test will use LIT and ETH with this same frozen entry logic and fresh full book/trade capture. Selection is based on completed evidence, not a claimed realized edge.
