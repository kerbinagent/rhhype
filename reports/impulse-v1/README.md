# Prospective impulse-dislocation quote pilot

Status: method frozen before collection; no outcomes collected yet.

This study tests whether a fresh relative-price shock identifies a profitable
**paired** entry and unwind. It does not place orders or replace a paper policy.
The authoritative [method](../../research/impulse-observer-plan.md) and code
are committed before collection. Metadata are frozen in `market-plan.json`;
its provenance records the source and selected-plan hashes.

| Assets | Venues | Frozen taker fees, each execution |
|---|---|---|
| BTC, ETH | Hyperliquid versus Lighter Core or RH | HL 4.5 bp; Core/RH 0 bp |
| NVDA, XAG | Hyperliquid HIP-3 versus Lighter Core or RH | HL 0.9 bp; Core/RH 0 bp |

These are discovery-time Standard account assumptions, including the sampled
market fees. They are not a promise of future or account-specific charges.
Each quote path pays four fees on its own execution notionals, then a 5 bp
reserve on the larger entry leg and an elapsed capital estimate. RH USDG and
HL USDC are assumed at parity for the quote comparison; conversion is unmodeled.
Equity and silver contract/oracle differences remain a hedge-basis risk.

Primary observation delay is 0.5 seconds **after confirmation**; the 1 second
stress scenario uses the same frozen candidate and quantity. Entry observation
must still occur by impulse+2 seconds. Late confirmation therefore leaves less
time for the stress scenario; its missing observations are reported explicitly.
Dollar comparisons across delays use only candidates with both complete paths.
Both source and collector receipt times must follow the relevant due time.

The experiment has no matched no-impulse control, so it cannot identify the
impulse feature's incremental contribution. Positive quoted outcomes would
still require a fill and failed-hedge study. Missing outcomes are not zeros,
and correlated candidates/scenarios are not a realizable portfolio tally.

Collection is bounded: eight physical pairs, one active candidate per pair,
two scenarios per candidate, 60 basis samples per pair and 5,000 exported
terminal rows. There is no raw book archive. The intended pilot duration is
1,200 seconds, with a hard CLI limit of 2,400 seconds. Atomic snapshots replace
old output, and logs rotate at 2 MiB with two backups. Export truncation, if
any, is counted explicitly.
