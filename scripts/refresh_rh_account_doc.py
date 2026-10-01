"""Bounded public documentation refresh; saves only the account table excerpt."""
import datetime, gzip, hashlib, json, urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/rh-account-doc-refresh-v1.json'

class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden and data.strip(): self.rows.append(data.strip())

def main():
    plan = json.loads(PLAN.read_bytes())
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == plan['source_sha256']
    req = urllib.request.Request(plan['url'], headers={'User-Agent': 'rhhype-paper-research/1.0'})
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read(2_000_001); assert len(raw) <= 2_000_000
        status = response.status
    parser = Text(); parser.feed(raw.decode())
    text = '\n'.join(parser.rows)
    start = text.index('Premium Account (Opt-in)')
    end = text.index('Account Switch', start)
    excerpt = text[start:end]
    assert 'Standard Account (Default)' in excerpt and len(excerpt) < 6000
    result = dict(url=plan['url'], fetched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status=status, response_bytes=len(raw), response_sha256=hashlib.sha256(raw).hexdigest(),
        plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(), account_tables_excerpt=excerpt,
        limitation='HTML not retained; exact extracted text and full response hash retained. Documentation does not verify private execution latency.')
    packed = gzip.compress(json.dumps(result, indent=2).encode(), mtime=0)
    assert len(packed) <= 4096
    out = ROOT / 'reports/rh-account-doc-refresh'; out.mkdir(exist_ok=False)
    with (out / 'evidence.json.gz').open('xb') as file: file.write(packed)
    print(json.dumps({'output_bytes':len(packed), 'status':status, 'response_bytes':len(raw)}))

if __name__ == '__main__': main()
