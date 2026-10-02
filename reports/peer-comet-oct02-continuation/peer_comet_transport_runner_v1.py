"""Bounded explicit-client follow-up; preserves previous failed experiments."""
import hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CORE='f7e0a72a37f4d1d340fa137266be9c1ba4d96c87a0a57ac9ca193d62b301796c'
HEADERS=[('User-Agent','rhhype-research/1.0'),('Accept','application/json')]
def main():
  if len(sys.argv)!=3: raise ValueError('plan and hash required')
  cp=ROOT/'scripts/peer_comet_pool_discovery_v2.py'
  with cp.open('rb') as f: data=f.read(8193)
  if len(data)!=8170 or hashlib.sha256(data).hexdigest()!=CORE: raise ValueError('core pin')
  v=dict(__file__=str(cp),__name__='pinned_core'); exec(compile(data,str(cp),'exec'),v)
  h=v['helper'](); need=v['need']; read=v['read']
  data=read(Path(sys.argv[1]),8192); need(h.sha(data)==sys.argv[2]); p=h.decode_json(data)
  digest=h.sha(read(Path(__file__),4096))
  need(p['runner_sha256']==digest and p['core_sha256']==CORE and p['mode'] in ('access','direct','weth'))
  need(p['headers']==dict(HEADERS))
  target=(ROOT/p['out_directory']).resolve(); need(target.is_relative_to(ROOT)); target.mkdir()
  u=v['u']; opener=u.build_opener(u.ProxyHandler({}),v['NoRedirect']()); opener.addheaders=HEADERS
  wire=v['Wire'](h,opener)
  try:
    if p['mode']=='access':
      out=dict(status='UNKNOWN',state_coherent=False,checks={},**v['FLAGS'])
      try:
        need(h.quantity(wire('eth_chainId',[]))==1)
        out['status']='access_confirmed'; out['checks']['chain']=True
      except Exception as e: out['error']=type(e).__name__+':'+ascii(e)[:120]
    else:
      raw=read(ROOT/v['CP'],12368); need(len(raw)==12368 and h.sha(raw)==v['CH'])
      out=v['collect'](h,h.decode_json(raw),p['mode'],wire)
    raw=wire.raw
    receipt=dict(calls=wire.calls,bytes=len(raw),trace_sha256=h.sha(raw),
      elapsed=v['time'].monotonic()-wire.start,status=out['status'],error=out.get('error'),
      runner_sha256=digest,core_sha256=CORE,helper_sha256=v['HH'],
      census_sha256=None if p['mode']=='access' else v['CH'],plan_sha256=sys.argv[2],**v['FLAGS'])
    cap=66560 if p['mode']=='access' else 196608
    files=[('raw.bin',raw,cap),('projection.json',h.encoded(out),10000),('receipt.json',h.encoded(receipt),2048)]
    for name,b,limit in files: need(len(b)<=limit)
    for name,b,limit in files:
      with (target/name).open('xb') as f: f.write(b)
    print(h.encoded(dict(calls=wire.calls,status=out['status'])).decode())
    return int(out['status']=='UNKNOWN')
  finally: wire.close()
if __name__=='__main__': raise SystemExit(main())
