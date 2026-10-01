# LIT spot/perp: 500 ms pair-skew sensitivity

Protocol frozen at `d0b23b9`. Fresh public capture **2026-10-01 18:26:38.044349–18:36:38.934519 UTC**, 600.890 seconds, one connection, no errors, 12,894 records and 1,400,545 compressed raw bytes. Manifest SHA256 `c5ae087d5e7f1935d1f9661b7f7c291a90627a4e11d08093dddd183361c31129`.

**Zero quotes, zero fills, zero P&L, flat inventory and $600 final USDC cash.** No capital or funding charge, rescue, or unknown obligation. One independent LIT portfolio, $100 target per leg; no orders sent.

The separate timing assumption permits source and receipt skew up to500ms, retaining the2second absolute age limit. All other rules match the prior cash-retention study, including5bp excursion for new entry, one native tick inside the spot bid,100ms maker activation and400ms cancel/taker delays.

Of12,608 book callbacks,5,359 were outside the admission window,1,056 failed the freshness/skew gate, and6,193 failed the5bp excursion gate. None reached admission. These are mutually exclusive first-failure counts; they do not establish that later cash/depth gates would have passed.

Independent raw-event/cash, boundary and request-rate audits passed. With no admissions or fills, execution checks are vacuous. This sample provides no evidence that500ms improves quote retention or profitability and cannot be represented as a250ms result. All raw data, metadata, source pins and outputs remain retained.

During later replay, the separate broad paper monitor was found stopped after its18:34:54 UTC durable checkpoint because a checkpoint batch exceeded its WAL reservation. This dedicated capture continued cleanly through its own fixed endpoint. The monitor was restored separately with a smaller checkpoint interval and unchanged strategy settings; its coverage gap is recorded in `reports/monitor-wal-incident`.
