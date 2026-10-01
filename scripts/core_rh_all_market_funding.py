"""Bounded public settled-funding screen; rates are not trading cashflows."""
import asyncio,datetime,gzip,hashlib,json,time
from decimal import Decimal as D
from pathlib import Path
import aiohttp
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/core-rh-all-market-funding-v1.json'
OUT=ROOT/'reports/core-rh-all-market-funding'
URLS={'lighter':'https://mainnet.zklighter.elliot.ai/api/v1/fundings','rh_lighter':'https://api.rh.lighter.xyz/api/v1/fundings'}
sha=lambda raw:hashlib.sha256(raw).hexdigest()
encode=lambda x:(json.dumps(x,separators=(',',':'))+'\n').encode()

async def run():
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert sha((ROOT/pin['path']).read_bytes())==pin['sha256']
 OUT.mkdir(exist_ok=False)
 meta={};excluded={};requests=[];wire=0;stored=0;data={};started=time.time()
 for pin in plan['metadata']:
  raw=(ROOT/pin['path']).read_bytes();request_raw=(ROOT/pin['request_path']).read_bytes()
  assert sha(raw)==pin['sha256'] and sha(request_raw)==pin['request_sha256']
  request=json.loads(request_raw);assert 0<=time.time_ns()-request['response_completed_utc_ns']<=1800*10**9
  rows=json.loads(gzip.decompress(raw))['order_book_details'];venue=pin['venue'];selected={};ex={}
  for r in rows:
   reason=None
   if r['market_type']!='perp' or r['status']!='active':reason='inactive_or_nonperp'
   elif D(str(r['multiplier']))!=1 or D(str(r['quote_multiplier']))!=1:reason='unit_multiplier'
   elif r.get('is_frozen',False) or r.get('market_config',{}).get('force_reduce_only',False):reason='frozen_or_reduceonly'
   if reason:ex[r['symbol']]=reason
   else:
    assert r['symbol'] not in selected
    selected[r['symbol']]=str(r['market_id'])
  meta[venue]=selected;excluded[venue]=ex
 assets=sorted(set(meta['lighter'])&set(meta['rh_lighter']));assert 0<len(assets)<=plan['max_assets']
 start=int(datetime.datetime.fromisoformat(plan['start_utc']).timestamp());end=int(datetime.datetime.fromisoformat(plan['end_utc']).timestamp())
 expected=set(range(start+3600,end+1,3600));assert len(expected)==24
 timeout=aiohttp.ClientTimeout(total=15)
 async with aiohttp.ClientSession(timeout=timeout) as session:
  async def venue_loop(venue):
   nonlocal wire,stored
   failures=0
   for asset in assets:
    if time.time()-started>=300 or wire>=16*1024*1024:break
    params={'market_id':meta[venue][asset],'resolution':'1h','start_timestamp':start,'end_timestamp':end+3599,'count_back':25}
    row={'venue':venue,'asset':asset,'url':URLS[venue],'params':params,'started_ns':time.time_ns()}
    try:
     async with session.get(URLS[venue],params=params) as response:
      row['status']=response.status;chunks=[];n=0
      async for chunk in response.content.iter_chunked(16384):
       n+=len(chunk);wire+=len(chunk)
       if n>131072 or wire>16*1024*1024:raise ValueError('wire_cap')
       chunks.append(chunk)
      raw=b''.join(chunks)
     packed=gzip.compress(raw,mtime=0)
     if stored+len(packed)>plan['categories_bytes']['raw']-32768:raise ValueError('raw_cap')
     filename=f'{venue}-{meta[venue][asset]}.json.gz';(OUT/filename).write_bytes(packed);stored+=len(packed)
     row.update(raw_bytes=len(raw),raw_sha256=sha(raw),compressed_sha256=sha(packed),file=filename)
     assert row['status']==200,f"http_{row['status']}"
     payload=json.loads(raw);assert payload['code']==200
     events={}
     for f in payload['fundings']:
      timestamp=int(f['timestamp']);bucket=timestamp//3600*3600
      if bucket not in expected:continue
      assert 0<=timestamp-bucket<=1 and bucket not in events
      rate=D(str(f['rate']));assert rate.is_finite() and rate>=0 and f['direction'] in ('long','short')
      events[bucket]=str(rate*100*(1 if f['direction']=='long' else -1))
     assert set(events)==expected,'incomplete_hourly_coverage'
     data[(venue,asset)]=events;row['valid_events']=len(events);failures=0
    except Exception as exc:
     row['error']=type(exc).__name__+': '+str(exc)[:200];failures+=1
    row['ended_ns']=time.time_ns();requests.append(row)
    if row.get('status')==429 or failures>=3 or 'cap' in row.get('error',''):break
    await asyncio.sleep(1.2)
  await asyncio.gather(*(venue_loop(v) for v in URLS))
 req=gzip.compress(encode(requests),mtime=0);assert stored+len(req)<=plan['categories_bytes']['raw']
 (OUT/'requests.json.gz').write_bytes(req)
 results=[]
 for asset in assets:
  if any((v,asset) not in data for v in URLS):results.append({'asset':asset,'status':'unknown_missing_or_invalid_venue'});continue
  values=[]
  for t in sorted(expected):
   core,rh=(D(data[(v,asset)][t]) for v in URLS);values.append((t,core,rh,rh-core))
  gaps=[abs(x[3]) for x in values];attempts=[]
  for before,after in zip(values,values[1:]):
   if abs(before[3])<6:continue
   rate=after[3]*(1 if before[3]>0 else -1)
   attempts.append({'event':after[0],'previous_gap_bps':str(before[3]),'selected_next_credit_bps':str(rate),'less_5bp_stress_bps':str(rate-5)})
  results.append({'asset':asset,'status':'complete','events':[[t,str(c),str(r),str(g)] for t,c,r,g in values],'max_abs_gap_bps':str(max(gaps)),'hindsight_events_over_5bp':sum(g>5 for g in gaps),'hindsight_events_at_least_6bp':sum(g>=6 for g in gaps),'lagged_6bp_entries':attempts})
 summary={'classification':'retrospective_settled_rate_screen_not_profit','plan_sha256':sha(PLAN.read_bytes()),'source_sha256':sha(Path(__file__).read_bytes()),'assets':assets,'excluded_metadata':excluded,'unmatched':{v:sorted(set(meta[v])-set(assets)) for v in URLS},'request_count':len(requests),'wire_bytes':wire,'raw_compressed_bytes':stored+len(req),'request_archive_sha256':sha(req),'started':started,'ended':time.time(),'results':results,'limitations':'Equal reference notional rate arithmetic only; actual venue settlement references, payment ownership, price/basis cashflows, fees and conversion not joined. Previous-hour selection is prospective in historical time but chosen after other research outcomes. No actual trades.'}
 packed=gzip.compress(encode(summary),mtime=0);assert len(packed)<=32768
 (OUT/'summary.json.gz').write_bytes(packed)
 print(json.dumps({'assets':len(assets),'requests':len(requests),'complete':sum(r['status']=='complete' for r in results),'errors':sum('error' in r for r in requests),'wire_bytes':wire,'raw_bytes':stored+len(req),'largest_gaps':sorted([{'asset':r['asset'],'max_bps':r['max_abs_gap_bps']} for r in results if r['status']=='complete'],key=lambda r:D(r['max_bps']),reverse=True)[:10]},indent=2))

if __name__=='__main__':asyncio.run(run())
