# Completed ACK scenario halt review

This offline review uses the completed `base` and `plus200` exploratory ACK results from the same 2026-09-30 capture. Neither scenario observes private acceptance, cancellation, or fills. Their known economics remain **conditional_known**. The immutable 21 replay dependencies and both completed outputs were checked; none was changed. The companion bounded record is `reports/passive-ack-halt-review/diagnostic.json`.

## Assessment

The two dominant halt mechanisms implement declared evidence limits. I found no economic bookkeeping defect that would justify clearing either unknown result. Coverage halts are **source-freshness expiries**, not demonstrated disconnects or tape loss. Late revisions show public books whose source times precede assumed activation but whose receipts arrive after it, contradicting the carried-forward queue anchor under the declared source-clock assumption.

One diagnostic defect is confirmed: `_check_late_revision` overwrites an evidence object's `late_revision` with each later qualifying book. The branch keeps its first halt time, so the summary can show a later supporting record than the event that first halted it. A future diagnostic-only change can preserve first and last evidence without assigning private fills or changing economics.

## Groups and first halt times

The holdout cutoff is **03:22:57.958514000 UTC**. Times below are seconds after that cutoff, rounded to six decimals; the JSON retains exact nanoseconds and UTC timestamps. A 16-branch row contains each combination of budgets $100/$250/$500/$1,000 and `control10s`, `passive_best10s`, `passive_target10s`, `passive_target60s`. Within each row, every branch shares the first halt reason and time. These are correlated counterfactual branches, not a portfolio.

| Scenario | Asset | Tier | Branches | First halt | Seconds |
| --- | --- | --- | ---: | --- | ---: |
| base | BTC | Premium | 12 | None: conditional complete | — |
| base | BTC | Premium | 4 | Lot/minimum unknown (`passive_best10s` only) | 226.188461 |
| base | BTC | Standard | 16 | Post-only rejection unresolved | 134.388085 |
| base | ETH | Premium | 16 | Late anchor revision | 162.287596 |
| base | ETH | Standard | 16 | Late anchor revision | 354.794701 |
| base | NVDA | Premium | 16 | Source-freshness expiry | 13.426941 |
| base | NVDA | Standard | 16 | Source-freshness expiry | 13.426941 |
| base | XAG | Premium | 16 | Late anchor revision | 120.937633 |
| base | XAG | Standard | 16 | Source-freshness expiry | 228.901535 |
| plus200 | BTC | Premium | 16 | Post-only rejection unresolved | 134.388085 |
| plus200 | BTC | Standard | 16 | Late anchor revision | 33.537378 |
| plus200 | ETH | Premium | 16 | Late anchor revision | 354.794701 |
| plus200 | ETH | Standard | 16 | Late anchor revision | 49.787931 |
| plus200 | NVDA | Premium | 16 | Source-freshness expiry | 13.426941 |
| plus200 | NVDA | Standard | 16 | Source-freshness expiry | 13.426941 |
| plus200 | XAG | Premium | 16 | Source-freshness expiry | 228.901535 |
| plus200 | XAG | Standard | 16 | Late anchor revision | 50.346446 |

Base has 48 coverage, 48 late-revision, 16 post-only, and four lot/minimum halts: 116 unknown branches. Its 12 conditional complete branches are all negative. Plus200 has 48 coverage, 64 late-revision, and 16 post-only halts: all 128 unknown. Unknown portfolio net stays unknown; no branch contributions are summed.

Base maker/cancel assumptions are Premium 100 ms and Standard 300 ms. Plus200 adds 200 ms to both: Premium 300 ms and Standard 500 ms. Matching first halts in base Standard and plus200 Premium are consistent with their shared 300 ms maker/cancel assumption. Fees and inherited taker delays still differ by tier, so this observation establishes no economic equivalence or causal latency effect.

## Source-freshness expiry

`_check_coverage` requires both RH and HL book source and receipt ages to remain within two seconds while an obligation exists. `_next_boundary` inserts the exact source/receipt age expiry; `_advance_to` tests it before accepting a later book. Accounting depth depletion deliberately does not count as missing coverage.

Two narrow raw windows identify the RH book that expires. HL snapshots remain fresh, and the RH nonce chain resumes continuously:

| Asset | Expiring RH source UTC | Last receipt UTC | Next RH source UTC | Next receipt UTC | Next arrival after expiry |
| --- | --- | --- | --- | --- | ---: |
| NVDA | 03:23:09.385455000 | 03:23:09.495186867 | 03:23:11.320297000 | 03:23:11.395918388 | 10.463387 ms |
| XAG | 03:26:44.860049000 | 03:26:44.946911548 | 03:26:46.908614000 | 03:26:46.996239472 | 136.190471 ms |

NVDA source updates are 1.934842 seconds apart, but receipt delay pushes the old source age beyond two seconds before refresh arrives. XAG source updates are 2.048565 seconds apart. `next.begin_nonce == previous.nonce` in both cases. This is consistent with a period without public book changes plus delivery delay; the narrow records do not establish feed completeness, an outage, or private execution.

The representative $1,000 `control10s` branches have an active second NVDA quote or active 29th XAG quote, with no recorded cancellation request/due time for that quote. Their modeled positions are zero at halt. Thus this specific expiry is not solely a canceled-order tombstone or depleted-depth artifact. Zero modeled inventory does not prove absence of private fills. The later fresh book cannot retrospectively establish the state throughout the interval under the declared two-second threshold.

## Late source-time anchor revision

For an ACK evidence object, `_check_late_revision` checks a later-received raw RH book when `anchor_source_ns <= book.source_ns <= assumed_effective_ns`. A changed same-price quantity, a post-only crossing, or a generation change makes the execution assumption unknown. Raw levels are copied before hypothetical accounting depletion. Historical checks continue after an unrelated branch halt and can invalidate old closed-episode contributions.

The primary plus200 XAG Standard $1,000 `control10s` branch illustrates the evidence directly:

- Seventh entry decision: **03:23:47.782584455 UTC**; assumed activation: **03:23:48.282584455 UTC**.
- Preceding anchor source/receipt: **03:23:48.153723000 / 03:23:48.251154758 UTC**; bid price **61.153**, assumed same-price queue **0**.
- First contradicting raw update: source **03:23:48.231635000**, receipt **03:23:48.304959502 UTC**, nonce **2636601410**, `begin_nonce=2636601360`. It adds bid **61.1530, quantity 686.55**.
- The source precedes assumed activation by **50.949455 ms**, but receipt follows it by **22.375047 ms**. The first halt is exactly that receipt. No private fill is inferred.
- The stored summary `late_revision` instead points to receipt **03:23:48.346573732 UTC**, 41.614230 ms later; that later book still has depth 686.55. It overwrote the first evidence.

Other halt groups likewise record changed same-price depth; plus200 BTC Standard also records a post-only crossing. These facts support conservative uncertainty about the assumed insertion queue. They do not calibrate RH's source clock to a private order acceptance clock or prove real order rejection/filling. Retrospectively replacing the anchor could define another explicitly assumed model, but these artifacts provide no basis for treating its private executions as observed or for choosing its latency to seek profit.

## Exact next useful test

Prepare a **future diagnostic-only** revision of `scripts/rh_passive_ack_scenarios.py::_check_late_revision` and its focused test module; keep this capture's 21 dependencies and published results immutable. Retain:

- `first_late_revision`: set once; existing `source_ns`, `received_ns`, `generation`, `same_price_depth`, `post_only_crossed`, and `book_sha256` fields.
- `last_late_revision`: latest qualifying distinct evidence, with the same fields.
- `late_revision_count`: count distinct `(received_ns, book_sha256)` observations, not method calls. Live book handling invokes the check in both `process` and `_on_book`, so a single event must not count twice.
- Preserve role, episode number, anchor/effective clock fields, first halt time, unknown reason, and all cash/fill/net behavior. Keep legacy `late_revision` as an explicitly labeled alias of the last record if compatibility is needed.

Regression: use the XAG times and price above with anchor queue zero, first update adding 686.55, then a second pre-activation-source update at the later receipt. Assert first evidence stays at 03:23:48.304959502, last advances, distinct count is two, and processing the same event through both check paths/repeating it does not increment the count. Include an unrelated earlier halt: historical episode invalidation must still run while the original first branch halt remains unchanged. Compare all economic fields with the current class; positions/cash must not change and affected contributions remain null.

A complementary coverage diagnostic can record the failing venue, source/receipt age, generation, timer boundary, processed receipt, active quote and cancellation state inside `_check_coverage`. Replay the two timestamp pairs as tiny synthetic fixtures and assert expiry at `old_source_ns + 2_000_000_001`, with the incoming fresh book unable to clear unknown. This tests the existing declared threshold; it does not relax it.

Further maker/cancel timing tuning is unsupported by this review. The useful immediate repair is evidence retention. Private ACK/fill observations and calibrated clocks would be needed to validate execution timing; no new capture or network work was performed here.

## Bounded review provenance

The companion JSON pins completed result hashes, the completed four-run readout hash, capture manifest/raw hashes inherited from their verified replay, all 21 actual dependency hashes, exact halt groups/representative evidence, and selected raw record offsets and uncompressed record hashes. Gzip member CRCs were checked while reading three narrow windows (3.5 s, 3.5 s, 0.4 s); no full raw scan or event replay was performed. The successful bounded seek read 4,599,808 compressed bytes including overlapping probes and decoded 252,866 bytes. An initial inefficient seek attempt stopped at its 8 MiB read cap and was discarded. The raw file's size/mtime remained unchanged; its full SHA was inherited from the completed verified artifacts, not recomputed by a full scan. Combined note and JSON output are capped below 1 MiB.
