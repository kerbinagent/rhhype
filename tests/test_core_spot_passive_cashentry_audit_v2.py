"""Exercise the complete independent audit with actual adapter level shapes."""
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

def test_complete_cycle_with_tuple_price_levels():
    import scripts.audit_core_spot_passive_cashentry as original
    from scripts.audit_core_spot_passive_cashentry_v2 import mutable_walk
    suite = runpy.run_path(str(ROOT / 'tests/test_core_spot_passive_cashentry.py'))
    test = suite['test_independent_audit_complete_profitable_synthetic_cycle']
    globals_ = test.__globals__
    book = globals_['book']
    def tuple_book(*args, **kwargs):
        event = book(*args, **kwargs)
        for side in ('bids', 'asks'):
            event[side] = [tuple(level) for level in event[side]]
        return event
    globals_['book'] = tuple_book
    with patch.object(original, 'walk', mutable_walk):
        test()

if __name__ == '__main__':
    test_complete_cycle_with_tuple_price_levels()
