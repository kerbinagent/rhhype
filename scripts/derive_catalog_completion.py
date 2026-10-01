"""One declared second-page fetch; preserve the incomplete original preflight."""
import datetime as dt
import gzip
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/derive-catalog-completion-allocation-v1.json'
OUT = ROOT/'reports/derive-catalog-completion'


def main():
    pb = PLAN.read_bytes(); p = json.loads(pb)
    for pin in p['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    OUT.mkdir(exist_ok=True); assert not any(OUT.iterdir())
    claim = {'plan_sha256': hashlib.sha256(pb).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f: json.dump(claim, f)
    terminal = {'status': 'failed_no_retry', 'requests': 0}
    try:
        req = urllib.request.Request(p['url'], data=json.dumps(p['body']).encode(),
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'rhhype-public-research/1.0'})
        terminal['requests'] = 1
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(262145); assert r.status == 200 and len(raw) <= 262144
        z = gzip.compress(raw, mtime=0); assert len(z) <= 8192
        with (OUT/'page2.json.gz').open('xb') as f: f.write(z)
        first = json.loads(gzip.decompress((ROOT/p['page1']).read_bytes()))['result']
        second = json.loads(raw)['result']
        assert first['pagination'] == second['pagination']
        rows = first['instruments']+second['instruments']
        assert len({r['instrument_name'] for r in rows}) == len(rows) == first['pagination']['count']
        assert first['pagination']['num_pages'] == 2
        terminal.update(status='catalogue_complete', count=len(rows), raw_sha256=hashlib.sha256(raw).hexdigest(),
                        received_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as e: terminal['error'] = str(e)[:250]
    b = (json.dumps(terminal, indent=2)+'\n').encode()
    assert len(b)+len(pb)+(OUT/'claim.json').stat().st_size <= 8192
    with (OUT/'terminal.json').open('xb') as f:f.write(b)
    print(json.dumps(terminal))


if __name__ == '__main__':main()
