"""One public deployment metadata read; no account/API credentials."""
import datetime as dt
import gzip
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/core-collateral-metadata-allocation-v1.json'
OUT = ROOT / 'reports/core-collateral-metadata'


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    assert plan['request_budget'] == 1 and plan['retry_budget'] == 0
    assert Path(__file__).stat().st_size <= 4096
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir()), 'No retries/overwrite'
    claim = {'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'plan_sha256': hashlib.sha256(p).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    cb = (json.dumps(claim, indent=2) + '\n').encode()
    assert len(p) + len(cb) + 600 <= 2048
    with (OUT / 'claim.json').open('xb') as f:
        f.write(cb)
    result = {'status': 'failed_no_retry'}
    try:
        request = urllib.request.Request(plan['endpoint'], headers={'User-Agent': 'rhhype-public-research/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(plan['decoded_byte_limit'] + 1)
            assert response.status == 200 and len(raw) <= plan['decoded_byte_limit']
        packed = gzip.compress(raw, mtime=0)
        assert len(packed) <= 8192
        with (OUT / 'response.json.gz').open('xb') as f:
            f.write(packed)
        obj = json.loads(raw)
        assert obj['code'] == 200
        result = {'status': 'completed', 'raw_bytes': len(raw), 'gzip_bytes': len(packed),
                  'raw_sha256': hashlib.sha256(raw).hexdigest(),
                  'gzip_sha256': hashlib.sha256(packed).hexdigest(),
                  'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        for row in obj['asset_details']:
            if row['symbol'] in ('ETH', 'USDC'):
                print(json.dumps(row))
    except Exception as exc:
        result['error'] = str(exc)[:180]
    data = (json.dumps(result, indent=2) + '\n').encode()
    assert len(data) <= 600 and len(p) + len(cb) + len(data) <= 2048
    with (OUT / 'terminal.json').open('xb') as f:
        f.write(data)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
