# RH passive-exit retirement corrected replay

**Separate corrected implementation: `entry-same-receipt-retirement-corrected-v1`.** Original v1 remains a separate result. The runtime branch binding uses `RetirementGuardPassiveExitBranch`; this amendment was frozen during the already launched capture, before its holdout cutoff. Qualifying retired-entry flow makes execution unknown without inventing fills or zero outcomes. Admission can stop earlier after unknown; price, queue, ACK, fees, quantity and economic assumptions retain original v1 definitions.


Status: **complete**; 128 independent branches.
Original fixed-best opportunities: 371212 book-event checks; retained admitted cohorts: 1298.
Primary Standard XAG/$1,000 same-entry complete pairs: 0; mean treatment minus control: None USD conditional on parity.

The primary contrast is descriptive and excludes no-flow, unsettled,
funding-unknown, and mismatched-entry cohorts from paired cash. Their
counts remain in analysis.json. Neither public trade-through nor a
displayed book establishes a private fill or executable conversion.
The final 80 seconds of the 20-minute holdout admit no new entries.
Unknown terminal inventory is not assigned a zero result.
