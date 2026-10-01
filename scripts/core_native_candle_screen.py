"""Fixed seven-asset September candle/cashflow proxy; all outcomes retained."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/core-native-candle-screen-allocation-v1.json'
OUT = ROOT / 'reports/core-native-candle-screen'
START, END = 1788220800, 1790812800
BLOCKS = ((0, 30), (0, 7), (7, 14), (14, 21), (21, 28), (28, 30))


def analyze(data, funding, market):
    candles = {}
    for kind in ('spot', 'perp'):
        obj = json.loads(data[kind], parse_float=D)
        assert obj['code'] == 200 and obj['r'] == '1d', 'candle schema'
        rows = sorted(obj['c'], key=lambda x: x['t'])
        assert [r['t'] for r in rows] == list(range(START * 1000, END * 1000, 86400000)), 'incomplete daily candles'
        for row in rows:
            for k in 'ohlcV':
                row[k] = D(row[k])
                assert row[k].is_finite() and (row[k] >= 0 if k == 'V' else row[k] > 0)
            assert row['l'] <= min(row['o'], row['c']) <= max(row['o'], row['c']) <= row['h'], 'OHLC'
        candles[kind] = rows
    obj = json.loads(funding, parse_float=D)
    assert obj['code'] == 200 and obj['resolution'] == '1h'
    fund = sorted(obj['fundings'], key=lambda x: x['timestamp'])
    assert [r['timestamp'] for r in fund] == list(range(START, END, 3600)), 'funding coverage'
    for r in fund:
        r['value'] = D(r['value'])
        assert r['value'].is_finite() and r['value'] >= 0 and r['direction'] in ('long', 'short')
    result = []
    for i, j in BLOCKS:
        s0, p0 = candles['spot'][i]['o'], candles['perp'][i]['o']
        q = (D(1000) / s0).quantize(D(1).scaleb(-market['decimals']), rounding=ROUND_DOWN)
        principal = q * s0
        row = {'start_day': i + 1, 'end_day': j, 'quantity': str(q), 'principal_usdc': str(principal)}
        if q < D(market['min_base']) or min(principal, q * p0) < D(market['min_quote']):
            row.update(status='below_minimum', candle_residual_usdc=None)
        else:
            fs = [r for r in fund if START + i * 86400 < r['timestamp'] < START + j * 86400]
            credit = q * sum((r['value'] * (1 if r['direction'] == 'long' else -1) for r in fs), D(0))
            basis = q * (candles['spot'][j - 1]['c'] - s0 + p0 - candles['perp'][j - 1]['c'])
            capital = 2 * principal * D('.05') * (j - i) / 365
            stress = principal * D('.0005')
            row.update(status='candle_proxy', funding_events=len(fs), inferred_funding_usdc=str(credit),
                       candle_basis_usdc=str(basis), capital_usdc=str(capital), stress_usdc=str(stress),
                       candle_residual_usdc=str(credit + basis - capital - stress),
                       zero_volume_days={k: sum(r['V'] == 0 for r in v[i:j]) for k, v in candles.items()})
        result.append(row)
    return result


def self_check():
    candles = {'code': 200, 'r': '1d', 'c': [dict(t=t, o=100, h=100, l=100, c=100, V=1000)
                for t in range(START * 1000, END * 1000, 86400000)]}
    fund = {'code': 200, 'resolution': '1h', 'fundings': [dict(timestamp=t, value='.01', direction='long')
            for t in range(START, END, 3600)]}
    data = {k: json.dumps(candles) for k in ('spot', 'perp')}
    market = {'decimals': 1, 'min_base': '1', 'min_quote': '10'}
    r = analyze(data, json.dumps(fund), market)[0]
    assert D(r['inferred_funding_usdc']) == D('71.9') and D(r['candle_basis_usdc']) == 0
    assert D(r['candle_residual_usdc']) == D('71.9') - D(100)/365*30 - D('.5')
    candles['c'][-1]['c'] = 99
    candles['c'][-1]['l'] = 99
    data['spot'] = json.dumps(candles)
    assert D(analyze(data, json.dumps(fund), market)[0]['candle_basis_usdc']) == -10
    candles['c'].pop()
    data['spot'] = json.dumps(candles)
    try:
        analyze(data, json.dumps(fund), market)
    except AssertionError:
        pass
    else:
        raise AssertionError('missing daily candle accepted')


def main():
    self_check()
    p = PLAN.read_bytes()
    plan = json.loads(p)
    assert Path(__file__).stat().st_size <= 8192
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT / 'claim.json').open('x') as f:
        json.dump({'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'plan_sha256': hashlib.sha256(p).hexdigest(),
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, f)
    provenance, outcomes, retained, requests = [], [], 0, 0
    for market in plan['universe']:
        asset = market['asset']
        data, errors = {}, []
        for kind in ('spot', 'perp'):
            try:
                if asset == 'ETH':
                    path = ROOT / ('reports/core-eth-collateral-candles/' + kind + '.json.gz')
                    raw = gzip.decompress(path.read_bytes())
                    source = {'reused': str(path.relative_to(ROOT))}
                else:
                    time.sleep(2)
                    params = dict(market_id=market[kind], resolution='1d', start_timestamp=START,
                                  end_timestamp=END - 1, count_back=31)
                    url = 'https://mainnet.zklighter.elliot.ai/api/v1/candles?' + urllib.parse.urlencode(params)
                    requests += 1
                    req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        raw = response.read(131073)
                        assert response.status == 200 and len(raw) <= 131072
                    packed = gzip.compress(raw, mtime=0)
                    assert retained + len(packed) <= 65536, 'raw budget'
                    with (OUT / (asset + '-' + kind + '.json.gz')).open('xb') as f:
                        f.write(packed)
                    retained += len(packed)
                    source = {'url': url, 'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
                provenance.append(dict(asset=asset, kind=kind, raw_sha256=hashlib.sha256(raw).hexdigest(), **source))
                data[kind] = raw
            except Exception as exc:
                errors.append(kind + ':' + type(exc).__name__ + ':' + str(exc)[:160])
        row = {'asset': asset, 'status': 'unknown', 'actual_pnl': None, 'errors': errors}
        try:
            assert len(data) == 2, 'missing requested candle series'
            funding = gzip.decompress((ROOT / market['funding']).read_bytes())
            row.update(status='complete_candle_proxy', blocks=analyze(data, funding, market))
        except Exception as exc:
            errors.append(type(exc).__name__ + ':' + str(exc)[:180])
        outcomes.append(row)
    result = dict(actual_pnl=None, development_not_validation=True, funding_value_units_inferred=True,
                  current_lot_rules_not_verified_for_history=True, candles_not_executable=True,
                  no_margin_solvency_claim=True, full_month_overlaps_weekly_blocks=True,
                  outcomes=outcomes, provenance=provenance)
    encoded = (json.dumps(result, indent=2) + '\n').encode()
    assert len(encoded) <= 49152
    with (OUT / 'summary.json').open('xb') as f:
        f.write(encoded)
    terminal = dict(status='completed_fixed_screen', requests=requests, raw_bytes=retained,
                    unknown_assets=sum(x['status'] == 'unknown' for x in outcomes),
                    summary_sha256=hashlib.sha256(encoded).hexdigest())
    with (OUT / 'terminal.json').open('x') as f:
        json.dump(terminal, f)
    assert len(p) + (OUT / 'claim.json').stat().st_size + (OUT / 'terminal.json').stat().st_size <= 16384
    print(json.dumps(terminal))
    for x in outcomes:
        print(x['asset'], x['status'], [r.get('candle_residual_usdc') for r in x.get('blocks', [])], x['errors'])


if __name__ == '__main__':
    main()
