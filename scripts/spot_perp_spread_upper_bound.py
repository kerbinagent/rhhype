"""Optimistic unit forecast bounds at retained samples, not hypothetical trades."""
import gzip,json,hashlib
from collections import defaultdict,deque
from decimal import Decimal as D
from statistics import median
from pathlib import Path
R=Path(__file__).resolve().parents[1]/'reports/core-spot-perp-reference-count'
def run():
 s=json.loads((R/'summary.json').read_text());assert not s['error'] and s['counters']['runtime_completed']==1
 rows=[json.loads(l) for l in gzip.decompress((R/'events.jsonl.gz').read_bytes()).splitlines()];assert all(r['kind'] in ('sample','invalid') for r in rows)
 h=defaultdict(lambda:deque(maxlen=125));stats=defaultdict(lambda:{'eligible_samples':0,'excursion_at_least_5bp':0,'positive_optimistic_bound':0,'best_case':None});last_sample=max(r['t'] for r in rows if r['kind']=='sample')
 for r in rows:
  if r['kind']=='invalid':assert r['book']['received']>=last_sample;continue
  t=r['t'];asset=r['asset'];h[asset].append((t,D(str(r['basis_bps']))));p=[v for at,v in h[asset] if t-122<=at<=t-2];times=[at for at,v in h[asset] if t-122<=at<=t-2]
  if not 122<=t-s['started_at']<480 or len(p)<60 or times[-1]-times[0]<89:continue
  a,b=r['books'];ab,aa,bb,ba=[D(str(v)) for v in (a['bids'][0][0],a['asks'][0][0],b['bids'][0][0],b['asks'][0][0])];am=(aa+ab)/2;bm=(ba+bb)/2
  expected=D(median(p))*am/10000;excursion=(bm-am-expected)/am*10000
  x=stats[asset];x['eligible_samples']+=1
  if excursion<5:continue
  x['excursion_at_least_5bp']+=1
  gross=bb-aa+ab-ba+bm-am-expected
  # Full-depth gross cannot exceed best prices. Actual hurdle is at least spot ask*1bp.
  margin=(gross-aa/10000)/am*10000
  if margin>0:x['positive_optimistic_bound']+=1
  case={'timestamp':t,'excursion_bps':str(excursion),'spot_spread_bps':str((aa-ab)/am*10000),'perp_spread_bps_on_spot_mid':str((ba-bb)/am*10000),'forecast_margin_upper_bound_bps':str(margin),'passive_spot_bid_saving_bps':str((aa-ab)/am*10000)}
  if x['best_case'] is None or margin>D(x['best_case']['forecast_margin_upper_bound_bps']):x['best_case']=case
 result={'schema':'spot-perp-unit-forecast-upper-bound-v1','raw_sha256':hashlib.sha256((R/'events.jsonl.gz').read_bytes()).hexdigest(),'minimum_reference_count':60,'assets':dict(stats),'scope':'Retained fresh sample callbacks inside122..480s only. Optimistic current4bestprices, no depth impact/fees/capital, subtract minimumpossible1bp hurdle using spot ask. This upper-bounds per-unit forecast margin at these samples, not all decision callbacks. Passive-bid saving is an arithmetic spread difference, not evidence of a fill or realized return. No execution rules or results changed.'}
 body=(json.dumps(result,indent=2)+'\n').encode();assert len(body)<8192
 with (R/'spread-upper-bound.json').open('xb') as f:f.write(body)
 print(body.decode())
if __name__=='__main__':run()
