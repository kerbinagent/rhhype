"""Bounded retrospective ETH carry screen. Candles are never executable quotes."""
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
PLAN = ROOT / 'reports/experiment-storage/core-eth-collateral-candle-allocation-v1.json'
OUT = ROOT / 'reports/core-eth-collateral-candles'
FUND = ROOT / 'reports/core-eth-funding-history/202609-v1/response.json.gz'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def put(name, b, cap):
    assert len(b) <= cap, (name, len(b), cap)
    with (OUT / name).open('xb') as f:
        f.write(b)


def analyze(data):
    start = 1788220800
    expected = list(range(start * 1000, 1790812800000, 86400000))
    candles = {}
    for name, raw in data.items():
        obj = json.loads(raw, parse_float=D)
        assert obj['code'] == 200 and obj['r'] == '1d'
        rows = sorted(obj['c'], key=lambda r: r['t'])
        assert [r['t'] for r in rows] == expected, (name, 'coverage')
        for r in rows:
            for k in 'ohlc':
                r[k] = D(r[k])
                assert r[k].is_finite() and r[k] > 0
            assert r['l'] <= min(r['o'], r['c']) <= max(r['o'], r['c']) <= r['h']
        candles[name] = rows
    fund_bytes = FUND.read_bytes()
    fund = json.loads(gzip.decompress(fund_bytes))['fundings']
    assert sorted(int(r['timestamp']) for r in fund) == list(range(start, 1790812800, 3600))
    results = []
    for i, j in ((0, 7), (7, 14), (14, 21), (21, 28), (28, 30), (0, 30)):
        s0, p0 = candles['spot'][i]['o'], candles['perp'][i]['o']
        s1, p1 = candles['spot'][j-1]['c'], candles['perp'][j-1]['c']
        qty = (D(1000) / s0).quantize(D('.0001'), rounding=ROUND_DOWN)
        principal = qty * s0
        cash = principal * D('.1')
        t0, t1 = start + i * 86400, start + j * 86400
        # Do not claim an opening-boundary payment before the assumed entry.
        frows = [r for r in fund if t0 < int(r['timestamp']) < t1]
        assert len(frows) == (j-i) * 24 - 1
        per_unit = D(0)
        for r in frows:
            assert r['direction'] in ('long', 'short')
            v = D(r['value'])
            assert v.is_finite() and v >= 0
            per_unit += v * (1 if r['direction'] == 'long' else -1)
        funding = qty * per_unit
        basis = qty * ((s1-s0) + (p0-p1))
        capital = (principal + cash) * D('.05') * (j-i) / 365
        stress = principal * D('.0005')
        # Price-only sensitivity; spot trade low is NOT the collateral oracle.
        # Pairing each day's spot low and mark high is asynchronous stress.
        headrooms = []
        for k in range(i, j):
            s_low, m_high = candles['spot'][k]['l'], candles['mark'][k]['h']
            portfolio = cash + qty * (p0-m_high)
            tav = portfolio + D('.70') * qty * s_low
            talt = portfolio + D('.85') * qty * s_low
            headrooms.append((tav - D('.05')*qty*m_high,
                              talt - D('.012')*qty*m_high))
        results.append({'days': j-i, 'start_day': i+1, 'end_day': j,
                        'quantity_eth': str(qty), 'spot_principal_usdc': str(principal),
                        'cash_buffer_usdc': str(cash), 'funding_events': len(frows),
                        'funding_inferred_usdc': str(funding),
                        'candle_basis_change_usdc': str(basis),
                        'capital_cost_usdc': str(capital), 'stress_usdc': str(stress),
                        'candle_proxy_residual_usdc': str(basis+funding-capital-stress),
                        'minimum_price_only_imr_headroom_proxy': str(min(x[0] for x in headrooms)),
                        'minimum_price_only_mmr_headroom_proxy': str(min(x[1] for x in headrooms))})
    return {'schema': 'retrospective-eth-candle-screen-v1', 'actual_pnl': None,
            'funding_units_inferred': True, 'historical_margin_availability_unverified': True,
            'candles_are_not_executable_quotes': True,
            'full_month_overlaps_blocks_do_not_add': True,
            'funding_gzip_sha256': sha(fund_bytes), 'results': results}


def main():
    plan_bytes = PLAN.read_bytes()
    plan = json.loads(plan_bytes)
    assert plan['requests_max'] == 3 and plan['retries'] == 0
    assert Path(__file__).stat().st_size <= 7168
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir()), 'No retries or overwrites'
    # A durable whole-run claim bounds even a process interruption.
    put('claim.json', (json.dumps({'plan_sha256': sha(plan_bytes),
                                  'source_sha256': sha(Path(__file__).read_bytes()),
                                  'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()})+'\n').encode(), 300)
    data, raw_total = {}, 0
    terminal = {'status': 'failed_no_retry', 'requests': 0}
    try:
        for name, endpoint, market in plan['requests']:
            if data:
                time.sleep(2)
            params = {'market_id': market, 'resolution': plan['resolution'],
                      'start_timestamp': plan['window'][0], 'end_timestamp': plan['window'][1],
                      'count_back': plan['count_back']}
            url = 'https://mainnet.zklighter.elliot.ai/api/v1/' + endpoint + '?' + urllib.parse.urlencode(params)
            terminal['requests'] += 1
            req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(65537)
                assert response.status == 200 and len(raw) <= 65536
            packed = gzip.compress(raw, mtime=0)
            assert raw_total + len(packed) <= 5120
            put(name+'.json.gz', packed, 5120-raw_total)
            raw_total += len(packed)
            data[name] = raw
        result = analyze(data)
        result['raw_sha256'] = {k: sha(v) for k, v in data.items()}
        result['plan_sha256'] = sha(plan_bytes)
        encoded = (json.dumps(result)+'\n').encode()
        put('summary.json', encoded, 5120)
        terminal.update(status='completed', summary_sha256=sha(encoded))
        print(json.dumps(result))
    except Exception as exc:
        terminal['error'] = str(exc)[:160]
    tb = (json.dumps(terminal)+'\n').encode()
    assert len(plan_bytes)+300+len(tb) <= 2048
    put('terminal.json', tb, 350)
    print(json.dumps(terminal))


if __name__ == '__main__':
    main()
