# Dated BTC carry: frozen observation method v1

2026-09-30. Authorized continuation of the broader research recommendation.
This is a public quotation feasibility study. It submits no orders, accesses
no account and makes no assertion of acquired inventory or closed profit.

## Selection and fixed schedule

Use Deribit BTC_USDC spot and the nearest active linear USDC settled BTC future
with 7–30 days remaining at the fixed activation time T0. Selection uses contract
metadata and expiry only. Do not choose an instrument or start time based on
prices. Freeze T0 at a whole UTC second before any order-book request. Observe
864 slots T0 + k × 300 seconds, k = 0…863, with endpoint T0 + 72 hours. Six primary
$1,000 decision slots are 0, 144, 288, 432, 576, 720; $100/$250/$500 are diagnostics.
There are 3,456 required rows, including every missing or rejected observation.

Inventory requests were already saved before this method. Exactly two fresh
instrument-list requests are allowed after source freeze: USDC futures and BTC
spot, each with 20-second timeout and 1 MiB decoded cap. Persist a claim before
requesting; no retries or redirects. Launch within 120 seconds of both fresh receipts using UTC and monotonic ages;
a backward UTC jump cannot revive stale metadata. The config embeds selected metadata, public entry fees, source
hashes, metadata hashes and expiry. A separate prepared freeze pins config,
constants, runtime and physical accounting. No freshness reset after launch.

## Collection, clocks and recovery

The immutable launch UTC/monotonic pair maps every deadline. Dispatch both
requests concurrently one second before each slot, with a one-second timeout,
no retries, no redirects and depth ten. A result arriving after either UTC or
monotonic deadline is inadmissible. Callback lateness and launch-clock drift
must each be at most 250 ms. A persistent mapping failure terminates capture;
there is no rebase. A durable per-slot claim prevents duplicate requests.

The offline validator requires a sampled slot, successful RPC and matching
open instrument, source and receipt ages at most two seconds, no future source
time, and paired API timestamps within 250 ms. The API timestamp is a snapshot
publication proxy; underlying routed exchange event age remains unknown.
Validate noncrossed, ordered positive depth, tick grids, common quantity grid,
minimum size, known entry price bands and the published 100 BTC spot default
maximum. Account-specific and omitted public controls remain unknown.

A restart never resumes sampling or fills missing slots. Finalize-only recovery
requires a dead collector lock, keeps existing sample hashes and labels all
uncollected slots. It preserves the last index without rehashing samples into
a replacement index. Any file written after the last index publication remains
retained but unindexed and unevaluated. Economic evaluation is prohibited before T0 + 72 hours, including on
early failure. Require both the original monotonic endpoint and UTC endpoint,
a consistent mapping within 250 ms, and the same host/boot clock identity.
A clock jump or reboot cannot release premature economics. A single durable analysis claim prevents rerunning economic
analysis. Source/config/metadata hashes are checked again before publishing;
compressed sample hashes and bounded gzip EOF reads protect each input. Every
scheduled identity is verified. A changed source or malformed terminal roster
blocks publication. A failed finalizer preserves the claim and artifacts for
inspection; it must not be silently rerun with modified rules.

## Conditional arithmetic and unknown cash flows

For budget B, q = floor[B / (max(spot ask, future bid) × common lot)] × common lot.
The common lot is the exact rational LCM of the two minimum quantity increments.
Walk q on both entry sides and both opposite sides. Reject insufficient depth,
zero q or a walked entry notional above B; do not resize or replace the slot.
Amounts and cash flows use exact rational arithmetic parsed from JSON decimals.

Let S and F be walked spot purchase and short future entry reference notionals.
Gross entry premium is F − S. Public spot/future entry rates must match pinned
metadata. The initial inventory reports 5 and 3.5 bp respectively. The config
uses fresh values. Terminal fee proxies apply the spot rate to S and a 2.5 bp
future delivery rate to F. The latter remains a scenario because the selected
weekly contract's actual delivery exemption has not been established.

Capital proxy = (2B + known entry fees) × 5% ×
(expiry + one hour − slot time)/(365 days). Thus the complete remaining maturity
is charged, even though observation lasts only 72 hours. Spot is fully funded;
short notional is not spendable proceeds. Separately earmark B for the derivative,
plus known entry fees; additional variation margin, buffers and terminal fees
are unresolved. Show 0% and 10% annual capital sensitivities separately. Stress
proxy = 5 bp × max(S,F). Conditional proxy = gross premium − entry fees − terminal
fee proxies − capital proxy − stress proxy. It is the budget left under these
assumptions for missing costs, not an all-cost profit or a rigorous upper bound.

Actual future spot exit price/notional and fees, settlement index mismatch,
USDC/USD conversion, delivery fee applicability, collateral path, private
execution, changing rules, spot fee debit currency/net inventory and underlying
source age remain unknown. All-in headroom and closed net P&L are null. Native
cash flows are USDC; the USD-labelled proxy assumes parity. Spot fee debit in
BTC could change the hedge quantity; gross q does not prove actual matched
inventory. Five-minute books do not prove survival between observations.

The endpoint summary reports conditional coverage and six predeclared decision
rows. At least 80% valid primary observations and positive conditional proxies
at three decisions across two days are prerequisites only. The all-cost gate
remains unresolved until missing cash flows have evidence-backed allowances.
No automatic successor, expanded capture or profitable-strategy claim follows.

## Physical budget and execution

Allocation: `reports/experiment-storage/dated-carry-allocation-v1.json`, frozen
in commit 139efe1, adds 16 MiB to the prior 820,000,000-byte reservation, for
836,777,216 bytes. Existing allocations remain retained. Category limits are
1 MiB source/control, 2 MiB metadata, 8 MiB samples, 2 MiB derived, and 3 MiB
terminal/audit/log. The old shared allowance has 257,096 bytes headroom.

Count external pinned source files as source/control, plus all physical study
files. Count old and temporary replacement bytes simultaneously. Reserve
262,144 terminal bytes before nonterminal writes. Limit slot decoded JSON to
262,144 bytes, response UTF-8 to 65,536 bytes, and study files to 4,000. Fixed
claim/index overhead fits the terminal limit; the initial source and metadata
usage is measured before launch. Data compressibility cannot be guaranteed:
if a category fills, terminate without raising the cap, retain all completed
samples and classify the remainder at the original endpoint. Do not drop old
artifacts to make the study fit. Only two fixed metadata requests and at most
1,728 fixed book requests are possible.

`scripts/prepare_dated_carry.py --fresh` prepares fresh metadata/config.
`scripts/dated_carry_collector.py --prepare` verifies and writes the freeze,
without network requests. `scripts/dated_carry_endpoint.py --launch` runs the
collector once and waits to the original endpoint before analysis. Its default
mode is dry. The production monitor and its 20-minute review daemon continue
independently. The foreground research agent may inspect collection status,
counts and errors but does not compute interim prices or economics.

Focused tests cover deadline/cancellation/drift, invalid depth/time/grid,
fee/capital arithmetic, full denominators, file integrity, storage replacement
peaks, no retry/restart and no premature endpoint analysis. Peer contract and
method review are recorded in the adjacent preflight and method-review files.
