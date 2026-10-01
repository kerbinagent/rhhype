"""Independent raw-book/reference/queue checks and Decimal spot/perp cash reconciliation."""
import collections,copy,gzip,json,math,sys,datetime
from decimal import Decimal as D,ROUND_FLOOR
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_capture import OUT,PLAN,HARD_BYTES,sha
from scripts.core_spot_passive_events import iter_events
R=ROOT/'reports/core-spot-passive/result';NS=10**9

def d(x):return D(str(x))
def eq(a,b):assert abs(d(a)-d(b))<D('0.00000001'),(a,b)
def walk(levels,qty,limit=None,side='sell',deplete=False):
 left=qty;value=D(0)
 for level in levels:
  p,q=map(d,level)
  if limit is not None and ((side=='sell' and p<limit) or (side=='buy' and p>limit)):break
  take=min(left,q);value+=take*p;left-=take
  if deplete:level[1]=q-take
  if not left:break
 if deplete:levels[:]=[level for level in levels if d(level[1])>0]
 return qty-left,value

def fresh(books,now):
 if set(books)!={'spot','perp'} or any(not b['bids'] or not b['asks'] for b in books.values()):return False
 a,b=books.values()
 return all(0<=now-v[k]<=2*NS for v in (a,b) for k in ('received_ns','source_ns')) and all(abs(a[k]-b[k])<=250_000_000 for k in ('received_ns','source_ns'))

def run():
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert not s['error'] and s['completion_marker_received']
 assert sha(PLAN)==s['plan_sha256'] and sha(R/'audit.jsonl.gz')==s['audit_sha256']
 rows=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()];assert len(rows)==s['audit_records']
 m=json.loads((OUT/'manifest.json').read_bytes());start=int(datetime.datetime.fromisoformat(m['started_utc']).timestamp()*NS)
 md=json.loads((OUT/'metadata/normalized.json').read_bytes())['markets']
 bytime=collections.defaultdict(list);clocks=collections.defaultdict(list);trades=collections.defaultdict(list)
 for r in rows:bytime[r['ns']].append(r)
 states=collections.defaultdict(dict);hist=collections.defaultdict(lambda:collections.deque(maxlen=125));last={};booktargets={};markbooks={};used=set();c=collections.Counter();end=None
 for e in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],max_raw_bytes=HARD_BYTES):
  if e['type']=='end':end=e;continue
  if not e.get('asset'):continue
  asset,kind=e['asset'].rsplit('_',1);now=e['received_ns'];books=states[asset]
  relevant=[r for r in bytime[now] if r['branch']==asset and r.get('callback_market')==e.get('market') and r.get('callback_kind')==e['type']]
  if e['type']=='invalidate':books.pop(kind,None);hist[asset].clear();last.pop(asset,None);continue
  if e['type']=='trade':trades[asset].append(e);continue
  if e['type']!='book':continue
  clocks[(asset,kind)].append((now,e['source_ns'],e['generation']))
  books[kind]=copy.deepcopy(e)
  if any(r['event'] in ('fill','activated') for r in relevant):booktargets[(asset,kind,now)]=copy.deepcopy(e)
  # Branch reserves public depth once for each taker fill on this callback.
  for r in relevant:
   if r['event']!='fill' or r['maker']:continue
   ident=id(r)
   if ident in used:continue
   assert r['source_venue']=='lighter' and r['market_kind']==kind and str(r['source_market'])==str(e['market'])
   assert e['source_ns']<=now and now-e['source_ns']<=2*NS
   levels=books[kind]['bids' if r['side']=='sell' else 'asks']
   q,v=walk(levels,d(r['qty']),deplete=True,side=r['side']);eq(q,r['qty']);eq(v,r['value']);used.add(ident);c['taker_walks']+=1
  if any(r['event']=='take_profit_mark' for r in relevant):markbooks[(asset,now)]=copy.deepcopy(books)
  if fresh(books,now):
   sp,pp=books['spot'],books['perp'];sm=sum(d(sp[k][0][0]) for k in ('bids','asks'))/2;pm=sum(d(pp[k][0][0]) for k in ('bids','asks'))/2
   basis=(pm/sm-1)*10000
   if asset not in last or now-last[asset]>=NS:hist[asset].append((now,basis));last[asset]=now
  for r in relevant:
   if r['event'] not in ('spot_admission','inside_quote_check'):continue
   active=r['event']=='inside_quote_check'
   if active and r['reason']=='stale_or_skewed_pair':assert not fresh(books,now);c['active_checks']+=1;continue
   assert fresh(books,now)
   if not active:assert 122*NS<=now-start<480*NS and now//(3600*NS)==(now+120*NS)//(3600*NS)
   refs=[(t,v) for t,v in hist[asset] if now-122*NS<=t<=now-2*NS]
   if active and r['reason']=='reference_warmup':assert len(refs)<60 or refs[-1][0]-refs[0][0]<89*NS;c['active_checks']+=1;continue
   assert len(refs)>=60 and refs[-1][0]-refs[0][0]>=89*NS
   current_ref=D(median(v for t,v in refs))
   if active:assert r['reason']!='under_5bp_excursion'
   if active and r['reason']=='post_only_cross':assert d(r['quote_price'])>=d(sp['asks'][0][0]);c['active_checks']+=1;continue
   if active and r['reason']=='insufficient_depth':
    qty=d(r['quote_qty']);assert any(walk(levels,qty)[0]<qty for levels in (pp['bids'],sp['bids'],pp['asks']));c['active_checks']+=1;continue
   assert refs==[(t,d(v)) for t,v in r['reference_rows']] and len(refs)==r['reference_count']
   ref=D(median(v for t,v in refs));eq(ref,r['reference_bps']);eq(basis,r['basis_bps']);assert active or basis-ref>=5
   sr,pr=md['maker'][asset],md['hedge'][asset];a,b=d(sr['qty_step']),d(pr['qty_step']);scale=D(10)**max(-a.as_tuple().exponent,-b.as_tuple().exponent,0);step=D(math.lcm(int(a*scale),int(b*scale)))/scale
   price=d(r['quote_price']) if active else d(sp['bids'][0][0])+d(sr['price_tick']);assert price<d(sp['asks'][0][0]);qty=d(r['quote_qty']) if active else (D(100)/max(price,d(pp['bids'][0][0]))/step).to_integral_value(rounding=ROUND_FLOOR)*step
   eq(price,r['price']);eq(qty,r['quantity']);assert qty*price<=100
   vals=[]
   for levels in (pp['bids'],sp['bids'],pp['asks']):q,v=walk(levels,qty);assert q==qty;vals.append(v)
   he,se,pe=vals;capital=(qty*price+he)*D('.05')*10/D(365*86400)
   forecast=he-qty*price+se-pe+qty*(pm-sm-ref*sm/10000)-capital
   eq(he,r['hedge_entry_value']);eq(se,r['spot_exit_value']);eq(pe,r['perp_exit_value']);eq(capital,r['capital']);eq(forecast,r['forecast_cash_after_capital']);assert (forecast>=D('.01'))==(r['reason']=='quote') and d(r['fees'])==0
   for role,rules,px in [('maker',sr,price),('hedge',pr,d(pp['bids'][0][0]))]:
    assert qty>=d(rules['min_qty']) and qty*px>=d(rules['min_notional']) and qty*px<=d(rules['max_quote']) and qty%d(rules['qty_step'])==0 and px%d(rules['price_tick'])==0
   c['active_checks' if active else 'admissions']+=1;c['reference_rows']+=len(refs)
 assert end and len(used)==sum(r['event']=='fill' and not r['maker'] for r in rows)
 results={}
 for asset,b in s['branches'].items():
  rr=[r for r in rows if r['branch']==asset];ff=[r for r in rr if r['event']=='fill'];cash={'maker':D(0),'hedge':D(0)};pos={'maker':D(0),'hedge':D(0)};lots={'maker':[],'hedge':[]};capital=D(0);base=D(0);prev=None;episodecash=D(0);episodecap=D(0);intents=[];exit_due={};unknown=next((r['ns'] for r in rr if r['event']=='unknown'),end['stopped_ns']+1)
  for idx,r in enumerate(rr):
   now=r['ns'];event=r['event']
   if event=='quote_requested':episodecash=sum(cash.values());episodecap=capital+(base*D(now-prev)*D('.05')/D(365*86400*NS) if prev else 0)
   if event=='hedge_scheduled':assert r['due_ns']-now==400_000_000;intents.append(r)
   if event=='exit_requested':exit_due={role:now+400_000_000 for role in ('maker','hedge') if d(r[role+'_pos'])!=0}
   if event=='take_profit_mark':
    books=markbooks[(asset,now)];assert fresh(books,now) and pos['maker']==-pos['hedge']>0
    q,v=walk(books['spot']['bids'],pos['maker']);assert q==pos['maker'];q,w=walk(books['perp']['asks'],-pos['hedge']);assert q==-pos['hedge']
    cap=capital+(base*D(now-prev)*D('.05')/D(365*86400*NS) if prev else 0)
    mark=sum(cash.values())-episodecash+v-w-(cap-episodecap);eq(mark,r['projected_net']);assert mark>=D('.01');c['take_profit_marks']+=1
   if event!='fill':continue
   role=r['venue'];kind='spot' if role=='maker' else 'perp';rules=md[role][asset];qty,value=d(r['qty']),d(r['value']);assert qty>0 and qty%d(rules['qty_step'])==0
   assert r['source_venue']=='lighter' and r['source_market']==rules['market'] and r['market_kind']==rules['market_kind']
   if prev is not None:capital+=base*D(now-prev)*D('.05')/D(365*86400*NS)
   prev=now
   if not r['maker']:
    book=booktargets[(asset,kind,now)]
    if role=='hedge' and r['side']=='sell':
     result=next(z for z in rr[idx+1:] if z['event']=='hedge_result');assert result['ns']==now and d(result['filled'])==qty
     intent=next(z for z in intents if d(z['qty'])==d(result['requested']));intents.remove(intent);due=intent['due_ns']
     desired=d(result['requested']);limit=d(result['limit']);expected=(d(intent['anchor_bid'])*D('.9999')/d(rules['price_tick'])).to_integral_value(rounding='ROUND_CEILING')*d(rules['price_tick']);eq(limit,expected)
     assert desired>=d(rules['min_qty']) and desired*limit>=d(rules['min_notional'])
     assert value/qty>=limit
    else:
     assert role in exit_due;due=exit_due[role]
     desired=abs(pos[role]);px=d(book['bids' if r['side']=='sell' else 'asks'][0][0])
     assert desired>=d(rules['min_qty']) and desired*px>=d(rules['min_notional'])
     exit_due[role]=now+400_000_000
    assert book['source_ns']>=due and not any(due<=t<now and src>=due and 0<=t-src<=2*NS for t,src,g in clocks[(asset,kind)])
   signed=qty if r['side']=='buy' else -qty;old=pos[role];left=qty
   if old and (old>0)!=(signed>0):
    while left and lots[role]:
     take=min(left,lots[role][0][0]);left-=take;lots[role][0][0]-=take
     if not lots[role][0][0]:lots[role].pop(0)
   if left:lots[role].append([left,value/qty])
   pos[role]+=signed;cash[role]+=value if signed<0 else -value
   assert pos['maker']>=0 and pos['hedge']<=0
   base=sum((q*p for ll in lots.values() for q,p in ll),D(0));principal=sum((q*p for q,p in lots['hedge']),D(0))
   state=next(z for z in rr[idx+1:] if z['event']=='cash_state');assert state['ns']==now
   actual=D(600)+sum(cash.values())-principal-capital;eq(actual,state['actual_cash_usdc']);eq(principal,state['perp_margin_usdc']);assert actual>=principal
  if prev is not None:capital+=base*D(end['stopped_ns']-prev)*D('.05')/D(365*86400*NS)
  eq(capital,b['capital_cost']);eq(cash['maker'],b['cash_maker_usdc']);eq(cash['hedge'],b['cash_hedge_usdc_synthetic']);eq(pos['maker'],b['maker_position']);eq(pos['hedge'],b['hedge_position']);eq(D(600)+sum(cash.values())-sum((q*p for q,p in lots['hedge']),D(0))-capital,b['actual_cash_usdc']);assert d(b['fees_maker'])==d(b['fees_hedge'])==0
  # Reconstruct displayed equal-price queue, then consume only eligible unique sell prints.
  starts=[i for i,r in enumerate(rr) if r['event']=='quote_requested'];assert len(starts)<=30
  for number,i in enumerate(starts):
   scoped=rr[i:starts[number+1] if number+1<len(starts) else len(rr)];qrow=scoped[0];price=d(qrow['price']);remaining=d(qrow['qty']);activation=next((z for z in scoped if z['event']=='activated'),None)
   assert qrow['due_ns']-qrow['ns']==100_000_000
   if not activation:assert not any(z['event']=='maker_increment' for z in scoped);continue
   book=booktargets[(asset,'spot',activation['ns'])];assert price>=d(book['bids'][-1][0]);assert book['source_ns']>=qrow['due_ns'] and price<d(book['asks'][0][0]);ahead=sum((d(q) for p,q in book['bids'] if d(p)==price),D(0));eq(ahead,activation['ahead_same'])
   cancel=next((z for z in scoped if z['event']=='cancel_requested'),None);cancel_due=cancel['due_ns'] if cancel else end['stopped_ns']
   if cancel:assert cancel_due-cancel['ns']==400_000_000
   expected=[]
   for t in trades[asset]:
    if not activation['ns']<=t['received_ns']<unknown or not book['source_ns']<=t['source_ns']<cancel_due or t['side']!='sell' or d(t['price'])>price:continue
    assert 0<=t['received_ns']-t['source_ns']<=2*NS and t['generation']==book['generation']
    flow=d(t['qty']);take=min(ahead,flow);ahead-=take;flow-=take;got=min(flow,remaining);remaining-=got
    if got:expected.append((t['received_ns'],str(t['trade_id']),got))
   observed=[(z['ns'],str(z['trade_id']),d(z['qty'])) for z in scoped if z['event']=='maker_increment' and z['ns']<unknown]
   assert expected==observed,(asset,number,expected,observed);c['queue_episodes']+=1;c['maker_flow_matches']+=len(observed)
  for e in b['episodes']:
   scoped=[z for z in rr if e['decided_ns']<=z['ns']<=e['flat_ns'] and z['event']=='fill']
   cashsum=sum((d(z['value'])*(1 if z['side']=='sell' else -1) for z in scoped),D(0));eq(cashsum,e['cash_known']);assert not scoped or len({z['ns']//(3600*NS) for z in scoped})==1
   reserve=max(d(e['entry_maker_notional']),d(e['entry_hedge_notional']))*D('.0005');eq(reserve,e['reserve_cost'])
   if not e.get('execution_unknown') and not e['funding_unknown']:eq(cashsum,e['fee_only_net']);eq(cashsum-reserve-d(e['capital_cost']),e['stressed_net'])
  results[asset]={'fills':len(ff),'cash_spot':str(cash['maker']),'cash_perp_synthetic':str(cash['hedge']),'capital':str(capital),'spot_inventory':str(pos['maker']),'perp_inventory':str(pos['hedge']),'unknown_reason':b['unknown_reason']}
 out={'audit':'passed','checks':dict(c),'branches':results,'summary_sha256':sha(R/'summary.json.gz'),'limitations':'Queue checked only before first unknown callback; unknown outcomes retained. Public-flow attribution remains conditional on queue and ACK assumptions. No private order/fill proof. All fills independently reconciled even in unknown branches; zero checks are vacuous.'}
 with (R/'independent-audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':run()
