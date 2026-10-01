"""Supplemental first eligible maker activation/cancel and actual entry-budget checks."""
import collections,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_capture import OUT,HARD_BYTES,sha
from scripts.core_spot_passive_events import iter_events
from decimal import Decimal as D
R=ROOT/'reports/core-spot-passive/result';NS=10**9

def run():
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert s['error'] is None and s['completion_marker_received']
 rows=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 clocks=collections.defaultdict(list);counts=collections.Counter();budgets=[]
 for e in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],max_raw_bytes=HARD_BYTES):
  if e['type']=='book' and e['asset'].endswith('_spot'):
   clocks[e['asset'].removesuffix('_spot')].append((e['received_ns'],e['source_ns'],e['generation']))
 for asset,b in s['branches'].items():
  rr=[r for r in rows if r['branch']==asset];starts=[i for i,r in enumerate(rr) if r['event']=='quote_requested']
  for number,idx in enumerate(starts):
   scope=rr[idx:starts[number+1] if number+1<len(starts) else len(rr)];q=scope[0]
   for event,request in [('activated',q),('cancel_effective',next((r for r in scope if r['event']=='cancel_requested'),None))]:
    row=next((r for r in scope if r['event']==event),None)
    if row is None:continue
    assert request is not None;due=request['due_ns'];eligible=[t for t,src,g in clocks[asset] if t>=due and src>=due and 0<=t-src<=2*NS]
    assert eligible and row['ns']==eligible[0],(asset,event,row['ns'],eligible[:1]);counts[event]+=1
   vals={role:sum((D(r['value']) for r in scope if r['event']=='fill' and r['venue']==role and r['side']==side),D(0)) for role,side in [('maker','buy'),('hedge','sell')]}
   budgets.append({'asset':asset,'attempt':number+1,'actual_entry_spot':str(vals['maker']),'actual_entry_perp':str(vals['hedge']),'within_100_per_leg':max(vals.values())<=100})
 out={'audit':'passed' if all(x['within_100_per_leg'] for x in budgets) else 'actual_entry_budget_scope_failed','checks':dict(counts),'actual_entry_budgets':budgets,'summary_sha256':sha(R/'summary.json.gz'),'note':'Supplementary source prepared during capture without reading economics. Original engine and protocol unchanged. If delayed hedge repricing crosses100 actual entry notional, retain the outcome but exclude it from a100-per-leg profit claim.'}
 with (R/'boundary-audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':run()
