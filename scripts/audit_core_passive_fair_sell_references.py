"""Independently rebuild fair SELL references, quantities and floors from raw books."""
import collections,gzip,json,sys
from decimal import Decimal as D,ROUND_FLOOR,ROUND_CEILING
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_lit_events import iter_events
from scripts.core_passive_lit_capture import OUT,sha
R=ROOT/'reports/core-passive-fair-sell';NS=10**9

def walk(levels,qty):
 left=qty;value=D(0)
 for p,q in levels:
  take=min(left,D(str(q)));value+=take*D(str(p));left-=take
  if not left:break
 assert not left
 return value

def run():
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert not s['error'] and s['completion_marker_received']
 plan=ROOT/'reports/experiment-storage/core-passive-fair-sell-freeze-v1.json';assert sha(plan)==s['plan_sha256']
 for pin in json.loads(plan.read_text())['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 rows=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 quotes=[r for r in rows if r['event']=='quote_requested'];ff=[r for r in rows if r['event']=='fair_value_admission'];assert len(quotes)==len(ff)<=100
 import datetime
 start=int(datetime.datetime.fromisoformat(json.loads((OUT/'manifest.json').read_text())['started_utc']).timestamp()*NS)
 for q,f in zip(quotes,ff):
  assert q['ns']==f['ns'] and q['price']==f['price'] and q['qty']==f['quantity'] and q['due_ns']-q['ns']==100_000_000
  now=q['ns'];assert 10*NS<=now-start<480*NS and now//(3600*NS)==(now+120*NS)//(3600*NS)
  refs=f['reference_rows'];assert len(refs)>=90 and refs[-1][0]-refs[0][0]>=89*NS
  assert refs[0][0]>=now-120*NS and refs[-1][0]<=now-2*NS and all(b[0]-a[0]>=NS for a,b in zip(refs,refs[1:]))
 expected={};admissions={};fills=collections.defaultdict(list)
 for row in rows:
  if row['event']=='fair_value_admission':
   assert row['ns'] not in admissions;admissions[row['ns']]=row
   for t,v in row['reference_rows']:
    if t in expected:assert expected[t]==D(v)
    expected[t]=D(v)
  if row['event']=='fill' and not row['maker']:fills[row['ns']].append(row)
 books={};checked={};nquotes=0
 for e in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],hedge_venue='rh_lighter',max_raw_bytes=3276800):
  now=e.get('received_ns')
  if e['type']=='invalidate':books.pop(e.get('venue'),None)
  if e['type']=='book':books[e['venue']]=dict(e)
  for f in fills.pop(now,[]):
   b=books[f['source_venue']];side='bids' if f['side']=='sell' else 'asks';left=D(f['qty']);remaining=[]
   for p,q in b[side]:
    p,q=D(str(p)),D(str(q));take=min(left,q);left-=take;q-=take
    if q:remaining.append([p,q])
   assert left==0;b[side]=remaining
  if now not in expected and now not in admissions:continue
  assert e['type']=='book'
  m,h=books['lighter'],books['rh_lighter'];mb=D(str(m['bids'][0][0]));ma=D(str(m['asks'][0][0]));hb=D(str(h['bids'][0][0]));ha=D(str(h['asks'][0][0]));mid=(mb+ma)/2
  assert all(0<=now-b['source_ns']<=2*NS and 0<=now-b['received_ns']<=2*NS for b in (m,h));assert abs(m['source_ns']-h['source_ns'])<=250_000_000 and abs(m['received_ns']-h['received_ns'])<=250_000_000
  def floorq(x):return (x/D('.01')).to_integral_value(rounding=ROUND_FLOOR)*D('.01')
  if now in expected:
   q=floorq(D(100)/max(ma,hb));ref=(walk(h['bids'],q)-walk(m['asks'],q))/q/mid*10000
   assert abs(ref-expected[now])<D('1e-20'),(now,ref,expected[now]);checked[now]=ref
  if now in admissions:
   a=admissions[now];center=D(median([checked[t] for t,v in a['reference_rows']]))
   assert center==D(a['median_close_bps']);q=floorq(D(100)/max(ma,ha))
   for iteration in range(16):
    assert q>0;hv=walk(h['asks'],q);unit=max(ma,hv/q);capcost=2*unit*D('.05')*D(10)/D(365*86400)
    assert D(a['fee_unit'])==0
    price=(max(ma,hv/q-center*mid/10000+unit*D('.0006')+capcost)/D('.0001')).to_integral_value(rounding=ROUND_CEILING)*D('.0001')
    nextq=min(q,floorq(D(100)/max(price,hv/q)))
    if nextq==q:break
    q=nextq
   else:raise AssertionError('iteration_cap')
   assert q==D(a['quantity']) and iteration+1==a['quantity_iterations']
   assert price==D(a['price']) and hv==D(a['hedge_entry_value']) and mid==D(a['maker_mid']) and capcost==D(a['capital_unit'])
   assert price<=D(str(m['asks'][-1][0])) and q*price<=100 and hv<=100
   forecast=q*(price-hv/q+center*mid/10000-capcost)
   assert abs(forecast-D(a['forecast_cash']))<D('1e-20') and forecast>=q*unit*D('.0006')
   nquotes+=1
 assert len(checked)==len(expected) and nquotes==len(admissions)
 out={'audit':'passed','raw_reference_values_checked':len(checked),'raw_quote_floors_checked':nquotes,'summary_sha256':sha(R/'summary.json.gz'),'checks':'Source pins, quote identity and timing gates; raw current/preceding books with branch-local taker depletion; reference timing/cadence/VWAP/freshness/skew; closing median; independent16step monotone quantity and upward tick price solution;100entrybudget/zero fees/capital/6bp forecast.','limitations':'Model-driven cancellations inherit frozen lifecycle tests and are not separately reconstructed here. Public queue allocation and private ACK/fill outcomes remain conditional.'}
 (R/'raw-reference-audit.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':run()
