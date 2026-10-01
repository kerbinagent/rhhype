"""Independent raw-book, signal, first-eligible IOC and cash audit.

Does not call the strategy's feature, execution, or portfolio implementations.
Uses the separately validated raw archive adapter shared by earlier studies.
"""
from pathlib import Path
from collections import Counter, deque
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from statistics import median
import gzip, hashlib, json, math, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.run_single_venue_study import inputs, PLAN, sha
NS=10**9
VS=('lighter','rh_lighter')

def num(x):return D(str(x))
def near(a,b):assert abs(num(a)-num(b)) < D('1e-8'),(a,b)
def clock(b,t):
    return bool(b and b.get('valid') and b.get('clock_valid') and b['bids'] and b['asks']
        and b['bids'][0][0]<b['asks'][0][0] and 0<=t-b['received_ns']<=2*NS
        and 0<=t-b['source_ns']<=2*NS and b['source_ns']<=b['received_ns'])
def pair(books,t):
    return (all(clock(books.get(v),t) for v in VS)
        and abs(books[VS[0]]['received_ns']-books[VS[1]]['received_ns'])<=250_000_000
        and abs(books[VS[0]]['source_ns']-books[VS[1]]['source_ns'])<=250_000_000)
def midpoint(b):return (float(b['bids'][0][0])+float(b['asks'][0][0]))/2
def match_book(w,b):
    for k,v in w.items():
        if k in ('bids','asks'):assert [[float(p),float(q)] for p,q in v]==[[float(p),float(q)] for p,q in b[k]]
        else:assert v==b[k],k

def verify_signal(s,books,refs,points,flows,now):
    v=s['venue'];other=VS[1] if v==VS[0] else VS[0]
    assert pair(books,now) and s['t']==now
    past=[(t,b) for t,b in refs if now-122*NS<=t<=now-2*NS]
    assert len(past)>=60 and past[-1][0]-past[0][0]>=89*NS
    assert len(past)==len(s['reference_rows'])
    for a,b in zip(past,s['reference_rows']):assert a[0]==b[0];near(a[1],b[1])
    current=10000*math.log(midpoint(books['lighter'])/midpoint(books['rh_lighter']))
    ref=median(x for _,x in past);residual=(current-ref)*(1 if v=='lighter' else -1)
    side=-1 if residual>0 else 1
    near(ref,s['reference_bps']);near(current,s['basis_bps']);near(residual,s['residual_bps'])
    assert side==s['direction']
    b=books[v];spread=(float(b['asks'][0][0])-float(b['bids'][0][0]))/midpoint(b)*10000
    near(spread,s['roundtrip_spread_bps']);assert abs(residual)>=spread+4
    if s['rule']=='gap_fade':assert abs(residual)>=5
    elif s['rule']=='leader_follow':
        p=next(p for p in reversed(points) if p['t']<=now-NS)
        assert now-NS-p['t']<=250_000_000
        moves={k:10000*math.log(midpoint(books[k])/p['mids'][k]) for k in VS}
        for k in VS:near(moves[k],s['moves_1s_bps'][k])
        assert abs(residual)>=3 and side*moves[other]>=3 and side*moves[v]<=.5*side*moves[other]
    else:
        assert s['rule']=='local_shock_fade' and abs(residual)>=3
        detail=s['shock'];bucket=now//NS-1;flow=flows[v][bucket]
        assert detail['completed_receipt_second']==bucket and detail['flow']==flow
        baseline=sorted((k,f['notional']) for k,f in flows[v].items() if now//NS-122<=k<=bucket-2)
        assert len(baseline)>=20 and baseline[-1][0]-baseline[0][0]>=60
        near(median(x for _,x in baseline),detail['baseline_median'])
        p=next(p for p in reversed(points) if p['t']<=bucket*NS)
        assert p==detail['pre'] and bucket*NS-p['t']<=250_000_000
        assert all(p['sources'][k]<=flow['min_source'] for k in VS) and b['source_ns']>=flow['max_source']
        imbalance=(flow['buy_qty']-flow['sell_qty'])/(flow['buy_qty']+flow['sell_qty'])
        sign=1 if imbalance>0 else -1
        assert abs(imbalance)>=.8 and side==-sign and flow['notional']>=5*median(x for _,x in baseline)
        depth=p['depth'][v]['buy' if sign==1 else 'sell']
        assert depth>0 and flow['buy_qty' if sign==1 else 'sell_qty']>=.25*depth
        assert sign*10000*math.log(midpoint(b)/p['mids'][v])>=2
        assert abs(10000*math.log(midpoint(books[other])/p['mids'][other]))<=1

def audit(name,manifest_hash=None):
    plan=json.loads(PLAN.read_bytes());out=ROOT/'reports/single-venue-research'/name
    result=json.loads(gzip.decompress((out/'summary.json.gz').read_bytes()))
    assert not result['error'] and result['observed_prefix_verified']
    assert result['complete_capture_verified'] is False and result['retrospective'] is True
    assert result['end']['truncated'] and result['end']['reason']=='compressed_size_cap'
    assert result['plan_sha256']==sha(PLAN) and result['trace_sha256']==sha(out/'trace.jsonl.gz')
    rows=[json.loads(x) for x in gzip.decompress((out/'trace.jsonl.gz').read_bytes()).splitlines()]
    assert len(rows)<=5000
    _,_,metadata,start,events=inputs(plan,name,manifest_hash or result['manifest_sha256'])
    by_time={}
    for r in rows:
        t=r['signal']['t'] if r['kind']=='signal' else (r['order']['request_ns'] if r['kind']=='request' else
            r['episode']['exit_ns'] if r['kind']=='closed' else r['t'])
        by_time.setdefault(t,[]).append(r)
    books={};refs=deque(maxlen=125);points=deque(maxlen=1400);flows={v:{} for v in VS}
    last_ref=last_point=None
    orders={};ledgers={};counts=Counter();seen=set();ended=None
    for event in events:
        now=event['received_ns'];kind=event['type'];v=event.get('venue')
        if kind=='invalidate':
            books.pop(v,None);refs.clear();points.clear();flows={v:{} for v in VS};last_ref=last_point=None
        if kind=='trade' and 0<=now-event['source_ns']<=2*NS:
            k=now//NS;f=flows[v].setdefault(k,dict(notional=0.,buy_qty=0.,sell_qty=0.,
                min_source=event['source_ns'],max_source=event['source_ns'],count=0))
            q=float(event['qty']);f['notional']+=q*float(event['price']);f['buy_qty' if event['buy_aggressor'] else 'sell_qty']+=q
            f['min_source']=min(f['min_source'],event['source_ns']);f['max_source']=max(f['max_source'],event['source_ns']);f['count']+=1
            for old in list(flows[v]):
                if old<k-125:del flows[v][old]
        if kind=='book':
            books[v]=event
            if pair(books,now):
                mids={k:midpoint(books[k]) for k in VS}
                if last_point is None or now-last_point>=100_000_000:
                    point=dict(t=now,mids=mids,sources={k:books[k]['source_ns'] for k in VS},depth={})
                    for k in VS:
                        b=books[k];point['depth'][k]={
                            'buy':sum(float(q) for p,q in b['asks'] if float(p)<=float(b['asks'][0][0])*1.0005),
                            'sell':sum(float(q) for p,q in b['bids'] if float(p)>=float(b['bids'][0][0])*.9995)}
                    points.append(point);last_point=now
                if last_ref is None or now-last_ref>=NS:
                    refs.append((now,10000*math.log(mids['lighter']/mids['rh_lighter'])));last_ref=now
        # Rows are emitted on a single raw callback; repeated trade timestamps cannot consume book rows.
        candidates=by_time.get(now,[]) if now not in seen else []
        if candidates and kind not in ('book','invalidate','end','control'):
            continue
        if kind=='book':
            for arm,order in list(orders.items()):
                if arm.endswith(':'+v) and clock(event,now) and order['due_ns']<=event['source_ns']<=now<=order['due_ns']+2*NS:
                    assert any(r['arm']==arm and r['kind']=='ioc' for r in candidates),('missed_first_eligible',arm,now)
        if candidates:seen.add(now)
        for r in candidates:
            arm=r['arm'];venue=arm.split(':')[1];m=metadata[venue]['LIT']
            ledger=ledgers.setdefault(arm,dict(cash=D(600),position=None,unknown=None,closed=0,requests=[]))
            counts[r['kind']]+=1
            if r['kind']=='signal':
                assert kind=='book' and not ledger['position'] and arm not in orders and not ledger['unknown']
                assert 122*NS<=now-start<480*NS
                verify_signal(r['signal'],books,refs,points,flows,now)
            elif r['kind']=='request':
                order=r['order'];assert arm not in orders and clock(books[venue],now)
                match_book(r['book'],books[venue]);assert order['request_ns']==now and order['due_ns']==now+400_000_000
                q=num(order['quantity']);px=num(order['limit']);side=order['side'];tick=num(m['price_tick'])
                bps=1 if order['action']=='entry' else 10
                best=num(books[venue]['asks' if side==1 else 'bids'][0][0])
                expected=(best*(1+D(side*bps)/10000)/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
                assert px==expected and q>=num(m['min_qty']) and q*px>=num(m['min_notional']) and q%num(m['qty_step'])==0
                if order['action']=='entry':
                    wanted=(D(100)/(num(books[venue]['asks'][0][0])*D('1.01'))/num(m['qty_step'])).to_integral_value(rounding=ROUND_FLOOR)*num(m['qty_step'])
                    assert q==wanted and not ledger['position'] and ledger['cash']>=100
                    assert any(x['kind']=='signal' and x['arm']==arm for x in candidates)
                else:
                    assert ledger['position'] and now-ledger['position']['entry_ns']>=10*NS
                    assert q==ledger['position']['remaining'] and side==-ledger['position']['side']
                orders[arm]=order;ledger['requests'].append(now)
            elif r['kind']=='ioc':
                order=orders.pop(arm);assert r['order']==order and kind=='book' and v==venue
                match_book(r['book'],event)
                assert clock(event,now) and order['due_ns']<=event['source_ns']<=now<=order['due_ns']+2*NS
                assert order['generation']==event['generation']
                left=num(order['quantity']);value=D(0);qty=D(0);expected=[]
                for px,size in event['asks' if order['side']==1 else 'bids']:
                    px,size=num(px),num(size)
                    if (order['side']==1 and px>num(order['limit'])) or (order['side']==-1 and px<num(order['limit'])):break
                    take=min(left,size)
                    if take>0:expected.append({'price':str(px),'quantity':str(take)});value+=px*take;qty+=take;left-=take
                    if not left:break
                near(qty,r['quantity']);near(value,r['value']);assert expected==r['fills']
                fee=value*num(m['taker_fee_bps'])/10000;near(fee,r['fee'])
                if order['action']=='entry' and qty>0:
                    assert value<=100
                    ledger['cash']-=fee
                    ledger['position']=dict(side=order['side'],quantity=qty,remaining=qty,entry_value=value,
                        entry_fee=fee,entry_ns=now,exit_value=D(0),exit_fee=D(0),capital=D(0),gross=D(0))
                elif order['action']=='exit':
                    p=ledger['position'];entry=p['entry_value']*qty/p['quantity']
                    gross=p['side']*(value-entry);capital=entry*D('.05')*D(now-p['entry_ns'])/D(NS*365*86400)
                    ledger['cash']+=gross-fee-capital;p['remaining']-=qty
                    for field,add in (('gross',gross),('exit_value',value),('exit_fee',fee),('capital',capital)):p[field]+=add
            elif r['kind']=='closed':
                p=ledger['position'];assert p and p['remaining']==0
                assert p['entry_ns']//(3600*NS)==now//(3600*NS)
                for k,x in p.items():near(x,r['episode'][k])
                net=p['gross']-p['entry_fee']-p['exit_fee']-p['capital']
                near(net,r['episode']['cash_after_capital']);near(net-p['entry_value']*D('.0005'),r['episode']['stressed_net'])
                near(ledger['cash'],r['cash']);ledger['position']=None;ledger['closed']+=1
            elif r['kind']=='unknown':
                if r['reason']=='order_confirmation_timeout':assert arm in orders and now>orders[arm]['due_ns']+2*NS
                elif r['reason']=='exit_below_published_minimum':
                    assert ledger['position'] and ledger['position']['remaining']>0
                elif r['reason']=='execution_book_invalidated':assert kind=='invalidate' and event.get('scope')=='book'
                elif r['reason']=='capture_ended_with_obligation':assert kind=='end'
                else:assert r['reason'] in ('exit_attempt_cap_with_residual','order_generation_changed','funding_crossing','actual_entry_notional_above_100')
                ledger['unknown']=r['reason'];orders.pop(arm,None)
        if kind=='end':ended=event
    assert ended and set(by_time)==seen
    for arm,r in result['arms'].items():
        ledger=ledgers.get(arm,dict(cash=D(600),position=None,unknown=None,closed=0,requests=[]))
        near(ledger['cash'],r['cash']);assert ledger['closed']==r['closed'] and ledger['unknown']==r['unknown']
        if r['complete']:assert not ledger['position'] and arm not in orders
        ts=ledger['requests'];peak=max((sum(t<=u<t+66*NS for u in ts) for t in ts),default=0)
        assert peak<=60,peak
    report=dict(status='passed',sample=name,counts=dict(counts),raw_capture_verified=True, complete_capture_verified=False, descriptive_incomplete_prefix=True,
        signal_checks_vacuous=counts['signal']==0,fill_checks_vacuous=counts['ioc']==0,
        summary_sha256=sha(out/'summary.json.gz'),trace_sha256=sha(out/'trace.jsonl.gz'),
        limits='Conditional public-book IOC execution. Signal and first-eligible book checks plus cash reconciliation; no private order acknowledgments or authenticated fills. Independent arms must not be summed.')
    target=out/'independent-audit.json';assert not target.exists();target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':audit(*sys.argv[1:])
