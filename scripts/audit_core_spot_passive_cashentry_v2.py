"""Audit-only repair: normalize immutable price levels before depletion."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import scripts.core_spot_passive_cashentry as setup
import scripts.audit_core_spot_passive_cashentry as original

_walk = original.walk

def mutable_walk(levels, qty, limit=None, side='sell', deplete=False):
    if deplete:
        # Adapter levels are tuples inside a mutable outer list. The original
        # auditor's synthetic fixtures used lists for both levels and sides.
        # Prices, quantities, order and depletion arithmetic are unchanged.
        levels[:] = [list(level) for level in levels]
    return _walk(levels, qty, limit=limit, side=side, deplete=deplete)

def main():
    setup.configure()
    original.PLAN = setup.PLAN
    original.OUT = setup.OUT
    original.R = setup.R
    original.HARD_BYTES = setup.HARD_BYTES
    original.iter_events = setup.events.iter_events
    original.walk = mutable_walk
    original.run()

if __name__ == '__main__':
    main()
