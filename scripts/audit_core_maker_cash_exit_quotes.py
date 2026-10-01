"""Independently check every quote gate/offset against branch-local remaining public depth."""
import collections,copy,datetime,gzip,json,sys
from decimal import Decimal as D,ROUND_FLOOR,ROUND_CEILING
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_lit_events import iter_events
from scripts.core_passive_lit_capture import OUT,sha
R=ROOT/'reports/core-maker-cash-exit';NS=10**9
s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert not s['error'] and s['completion_marker_received']
trace=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()];bytime=collections.defaultdict(list)
for r in trace:bytime[r['ns']].append(r)
manifest=json.loads((OUT/'manifest.json').read_bytes());start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
state={label:{} for label in s['branches']};counts=collections.Counter();depleted=0;quotes={};activations=0;marks=0
ledger={label:dict(cash=D(0),capital=D(0),last=None,pos={v:D(0) for v in ('lighter','rh_lighter')},lots={v:[] for v in ('lighter','rh_lighter')}) for label in s['branches']}
for event in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],hedge_venue='rh_lighter',max_raw_bytes=3276800):
 now=event.get('received_ns');venue=event.get('venue')
 for label,books in state.items():
  if event['type']=='book':books[venue]=copy.deepcopy(event)
  elif event['type']=='invalidate':books.pop(venue,None)
 for r in bytime.pop(now,[]):
  label=r['branch'];books=state[label];account=ledger[label];buy_maker=label.endswith('-buy')
  if r['event'] in ('fill','quote_requested','take_profit_mark'):
   if account['last'] is not None:
    base=sum((q*p for lots in account['lots'].values() for q,p in lots),D(0))
    account['capital']+=base*D(now-account['last'])*D('.05')/D(365*86400*NS)
   account['last']=now
  if r['event']=='fill':
   source=r['source_venue'];qty=D(r['qty']);value=D(r['value']);signed=qty if r['side']=='buy' else -qty;old=account['pos'][source];left=qty
   if old and (old>0)!=(signed>0):
    while left and account['lots'][source]:
     take=min(left,account['lots'][source][0][0]);left-=take;account['lots'][source][0][0]-=take
     if not account['lots'][source][0][0]:account['lots'][source].pop(0)
   if left:account['lots'][source].append([left,value/qty])
   account['pos'][source]+=signed;account['cash']+=value if signed<0 else -value
  if r['event']=='take_profit_mark':
   mark=account['cash']-account['start_cash']-account['capital']+account['start_capital']
   for source,position in account['pos'].items():
    book=books[source];assert 0<=now-book['source_ns']<=2*NS and 0<=now-book['received_ns']<=2*NS
    left=abs(position);value=D(0)
    for price,size in book['bids' if position>0 else 'asks']:
     take=min(left,D(str(size)));value+=take*D(str(price));left-=take
     if not left:break
    assert not left;mark+=value if position>0 else -value
   assert abs(mark-D(r['projected_net']))<D('.00000001') and mark>=D('.01')-D('.00000001');marks+=1
  if r['event']=='fill' and not r['maker']:
   book=books[r['source_venue']];side='asks' if r['side']=='buy' else 'bids';left=D(r['qty']);value=D(0);remaining=[]
   for p,q in book[side]:
    p,q=D(str(p)),D(str(q));take=min(q,left);left-=take;value+=take*p;q-=take
    if q:remaining.append([p,q])
   assert left==0 and abs(value-D(r['value']))<D('.00000001');book[side]=remaining;depleted+=1
  if r['event']=='activated':
   q=quotes[label];maker=books['lighter'];assert maker['source_ns']>=q['due_ns']
   assert D(q['price'])<D(str(maker['asks'][0][0])) if buy_maker else D(q['price'])>D(str(maker['bids'][0][0]))
   assert D(r['ahead_same'])==sum((D(str(size)) for price,size in maker['bids' if buy_maker else 'asks'] if D(str(price))==D(q['price'])),D(0));activations+=1
  if r['event']=='quote_requested':
   quotes[label]=r;account['start_cash']=account['cash'];account['start_capital']=account['capital']
   assert 10*NS<=now-start<480*NS
   assert now//(3600*NS)==(now+120*NS)//(3600*NS)
   counts[label]+=1;assert counts[label]<=100
   maker,hedge=books['lighter'],books['rh_lighter']
   assert all(0<=now-x['received_ns']<=2*NS and 0<=now-x['source_ns']<=2*NS for x in (maker,hedge))
   assert abs(maker['received_ns']-hedge['received_ns'])<=250_000_000 and abs(maker['source_ns']-hedge['source_ns'])<=250_000_000
   offset=D(label.split('-')[1].replace('bp',''));tick=D('.0001');step=D('.01')
   side='bids' if buy_maker else 'asks'
   price=(D(str(maker[side][0][0]))*(1+(-offset if buy_maker else offset)/10000)/tick).to_integral_value(rounding=ROUND_FLOOR if buy_maker else ROUND_CEILING)*tick
   qty=(D(100)/max(price,D(str(hedge[side][0][0])))/step).to_integral_value(rounding=ROUND_FLOOR)*step
   assert D(r['price'])==price and D(r['qty'])==qty,(label,now,r['price'],str(price))
   assert price>=D(str(maker[side][-1][0])) if buy_maker else price<=D(str(maker[side][-1][0]))
   assert r['due_ns']-now==100_000_000
assert all(counts[label]==b['counts'].get('quote_requested',0) for label,b in s['branches'].items())
result={'audit':'passed','quotes_checked':dict(counts),'taker_depth_depletions':depleted,'activation_queue_snapshots_checked':activations,'cash_take_profit_marks_checked':marks,'checks':'Every actual quote time inside10..480s,100cap,hourguard,exact10bp currentbook offset, 100ms activation and commonlot quantity; branch-local depth subtracts preceding takerfills before quote decisions. Cash-only profit request marks independently rebuilt from remaining executable books, FIFO capital and episode cash; no reserve subtraction. Freshness and pair skew checked independently; every activation checks source advancement, post-only price and queue ahead at the quote.','summary_sha256':sha(R/'summary.json.gz')}
(R/'quote-gate-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
