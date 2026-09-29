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

Verified launch: **20:40:39 UTC**, PID **2256789**, commit **7742531**.
Expected stop **21:00:39 UTC**. `launch.json` records the exact command and
initial process/snapshot checks. Analysis will preserve still-open exposure
at the deadline rather than invent a close.
