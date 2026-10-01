"""At most two public Boros market-registry pages; no account endpoints."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/boros-core-eth-market-allocation-v1.json'
OUT=ROOT/'reports/boros-core-eth-markets'


def main():
    p=PLAN.read_bytes(); plan=json.loads(p)
    assert plan['requests_max']==2 and plan['retries']==0
    reserve=(ROOT/plan['reserve']).read_bytes()
    assert hashlib.sha256(reserve).hexdigest()==plan['reserve_sha256']
    assert Path(__file__).stat().st_size<=8192
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(p).hexdigest(),
           'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    terminal={'status':'failed_no_retry','requests':0}
    all_rows=[]; provenance=[]; total_raw=0; cursor=None
    try:
        for i in range(2):
            params=dict(plan['params'])
            if cursor:params['resumeToken']=cursor
            url=plan['url']+'?'+urllib.parse.urlencode(params)
            terminal['requests']+=1
            req=urllib.request.Request(url,headers={'User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=15) as r:
                raw=r.read(plan['decoded_limit_per_response']+1)
                assert r.status==200 and len(raw)<=plan['decoded_limit_per_response']
            zipped=gzip.compress(raw,mtime=0)
            assert total_raw+len(zipped)<=32768
            with (OUT/(str(i)+'.json.gz')).open('xb') as f:f.write(zipped)
            total_raw+=len(zipped)
            provenance.append({'url':url,'received_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                               'raw_sha256':hashlib.sha256(raw).hexdigest(),'gzip_bytes':len(zipped)})
            obj=json.loads(raw)
            assert isinstance(obj['results'],list)
            all_rows.extend(obj['results'])
            cursor=obj.get('resumeToken')
            if not cursor:break
            time.sleep(2)
        assert len({r['marketId'] for r in all_rows})==len(all_rows)
        selected=[r for r in all_rows if r.get('metadata',{}).get('fundingRateSymbol')=='lighter-eth']
        summary={'actual_pnl':None,'registry_complete':not bool(cursor),'rows_received':len(all_rows),
                 'exact_stream_matches':selected,'provenance':provenance}
        b=(json.dumps(summary,indent=2)+'\n').encode();assert len(b)<=16384
        with (OUT/'summary.json').open('xb') as f:f.write(b)
        terminal.update(status='completed',summary_sha256=hashlib.sha256(b).hexdigest())
        print(json.dumps(summary))
    except Exception as e:terminal['error']=str(e)[:300]
    b=(json.dumps(terminal)+'\n').encode()
    assert len(p)+len(b)+(OUT/'claim.json').stat().st_size+len(reserve)<=8192
    with (OUT/'terminal.json').open('xb') as f:f.write(b)
    print(json.dumps(terminal))


if __name__=='__main__':main()
