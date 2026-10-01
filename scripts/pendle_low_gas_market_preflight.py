"""Fixed low-gas-chain catalogue; no selection by yield or wallet access."""
import datetime, gzip, hashlib, json, time, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/pendle-low-gas-market-preflight-allocation-v1.json'
OUT = ROOT/'reports/pendle-low-gas-market-preflight'

def main():
    plan = json.loads(PLAN.read_bytes())
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    trace, results = [], []
    used = 0
    now = time.time()
    for chain in plan['chains']:
        rows = []
        total = None
        error = None
        for page in range(plan['max_pages_per_chain']):
            params = {'chainId':chain, 'isActive':'true', 'limit':100, 'skip':page*100}
            url = 'https://api-v2.pendle.finance/core/v2/markets/all?'+urllib.parse.urlencode(params)
            item = {'url':url, 'started_at':time.time()}
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    raw = response.read(2_000_001)
                    assert len(raw) <= 2_000_000
                    packed = gzip.compress(raw, mtime=0)
                    assert used+len(packed) <= plan['categories_bytes']['raw']
                    name = f'{chain}-{page}.json.gz'
                    (OUT/name).write_bytes(packed)
                    used += len(packed)
                    item.update(status=response.status, path=name, bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest())
                    data = json.loads(raw)
                    assert data['skip']==page*100 and data['limit']==100
                    assert total is None or total==data['total']
                    total=data['total']
                    assert all(r['chainId']==chain for r in data['results'])
                    rows += data['results']
            except Exception as exc:
                error = type(exc).__name__+':'+str(exc)
                item['error']=error
            item['ended_at']=time.time()
            trace.append(item)
            if error or len(rows)==total:
                break
        complete = not error and len(rows)==total
        assert len({r['address'] for r in rows})==len(rows)
        compact=[]
        for r in rows:
            expiry=datetime.datetime.fromisoformat(r['expiry'].replace('Z','+00:00')).timestamp()
            days=(expiry-now)/86400
            eligible=complete and r.get('isVolatile') is False and 7<=days<=90
            compact.append({k:r.get(k) for k in ['chainId','address','name','expiry','pt','sy','underlyingAsset','accountingAsset','isVolatile']} | {'days':days,'liquidity':r['details']['liquidity'],'eligible_for_asset_verification':eligible})
        candidates=sorted([r for r in compact if r['eligible_for_asset_verification']], key=lambda r:(abs(r['days']-30),-r['liquidity'],r['address']))
        results.append({'chain':chain,'complete':complete,'total':total,'received':len(rows),'error':error,'markets':compact,'first_candidate':candidates[0] if candidates else None})
    summary={'recorded_at':now,'actual_pnl':None,'pricing_not_performed':True,'chains':results}
    b=(json.dumps(summary,indent=2)+'\n').encode()
    assert len(b)<=32768
    (OUT/'summary.json').write_bytes(b)
    (OUT/'terminal.json').write_text(json.dumps({'requests':trace,'raw_bytes':used,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest()},indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':
    main()
