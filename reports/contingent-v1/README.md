# HL-first contingent paper trial v1

Method and runtime code frozen before launch; 19 routes across 11 assets.
The [method](../../research/contingent-entry-plan.md) changes entry sequencing
only. Both independent policies receive the same selected candidates and
public WebSocket books. No real orders or extra REST book requests.

Run for 1,200 seconds with bounded SQLite state and rotating logs. The source
metadata and executable code hashes are preserved here. Results must retain
abstentions, zero fills, failed hedges and unresolved positions. Compare
matched candidate outcomes, not summed policy portfolios.

This selected WebSocket-only study does not reproduce production REST timing.
RH USDG versus HL USDC assumes parity, without executable conversion costs.
