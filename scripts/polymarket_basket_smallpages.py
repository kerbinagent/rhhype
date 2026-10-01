#!/usr/bin/env python3
"""Public-only optimistic complete-NO basket screen; never an execution P&L."""
import asyncio,gzip,hashlib,json,time,sys
from pathlib import Path
from decimal import Decimal as D, ROUND_DOWN
from collections import Counter
import aiohttp
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/polymarket-basket-smallpages-allocation-v1.json'
OUT=ROOT/'reports/polymarket-basket-smallpages'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def packed(x):return gzip.compress(json.dumps(x,separators=(',',':')).encode(),mtime=0)
def parse(x):return json.loads(x) if isinstance(x,str) else x

def select(events):
    chosen=[];reasons=Counter()
    for e in events:
        ms=e.get('markets',[])
        if not e.get('negRisk') or e.get('negRiskAugmented') or not 2<=len(ms)<=20:reasons['type_or_question_count']+=1;continue
        if not all(m.get('active') and not m.get('closed') and m.get('acceptingOrders') and m.get('enableOrderBook') and m.get('negRisk') for m in ms):reasons['inactive_member']+=1;continue
        ids={m.get('negRiskMarketID') for m in ms}
        if len(ids)!=1 or not next(iter(ids)):reasons['mixed_or_missing_market_id']+=1;continue
        tokens=[]
        try:
            for m in ms:
                outcomes=parse(m['outcomes']);t=parse(m['clobTokenIds'])
                assert len(t)==len(outcomes)==2 and outcomes.count('No')==1
                tokens.append(str(t[outcomes.index('No')]))
            assert len(set(tokens))==len(tokens)
        except Exception:reasons['token_mapping']+=1;continue
        chosen.append({'event_id':e['id'],'title':e['title'],'liquidity':e.get('liquidity'),'market_id':next(iter(ids)),'tokens':tokens,'conditions':[m['conditionId'] for m in ms]})
        if len(chosen)==3:break
    return chosen,dict(reasons)

def cost(levels,q):
    value=D(0)
    for p,s in levels:
        take=min(s,q);value+=take*p;q-=take
        if q<=0:return value
    return None

def screen(basket,books,received):
    result={'event_id':basket['event_id'],'title':basket['title'],'questions':len(basket['tokens']),'catalog_completeness_onchain_verified':False}
    index={str(b['asset_id']):b for b in books};legs=[];minimum=D(0);ages=[]
    for token,condition in zip(basket['tokens'],basket['conditions']):
        if token not in index:return result|{'status':'missing_book'}
        b=index[token]
        if b.get('market')!=condition or not b.get('neg_risk'):return result|{'status':'book_identity_mismatch'}
        asks=sorted((D(x['price']),D(x['size'])) for x in b['asks'] if D(x['size'])>0)
        if not asks or any(p<=0 or p>=1 for p,s in asks):return result|{'status':'invalid_or_empty_asks'}
        legs.append(asks);minimum=max(minimum,D(str(b['min_order_size'])))
        ages.append(received-float(b['timestamp'])/1000)
    maxq=min(sum((s for p,s in l),D(0)) for l in legs);lo=D(0);hi=maxq
    for _ in range(80):
        q=(lo+hi)/2;v=sum(cost(l,q) for l in legs)
        if v<=100:lo=q
        else:hi=q
    q=(lo*1000000).to_integral_value(rounding=ROUND_DOWN)/1000000
    if q<minimum:return result|{'status':'public_minimum_or_depth_exceeds_budget','max_quantity':str(q),'min_quantity':str(minimum)}
    v=sum(cost(l,q) for l in legs);payout=q*(len(legs)-1)
    # A convex increasing cost makes the best quote surplus occur at a level boundary or budget boundary.
    candidates={minimum,q}
    for l in legs:
        cumulative=D(0)
        for _,s in l:
            cumulative+=s
            if minimum<=cumulative<=q:candidates.add(cumulative)
    best=max(candidates,key=lambda z:z*(len(legs)-1)-sum(cost(l,z) for l in legs))
    bestcost=sum(cost(l,best) for l in legs);surplus=best*(len(legs)-1)-bestcost
    return result|{'status':'quote_screen_only','max_budget_quantity':str(q),'max_budget_cost':str(v),'max_budget_payout_upperbound':str(payout),'max_budget_gross_quote_surplus':str(payout-v),'best_quantity':str(best),'best_cost':str(bestcost),'best_gross_quote_surplus':str(surplus),'positive_candidate':surplus>0,'best_ask_sum':str(sum(l[0][0] for l in legs)),'book_age_seconds':ages,'book_timestamp_span_seconds':max(ages)-min(ages),'unmodeled':['onchain basket completeness/identity','conversion fee','CLOB fees','gas','taker delay','leg execution/unwind','collateral conversion availability']}

async def run():
    plan=json.loads(PLAN.read_bytes());OUT.mkdir(exist_ok=False);retained=0;requests=[];start=time.time();result={'source_sha256':sha(__file__),'plan_sha256':sha(PLAN),'started_at':start,'actual_pnl':None,'paper_trades':0};errors=[]
    async def fetch(session,name,url,body=None):
        nonlocal retained
        began=time.time();buf=bytearray();truncated=False
        async with session.request('POST' if body is not None else 'GET',url,json=body) as r:
            async for chunk in r.content.iter_chunked(16384):
                if len(buf)+len(chunk)>2000000:truncated=True;break
                buf.extend(chunk)
            rec={'url':url,'request_body':body,'began':began,'received':time.time(),'status':r.status,'truncated':truncated,'body':buf.decode(errors='replace')}
        data=packed(rec)
        if retained+len(data)>plan['categories_bytes']['raw']:raise ValueError('raw_cap_before_write: unretained response '+name)
        path=OUT/(name+'.json.gz');path.write_bytes(data);retained+=len(data);requests.append({'path':str(path.relative_to(ROOT)),'bytes':len(data),'sha256':sha(path),'status':rec['status'],'received':rec['received']})
        if truncated or rec['status']!=200:raise ValueError('incomplete_or_http_error '+name)
        return json.loads(rec['body']),rec['received']
    try:
        async with asyncio.timeout(60):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                events=[];chosen=[]
                for i in range(10):
                    page,_=await fetch(session,f'catalog-{i}',f'https://gamma-api.polymarket.com/events?active=true&closed=false&limit=1&offset={i}&order=liquidity&ascending=false');assert isinstance(page,list);events.extend(page)
                    unique={str(e['id']):e for e in events};chosen,reasons=select(list(unique.values()));result.update(catalog_count=len(events),unique_count=len(unique),selected=chosen,selection_rejections=reasons,snapshots=[])
                    if len(chosen)==3:break
                    if retained>plan['categories_bytes']['raw']-131072:result['catalog_stopped_for_book_reserve']=True;break
                if chosen:
                    body=[{'token_id':t} for b in chosen for t in b['tokens']]
                    for i in range(2):
                        if i:await asyncio.sleep(1)
                        books,received=await fetch(session,f'books-{i}','https://clob.polymarket.com/books',body);assert isinstance(books,list)
                        result['snapshots'].append({'received':received,'baskets':[screen(b,books,received) for b in chosen]})
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    result.update(ended_at=time.time(),errors=errors,requests=requests,raw_bytes=retained)
    data=(json.dumps(result,indent=2)+'\n').encode();assert len(data)<plan['categories_bytes']['output']
    (OUT/'summary.json').write_bytes(data);print(data.decode())
if __name__=='__main__':
    if sys.argv[1:]==['run']:asyncio.run(run())
