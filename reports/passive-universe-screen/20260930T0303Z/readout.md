# Incomplete first universe screen

The first frozen attempt stopped at 2026-09-30T03:06:28.939503+00:00 after RH disconnected before round three. It collected two of five rounds, 42 of 105 planned HL books, and 168 of 420 planned size observations. There were 120 valid observed size rows and 48 stale source/receipt rejections. Another 252 size observations were never sampled. **No asset has three valid rounds; there is no eligible ranking or completed five-round result.**

The 26-route denominator retained 21 assets. XAU failed the required HL growth-mode-field check; SPCX/PONS/SKHY/SOXL failed the conservative underlying allowlist. Fresh volume thresholds and metadata were otherwise applied without overrides.

The socket received 6,183 tickers and ignored 1,050 initial trade-history rows plus two non-post-subscription updates. It stored 534 ordinary deduplicated post-subscription prints. No malformed/duplicate counter was incremented and the 20,000-print ledger cap was not reached; this does not prove a complete public tape. The original runner did not persist precise socket-close or per-market subscription-acknowledgement times. Round 0's receipt bucket ran for 60.0008 seconds. Round 1's nominal bucket was about 60 seconds, but socket loss before detection may have shortened actual observation. Warmup is a separate round -1 bucket. The trade aggregate describes observed aggressor flow and is unrelated to maker fills.

All valid static stressed margins observed in this attempt were negative. Each row remains a conditional unchanged-book two-maker RH / two-taker HL quote calculation, not realized or expected profit. No fill, private ACK, actual queue position, funding, financing or USDG/USDC conversion was measured. Original frozen files and raw quote hashes are preserved.

The existing streaming implementation's explicit application keepalive addresses busy-inbound heartbeat starvation. A separately authorized, independently frozen replication uses fixed 30-second outbound application pings. Its request budget is additional and the first attempt's 42 HL reads remain in cumulative accounting; the two attempts are never pooled into a median.
