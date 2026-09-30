# Prospective RH spread-regime sentinel — plan only

**No implementation or collection is authorized by this note.** Method review precedes implementation approval. This is one new bounded sampled-network study, not reuse of archive evidence or a full canonical archive. [Allocation](../reports/experiment-storage/rh-spread-regime-sentinel-allocation-v1.json): 500,000 bytes including all artifacts/logs. No automatic repeat, full capture, promotion or orders.

## Question and prior rejection

Do newly observed RH spreads persistently clear the unchanged $0.10 target and 5bp minimum stress even with a frictionless hedge? The [prior bound](../reports/passive-universe-hedge-budget/0310Z-input-v1/readout.md) rejects every eligible median. LIT had five valid rounds: its $1,000 maximum was +$0.19326440, median −$0.12423520, and only one round positive. The same round was +$0.04663220 at $500: correlated sizes, not recurrence. Actual HL costs erased it. At unchanged observed RH quotes, Core costs cannot rescue that rejected median. This sentinel instead tests **new prices across the original universe**, with stronger median/coverage requirements; it cannot establish hedge feasibility or future profit.

## Frozen scope and quantity

Retain the original 21 assets, in original order: BTC, ETH, LIT, NVDA, SOL, HYPE, AAPL, XAG, GOOGL, SNDK, NEAR, ZEC, XRP, MSFT, MU, TSLA, META, CRCL, AMD, AMZN, INTC. Budgets: $100/$250/$500/$1,000; no substitutions. Hash/reference the [0310Z universe](../reports/passive-universe-screen/20260930T0310Z/universe.json); do not copy the unrelated market plan.

A successful preparation completes exactly three fresh public metadata requests (at most three attempts on failure): RH orderBookDetails, HL native metaAndAssetCtxs, HL xyz metaAndAssetCtxs. No retry or alternative endpoint. Preserve full responses, request/receipt provenance and hashes. Validate fixed identities, underlying/unit assumptions, public Standard RH maker fee exactly unchanged at zero, lot/tick/min/max rules, reference-price sanity and the original >=$1M volume checks. Require the original RH and HL common-lot inputs to remain compatible and unchanged; otherwise retain that asset's entire planned denominator as metadata-ineligible. No Core or HL book request occurs. Hedge depth, conversion and fills remain unknown.

Use **q=floor(budget/RHask/original_common_lot)×original_common_lot**, with the original quantity rule. No continuous quantity or finer Core lot. Check q/both RH prices against fresh RH quantity/notional/grid bounds and unchanged reference lot rules. Maker top size does not establish fills or require q to fit. Compute the exact rational optimistic budget:

`U = q×(RHask−RHbid) − 0.10 − 0.0005×q×RHbid`.

This explicitly forgives all fees/hedge spread and uses RH opening notional as minimum stress base. Nonnegative static hedge costs/larger-entry stress can reduce U. U excludes funding, credits/rebates and transfers; it is not an overall-profit upper bound. Valid RH observations are not complete paired observations. Hedge coverage, queue/fills, funding, capital and USDG/USDC conversion remain unknown; dollar parity is conditional.

## One window and causal sampling

Freeze source/method/tests hashes before metadata preparation; freeze validated metadata and UTC/monotonic schedule before connection. Set T0 ten seconds after run activation. The endpoint is **T0+1,200 seconds**. Sample at T0+k×60 seconds for k=0..19, with four fixed blocks k=0..4, 5..9, 10..14, 15..19. No quote-dependent waits/extension/early economic stop. Retain 420 asset/slot references and **1,680 asset/slot/budget rows**, including every metadata-ineligible, missing or failed slot.

Use one read-only RH websocket, at most 21 fixed ticker subscriptions with validated identities, explicit outbound application ping every 30 seconds and **no automatic reconnect**. No trades, reconstruction or full frame archive. Retain sampled raw messages with receipt UTC/monotonic/generation; no intervening stream.

Advance an async scheduler against absolute monotonic deadlines. Snapshot latest tickers already received before the sampling callback; save planned/actual UTC/monotonic times. Dispatch lateness must be 0..250ms; otherwise that slot fails for all assets. Emit every missed slot. Source and receipt ages at actual sample time must be 0..2s, with source<=receipt<=sample; this is not calibrated one-way latency. Apply the frozen UTC/monotonic mapping guard at every ticker receipt BEFORE source acceptance/high-water advancement, and at sampling. A deviation >250ms clears ticker state and invalidates affected slots without advancing the watermark. Resume only when receipts match the unchanged frozen mapping and all other checks pass; no rebaselining, clock repair or quote-dependent grace period.

Validate RH channel/market/symbol, source integer microseconds, finite positive bid/ask and top sizes, bid<ask and fresh metadata grids. A malformed ticker, source regression, source ahead of receipt, generation change or terminal connection error clears the affected ticker state; an unidentifiable ticker fault clears all state. Advance the source high-water mark only on accepted, mapping-valid, clock-valid, nonfuture snapshots; retain it across malformed/regressed updates. An invalid future timestamp must not poison it. A later valid fresh snapshot can restore state; never fall back to an older favorable quote. Silence exceeding freshness makes the sampled row stale. Disconnect/ping failure closes collection; future slots remain missing with the reason. No fabricated gap continuity, public tape or queue observation is implied.

## Gate, endpoint and reporting

Compute/inspect no U before the endpoint; technical health/byte monitoring is allowed. At $1,000, an asset satisfies the prospective prerequisite only if **all** hold:

1. At least 16/20 valid size observations.
2. Median U across all valid observations in the full window is strictly >0.
3. At least three of four fixed blocks each have >=4/5 valid observations and median U strictly >0.

Even medians average the two central exact values. Missing economics are not imputed. Report all four sizes: coverage/exclusions/median/max/blocks. Smaller sizes cannot rescue the primary gate; no alternate winner, relaxation, pooling or subset selection. Passing only permits considering a separately reviewed actual-cost screen; no Core data/capture/trading follows automatically. Failure ends this single study.

## Stages and bounds

After method review and explicit implementation approval: build a **default dry mode** that prints scope/bounds without network. Fixtures cover clocks/invalidation/dispatch, exact math/medians, all 1,680 rows and caps. Explicit prepare-metadata stages at most three requests; root reviews metadata/source/tests before separate freeze/run. Metadata must be <=120s old at T0 (each response completion); expiry ends preparation without a refetch. Do not connect the quote websocket while waiting for review.

Enforce <=500,000 aggregate bytes before every write, including failures/logs/manifests. Prior metadata totals 227,750 bytes; compress sampled messages/rows. Implementation review freezes sublimits/finalization reserve, timeouts and decoded/line bounds; no denominator trimming or cap increase. Technical stops close collection and flag remaining slots collector-stopped. Report incompleteness at the endpoint, with no early economic readout. Verify before/after source/reference/metadata hashes and exact slot keys before complete/failed publication. Account this as new sampled network evidence, not archive reuse.

### Implementation bounds (before source freeze)

Category ceilings sum to 500,000 bytes: control/source/metadata provenance/manifests/index 90,000; full metadata responses 280,000; compressed sampled messages 80,000; compressed derived rows/summary 40,000; reports/failure/logs 10,000. Initial source/method/tests/source-freeze/index must fit 60,000 control bytes before a metadata request, reserving 30,000 for later control artifacts. Every aggregate/category check includes the storage index and completed gzip trailer before disk writes. Normal sampled evidence stops at 75,000 compressed bytes, reserving 5,000 for missing-slot finalization; normal decoded prefix <=1,750,000 bytes, reserving 250,000 for all remaining placeholders; final decoded sampled evidence <=2,000,000 bytes, line <=65,536. Derived CSV decoded <=1,000,000. Overflow fails without increasing a limit.

HTTP timeout 20s per request; at most three attempts/no redirects to alternative endpoints or retries. HTTP timeout/status/body-cap failures retain endpoint/start/status/error provenance and all 1,680 uncollected rows. Websocket handshake timeout 10s; message <=32,768 bytes, aggregate ingress <=64,000,000 bytes, <=100,000 messages including binary/control variants. Prior bounded manifest implies ~42 tickers/s, versus ~82.6 messages/s permitted over the new 1,210s connection window; this supports a bound, not a completion guarantee. Unexpected binary, server/subscription error, repeated connection greeting or repeated subscribed/ticker is a technical terminal stop; no new generation/reconnect is inferred.

Source/reference/prepared metadata and root-freeze hashes are reverified before any websocket creation. Metadata ages are checked against both response-completion UTC and monotonic timestamps at anticipated T0. Metadata expiry at freeze or run publishes an explicit failed preparation with all rows and no refetch. Collector technical stops may remain idle to the fixed endpoint and then report incomplete economics; user stop closes immediately, retains full missing/unadjudicated denominators and never computes economics before that endpoint. Sample history keeps planned and actual timing; raw message fields remain unchanged inside compressed sample records. No code or metadata stage may tune economic rules.

Numeric inputs are bounded before Fraction conversion: <=80 representation characters, <=40 coefficient digits, absolute decimal exponent/adjusted magnitude <=18. Selected metadata numeric fields receive the same guard before the existing selector. Protocol autoping is disabled; delivered PING/PONG frames are counted and PING answered explicitly. Ingress byte counts cover delivered payloads, not transport headers. HTTP redirects and aiohttp internal connection retry are disabled. Before websocket creation, require at least10,000 control bytes remaining (2,000 index growth plus8,000 terminal reserve) for terminal manifests/index; otherwise publish a failed stage without connecting. Runtime Python/aiohttp versions are frozen and rechecked.

Normal control writes reserve8,000 bytes below the90,000 ceiling; failure/endpoint finalization alone may use that reserve. Thus even a preparation/freeze reserve failure can retain its full1,680-row failure publication without exhausting control/index space.

Schedule-write reserve failure also publishes all failed rows before any websocket. Terminal failed-request provenance uses finalization reserve before failure publication.
