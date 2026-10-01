"""Offline reference eligibility diagnostics only; no counterfactual fill/P&L claims."""
import gzip,json,hashlib
from collections import defaultdict,deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run():
 out=ROOT/'reports/core-spot-perp-alts-retry';raw=out/'events.jsonl.gz';s=json.loads((out/'summary.json').read_text());assert s['error'] is None and s['counters']['runtime_completed']==1
 history=defaultdict(lambda:deque(maxlen=125));counts=defaultdict(lambda:defaultdict(int));maximum=defaultdict(int)
 for line in gzip.decompress(raw.read_bytes()).splitlines():
  r=json.loads(line)
  if r['kind']=='invalid':continue # This completed capture only has shutdown invalidations after its samples.
  if r['kind']!='sample':continue
  a=r['asset'];t=r['t'];history[a].append((t,r['basis_bps']));counts[a]['sample_count']+=1
  prior=[x for x in history[a] if t-122<=x[0]<=t-2];maximum[a]=max(maximum[a],len(prior))
  if not 122<=t-s['started_at']<480:continue
  counts[a]['sample_callbacks_inside_admission_time']+=1
  span=bool(prior) and prior[-1][0]-prior[0][0]>=89
  for threshold in (30,60,90):
   if span and len(prior)>=threshold:counts[a][f'reference_eligible_at_count_{threshold}']+=1
 result={'schema':'reference-coverage-only-v1','raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'assets':{a:{**counts[a],'maximum_retained_reference_count':maximum[a]} for a in counts},'scope':'At retained fresh sample callbacks only; past122s window ending2s before observation and89s minimum span. Counts30/60/90 compared solely for reference availability. Does not evaluate forecasts, trading eligibility, book callbacks not sampled, or hypothetical fills/P&L. Execution freshness and source advancement are unchanged.'}
 data=(json.dumps(result,indent=2)+'\n').encode();assert len(data)<4096
 with (out/'reference-coverage.json').open('xb') as f:f.write(data)
 print(data.decode())
if __name__=='__main__':run()
