import datetime as dt
import gzip,hashlib,json,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/boros-eth-depth-correction-allocation-v2.json'
OUT=ROOT/'reports/boros-eth-depth-corrected'


def get(url,limit):
    req=urllib.request.Request(url,headers={'User-Agent':'rhhype-public-research/1.0'})
    with urllib.request.urlopen(req,timeout=15) as r:
        b=r.read(limit+1);assert r.status==200 and len(b)<=limit
    return b


def main():
    p=PLAN.read_bytes();plan=json.loads(p)
    assert plan['requests_max']==2 and plan['retries']==0
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(p).hexdigest(),
           'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    result={'status':'failed_no_retry','requests':0}
    try:
        result['requests']+=1
        raw=get(plan['docs_url'],524288)
        spec,_=json.JSONDecoder().raw_decode(raw.decode().split('const config = ',1)[1])
        spec=spec['content']
        endpoint=spec['paths']['/v1/markets/order-book']['get']
        step=next(p for p in endpoint['parameters'] if p['name']=='tickSize')
        assert .0001 in step['schema']['enum']
        excerpt={'source_url':plan['docs_url'],'full_html_sha256':hashlib.sha256(raw).hexdigest(),
                 'endpoint':endpoint,'schemas':{k:spec['components']['schemas'][k] for k in
                    ('OrderBooksResponse','SideTickResponse','SyncStatusResponse')}}
        b=(json.dumps(excerpt,indent=2)+'\n').encode();assert len(b)<=12288
        with (OUT/'schema-excerpt.json').open('xb') as f:f.write(b)
        result['requests']+=1
        book=get(plan['book_url'],131072)
        z=gzip.compress(book,mtime=0);assert len(b)+len(z)<=16384
        with (OUT/'book.json.gz').open('xb') as f:f.write(z)
        result.update(status='completed',book_raw_sha256=hashlib.sha256(book).hexdigest(),
                      received_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        print(book.decode())
    except urllib.error.HTTPError as e:
        result['error']=str(e);result['error_body']=e.read(500).decode(errors='replace')
    except Exception as e:result['error']=str(e)[:300]
    b=(json.dumps(result,indent=2)+'\n').encode()
    assert len(p)+(OUT/'claim.json').stat().st_size+len(b)<=4096
    with (OUT/'terminal.json').open('xb') as f:f.write(b)
    print(json.dumps(result))


if __name__=='__main__':main()
