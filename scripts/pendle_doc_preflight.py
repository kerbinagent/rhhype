"""Bounded public API documentation capture; no market or wallet operations."""
import gzip, hashlib, json, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/pendle-doc-preflight-allocation-v1.json'
OUT = ROOT / 'reports/pendle-doc-preflight'

def main():
    plan = json.loads(PLAN.read_bytes())
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    rows = []
    used = 0
    for i, url in enumerate(plan['urls']):
        row = {'url': url, 'started_at': time.time()}
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(2_000_001)
                assert len(data) <= 2_000_000
                packed = gzip.compress(data, mtime=0)
                assert used + len(packed) <= plan['categories_bytes']['raw']
                name = f'{i}.gz'
                (OUT / name).write_bytes(packed)
                used += len(packed)
                row.update(status=response.status, path=name, bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest())
        except Exception as exc:
            row['error'] = type(exc).__name__ + ':' + str(exc)
        row['ended_at'] = time.time()
        rows.append(row)
    result = {'requests': rows, 'raw_bytes': used, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'plan_sha256': hashlib.sha256(PLAN.read_bytes()).hexdigest()}
    (OUT / 'terminal.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))

if __name__ == '__main__':
    main()
