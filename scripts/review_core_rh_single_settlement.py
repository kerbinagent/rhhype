"""Bounded rate-only review of an existing derived hourly table; no network."""
import csv
import hashlib
import io
import json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
ALLOCATION = ROOT / 'reports/experiment-storage/core-rh-single-settlement-review-allocation-v1.json'
OUT = ROOT / 'reports/funding-carry/core-rh-single-settlement-review.json'


def main():
    allocation = json.loads(ALLOCATION.read_bytes())
    source = ROOT / allocation['source_path']
    assert source.stat().st_size == allocation['source_bytes'] < 100000
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == allocation['source_sha256']
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert len(rows) == 384
    joined = defaultdict(dict)
    for row in rows:
        key = row['asset'], row['event_utc']
        venue = row['venue']
        assert venue in ('lighter_core', 'rh_lighter')
        assert venue not in joined[key]
        rate, hl = D(row['venue_long_pays_bps']), D(row['hl_long_pays_bps'])
        assert rate.is_finite() and hl.is_finite()
        joined[key][venue] = (rate, hl)
    assert len(joined) == 192
    groups = defaultdict(list)
    for (asset, event), pair in sorted(joined.items()):
        assert set(pair) == {'lighter_core', 'rh_lighter'}
        core, hl_core = pair['lighter_core']
        rh, hl_rh = pair['rh_lighter']
        assert hl_core == hl_rh
        # Absolute differential gives a hindsight choice of hedge direction.
        # Subsets additionally allow either, both, or neither funding event.
        differential = abs(core - rh)
        subset = max(abs(core), abs(rh), differential)
        groups[asset].append((event, differential, subset))
    assert set(groups) == {'BTC', 'ETH', 'SOL', 'HYPE', 'ZEC', 'COIN', 'XAG', 'NVDA'}
    assert all(len(v) == 24 for v in groups.values())
    thresholds = {str(b): D(5) + D('0.10') / b * 10000 for b in (100, 250, 500, 1000)}
    result = {
        'classification': 'exploratory_equal_reference_notional_rate_arithmetic',
        'source_sha256': digest,
        'source_rows': len(rows),
        'joined_events': len(joined),
        'rates_unit': 'basis_points_per_settlement',
        'hurdles_bp_before_capital_and_trading_cashflows': {k: str(v) for k, v in thresholds.items()},
        'groups': [],
        'actual_settlement_ownership_verified': False,
        'exact_cashflows_or_execution_bound': False,
        'economic_profit_claim': False,
    }
    for asset, values in sorted(groups.items()):
        diffs = [x[1] for x in values]
        subsets = [x[2] for x in values]
        result['groups'].append({
            'asset': asset, 'events': len(values),
            'abs_differential_min_median_max_bp': [str(x) for x in (min(diffs), median(diffs), max(diffs))],
            'favorable_ownership_subset_max_bp': str(max(subsets)),
            'subset_clears_hurdle_counts': {k: sum(x >= h for x in subsets) for k, h in thresholds.items()},
        })
    assert source.read_bytes() == data
    output = (json.dumps(result, separators=(',', ':')) + '\n').encode()
    assert len(output) <= 3000
    with OUT.open('xb') as handle:
        handle.write(output)
    print(output.decode())


if __name__ == '__main__':
    main()
