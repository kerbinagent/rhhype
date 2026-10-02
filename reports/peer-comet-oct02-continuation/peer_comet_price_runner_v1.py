"""Proposed pinned price runner; execute only after a separate freeze/allocation."""
import hashlib,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
V2='scripts/peer_comet_pool_discovery_v2.py'
V2_SHA='f7e0a72a37f4d1d340fa137266be9c1ba4d96c87a0a57ac9ca193d62b301796c'
CORE='scripts/peer_comet_price_core_v1.py'
CORE_SHA='2e1a98a3be0500d6f78678be020536d7ae9ea20a2c17485a68cfef6277c915e9'
INTERFACE='research/peer-comet-price-interface-v1-root.json'
LIMITS=dict(rpc=55,transport_rpc=64,raw_bytes=196608,projection_bytes=6000,
  receipt_bytes=1536,request_seconds=10,run_seconds=120)
def run(plan_path,expected_plan_sha):
  with (ROOT/V2).open('rb') as f: raw=f.read(8171)
  if len(raw)!=8170 or hashlib.sha256(raw).hexdigest()!=V2_SHA:
    raise ValueError('v2 pin')
  ns=dict(__file__=str(ROOT/V2),__name__='verified_v2'); exec(raw,ns)
  v=SimpleNamespace(**ns); h=v.helper()
  raw=v.read(Path(plan_path),4096); v.need(h.sha(raw)==expected_plan_sha)
  plan=h.decode_json(raw)
  v.need(plan['schema']=='peer-comet-price-metadata-v1' and
    plan['status']=='frozen_metadata_probe' and plan['mode']=='all13_same_parent_prices' and
    plan['limits']==LIMITS)
  a=plan['authorization']
  v.need(type(a['coordinator_message']) is str and bool(a['coordinator_message']) and
    a['raw_bytes']==196608)
  pins=plan['pins']; v.need(set(pins)=={'runner','v2','helper','core','census','interface'})
  hashes={}
  def pin(role,path,cap,wanted=None):
    d=pins[role]; v.need(set(d)=={'path','bytes','sha256'} and d['path']==path)
    data=v.read(ROOT/path,cap)
    v.need(type(d['bytes']) is int and len(data)==d['bytes'] and h.sha(data)==d['sha256'])
    if wanted is not None: v.need(d['sha256']==wanted)
    hashes[role]=d['sha256']; return data
  pin('v2',V2,8170,V2_SHA)
  pin('helper','scripts/peer_comet_eligibility_v1.py',65536,v.HH)
  v.need(Path(__file__).resolve()==(ROOT/'scripts/peer_comet_price_runner_v1.py').resolve())
  pin('runner','scripts/peer_comet_price_runner_v1.py',4096)
  data=pin('core',CORE,4200,CORE_SHA); core={}; exec(data,core)
  c=h.decode_json(pin('census',v.CP,12368,v.CH))
  pin('interface',INTERFACE,2642,core['PINS']['interface'])
  v.need(core['PINS']=={k:hashes[k] for k in core['PINS']})
  v.census(h,c)
  for side in ('peer','root'):
    n=plan['retention'][side+'_raw_before']; g=plan['retention'][side+'_raw_grant']
    v.need(type(n) is int and type(g) is int and 0<=n and n+196608<=g)
  out=(ROOT/plan['out_directory']).resolve(); v.need(out.is_relative_to(ROOT)); out.mkdir()
  opener=v.u.build_opener(v.u.ProxyHandler({}),v.NoRedirect())
  opener.addheaders=[('User-Agent','rhhype-research/1.0'),('Accept','application/json')]
  wire=v.Wire(h,opener)
  try:
    def rpc(method,params):
      v.need(wire.calls<55); return wire(method,params)
    result=core['collect'](v,h,c,rpc); projection=h.encoded(result)
    receipt=h.encoded(dict(calls=wire.calls,planned_calls=55,raw_bytes=len(wire.raw),
      raw_sha256=h.sha(wire.raw),projection_sha256=h.sha(projection),
      plan_sha256=expected_plan_sha,pins=hashes,state_coherent=result['state_coherent'],
      elapsed_seconds=v.time.monotonic()-wire.start,error=result.get('error'),**v.FLAGS))
    files=[('raw.bin',wire.raw,196608),('projection.json',projection,6000),
      ('receipt.json',receipt,1536)]
    for name,data,cap in files: v.need(len(data)<=cap)
    for name,data,cap in files:
      with (out/name).open('xb') as f: f.write(data)
    return int(not result['state_coherent'])
  finally: wire.close()
if __name__=='__main__':
  if len(sys.argv)!=3: raise SystemExit('usage: frozen-plan.json expected-sha256')
  raise SystemExit(run(sys.argv[1],sys.argv[2]))
