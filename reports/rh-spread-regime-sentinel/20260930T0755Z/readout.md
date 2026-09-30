# Sentinel preparation failed before quote collection

The 07:55 UTC preparation made three successful public metadata requests; all 21 original assets were eligible. The source was committed as `c16be2f`, and the reviewed metadata stage as `53a2a66`.

The run stopped at its pre-connection control-space guard. Reconstructed control usage was **80274 bytes**, above the fixed **80,000-byte** admission threshold. No websocket was opened, no ticker was collected, and no economics were computed. All **1,680** planned size rows are preserved as uncollected.

This is an implementation/preflight failure, not market evidence. The offline full-artifact fixture checked the 90,000-byte category ceiling but did not exercise the stricter actual run-admission check. The failure guard itself preserved the denominator. The original stage and all sources remain frozen; it will not be retried. A separate resource-only proposal is under review, without authorization for another network request.

See `root-failure-audit.json` for verified hashes and exact keys. No losses, portfolios or prior evidence were reset.
