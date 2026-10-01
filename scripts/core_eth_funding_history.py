"""Single bounded public historical request; fixed ETH funding screen, no quotes."""
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
PLAN = ROOT / 'reports/experiment-storage/core-eth-funding-history-allocation-v1.json'
OUT = ROOT / 'reports/core-eth-funding-history/202609-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def put(name, data, cap):
    assert len(data) <= cap, (name, len(data), cap)
    with (OUT / name).open('xb') as f:
        f.write(data)


def main():
    plan_bytes = PLAN.read_bytes()
    plan = json.loads(plan_bytes)
    assert plan['request_budget'] == 1 and plan['retry_budget'] == 0
    p = plan['params']
    assert dt.datetime.fromtimestamp(p['start_timestamp'], dt.timezone.utc).isoformat() == '2026-09-01T00:00:00+00:00'
    assert dt.datetime.fromtimestamp(p['end_timestamp'], dt.timezone.utc).isoformat() == '2026-09-30T23:59:59+00:00'
    assert Path(__file__).stat().st_size <= 8192
    OUT.mkdir(parents=True, exist_ok=True)
    assert not any(OUT.iterdir()), 'No retry or overwrite'
    url = plan['endpoint'] + '?' + urllib.parse.urlencode(p)
    claim = {'url': url, 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'plan_sha256': digest(plan_bytes),
             'script_sha256': digest(Path(__file__).read_bytes()),
             'requests_max': 1, 'retries': 0}
    cb = (json.dumps(claim, indent=2) + '\n').encode()
    assert len(plan_bytes) + len(cb) + 800 <= 4096
    put('request-claim.json', cb, 1000)
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(262145)
            assert response.status == 200 and len(raw) <= 262144
        compressed = gzip.compress(raw, mtime=0)
        put('response.json.gz', compressed, 32768)
        obj = json.loads(raw, parse_float=D)
        assert obj['code'] == 200 and obj['resolution'] == '1h'
        expected = list(range(p['start_timestamp'], p['end_timestamp'] + 1, 3600))
        assert len(expected) == 720
        values, outside = {}, 0
        for row in obj['fundings']:
            t = int(row['timestamp'])
            if t not in expected:
                outside += 1
                continue
            assert t not in values, 'Duplicate event'
            assert row['direction'] in ('long', 'short')
            rate = D(row['rate'])
            assert rate.is_finite() and rate >= 0
            values[t] = rate * 100 * (1 if row['direction'] == 'long' else -1)
        blocks = []
        for i, j in ((0, 168), (168, 336), (336, 504), (504, 672), (672, 720)):
            ts = expected[i:j]
            present = [values[t] for t in ts if t in values]
            complete = len(present) == len(ts)
            days = D(len(ts)) / 24
            capital = D('0.05') * 2 * 10000 * days / 365
            rate_sum = sum(present) if complete else None
            blocks.append({'start_utc': dt.datetime.fromtimestamp(ts[0], dt.timezone.utc).isoformat(),
                           'days': str(days), 'expected_hours': len(ts),
                           'received_hours': len(present), 'negative_hours': sum(v < 0 for v in present),
                           'funding_rate_sum_bps': None if rate_sum is None else str(rate_sum),
                           'capital_bps': str(capital), 'stress_bps': 5,
                           'rate_less_capital_stress_bps': None if rate_sum is None else str(rate_sum - capital - 5)})
        result = {'schema': 'core-eth-historical-rate-screen-v1', 'expected_hours': 720,
                  'received_hours': len(values), 'outside_window_rows': outside,
                  'not_pnl_or_fresh_validation': True, 'actual_net_pnl': None,
                  'omitted': ['entry/exit basis', 'spread/impact', 'changing index notional',
                              'fills', 'margin/liquidation', 'withdrawal/conversion'],
                  'blocks': blocks, 'raw_sha256': digest(raw),
                  'gzip_sha256': digest(compressed), 'raw_bytes': len(raw),
                  'compressed_bytes': len(compressed), 'plan_sha256': digest(plan_bytes)}
        data = (json.dumps(result, indent=2) + '\n').encode()
        put('summary.json', data, 4096)
        terminal = {'status': 'completed', 'received_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'elapsed_seconds': time.monotonic() - start, 'requests': 1, 'retries': 0,
                    'summary_sha256': digest(data)}
    except Exception as exc:
        terminal = {'status': 'failed_no_retry', 'error': str(exc)[:300],
                    'elapsed_seconds': time.monotonic() - start, 'requests_max': 1}
    tb = (json.dumps(terminal, indent=2) + '\n').encode()
    assert len(plan_bytes) + len(cb) + len(tb) <= 4096
    put('terminal.json', tb, 800)
    print(json.dumps(terminal))
    if terminal['status'] == 'completed':
        print(json.dumps(result))


if __name__ == '__main__':
    main()
