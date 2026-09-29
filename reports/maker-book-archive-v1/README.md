# Public full-book reconstruction

The [method and coverage report](../../research/maker-book-archive.md) describes the separate [full-book event archive](derived/book-events.jsonl.gz), [RH anchor diagnostic](derived/rh-anchor-diagnostics.json), and [manifest with input/output hashes](derived/manifest.json).

The stopped NVDA/XAG capture yielded 5,864 nonce/snapshot-contiguous valid full-book events, zero invalidations, and 166 RH anchor rows. With the prior 1-second receipt and 2-second source freshness rules, RH full books were fresh at 78/83 NVDA and 80/83 XAG anchors, versus 38/83 and 32/83 for RH ticker. This is a post hoc public-data coverage audit. No prior case was reclassified; displayed levels do not imply queue position, fills, or profit.
