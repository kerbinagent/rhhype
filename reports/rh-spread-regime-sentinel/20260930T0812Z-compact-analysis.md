# Completed spread-regime prerequisite: no asset advances

The separately allocated compact study completed its fixed window on
30 September 2026, **08:12:57.655706–08:32:57.655706 UTC**. All 21 assets
failed the predeclared $1,000 prerequisite. This is a completed negative
quote-screen result, not observed trading P&L.

## Result and denominator

All 420 planned asset/slot references and 1,680 asset/slot/size rows are
retained. There are **1,340 valid size observations and 340 stale rows**
(335 valid and 85 stale asset references). No asset became metadata-ineligible.
Every one of the 84 asset/size medians is negative; all 336 fixed-block
medians are negative. Thirteen assets meet the primary coverage threshold
of at least 16/20, but none meets the economic threshold. Eight assets also
fail primary coverage. Missing values remain missing, never zero returns.

The frozen primary requires at least 16/20 valid, a strictly positive full
median, and at least three of four blocks each with at least 4/5 valid and a
strictly positive median. Smaller sizes cannot rescue it. The only positive
optimistic budgets are three $1,000 rows: NEAR slots 4 and 5 (+$0.07489952,
+$0.07440609) and LIT slot 10 (+$0.046336). The two NEAR rows are adjacent
minutes, not evidence of independent episodes. LIT's median is −$0.25192590
(1/18 positive); NEAR's is −$0.225611905 (2/20 positive). There are no positive
observations at $100/$250/$500.

| Asset | Valid / 20 | Positive / valid | Median U, USD | Maximum U, USD | Passing blocks / 4 |
|---|---:|---:|---:|---:|---:|
| BTC | 20 | 0 | -0.5048459685 | -0.433884229 | 0 |
| ETH | 20 | 0 | -0.48180263325 | -0.438845104 | 0 |
| LIT | 18 | 1 | -0.2519259 | 0.046336 | 0 |
| NVDA | 16 | 0 | -0.33790883 | -0.29406948 | 0 |
| SOL | 19 | 0 | -0.38835487 | -0.33749335 | 0 |
| HYPE | 17 | 0 | -0.40234659 | -0.355152475 | 0 |
| AAPL | 10 | 0 | -0.34259442 | -0.26694442 | 0 |
| XAG | 14 | 0 | -0.2675880175 | -0.177858286 | 0 |
| GOOGL | 11 | 0 | -0.395683025 | -0.30812795 | 0 |
| SNDK | 16 | 0 | -0.33918796 | -0.26396704 | 0 |
| NEAR | 20 | 2 | -0.225611905 | 0.07489952 | 0 |
| ZEC | 18 | 0 | -0.27852595 | -0.2068692 | 0 |
| XRP | 18 | 0 | -0.331825225 | -0.26480815 | 0 |
| MSFT | 13 | 0 | -0.30548026 | -0.246594555 | 0 |
| MU | 16 | 0 | -0.29221335 | -0.24540132 | 0 |
| TSLA | 11 | 0 | -0.289936225 | -0.26165457 | 0 |
| META | 13 | 0 | -0.275098495 | -0.16710652 | 0 |
| CRCL | 14 | 0 | -0.18868281325 | -0.015965698 | 0 |
| AMD | 17 | 0 | -0.205737835 | -0.07461373 | 0 |
| AMZN | 15 | 0 | -0.316948 | -0.276531085 | 0 |
| INTC | 19 | 0 | -0.34176555 | -0.2557367 | 0 |

## Meaning and limits

U = q×(RHask−RHbid)−$0.10−0.0005×q×RHbid, with q rounded down to the
original common lot. This forgives all hedge spread and fees and assumes
the two RH top prices can be obtained. The 5 bp term is the unchanged
stress allowance, not a published exchange fee. U excludes funding,
credits/rebates, transfers, capital and conversion; it is not an overall
profit bound. All 1,680 paired-hedge outcomes remain unknown. There is no
queue, fill, Core depth or HL depth evidence in this study.

The evidence fails the declared advancement test. It does not prove that
all future prices, wider passive quotes, dynamic basis strategies or other
markets are unprofitable. It supplies no basis for relaxing the test,
selecting the three favorable minutes, promoting LIT/NEAR, or automatically
opening a full three-venue capture. This single study ends here; continuing
research and production reviews require separate decisions.

## Provenance, timing and resources

- Original collector freeze `c16be2f`; compact wrapper freeze `c927e2a`;
  fresh metadata/root freeze `a531060`, all before launch. Three fresh
  metadata requests and one websocket, 21 ticker subscriptions, 40 application
  pings; no reconnect. Six total metadata requests across both sentinel
  stages, with the first failed stage retained separately.
- Endpoint publication at 08:32:57.780645UTC. All 20 slots sampled; maximum
  dispatch delay 2.275656 ms against 250 ms. The collector reports no technical
  stop. Recorded close code 1006 is retained: the receiver was cancelled
  during endpoint cleanup, so this is not evidence of a graceful close.
- Delivered ingress 23,202,362 bytes and 88,945 messages, under 64 MB/100,000 caps.
  Eight dependencies, six compressed/decompressed source archives, all
  output hashes and category limits verified by the independent auditor.
- Auditor/source tests frozen in `3022b04` before the endpoint. Root and
  author passed five synthetic tests including deliberate corrupted math,
  clocks, hashes and block decisions. Root ran the auditor **once**, after
  both endpoint clocks and the terminal manifest, with a passing result.
  It independently recomputed all 1,680 rows and 84 groups/336 blocks.
- The auditor pins the fresh metadata and selection; root independently
  checked the full responses before launch. It cannot reconstruct every
  intervening invalidation/high-water update from the sampled stream.
- Final stage 337,548 bytes: control 59,849; metadata 227,891; samples 26,938;
  derived 17,353; logs 5,517. Auditor 18,433 bytes, tests 10,032 bytes and report
  900 bytes add 29,365 bytes. The entire stage, auditor, tests, audit report
  and this analysis fit below the unchanged 500,000-byte allocation.
  The failed first 500,000-byte allocation is not released; shared reserved
  maximum remains 32,110,904 of 33,000,000 bytes.

[Full four-size readout](20260930T0812Z-compact/readout.md),
[independent audit](20260930T0812Z-compact-audit.json),
[frozen method](../../research/rh-spread-regime-sentinel-plan.md), and
[first-stage failure](20260930T0755Z/readout.md) remain available.
