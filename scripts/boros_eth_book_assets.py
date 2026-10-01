"""Two fixed public metadata/depth reads for the previously selected ETH market."""
import datetime as dt
import gzip
import hashlib
import json
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/boros-eth-book-assets-allocation-v1.json'
OUT=ROOT/'reports/boros-eth-book-assets'


def main():
    p=PLAN.read_bytes();plan=json.loads(p)
    assert plan['requests_max']==2 and plan['retries']==0 and plan['selected_market_id']==199
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(p).hexdigest(),
           'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    provenance=[];size=0
    for name,url in plan['requests']:
        record={'name':name,'url':url,'status':'failed_no_retry'}
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=15) as r:
                b=r.read(131073);assert r.status==200 and len(b)<=131072
            z=gzip.compress(b,mtime=0);assert size+len(z)<=32768
            with (OUT/(name+'.json.gz')).open('xb') as f:f.write(z)
            size+=len(z)
            record.update(status='completed',raw_bytes=len(b),gzip_bytes=len(z),
                          raw_sha256=hashlib.sha256(b).hexdigest(),
                          received_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            obj=json.loads(b)
            print(name,json.dumps(obj)[:18000])
        except Exception as e:record['error']=str(e)[:200]
        provenance.append(record)
    result=(json.dumps(provenance,indent=2)+'\n').encode()
    assert len(p)+len(result)+(OUT/'claim.json').stat().st_size<=8192
    with (OUT/'terminal.json').open('xb') as f:f.write(result)
    print(json.dumps(provenance))


if __name__=='__main__':main()
