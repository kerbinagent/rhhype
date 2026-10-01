import gzip, hashlib, json, urllib.request
from pathlib import Path
R = Path(__file__).resolve().parents[1]
P = R/'reports/experiment-storage/boros-symbol-eligibility-allocation-v1.json'
O = R/'reports/boros-symbol-eligibility'
def main():
    p=P.read_bytes(); plan=json.loads(p)
    assert plan['requests']==1 and plan['retries']==0
    assert Path(__file__).stat().st_size<=1536
    O.mkdir(exist_ok=True)
    assert not any(O.iterdir())
    with (O/'claim').open('x') as f:f.write(hashlib.sha256(p).hexdigest())
    result={}
    try:
        req=urllib.request.Request(plan['url'],headers={'User-Agent':'rhhype-public-research/1.0'})
        with urllib.request.urlopen(req,timeout=15) as r:
            b=r.read(65537);assert r.status==200 and len(b)<=65536
        z=gzip.compress(b,mtime=0);assert len(z)<=2048
        with (O/'response.json.gz').open('xb') as f:f.write(z)
        result={'status':'completed','raw_sha256':hashlib.sha256(b).hexdigest()}
        print(b.decode())
    except Exception as e:result={'error':str(e)[:80]}
    s=json.dumps(result);assert len(p)+64+len(s)<=1024
    with (O/'terminal.json').open('x') as f:f.write(s)
    print(s)
if __name__=='__main__':main()
