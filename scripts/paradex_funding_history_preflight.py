"""Two bounded public funding history requests; no account endpoints."""
import asyncio,gzip,hashlib,json,time
from pathlib import Path
import aiohttp
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/paradex-funding-history-preflight';PLAN=ROOT/'reports/experiment-storage/paradex-funding-history-preflight-allocation-v1.json'
def sha(b):return hashlib.sha256(b).hexdigest()
async def run():
 plan=json.loads(PLAN.read_bytes());assert sha(Path(__file__).read_bytes())==plan['source_sha256'];OUT.mkdir(exist_ok=False);rows=[]
 async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
  for asset in ['BTC','ETH']:
   url=f'https://api.prod.paradex.trade/v1/funding/data?market={asset}-USD-PERP&page_size=20';began=time.time()
   try:
    async with s.get(url) as r:
     status=r.status;body=await r.content.read(65537);assert len(body)<=65536
    rows.append({'asset':asset,'url':url,'started':began,'received':time.time(),'status':status,'body':body.decode()})
   except Exception as e:rows.append({'asset':asset,'url':url,'started':began,'received':time.time(),'error':type(e).__name__+':'+str(e)})
 body=gzip.compress(json.dumps(rows,separators=(',',':')).encode(),mtime=0);assert len(body)<=8192;(OUT/'responses.json.gz').write_bytes(body)
 summary={'sha256':sha(body),'source_sha256':sha(Path(__file__).read_bytes()),'plan_sha256':sha(PLAN.read_bytes()),'assets':[]}
 for row in rows:
  data={'asset':row['asset'],'error':row.get('error'),'http_status':row.get('status')}
  if row.get('status')==200:
   records=json.loads(row['body'])['results'];times=sorted(x['created_at'] for x in records);gaps=[b-a for a,b in zip(times,times[1:])]
   assert all(x['market']==row['asset']+'-USD-PERP' for x in records)
   data.update(n=len(records),time_min=min(times) if times else None,time_max=max(times) if times else None,gaps_ms=sorted(set(gaps)),oldest_age=row['received']-min(times)/1000 if times else None,newest_age=row['received']-max(times)/1000 if times else None,has_index=all('funding_index' in x for x in records))
  summary['assets'].append(data)
 out=(json.dumps(summary,indent=2)+'\n').encode();assert len(out)<=2048;(OUT/'summary.json').write_bytes(out);print(out.decode())
if __name__=='__main__':asyncio.run(run())
