"""Independently rebuild selected closing references and quote caps from raw books."""
import collections,gzip,json,sys
from decimal import Decimal as D,ROUND_FLOOR
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_lit_events import iter_events
from scripts.core_passive_lit_capture import OUT,sha
R=ROOT/'reports/core-passive-fair-value';NS=10**9

def walk(levels,qty):
 left=qty;value=D(0)
 for p,q in levels:
  take=min(left,D(str(q)));value+=take*D(str(p));left-=take
  if not left:break
 assert not left
 return value

def run():
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert not s['error'] and s['completion_marker_received']
 rows=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 expected={};admissions={};fills=collections.defaultdict(list)
 for row in rows:
  if row['event']=='fair_value_admission':
   admissions[row['ns']]=row
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
  assert all(0<=now-b['source_ns']<=2*NS for b in (m,h));assert abs(m['source_ns']-h['source_ns'])<=250_000_000
  if now in expected:
   q=(D(100)/max(mb,ha)/D('.01')).to_integral_value(rounding=ROUND_FLOOR)*D('.01')
   ref=(walk(m['bids'],q)-walk(h['asks'],q))/q/mid*10000
   assert abs(ref-expected[now])<D('1e-20'),(now,ref,expected[now]);checked[now]=ref
  if now in admissions:
   a=admissions[now];q=(D(100)/max(mb,hb)/D('.01')).to_integral_value(rounding=ROUND_FLOOR)*D('.01');assert q==D(a['quantity'])
   center=D(median([checked[t] for t,v in a['reference_rows']]))
   hv=walk(h['bids'],q);unit=max(mb,hv/q);capcost=2*unit*D('.05')*D(10)/D(365*86400)
   assert D(a['fee_unit'])==0 # Fresh frozen metadata Standard fees are zero.
   price=(min(mb,hv/q+center*mid/10000-unit*D('.0006')-capcost)/D('.0001')).to_integral_value(rounding=ROUND_FLOOR)*D('.0001')
   assert price==D(a['price']) and hv==D(a['hedge_entry_value']) and mid==D(a['maker_mid']) and capcost==D(a['capital_unit'])
   assert price>=D(str(m['bids'][-1][0]));nquotes+=1
 assert len(checked)==len(expected) and nquotes==len(admissions)
 out={'audit':'passed','raw_reference_values_checked':len(checked),'raw_quote_caps_checked':nquotes,'summary_sha256':sha(R/'summary.json.gz'),'checks':'Raw current and retained preceding books, branch-local taker depth depletion, reference VWAPs, reference source freshness/skew, quantities, closing medians, hedge VWAP, zero-fee/capital terms and downward-rounded6bp price cap.','limitations':'Model-driven cancellations inherit frozen lifecycle tests and are not separately reconstructed here. Public queue allocation and execution ACKs remain conditional.'}
 (R/'raw-reference-audit.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':run()
