"""Bounded multi-asset single-venue research capture; no trading requests."""
import asyncio,gzip,hashlib,json,sys,time
from pathlib import Path
from decimal import Decimal as D
import aiohttp
import maker_capture as transport
from core_rh_small_shortterm import Archive,CapError

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/single-venue-multi-v1.json'
OUT=ROOT/'reports/single-venue-multi/capture'
HARD_SECONDS=600
HARD_BYTES=8519680
MAX_METADATA_AGE_NS=30*60*10**9
MAX_TRADE_IDS=100000
METADATA_MAX_BYTES=65536
VENUES=('rh_lighter','lighter')
SELECTED={'rh_lighter':{'LIT':'5','VVV':'8','ZEC':'4'},'lighter':{'LIT':'120','VVV':'69','ZEC':'90'}}
REQUESTS={
 'rh_markets':('GET','https://api.rh.lighter.xyz/api/v1/orderBookDetails',None),
 'core_markets':('GET','https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails',None),
 'rh_assets':('GET','https://api.rh.lighter.xyz/api/v1/assetDetails',None),
 'core_assets':('GET','https://mainnet.zklighter.elliot.ai/api/v1/assetDetails',None),
}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def select_three(path):
 raw=path.read_bytes();p=json.loads(raw);assert p['selected']==SELECTED
 return p['selected'],hashlib.sha256(raw).hexdigest()

def verify_metadata(directory,selected,plan_hash,*,fresh=False):
 normalized={'markets':{},'raw_requests':{},'market_plan_sha256':plan_hash}
 data={}
 for name,(method,url,body) in REQUESTS.items():
  request=json.loads((directory/f'{name}.request.json').read_bytes())
  packed=(directory/f'{name}.json.gz').read_bytes();assert len(packed)<=METADATA_MAX_BYTES
  raw=gzip.decompress(packed);assert len(raw)<=2_000_000
  assert request['method']==method and request['url']==url and request['json_body']==body and request['status']==200
  assert request['raw_bytes']==len(raw) and request['sha256']==hashlib.sha256(raw).hexdigest() and request['compressed_sha256']==hashlib.sha256(packed).hexdigest()
  if fresh:assert 0<=time.time_ns()-request['response_completed_utc_ns']<=MAX_METADATA_AGE_NS
  data[name]=json.loads(raw);normalized['raw_requests'][name]=request
 for venue,prefix,collateral in (('rh_lighter','rh','USDG'),('lighter','core','USDC')):
  body=data[prefix+'_markets'];assert body['code']==200
  normalized['markets'][venue]={}
  for asset,market in selected[venue].items():
   rows=[r for r in body['order_book_details'] if str(r['market_id'])==market];assert len(rows)==1
   r=rows[0];assert r['symbol']==asset and r['status']=='active' and r['market_type']=='perp'
   assert not r.get('is_frozen',False) and not r.get('market_config',{}).get('force_reduce_only',False)
   assert D(str(r['multiplier']))==1 and D(str(r['quote_multiplier']))==1
   assert D(str(r['maker_fee']))==0 and D(str(r['taker_fee']))==0
   pd,sd=r['supported_price_decimals'],r['supported_size_decimals']
   assert r['price_decimals']==pd and r['size_decimals']==sd and 0<=pd<=12 and 0<=sd<=12
   assets=data[prefix+'_assets'];assert assets['code']==200
   assert len([a for a in assets['asset_details'] if a['symbol']==collateral and a['margin_mode']=='enabled'])==1
   m={'venue':venue,'asset':asset,'market':market,'price_tick':str(D(10)**-pd),'qty_step':str(D(10)**-sd),'min_qty':str(r['min_base_amount']),'min_notional':str(r['min_quote_amount']),'max_quote':str(r['order_quote_limit']),'maker_fee_bps':'0','taker_fee_bps':'0','collateral':collateral,'contract_multiplier':'1','processing_delay_ms':300,'max_qty':None,'maximum_base_quantity_unknown':True}
   assert all(D(m[k])>0 for k in ('price_tick','qty_step','min_qty','min_notional','max_quote'))
   normalized['markets'][venue][asset]=m
 if (directory/'normalized.json').exists():assert json.loads((directory/'normalized.json').read_bytes())==normalized
 assert sha(directory/'market_plan.json')==plan_hash
 return normalized

class Writer:
 def __init__(self,path,cap):self.archive=Archive(path,cap)
 @property
 def bytes_written(self):return self.archive.bytes
 @property
 def records(self):return self.archive.count
 def write(self,row):
  try:self.archive.add(row)
  except CapError as exc:raise transport.SizeCapReached from exc
 def close(self):self.archive.close()

def subscriptions(venue,markets):
 feeds=('order_book','trade')
 return [{'type':'subscribe','channel':f'{feed}/{market}'} for market in markets.values() for feed in feeds]

async def main():
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 OUT.mkdir(parents=True,exist_ok=False);md=OUT/'metadata';md.mkdir()
 (md/'market_plan.json').write_bytes(PLAN.read_bytes());total=(md/'market_plan.json').stat().st_size
 terminal={'status':'metadata_pending','started_ns':time.time_ns(),'plan_sha256':sha(PLAN)}
 try:
  async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
   for name,(method,url,body) in REQUESTS.items():
    started=time.time_ns()
    async with session.get(url) as response:
     pieces=[];read_bytes=0
     async for chunk in response.content.iter_chunked(65536):
      read_bytes+=len(chunk);assert read_bytes<=2_000_000
      pieces.append(chunk)
     raw=b"".join(pieces);response.raise_for_status()
     status=response.status
    ended=time.time_ns();packed=gzip.compress(raw,mtime=0)
    request={'method':method,'url':url,'json_body':body,'status':status,'raw_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'compressed_sha256':hashlib.sha256(packed).hexdigest(),'request_started_utc_ns':started,'response_completed_utc_ns':ended,'raw_file':f'{name}.json.gz'}
    rb=(json.dumps(request,indent=2)+'\n').encode();assert total+len(packed)+len(rb)<=METADATA_MAX_BYTES-8192
    (md/f'{name}.json.gz').write_bytes(packed);(md/f'{name}.request.json').write_bytes(rb);total+=len(packed)+len(rb)
  n=verify_metadata(md,SELECTED,sha(PLAN),fresh=True);write(md/'normalized.json',n)
  total=sum(f.stat().st_size for f in md.iterdir());assert total<=METADATA_MAX_BYTES
  writer=Writer(OUT/'frames.jsonl.gz',p['categories_bytes']['raw'])
  run=transport.Capture(writer,SELECTED,HARD_SECONDS,HARD_BYTES)
  transport.subscriptions=subscriptions;transport.MAX_RECONNECTS=2
  tasks=[asyncio.create_task(run.venue_loop(v)) for v in VENUES]
  mono=time.monotonic();deadline=mono+HARD_SECONDS
  try:
   while not run.stop.is_set():
    if abs((time.time_ns()-run.started_ns)/1e9-(time.monotonic()-mono))>.25:run.finish('clock_shift');break
    if time.monotonic()>=deadline:run.finish('duration_limit');break
    if any(task.done() for task in tasks):run.finish('one_venue_ended');break
    write(OUT/'status.json',{'elapsed_seconds':time.monotonic()-mono,'compressed_bytes':writer.bytes_written,'records':writer.records,'connections':len(run.generations),'errors':run.errors,'economic_evaluation':False})
    await asyncio.sleep(1)
  finally:
   for task in tasks:task.cancel()
   outcomes=await asyncio.gather(*tasks,return_exceptions=True);writer.close()
  manifest={'schema':'single-venue-multi-public-capture-v1','read_only':True,'started_utc':transport.utc_iso_ns(run.started_ns),'ended_utc':transport.utc_iso_ns(time.time_ns()),'end_reason':run.end_reason,'truncated':run.end_reason!='duration_limit','dropped_complete_frame_on_cap':run.dropped_on_cap,'configured_seconds':HARD_SECONDS,'configured_total_bytes':HARD_BYTES,'compressed_payload_bytes':writer.bytes_written,'payload_records':writer.records,'frames_sha256':sha(OUT/'frames.jsonl.gz'),'market_plan_sha256':sha(PLAN),'selected_markets':SELECTED,'metadata_bytes':total,'generations':run.generations,'errors':run.errors,'record_counts':dict(run.counts),'source_sha256':sha(__file__),'economic_evaluation':False}
  write(OUT/'manifest.json',manifest);terminal.update(status='capture_completed',end_reason=run.end_reason,manifest_sha256=sha(OUT/'manifest.json'))
 except Exception as exc:terminal.update(status='failed_no_retry',error=type(exc).__name__+': '+str(exc)[:400])
 terminal['ended_ns']=time.time_ns();write(OUT/'terminal.json',terminal);print(json.dumps(terminal),flush=True)

if __name__=='__main__':
 if sys.argv[1:]==['run']:asyncio.run(main())
 else:print('Use run explicitly after freezing protocol and source pins.')
