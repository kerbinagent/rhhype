"""Bounded public documentation/metadata preflight. No quotes, accounts or orders."""
import datetime as dt
import gzip
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/derive-box-preflight-allocation-v1.json'
OUT = ROOT/'reports/derive-box-preflight'


def main():
    pb = PLAN.read_bytes()
    plan = json.loads(pb)
    assert hashlib.sha256((ROOT/plan['previous']).read_bytes()).hexdigest() == plan['previous_sha256']
    assert len(plan['requests']) == 8 and plan['retries'] == 0
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    claim = {'plan_sha256': hashlib.sha256(pb).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:
        json.dump(claim, f)
    status = {'status': 'failed_no_retry', 'provenance': [], 'requests': 0}
    packed_total = 0
    try:
        for name, url, body, cap in plan['requests']:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'User-Agent': 'rhhype-public-research/1.0', 'Content-Type': 'application/json'})
            status['requests'] += 1
            try:
                response = urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as e:
                response = e
            with response:
                raw = response.read(cap+1)
                assert len(raw) <= cap, 'decoded response cap'
                code = response.status
            packed = gzip.compress(raw, mtime=0)
            assert packed_total+len(packed) <= 131072
            with (OUT/(name+'.gz')).open('xb') as f:
                f.write(packed)
            packed_total += len(packed)
            status['provenance'].append({'name': name, 'url': url, 'body': body,
                                         'http_status': code, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                                         'bytes': len(raw), 'gzip_bytes': len(packed),
                                         'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
            assert code == 200, f'HTTP {code}; no retry'
            if body is not None:
                obj = json.loads(raw)
                assert 'error' not in obj, str(obj.get('error'))[:200]
        status['status'] = 'completed_metadata_only'
    except Exception as e:
        status['error'] = str(e)[:300]
    b = (json.dumps(status, indent=2)+'\n').encode()
    assert len(b)+len(pb)+(OUT/'claim.json').stat().st_size <= 49152
    assert Path(__file__).stat().st_size <= 16384
    with (OUT/'terminal.json').open('xb') as f:
        f.write(b)
    print(json.dumps(status))


if __name__ == '__main__':
    main()
