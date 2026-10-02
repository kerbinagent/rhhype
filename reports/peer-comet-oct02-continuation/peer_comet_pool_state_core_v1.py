"""Fixed historical pool getter observations; no execution or economic proof."""
import signal,struct,time,urllib.request as u,urllib.error as ue
RAW_CAP=94208
SELECTORS=dict(factory='c45a0155',token0='0dfe1681',token1='d21220a7',
 fee='ddca3f43',slot0='3850c7bd')
CAPS=dict(requests=64,response_bytes=65536,raw_bytes=RAW_CAP,
 request_seconds=10,run_seconds=120,projection_bytes=2560,receipt_bytes=768)
FLAGS=dict(authority_verified=False,source_equivalence_proven=False,
 liquidity_observed=False,depth_observed=False,execution_proven=False,
 economic_cash_evaluated=False,cash_closed=False,inclusion_proven=False)
def need(ok):
 if not ok: raise ValueError('pool getter gate')
class NoRedirect(u.HTTPRedirectHandler):
 def redirect_request(self,*a,**k): return None
class Wire:
 def __init__(self,h,opener=None,clock=time.monotonic):
  need(signal.getitimer(signal.ITIMER_REAL)[0]==0)
  self.h=h; self.raw=bytearray(); self.calls=0; self.clock=clock
  self.start=clock()
  self.opener=opener or u.build_opener(u.ProxyHandler({}),NoRedirect())
  self.opener.addheaders=[('User-Agent','rhhype-research/1.0'),('Accept','application/json')]
  self.old=signal.signal(signal.SIGALRM,self.timeout)
  signal.setitimer(signal.ITIMER_REAL,120)
 def timeout(self,*a): raise TimeoutError('absolute deadline')
 def close(self):
  signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,self.old)
 def __call__(self,method,params):
  h=self.h; left=115-self.clock()+self.start
  need(self.calls<64 and left>0)
  req=dict(jsonrpc='2.0',id=self.calls+1,method=method,params=params)
  meta=dict(request=req,http_status=None,complete=False)
  limit=min(65536,RAW_CAP-len(self.raw)-len(h.encoded(meta))-8); need(limit>0)
  self.calls+=1; body=bytearray(); response=None
  try:
   signal.setitimer(signal.ITIMER_REAL,min(10,left))
   request=u.Request('https://ethereum-rpc.publicnode.com',data=h.encoded(req),
    headers={'Content-Type':'application/json'})
   try: response=self.opener.open(request,timeout=10)
   except ue.HTTPError as error: response=error
   status=response.code; need(type(status) is int and 100<=status<=999)
   meta['http_status']=status; reader=getattr(response,'read1',response.read)
   while len(body)<limit:
    want=min(4096,limit-len(body))
    try: part=reader(want)
    except BaseException as error:
     partial=getattr(error,'partial',b'')
     need(type(partial) is bytes and len(partial)<=want)
     body.extend(partial); raise
    need(type(part) is bytes and len(part)<=want)
    if not part: meta['complete']=True; break
    body.extend(part)
  finally:
   signal.setitimer(signal.ITIMER_REAL,max(.001,120-self.clock()+self.start))
   header=h.encoded(meta); need(len(self.raw)+8+len(header)+len(body)<=RAW_CAP)
   self.raw.extend(struct.pack('>I',len(header))+header+struct.pack('>I',len(body))+body)
   if response is not None: response.close()
  need(meta['http_status']==200 and meta['complete'] and len(body)<=65535)
  value=h.decode_json(body)
  need(type(value) is dict and value.get('jsonrpc')=='2.0' and
   type(value.get('id')) is int and value['id']==req['id'] and
   'error' not in value and 'result' in value)
  return value['result']
def queue(v,h,c,direct,weth):
 parent,m,assets=v.census(h,c); rows=[]; seen=set()
 for mode,p in (('direct',direct),('weth',weth)):
  need(p['mode']==mode and p['status']=='metadata_complete' and
   p['state_coherent'] is True and p['parent']==parent and len(p['rows'])==52)
  target=h.USDC if mode=='direct' else h.WETH
  for i,r in enumerate(p['rows']):
   index,fee=i//4,(100,500,3000,10000)[i%4]
   need(type(r['index']) is int and r['index']==index and
    type(r['fee']) is int and r['fee']==fee)
   if assets[index]==target:
    need(r['status']=='structural_same_token' and r['pool'] is None and r['reached'] is False)
    continue
   need(r['reached'] is True and type(r['pool']) is str and len(r['pool'])==42)
   pool=h.address('0x'+'00'*12+r['pool'][2:],nonzero=False); need(pool==r['pool'])
   if pool==h.ZERO: need(r['status']=='reported_zero_address'); continue
   need(r['status']=='reported_nonzero_address' and pool not in seen); seen.add(pool)
   a,b=sorted((assets[index],target))
   rows.append(dict(id=len(rows),mode=mode,index=index,fee=fee,pool=pool,token0=a,token1=b))
 need(len(rows)==59)
 return parent,m['identity']['implementation_slot'],rows
def slot0(h,value):
 raw=h.hex_bytes(value,224)
 w=['0x'+raw[i:i+32].hex() for i in range(0,224,32)]
 return [str(h.uint(w[0],160)),h.sint(w[1],24),h.uint(w[2],16),
  h.uint(w[3],16),h.uint(w[4],16),h.uint(w[5],8),h.boolean(w[6])]
def collect(h,parent,implementation,queue,batch,rpc):
 need(type(batch) is int and 0<=batch<6 and len(queue)==59)
 chosen=queue[batch*10:min(59,(batch+1)*10)]
 rows=[dict(id=q['id'],status='UNKNOWN',identity_checks_passed=0,slot0=None) for q in chosen]
 planned=5+5*len(chosen); calls=0; current=None
 out=dict(batch=batch,parent_hash=parent['hash'],planned_calls=planned,
  status='UNKNOWN',state_coherent=False,rows=rows,**FLAGS)
 anchor=h.state_selector(parent)
 def call(method,params):
  nonlocal calls
  need(calls<planned); calls+=1; return rpc(method,params)
 def impl():
  return h.address(call('eth_getStorageAt',[h.COMET,h.IMPLEMENTATION_SLOT,anchor]))
 try:
  need(h.quantity(call('eth_chainId',[]))==1)
  need(h.header(call('eth_getBlockByNumber',[parent['number'],False]))==parent)
  need(impl()==implementation)
  for q,row in zip(chosen,rows):
   current=row
   for field,expected in (('factory',h.FACTORY),('token0',q['token0']),
     ('token1',q['token1']),('fee',q['fee'])):
    row['failed_step']=field
    obj=dict(h.call_object(h.COMET,'baseToken()'),to=q['pool'],input='0x'+SELECTORS[field])
    value=call('eth_call',[obj,anchor])
    observed=h.uint(value,24) if field=='fee' else h.address(value)
    need(observed==expected); row['identity_checks_passed']+=1
   row['failed_step']='slot0'
   obj=dict(h.call_object(h.COMET,'baseToken()'),to=q['pool'],input='0x'+SELECTORS['slot0'])
   row['slot0']=slot0(h,call('eth_call',[obj,anchor]))
   row['status']='reported_uninitialized' if row['slot0'][0]=='0' else 'reported_slot0'
   row.pop('failed_step'); current=None
  need(impl()==implementation)
  need(h.header(call('eth_getBlockByNumber',[parent['number'],False]))==parent)
  out['status']='metadata_complete'; out['state_coherent']=True
 except Exception as error:
  if current is not None: current['failed']=True
  out['error']=ascii(type(error).__name__)[:40]+':'+ascii(error)[:120]
  for row in rows: row['status']='UNKNOWN'
 out['attempted_calls']=calls
 need(len(h.encoded(out))<=2560)
 return out
def receipt(h,out,wire,manifest_sha):
 data=h.encoded(dict(batch=out['batch'],calls=wire.calls,planned_calls=out['planned_calls'],
  elapsed_seconds=wire.clock()-wire.start,raw_bytes=len(wire.raw),raw_sha256=h.sha(wire.raw),
  projection_sha256=h.sha(h.encoded(out)),manifest_sha256=manifest_sha,
  state_coherent=out['state_coherent'],status=out['status'],**FLAGS))
 need(len(data)<=768)
 return data
