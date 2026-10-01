"""Post-endpoint diagnostic of original quote economics at activation; no alternate fills."""
import collections,gzip,json,sys
from decimal import Decimal as D
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_spot_passive_inside as setup
from scripts.audit_core_spot_passive_inside import fresh,walk,d
setup.configure()
rows=[json.loads(x) for x in gzip.decompress((setup.R/'audit.jsonl.gz').read_bytes()).splitlines()]
quotes=[];active=None
for row in rows:
 if row['event']=='quote_requested':active=dict(decided_ns=row['ns'],price=row['price'],qty=row['qty']);quotes.append(active)
 elif row['event']=='activated':active.update(activation_ns=row['ns'],ahead_same=row['ahead_same'],ahead_better=row['ahead_better'])
 elif row['event']=='cancel_requested':active['cancel_due_ns']=row['due_ns']
targets={q['activation_ns']:q for q in quotes};books={};hist=collections.deque(maxlen=125);last=None;NS=10**9;trades=[];end=None
for e in setup.events.iter_events(setup.OUT,expected_manifest_sha256=setup.capture.sha(setup.OUT/'manifest.json'),max_raw_bytes=setup.HARD_BYTES):
 if e['type']=='end':end=e;continue
 if not e.get('asset'):continue
 kind=e['asset'].rsplit('_',1)[1];now=e['received_ns']
 if e['type']=='invalidate':books.pop(kind,None);hist.clear();last=None;continue
 if e['type']=='trade':trades.append(e);continue
 if e['type']!='book':continue
 books[kind]=e
 if not fresh(books,now):continue
 s,p=books['spot'],books['perp'];sm=sum(d(s[k][0][0]) for k in ('bids','asks'))/2;pm=sum(d(p[k][0][0]) for k in ('bids','asks'))/2;basis=(pm/sm-1)*10000
 if last is None or now-last>=NS:hist.append((now,basis));last=now
 if now not in targets or kind!='spot':continue
 q=targets[now];refs=[v for t,v in hist if now-122*NS<=t<=now-2*NS];assert len(refs)>=60
 ref=D(median(refs));qty=d(q['qty']);price=d(q['price']);vals=[]
 for levels in (p['bids'],s['bids'],p['asks']):got,value=walk(levels,qty);assert got==qty;vals.append(value)
 he,se,pe=vals;capital=(qty*price+he)*D('.05')*10/D(365*86400)
 forecast=he-qty*price+se-pe+qty*(pm-sm-ref*sm/10000)-capital
 q.update(activation_source_ns=e['source_ns'],activation_delay_ms=D(now-q['decided_ns'])/10**6,basis_bps=basis,reference_bps=ref,excursion_bps=basis-ref,forecast_at_original_quote_ignoring_excursion_gate=forecast,spot_bid=s['bids'][0][0],spot_ask=s['asks'][0][0],perp_bid=p['bids'][0][0],perp_ask=p['asks'][0][0])
assert end
for q in quotes:
 eligible=[t for t in trades if q['activation_ns']<=t['received_ns'] and q['activation_source_ns']<=t['source_ns']<q['cancel_due_ns'] and t['side']=='sell' and d(t['price'])<=d(q['price'])]
 q['eligible_sell_prints']=len(eligible);q['eligible_sell_quantity']=sum((d(t['qty']) for t in eligible),D(0))
out=dict(diagnostic='completed_capture_activation_only',manifest_sha256=setup.capture.sha(setup.OUT/'manifest.json'),quotes=quotes,ordinary_live_prints=len(trades),ordinary_live_value=sum((d(t['qty'])*d(t['price']) for t in trades),D(0)),scope='Recompute original admitted price/quantity forecast at activation without the5bp excursion gate, solely to diagnose cancellation. Does not change quote policy, attribute alternate fills or estimate alternate P&L.')
with (setup.R.parent/'activation-diagnostic.json').open('x') as f:json.dump(out,f,indent=2,default=str);f.write('\n')
print(json.dumps(out,indent=2,default=str))
