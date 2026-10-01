"""Exploratory rate/capital arithmetic from the stopped September funding archive."""
import csv
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'reports/funding-carry/raw'
OUT = ROOT / 'reports/spot-perp-idea-screen/summary.json'
CAPITAL = D('0.05') * 2 * 10000 / 365
hashes = {}


def read(path):
    data = path.read_bytes()
    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def rates(venue, asset):
    raw = read(RAW / venue / (asset + '.json'))
    if venue == 'hl':
        rows = [(int(r['time']) // 3600000 * 3600,
                 D(r['fundingRate']) * 10000) for r in raw]
    else:
        assert raw['code'] == 200 and raw['resolution'] == '1h'
        rows = []
        for r in raw['fundings']:
            assert r['direction'] in ('long', 'short')
            x = D(r['rate'])
            assert x >= 0
            rows.append((int(r['timestamp']), x * 100 *
                         (1 if r['direction'] == 'long' else -1)))
    rows.sort()
    assert [t for t, _ in rows] == list(range(1790528400, 1790701200, 3600))
    assert all(x.is_finite() for _, x in rows)
    return [x for _, x in rows]


def summarize(name, x, fee_bps):
    a, b = sum(x[:24]), sum(x[24:])
    return {'candidate': name, 'first_day_rate_bps': str(a),
            'second_day_rate_bps': str(b),
            'second_day_negative_hours': sum(v < 0 for v in x[24:]),
            'second_day_after_capital_bps': str(b - CAPITAL),
            'roundtrip_fee_scenario_bps': str(fee_bps),
            'seven_day_required_daily_rate_bps': str(CAPITAL + (fee_bps + 5) / 7),
            'seven_day_constant_second_day_rate_residual_bps':
                str(7 * (b - CAPITAL) - fee_bps - 5)}


def main():
    # HL scenarios deliberately forgive spot trading fees: an optimistic hurdle,
    # not a claim of an available free spot route. Direction always short perp.
    rows = []
    for asset in ('BTC', 'ETH', 'SOL', 'HYPE'):
        rows.append(summarize('funded spot + short HL ' + asset,
                              rates('hl', asset), D(9)))
    core_eth = rates('lighter_core', 'ETH')
    rows.append(summarize('Core ETH spot + short Core ETH perp', core_eth, D(0)))
    markets = read(RAW / 'lighter_core/markets.json')
    spot = [m for m in markets['spot_order_book_details'] if m['symbol'] == 'ETH/USDC']
    assert len(spot) == 1 and spot[0]['market_type'] == 'spot'
    comparisons = []
    for asset in ('BTC', 'ETH', 'SOL'):
        core, rh = rates('lighter_core', asset), rates('rh_lighter', asset)
        diff = [c - r for c, r in zip(core, rh)]
        direction = 1 if sum(diff[:24]) >= 0 else -1
        comparisons.append(summarize(asset + (': short Core / long RH' if direction == 1
                                              else ': long Core / short RH'),
                                     [direction * x for x in diff], D(0)))
    # Independent check against the pre-existing CSV's HL rates. Each asset
    # occurs twice there; take the fixed Core comparison only, never sum both.
    with (ROOT / 'reports/funding-carry/holdout_hourly.csv').open() as f:
        old = list(csv.DictReader(f))
    for row, asset in zip(rows[:4], ('BTC', 'ETH', 'SOL', 'HYPE')):
        values = [D(r['hl_long_pays_bps']) for r in old
                  if r['asset'] == asset and r['venue'] == 'lighter_core']
        assert len(values) == 24
        assert abs(sum(values) - D(row['second_day_rate_bps'])) < D('0.00000001')
    result = {'schema': 'exploratory-spot-perp-rate-hurdle-v1',
              'window': '2026-09-27T17:00Z through 2026-09-29T16:00Z; two 24-event days',
              'not_fresh_validation': True, 'actual_cashflow_or_pnl': None,
              'capital_scenario': '5% annual on 2x one-leg notional, 365-day simple basis',
              'capital_bps_per_day': str(CAPITAL), 'stress_bps': 5,
              'seven_day_numbers_are_extrapolations_not_observed_returns': True,
              'omitted': ['entry/exit basis', 'spreads and impact', 'changing oracle notional',
                          'actual fills', 'collateral path', 'conversions', 'private fees'],
              'spot_perp_candidates': rows, 'core_rh_comparisons': comparisons,
              'archived_core_eth_spot': {k: spot[0][k] for k in
                                        ('symbol', 'market_id', 'status', 'market_type')},
              'source_sha256': hashes,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': '48 unique consecutive hours each; finite rates; historical CSV cross-check'}
    data = (json.dumps(result, indent=2) + '\n').encode()
    assert len(data) <= 8192
    OUT.parent.mkdir(exist_ok=True)
    assert not any(OUT.parent.iterdir()), 'Do not overwrite a prior exploratory result'
    with OUT.open('xb') as f:
        f.write(data)
    for row in rows + comparisons:
        print(row['candidate'], 'day2=', row['second_day_rate_bps'],
              '7d_hurdle=', row['seven_day_required_daily_rate_bps'],
              '7d_extrapolated_residual=', row['seven_day_constant_second_day_rate_residual_bps'])


if __name__ == '__main__':
    main()
