# Paper results for the current strategy version

The next planned collector rollout starts version attribution in the existing
paper database. This first epoch begins at rollout, even when strategy sources
are unchanged. It does not reconstruct a historical strategy inception date.
All existing positions become legacy carryover, including pending entries,
partial exits, and unresolved funding. Their later settlements are excluded
from the new epoch's P&L, counts, wins, and closed-trade fees.

The current collector and viewer must be restarted at that planned rollout to
load this code. A viewer already running retains its imported old layout.
Preparing or previewing this change does not itself restart either process.

Version identity hashes execution config, explicit market/fee/transport
selection, and `paper_engine.py`, `paper_strategies.py`, and `paper_funding.py`.
It separately hashes the execution helpers `common_step`, `affordable_quantity`,
and `walk` in `monitor.py`. Pure UI, observer, orchestration, and attribution
edits do not change the identity. A restart with the same identity reuses the
saved epoch ID, start time, and totals. A changed identity starts a new epoch;
positions already admitted retain their original epoch.

The existing paper-store config compatibility gate remains in place. Version
attribution does not authorize or enable a configuration migration or capital
reset. An incompatible config still needs a separate approved migration.

The observer subclasses the existing engine to tag positions before their
first transition is copied, and records outcomes only after final funding
settlement. Base execution, wallets, collateral constraints, fees, and capital
floors remain unchanged. The epoch's cumulative totals are saved atomically
with the engine state, rather than reconstructed from the retained trade ring.
More than 5000 completed trades and retention eviction therefore preserve the
current totals. Incomplete funding remains pending and unknown.

The TUI headline shows the current epoch's settled count, wins, estimated count,
net, modeled exchange fees, stress allowance, and open liquidation mark. Net
includes the existing stress allowance, which is displayed separately from
modeled exchange charges. Closed fees and stress columns cover settled trades.
Version, epoch, UTC start time, snapshot age, and feed health remain visible.
At 80 columns by 24 rows, all eight portfolios and ten opening signals fit;
signals use two columns and remain explicitly labeled as observed edge.

Carryover exposure and unresolved funding are labeled separately and excluded
from headline P&L. Cash and free collateral are the full paper wallet across
all versions, explicitly labeled as sums. Venue cash cannot be pooled: a
strategy can be blocked at one venue even when its total appears ample. These
sums are context, not a tradable balance or a fresh profit baseline. Unknown
spendable collateral remains `?`. The JSON snapshot also
preserves per-venue balances and carryover quantities by market and side.

The original lifetime accounting remains in the engine state. Epoch history
keeps 16 completed epochs plus any epochs pinned by open or pending obligations.
Retired epoch totals are accumulated into a separate archive, never added to
the headline. At most 64 pinned or active epochs are allowed; exceeding that
limit rejects a rollout explicitly. Combined with the 16 completed epochs,
that bounds detailed history to 80 epochs. The existing 2 MiB state gate also
continues to reject oversized checkpoints atomically without losing the prior
durable state.

Offline tests cover initial attribution, legacy and prior-version closures,
duplicate settlements, restart, public restore, reindexing, more than 5000
settlements, retention eviction, bounded history, source/config identity, and
the 80 by 24 layout. Review artifacts in `reports/paper-strategy-epoch-review`
record a read-only rehearsal using a deep copy of the live saved engine state;
the rehearsal never feeds, ticks, or writes the live paper database.
