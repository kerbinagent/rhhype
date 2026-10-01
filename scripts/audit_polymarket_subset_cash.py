"""Independent Decimal replay of every frozen selected-NO prefix quote."""
import gzip,hashlib,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/polymarket-subset-cash'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def walk(rows,qty):
 left=qty;value=D(0)
 for price,size in sorted(rows):
  take=min(left,size);value+=take*price;left-=take
  if left==0:return value
 raise AssertionError('insufficient depth')
def parse(x):return json.loads(x) if isinstance(x,str) else x
s=json.loads(gzip.decompress((OUT/'summary.json.gz').read_bytes()));assert not s['errors']
events={};snapshots={}
for r in s['requests']:
 p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 raw=json.loads(gzip.decompress(p.read_bytes()));assert raw['status']==200 and not raw['truncated']
 data=json.loads(raw['body'])
 if p.name.startswith('catalog'):
  for e in data:events[str(e['id'])]=e
 else:snapshots[raw['received']]={b['asset_id']:b for b in data}
for b in s['selected']:
 e=events[str(b['event_id'])];eligible=[]
 for m in e['markets']:
  title=m.get('groupItemTitle','').strip()
  if not title or any(v in title.lower() for v in ('other','placeholder','unnamed','person ')):continue
  if not all(m.get(k) for k in ('active','acceptingOrders','enableOrderBook','negRisk')) or m.get('closed'):continue
  if m.get('negRiskMarketID')!=e.get('negRiskMarketID'):continue
  oo,pp,tt=(parse(m[k]) for k in ('outcomes','outcomePrices','clobTokenIds'))
  assert len(oo)==len(pp)==len(tt)==2 and set(oo)=={'Yes','No'}
  eligible.append((D(pp[oo.index('Yes')]),str(m['id']),str(tt[oo.index('No')]),m['conditionId']))
 eligible=sorted(eligible,key=lambda x:(-x[0],x[1]))[:20]
 assert b['tokens']==[x[2] for x in eligible] and b['conditions']==[x[3] for x in eligible]
byevent={str(b['event_id']):b for b in s['selected']};checked=0;positive=0;min_age=None;max_age=0;best=[]
for snap in s['snapshots']:
 index=snapshots[snap['received']]
 for r in snap['baskets']:
  b=byevent[str(r['event_id'])];k=r['subset_count'];assert r['tokens']==b['tokens'][:k]
  books=[index[t] for t in r['tokens']];levels=[]
  for i,book in enumerate(books):
   assert book['market']==b['conditions'][i] and book['neg_risk']
   levels.append([(D(v['price']),D(v['size'])) for v in book['asks'] if D(v['size'])>0])
   age=D(str(snap['received']))-D(book['timestamp'])/1000
   min_age=age if min_age is None else min(min_age,age);max_age=max(max_age,age)
  assert r['status']=='quote_screen_only'
  minimum=max(D(str(v['min_order_size'])) for v in books)
  top=sum(min(p for p,q in ll) for ll in levels);assert top==D(r['best_ask_sum'])
  for prefix in ('max_budget','best'):
   q=D(r[prefix+'_quantity']);assert q>=minimum and q*1000000==(q*1000000).to_integral_value()
   cost=sum(walk(ll,q) for ll in levels);assert cost==D(r[prefix+'_cost']) and cost<=100
   cash=q*(k-1);assert cash-cost==D(r[prefix+'_gross_quote_surplus'])
  # Convex asks: if even the marginal best-price basket is costly, every size loses.
  assert top>=k-1 and not r['positive_candidate']
  positive+=bool(r['positive_candidate']);checked+=1
  best.append({'event':r['title'],'k':k,'gross_at_max_budget':r['max_budget_gross_quote_surplus'],'gross_at_best_size':r['best_gross_quote_surplus'],'ask_sum':str(top),'cash_per_share':k-1})
assert checked==114
out={'audit':'passed','all_quote_rows_checked':checked,'positive_gross_cash_candidates':positive,'book_age_seconds':[str(min_age),str(max_age)],'closest_budget_quotes':sorted(best,key=lambda x:D(x['gross_at_max_budget']),reverse=True)[:6],'summary_sha256':sha(OUT/'summary.json.gz'),'limitations':'Optimistic zero conversion/trading fees and gas. Selected conditionIDs and tokenIDs verified against public metadata only. No onchain convertibility or actual fills; complementYES retained atzero valuation, not a completedcycle.'}
(OUT/'audit.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
