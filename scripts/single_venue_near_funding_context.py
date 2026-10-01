"""Two bounded public history reads for already-observed NEAR basis context."""
import datetime,gzip,hashlib,json,time,urllib.request,urllib.parse
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/single-venue-broad-dynamics-v1.json'
OUT=ROOT/'reports/single-venue-research/near-funding-context'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    OUT.mkdir(exist_ok=False);requests=[];rows=[]
    start=int(datetime.datetime(2026,10,1,16,tzinfo=datetime.timezone.utc).timestamp())
    end=start+7*3600-1;expected=set(range(start+3600,start+7*3600,3600))
    for venue,host,market in (('lighter','https://mainnet.zklighter.elliot.ai',10),('rh_lighter','https://api.rh.lighter.xyz',7)):
        params=dict(market_id=market,resolution='1h',start_timestamp=start,end_timestamp=end,count_back=7)
        url=host+'/api/v1/fundings?'+urllib.parse.urlencode(params)
        request=dict(venue=venue,url=url,started_ns=time.time_ns())
        try:
            with urllib.request.urlopen(url,timeout=15) as response:
                raw=response.read(16385);request['http_status']=response.status
            assert len(raw)<=16384,'response cap'
            packed=gzip.compress(raw,mtime=0)
            target=OUT/(venue+'.json.gz');assert sum(p.stat().st_size for p in OUT.iterdir())+len(packed)<=24576
            target.write_bytes(packed);request.update(raw_bytes=len(raw),compressed_sha256=sha(target))
            body=json.loads(raw);assert body['code']==200;events={}
            for event in body['fundings']:
                t=int(event['timestamp']);bucket=t//3600*3600
                if bucket not in expected:continue
                assert t-bucket<=1 and bucket not in events
                rate=D(str(event['rate']));assert rate.is_finite() and rate>=0 and event['direction'] in ('long','short')
                events[bucket]=str(rate*100*(1 if event['direction']=='long' else -1))
            assert set(events)==expected,'incomplete six-event coverage'
            rows.append(dict(venue=venue,asset='NEAR',status='complete',events=[dict(timestamp=t,signed_long_payment_bps=events[t]) for t in sorted(events)]))
        except Exception as exc:
            request['error']=type(exc).__name__+': '+str(exc)[:200]
            rows.append(dict(venue=venue,asset='NEAR',status='unknown',error=request['error']))
        request['ended_ns']=time.time_ns();requests.append(request)
    report=dict(plan_sha256=sha(PLAN),source_sha256=sha(Path(__file__)),requests=requests,rows=rows,
        limits='Historical API rates, not account cash payments or explanation of the current basis. Percent rate converted to bp; positive means longs pay. Six hourly settlements ending22:00UTC. Public data only, no retry, auth, orders, wallet or proxy.')
    blob=(json.dumps(report,indent=2)+'\n').encode();assert sum(p.stat().st_size for p in OUT.iterdir())+len(blob)<=32768
    (OUT/'summary.json').write_bytes(blob);print(json.dumps(rows,indent=2))

if __name__=='__main__':run()
