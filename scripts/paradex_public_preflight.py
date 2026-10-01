"""Fixed public REST connectivity/schema preflight, no auth or order requests."""
import gzip,hashlib,json,time,urllib.request
from pathlib import Path
R=Path(__file__).resolve().parents[1];O=R/'reports/paradex-public-preflight';P=R/'reports/experiment-storage/paradex-public-preflight-allocation-v1.json'
def main():
    p=json.loads(P.read_bytes());assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==p['source_sha256']
    O.mkdir(exist_ok=False);trace=[]
    urls=[f'https://api.prod.paradex.trade/v1/markets?market={a}-USD-PERP' for a in p['assets']]
    urls += [f'https://api.prod.paradex.trade/v1/orderbook/{a}-USD-PERP?depth=20' for _ in range(3) for a in p['assets']]
    for i,url in enumerate(urls):
        if i:time.sleep(1)
        x={'url':url,'sent':time.time()}
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=12) as response:
                body=response.read(131073);x['http_status']=response.status
            assert len(body)<=131072
            x['body']=json.loads(body);x['body_sha256']=hashlib.sha256(body).hexdigest()
        except Exception as exc:x['error']=type(exc).__name__+': '+str(exc)[:200]
        x['received']=time.time();trace.append(x)
        packed=gzip.compress(json.dumps(trace).encode(),mtime=0);assert len(packed)<=32768
        (O/'trace.json.gz').write_bytes(packed)
    terminal={'requests':len(trace),'errors':sum('error' in x for x in trace),'ended':time.time(),'scope':'Schema/transport only; no paper trades or profit claims.'}
    (O/'terminal.json').write_text(json.dumps(terminal,indent=2)+'\n');print(json.dumps(terminal))
if __name__=='__main__':main()
