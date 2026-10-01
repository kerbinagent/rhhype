"""Independently check every quote gate/offset against branch-local remaining public depth."""
import collections,copy,datetime,gzip,json,sys
from decimal import Decimal as D,ROUND_FLOOR
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_maker_lit_events import iter_events
from scripts.core_maker_lit_capture import OUT,sha
R=ROOT/'reports/core-maker-lit-ioc-coordinator';NS=10**9
s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert not s['error'] and s['completion_marker_received']
trace=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()];bytime=collections.defaultdict(list)
for r in trace:bytime[r['ns']].append(r)
manifest=json.loads((OUT/'manifest.json').read_bytes());start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
state={label:{} for label in s['branches']};counts=collections.Counter();depleted=0
for event in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],hedge_venue='lighter',max_raw_bytes=3276800):
 now=event.get('received_ns');venue=event.get('venue')
 for label,books in state.items():
  if event['type']=='book':books[venue]=copy.deepcopy(event)
  elif event['type']=='invalidate':books.pop(venue,None)
 for r in bytime.pop(now,[]):
  label=r['branch'];books=state[label]
  if r['event']=='fill' and not r['maker']:
   book=books[r['source_venue']];side='asks' if r['side']=='buy' else 'bids';left=D(r['qty']);value=D(0);remaining=[]
   for p,q in book[side]:
    p,q=D(str(p)),D(str(q));take=min(q,left);left-=take;value+=take*p;q-=take
    if q:remaining.append([p,q])
   assert left==0 and abs(value-D(r['value']))<D('.00000001');book[side]=remaining;depleted+=1
  if r['event']=='quote_requested':
   assert 10*NS<=now-start<480*NS
   assert now//(3600*NS)==(now+120*NS)//(3600*NS)
   counts[label]+=1;assert counts[label]<=100
   maker,hedge=books['rh_lighter'],books['lighter']
   offset=D(label.split('-')[1].replace('bp',''));tick=D('.0001');step=D('.01')
   price=(D(str(maker['bids'][0][0]))*(1-offset/10000)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
   qty=(D(100)/max(price,D(str(hedge['bids'][0][0])))/step).to_integral_value(rounding=ROUND_FLOOR)*step
   assert D(r['price'])==price and D(r['qty'])==qty,(label,now,r['price'],str(price))
   assert price>=D(str(maker['bids'][-1][0])) and r['due_ns']-now==400_000_000
assert all(counts[label]==b['counts'].get('quote_requested',0) for label,b in s['branches'].items())
result={'audit':'passed','quotes_checked':dict(counts),'taker_depth_depletions':depleted,'checks':'Every actual quote time inside10..480s,100cap,hourguard,exact5/10bp currentbook offset and commonlot quantity; branch-local depth subtracts preceding takerfills before quote decisions. Freshness is checked by frozen engine and main audit.','summary_sha256':sha(R/'summary.json.gz')}
(R/'quote-gate-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
