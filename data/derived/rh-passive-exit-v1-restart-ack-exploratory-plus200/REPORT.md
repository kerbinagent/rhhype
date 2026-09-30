# EXPLORATORY POST-CAPTURE ACK model replay

EXPLORATORY POST-CAPTURE MODEL: one explicitly selected deterministic ACK sensitivity. The model is prepared after capture launch and is not an original prospective v1 result or the separately frozen retirement-corrected result. Code snapshots attest the implementation used for this diagnostic; they are not a pre-holdout freeze or authorization. Native trade IDs are assumed stable across transport generations. Private ACK clocks, actual fills, queue position and private notification timing are unobserved. Completed economics are conditional scenario results, never a guaranteed/executable profit bound or causal improvement over strict v1. Changes combine deterministic clocks with ordered coverage checks, raw-anchor revision checks, native-ID evidence, and outer historical execution guards that still operate after an unrelated halt.

Selected scenario: `plus200` (`assumed_ack_plus_200ms`). standard: maker 500000000 ns, cancel 500000000 ns; premium: maker 300000000 ns, cancel 300000000 ns. Every branch remains independent; correlated branch nets are never summed. Changed fills or admission histories are sensitivity diagnostics. Unknown execution, funding, or obligations retain unknown net.


Status: **complete**; 128 independent branches.
Original fixed-best opportunities: 371212 book-event checks; retained admitted cohorts: 352.
Primary Standard XAG/$1,000 same-entry complete pairs: 0; mean treatment minus control: None USD conditional on parity.

The primary contrast is descriptive and excludes no-flow, unsettled,
funding-unknown, and mismatched-entry cohorts from paired cash. Their
counts remain in analysis.json. Neither public trade-through nor a
displayed book establishes a private fill or executable conversion.
The final 80 seconds of the 20-minute holdout admit no new entries.
Unknown terminal inventory is not assigned a zero result.
