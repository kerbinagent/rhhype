"""Reused Aster ETH/BTC history: funding budget and required extra yield."""
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/aster-collateral-rate-budget-allocation-v1.json'
OUT = ROOT / 'reports/aster-collateral-rate-budget'


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    outcomes = []
    start = plan['window_start_ms']
    for asset in ['ETH', 'BTC']:
        rows = json.loads((ROOT / ('data/raw/comparators/20260929T035055Z/aster/fundings_30d/' + asset + '.json')).read_bytes())
        assert [r['fundingTime'] for r in rows] == list(range(1788076800000, 1790640000001, 28800000))
        assert all(r['symbol'] == asset + 'USDT' and D(r['fundingRate']).is_finite() for r in rows)
        for i, j in plan['blocks']:
            lo, hi = start + i * 86400000, start + j * 86400000
            rates = [D(r['fundingRate']) for r in rows if lo < r['fundingTime'] < hi]
            assert len(rates) == (j-i)*3 - 1
            funding = sum(rates, D(0)) * 10000
            capital = D('1.1') * D('.05') * 10000 * (j-i) / 365
            fee, stress = D(8), D(5)
            residual = funding - capital - fee - stress
            required_yield = max(D(0), -residual) / 10000 * 365 / (j-i)
            outcomes.append(dict(asset=asset, start_day_offset=i, end_day_offset=j, funding_events=len(rates),
                                 funding_bps=str(funding), capital_bps=str(capital), trading_fee_bps=str(fee),
                                 stress_bps=str(stress), residual_before_extra_yield_bps=str(residual),
                                 required_extra_simple_apr_before_missing_costs=str(required_yield),
                                 negative_payments=sum(r<0 for r in rates)))
    result = dict(actual_pnl=None, historical_development_only=True, cashflow_not_computed=True,
                  collateral_margin_feasibility_unknown=True, baseline_extra_yield=0,
                  full_period_overlaps_weekly_blocks=True, outcomes=outcomes,
                  omitted=['basis', 'changing oracle notional', 'spot/mint/redemption costs', 'spreads',
                           'collateral discount path', 'negative-balance interest', 'actual staking/reward yield'])
    b = (json.dumps(result, indent=2) + '\n').encode()
    assert len(b) <= 16384
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT/'summary.json').open('xb') as f:
        f.write(b)
    with (OUT/'terminal.json').open('x') as f:
        json.dump(dict(status='completed_offline', requests=0, summary_sha256=hashlib.sha256(b).hexdigest(),
                       source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       plan_sha256=hashlib.sha256(p).hexdigest()),f)
    for r in outcomes:
        print(r['asset'],r['start_day_offset'],r['end_day_offset'],r['residual_before_extra_yield_bps'],r['required_extra_simple_apr_before_missing_costs'])


if __name__ == '__main__':
    main()
