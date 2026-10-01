"""Fixed September Core/RH rate persistence diagnostic, never a P&L backtest."""
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
PLAN = ROOT / 'reports/experiment-storage/core-rh-monthly-funding-allocation-v1.json'
OUT = ROOT / 'reports/core-rh-monthly-funding'
START, END = 1788220800, 1790812800


def rates(raw):
    obj = json.loads(raw)
    assert obj['code'] == 200 and obj['resolution'] == '1h'
    rows = {}
    for r in obj['fundings']:
        t = r['timestamp']
        assert isinstance(t, int) and START <= t < END and (t-START) % 3600 == 0
        assert t not in rows and r['direction'] in ('long', 'short')
        rate = D(r['rate'])
        assert rate.is_finite() and rate >= 0
        rows[t] = rate * 100 * (1 if r['direction'] == 'long' else -1)
    return rows


def analyze(data):
    result = []
    for asset in ('SOL', 'BTC', 'ETH'):
        core, rh = rates(data['core_'+asset]), rates(data['rh_'+asset])
        delta = {t: core[t]-rh[t] for t in core.keys() & rh.keys()}
        train = list(range(START, START+7*86400, 3600))
        complete = all(t in delta for t in train)
        train_sum = sum((delta[t] for t in train), D(0)) if complete else None
        direction = None if train_sum is None else (1 if train_sum >= 0 else -1)
        blocks = []
        # Inclusive settlement grid; these are rate blocks, not entry/exit cashflows.
        for a, b in ((7, 14), (14, 21), (21, 28), (28, 30), (7, 30)):
            expected = list(range(START+a*86400, START+b*86400, 3600))
            observed = [t for t in expected if t in delta]
            usable = direction is not None and len(observed) == len(expected)
            net = sum((delta[t]*direction for t in observed), D(0)) if usable else None
            capital = D(1000)*(b-a)/365  # 5% on 2x one-leg notional, in bp.
            blocks.append({'start_day': a+1, 'end_day': b, 'expected_hours': len(expected),
                           'observed_hours': len(observed), 'rate_bps': str(net) if usable else None,
                           'capital_bps_2x': str(capital), 'stress_bps': '5',
                           'residual_rate_proxy_bps': str(net-capital-5) if usable else None,
                           'max_capital_multiple_after_stress': str((net-5)*365/(D(500)*(b-a))) if usable else None,
                           'positive_hours': sum(delta[t]*direction > 0 for t in observed) if usable else None})
        result.append({'asset': asset, 'primary': asset == 'SOL', 'core_hours': len(core),
                       'rh_hours': len(rh), 'train_hours': sum(t in delta for t in train),
                       'train_core_minus_rh_bps': str(train_sum) if complete else None,
                       'selected_short_venue': ('core' if direction == 1 else 'rh') if direction else None,
                       'blocks': blocks})
    return {'actual_pnl': None, 'rate_sums_not_fixed_quantity_cashflows': True,
            'aggregate_overlaps_blocks': True, 'historical_development_not_prospective_validation': True,
            'primary_asset_selected_after_overlapping_48h_research': True, 'assets': result}


def main():
    pb = PLAN.read_bytes()
    plan = json.loads(pb)
    assert plan['requests_max'] == 5 and plan['retries'] == 0
    assert Path(__file__).stat().st_size <= 16384
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir()), 'No retries or overwrite'
    claim = {'plan_sha256': hashlib.sha256(pb).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:
        json.dump(claim, f)
    data = {'core_ETH': gzip.decompress((ROOT/plan['reused_core_eth']).read_bytes())}
    terminal = {'status': 'failed_no_retry', 'requests': 0}
    provenance, packed_size = [], 0
    try:
        for name, host, market in plan['requests']:
            if terminal['requests']:
                time.sleep(2)
            params = dict(market_id=market, resolution='1h', start_timestamp=START,
                          end_timestamp=END-1, count_back=721)
            url = host+'/api/v1/fundings?'+urllib.parse.urlencode(params)
            terminal['requests'] += 1
            req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(262145)
                assert response.status == 200 and len(raw) <= 262144
            packed = gzip.compress(raw, mtime=0)
            assert packed_size+len(packed) <= 65536
            with (OUT/(name+'.json.gz')).open('xb') as f:
                f.write(packed)
            packed_size += len(packed)
            data[name] = raw
            provenance.append({'name': name, 'url': url, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                               'gzip_bytes': len(packed), 'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
        result = analyze(data)
        result['provenance'] = provenance
        encoded = (json.dumps(result, indent=2)+'\n').encode()
        assert len(encoded) <= 16384
        with (OUT/'summary.json').open('xb') as f:
            f.write(encoded)
        terminal.update(status='completed', summary_sha256=hashlib.sha256(encoded).hexdigest())
        print(json.dumps(result))
    except Exception as exc:
        terminal['error'] = str(exc)[:300]
    tb = (json.dumps(terminal)+'\n').encode()
    assert len(pb)+(OUT/'claim.json').stat().st_size+len(tb) <= 16384
    with (OUT/'terminal.json').open('xb') as f:
        f.write(tb)
    print(json.dumps(terminal))


if __name__ == '__main__':
    main()
