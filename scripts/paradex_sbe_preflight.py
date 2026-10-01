"""Bounded unauthenticated Paradex snapshot/funding SBE transport preflight."""
import asyncio,base64,gzip,hashlib,json,struct,sys,time,xml.etree.ElementTree as ET
from collections import Counter,defaultdict
from pathlib import Path
import aiohttp
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/paradex-sbe-preflight'
PLAN=ROOT/'reports/experiment-storage/paradex-sbe-preflight-allocation-v1.json'
SCHEMA='https://raw.githubusercontent.com/tradeparadex/paradex-py/main/paradex_py/api/sbe/paradex_1_0.xml'
WS='wss://ws-public.api.prod.paradex.trade/v1?sbeSchemaId=1&sbeSchemaVersion=1'
MARKETS=['BTC-USD-PERP','ETH-USD-PERP']
def encode(x):return (json.dumps(x,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
class Decoder:
 def __init__(self,xml):
  root=ET.fromstring(xml);assert root.get('id')=='1'
  self.types={x.get('name'):x for x in root.find('types')}
  self.messages={int(x.get('id')):x for x in root if x.tag.endswith('message')}
 def primitive(self,name):
  fmts={'int64':'q','uint64':'Q','uint8':'B','int8':'b','int16':'h','uint16':'H','int32':'i','uint32':'I'}
  if name in fmts:return fmts[name],1
  x=self.types[name]
  if x.tag in ('enum','set'):return self.primitive(x.get('encodingType'))
  if x.tag=='type':return self.primitive(x.get('primitiveType'))
  fields=[y for y in x if y.get('presence')!='constant']
  assert len(fields)==1
  f,_=self.primitive(fields[0].get('primitiveType'))
  exp=next((int(y.text) for y in x if y.get('name')=='exponent'),0)
  return f,10.**exp
 def fields(self,node,body,start,version,block):
  out={};at=start
  for x in node.findall('field'):
   if int(x.get('sinceVersion','0'))>version:continue
   fmt,scale=self.primitive(x.get('type'));size=struct.calcsize('<'+fmt)
   assert at+size<=start+block and at+size<=len(body)
   val=struct.unpack_from('<'+fmt,body,at)[0];at+=size
   out[x.get('name')]=None if val==-(2**63) else val if scale==1 else val*scale
  return out
 def decode(self,b):
  block,tid,sid,version=struct.unpack_from('<HHHH',b);assert sid==1 and version==1
  if tid not in (2,3,5):return {'template':tid,'unsupported':True}
  node=self.messages[tid];out=self.fields(node,b,8,version,block);at=8+block
  for group in node.findall('group'):
   width,count=struct.unpack_from('<HH',b,at);at+=4
   assert count<=100 and at+width*count<=len(b)
   out[group.get('name')]=[self.fields(group,b,at+i*width,version,width) for i in range(count)]
   at+=width*count
  for data in node.findall('data'):
   if int(data.get('sinceVersion','0'))>version:continue
   size=b[at];at+=1;assert at+size<=len(b)
   out[data.get('name')]=b[at:at+size].decode();at+=size
  assert at==len(b);out['template']=tid
  return out
async def run():
 plan=json.loads(PLAN.read_bytes());assert sha(Path(__file__).read_bytes())==plan['source_sha256']
 OUT.mkdir(exist_ok=False);rows=[];packed=gzip.compress(b'',mtime=0);counts=Counter();ages=defaultdict(list);seqs={};error=None;reason='duration';started=time.time()
 def append(row):
  nonlocal packed
  body=gzip.compress(b''.join(encode(x) for x in rows+[row]),mtime=0)
  if len(body)>49152:return False
  rows.append(row);packed=body;return True
 try:
  async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
   async with s.get(SCHEMA) as r:
    r.raise_for_status();body=await r.content.read(200001);assert len(body)<=200000
   compressed=gzip.compress(body,mtime=0);assert len(compressed)<=16384
   (OUT/'schema.xml.gz').write_bytes(compressed);decoder=Decoder(body)
   async with s.ws_connect(WS,heartbeat=15,max_msg_size=262144) as ws:
    for i,channel in enumerate([c for m in MARKETS for c in (f'order_book.{m}.snapshot@15@100ms',f'funding_data.{m}')]):
     await ws.send_json({'jsonrpc':'2.0','id':i+1,'method':'subscribe','params':{'channel':channel}})
    start=time.monotonic()
    while time.monotonic()-start<60:
     try:msg=await ws.receive(timeout=2)
     except asyncio.TimeoutError:continue
     now=time.time()
     if msg.type in (aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):reason='disconnect';break
     if msg.type not in (aiohttp.WSMsgType.TEXT,aiohttp.WSMsgType.BINARY):continue
     binary=msg.type==aiohttp.WSMsgType.BINARY
     row={'received':now,'binary':binary,'payload':base64.b64encode(msg.data).decode() if binary else msg.data}
     if not append(row):reason='raw_cap';break
     counts['binary' if binary else 'text']+=1
     if not binary:
      d=json.loads(msg.data)
      if d.get('error'):counts['subscription_errors']+=1
      continue
     d=decoder.decode(msg.data);tid=d['template'];counts[f'template_{tid}']+=1
     if d.get('unsupported'):continue
     assert d['market'] in MARKETS
     label=f"{tid}:{d['market']}";at=d['ts']/1e6;ages[label].append(now-at)
     if at>now:counts['future_clock']+=1
     if d['seq']<seqs.get(label,-1):counts['sequence_reversal']+=1
     seqs[label]=d['seq']
     if tid==3:
      assert d['pkgType']==0
      a,b=d['asks'],d['bids']
      assert a and b and all(x['price']>0 and x['size']>0 for x in a+b)
      assert all(a[i]['price']<a[i+1]['price'] for i in range(len(a)-1))
      assert all(b[i]['price']>b[i+1]['price'] for i in range(len(b)-1))
      assert b[0]['price']<a[0]['price']
 except Exception as exc:error=type(exc).__name__+':'+str(exc)
 (OUT/'frames.jsonl.gz').write_bytes(packed)
 summary={'error':error,'stop_reason':reason,'started':started,'ended':time.time(),'counts':dict(counts),'raw_bytes':len(packed),'raw_sha256':sha(packed),'source_sha256':sha(Path(__file__).read_bytes()),'plan_sha256':sha(PLAN.read_bytes()),'schema_sha256':sha((OUT/'schema.xml.gz').read_bytes()) if (OUT/'schema.xml.gz').exists() else None,'ages':{k:{'n':len(v),'min':min(v),'median':sorted(v)[len(v)//2],'max':max(v),'within_2s':sum(0<=x<=2 for x in v)} for k,v in ages.items()},'limitations':'Transport/freshness only. Book ts is the published schema timestamp, not authenticated order ACK or private execution. No economics, accounts, orders, interactive/RPI feed or credentials.'}
 result=encode(summary);assert len(result)<=8192;(OUT/'summary.json').write_bytes(result);print(result.decode())
if __name__=='__main__':asyncio.run(run())
