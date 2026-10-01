"""Fixed native-spot universe: September funding-only development screen."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/core-native-funding-screen'
PLAN = ROOT / 'reports/experiment-storage/core-native-funding-screen-allocation-v1.json'
START, END = 1788220800, 1790812800
BLOCKS = ((0, 30), (0, 7), (7, 14), (14, 21), (21, 28), (28, 30))


def analyze(raw):
    obj = json.loads(raw, parse_float=D)
    assert obj['code'] == 200 and obj['resolution'] == '1h', 'response schema'
    rows = sorted(obj['fundings'], key=lambda x: x['timestamp'])
    assert [r['timestamp'] for r in rows] == list(range(START, END, 3600)), 'incomplete or duplicate hours'
    values = []
    for row in rows:
        rate = D(row['rate'])
        assert rate.is_finite() and rate >= 0 and row['direction'] in ('long', 'short'), 'invalid rate'
        values.append(rate * 100 * (1 if row['direction'] == 'long' else -1))
    results = []
    for i, j in BLOCKS:
        # Inferred rate budget only: no entry-hour receipt; no closing-hour
        # receipt at the next midnight. Fixed units, not time-varying cashflow.
        rates = values[i * 24 + 1:j * 24]
        funding = sum(rates, D(0))
        hurdle = D('.05') * 2 * 10000 * (j - i) / 365 + 5
        results.append({'start_day': i + 1, 'end_day': j, 'events': len(rates),
                        'rate_sum_bps': str(funding), 'capital_and_stress_bps': str(hurdle),
                        'rate_residual_bps': str(funding - hurdle),
                        'negative_hours': sum(x < 0 for x in rates),
                        'max_capital_multiple_before_execution_cost': str((funding - 5) / (D('.05') * 10000 * (j - i) / 365))})
    return results


def self_check():
    rows = [{'timestamp': t, 'rate': '.00125', 'direction': 'long'} for t in range(START, END, 3600)]
    obj = {'code': 200, 'resolution': '1h', 'fundings': rows}
    result = analyze(json.dumps(obj))
    assert D(result[0]['rate_sum_bps']) == D('89.875') and result[0]['events'] == 719
    assert D(result[1]['rate_sum_bps']) == D('20.875') and result[1]['events'] == 167
    rows[1]['direction'] = 'short'
    assert D(analyze(json.dumps(obj))[0]['rate_sum_bps']) == D('89.625')
    rows.pop()
    try:
        analyze(json.dumps(obj))
    except AssertionError:
        pass
    else:
        raise AssertionError('missing hour accepted')


def main():
    self_check()
    raw_plan = PLAN.read_bytes()
    plan = json.loads(raw_plan)
    assert Path(__file__).stat().st_size <= 8192
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    claim = {'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'plan_sha256': hashlib.sha256(raw_plan).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (OUT / 'claim.json').open('x') as f:
        json.dump(claim, f)
    outcomes, provenance, retained = [], [], 0
    for asset, market in plan['universe']:
        record = {'asset': asset, 'market_id': market, 'status': 'unknown', 'actual_pnl': None}
        try:
            if asset == 'ETH':
                path = ROOT / plan['reused_eth']
                data = gzip.decompress(path.read_bytes())
                provenance.append({'asset': asset, 'reused': plan['reused_eth'],
                                   'raw_sha256': hashlib.sha256(data).hexdigest()})
            else:
                time.sleep(2)
                params = {'market_id': market, 'resolution': '1h', 'start_timestamp': START,
                          'end_timestamp': END - 1, 'count_back': 721}
                url = 'https://mainnet.zklighter.elliot.ai/api/v1/fundings?' + urllib.parse.urlencode(params)
                request = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(262145)
                    assert response.status == 200 and len(data) <= 262144, 'response bound'
                packed = gzip.compress(data, mtime=0)
                assert retained + len(packed) <= 65536, 'raw allocation exhausted'
                with (OUT / (asset + '.json.gz')).open('xb') as f:
                    f.write(packed)
                retained += len(packed)
                provenance.append({'asset': asset, 'url': url, 'raw_sha256': hashlib.sha256(data).hexdigest(),
                                   'received_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'gzip_bytes': len(packed)})
            record.update(status='complete_rate_proxy', blocks=analyze(data))
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)[:240]
        outcomes.append(record)
    result = {'actual_pnl': None, 'development_not_holdout': True, 'rate_units_percent_inferred': True,
              'direction': 'long funded native spot / short corresponding perp, every asset',
              'capital_scenario': '2x one-leg principal at 5% simple annual; 5bp stress per block',
              'omitted': ['changing oracle notional', 'basis', 'spreads and impact', 'margin path', 'actual execution'],
              'overlap': 'full-month row overlaps weekly diagnostics; boundary payments intentionally excluded',
              'outcomes': outcomes, 'provenance': provenance}
    encoded = (json.dumps(result, indent=2) + '\n').encode()
    assert len(encoded) <= 32768
    with (OUT / 'summary.json').open('xb') as f:
        f.write(encoded)
    terminal = {'status': 'completed_fixed_screen', 'asset_count': len(outcomes), 'requests_max': 6,
                'unknown_assets': sum(x['status'] == 'unknown' for x in outcomes),
                'retained_raw_bytes': retained, 'summary_sha256': hashlib.sha256(encoded).hexdigest()}
    with (OUT / 'terminal.json').open('x') as f:
        json.dump(terminal, f)
    assert len(raw_plan) + (OUT / 'claim.json').stat().st_size + (OUT / 'terminal.json').stat().st_size <= 8192
    print(json.dumps(terminal))
    for x in outcomes:
        print(x['asset'], x['status'], [r['rate_residual_bps'] for r in x.get('blocks', [])])


if __name__ == '__main__':
    main()
