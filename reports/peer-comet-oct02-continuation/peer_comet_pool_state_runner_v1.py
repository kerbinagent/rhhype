"""Pinned six-batch pool getter runner; requires a separately frozen manifest."""
import hashlib,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
SELF='scripts/peer_comet_pool_state_runner_v1.py'
PREFIX='reports/peer-comet-pool-state-v1'
PLAN='reports/experiment-storage/peer-comet-pool-state-v1-plan.json'
ENDPOINT='https://ethereum-rpc.publicnode.com'
FIXED={
'v2':('scripts/peer_comet_pool_discovery_v2.py',8170,'f7e0a72a37f4d1d340fa137266be9c1ba4d96c87a0a57ac9ca193d62b301796c'),
'helper':('scripts/peer_comet_eligibility_v1.py',30601,'879f58149d222bdfaa627d28b4335c2b01c72aba51a3771655f61764f473a908'),
'core':('scripts/peer_comet_pool_state_core_v1.py',7023,'01e76644b43ba475c1af222ba97ce4a71c793f4e28fbb617c6f26e7618020a5e'),
'census':('research/peer-comet-all13-inventory-v1-root.json',12368,'77ece9feac7ee802ad9ec675b1d058c015b19aa510f3a6a00783abe6a5f171c0'),
'direct':('reports/peer-comet-direct-explicit-client-v1/projection.json',7346,'a022db4917b47367299dc18328713def94205414503c72f52cb024267c06b26d'),
'weth':('reports/peer-comet-weth-explicit-client-v1/projection.json',7197,'ddb01ea9701b9ab82690fc92ca7a8448013d88098aff1c1f56f266e34246d6f7')}
def run(manifest_path,manifest_sha,batch):
 if type(batch) is not int or not 0<=batch<6: raise ValueError('batch')
 with (ROOT/FIXED['v2'][0]).open('rb') as f: data=f.read(8171)
 if len(data)!=8170 or hashlib.sha256(data).hexdigest()!=FIXED['v2'][2]: raise ValueError('v2 pin')
 vns=dict(__file__=str(ROOT/FIXED['v2'][0]),__name__='verified_v2'); exec(data,vns)
 v=SimpleNamespace(**vns); h=v.helper()
 v.need(Path(manifest_path).resolve()==(ROOT/PLAN).resolve())
 raw=v.read(Path(manifest_path),3500); v.need(h.sha(raw)==manifest_sha); p=h.decode_json(raw)
 v.need(p['schema']=='peer-comet-pool-state-v1' and p['status']=='frozen_metadata_probe' and
  p['mode']=='all59_fixed_parent_slot0' and p['endpoint']==ENDPOINT and p['output_prefix']==PREFIX)
 a=p['authorization']; v.need(type(a['coordinator_message']) is str and bool(a['coordinator_message'])
  and a['raw_total_bytes']==565248)
 pins=p['pins']; v.need(set(pins)==set(FIXED)|{'runner'}); loaded={}
 for role,(path,size,digest) in FIXED.items():
  v.need(pins[role]==dict(path=path,bytes=size,sha256=digest))
  b=v.read(ROOT/path,size); v.need(len(b)==size and h.sha(b)==digest); loaded[role]=b
 v.need(Path(__file__).resolve()==(ROOT/SELF).resolve())
 r=pins['runner']; v.need(set(r)=={'path','bytes','sha256'} and r['path']==SELF and type(r['bytes']) is int)
 b=v.read(ROOT/SELF,8192); v.need(len(b)==r['bytes'] and h.sha(b)==r['sha256'])
 n={}; exec(loaded['core'],n); core=SimpleNamespace(**n)
 v.need(p['limits']==dict(core.CAPS,raw_total_bytes=565248,planned_calls=[55,55,55,55,55,50]))
 parent,implementation,q=core.queue(v,h,*(h.decode_json(loaded[k]) for k in ('census','direct','weth')))
 v.need(p['queue']==dict(count=59,batch_size=10,batch_count=6,
  order='direct_then_weth_storage',sha256=h.sha(h.encoded(q))))
 for side in ('peer','root'):
  before=p['reservation'][side+'_raw_before']; grant=p['reservation'][side+'_raw_grant']
  v.need(type(before) is int and type(grant) is int and 0<=before and grant<=1048576 and before+565248<=grant)
 out=ROOT/PREFIX/('batch-'+str(batch)); v.need(out.resolve()==out); out.mkdir(parents=True)
 wire=core.Wire(h)
 try:
  result=core.collect(h,parent,implementation,q,batch,wire)
  files=[('raw.bin',wire.raw,94208),('projection.json',h.encoded(result),2560),
   ('receipt.json',core.receipt(h,result,wire,manifest_sha),768)]
  for name,data,cap in files: v.need(len(data)<=cap)
  for name,data,cap in files:
   with (out/name).open('xb') as f: f.write(data)
  return int(not result['state_coherent'])
 finally: wire.close()
if __name__=='__main__':
 if len(sys.argv)!=4 or sys.argv[3] not in ('0','1','2','3','4','5'):
  raise SystemExit('usage: frozen-manifest.json expected-sha256 batch0..5')
 raise SystemExit(run(sys.argv[1],sys.argv[2],int(sys.argv[3])))
