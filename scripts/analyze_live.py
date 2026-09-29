#!/usr/bin/env python3
"""Rebuild size-aware observed spreads from archived books, without forward filling.
All monetary units assume quoted stablecoins at USD parity; explicit sensitivity follows.
"""
import argparse,collections,csv,datetime as dt,itertools,json,math,pathlib,statistics
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/derived'

def csvwrite(path,rows):
    if not rows:return
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def quantile(x,q):return float(np.quantile(x,q)) if x else None

def levels(row):
    b=row.get('body') or {}
    if row['venue']=='hyperliquid':
        ls=b.get('levels') or [[],[]]
        bid=[(float(x['px']),float(x['sz'])) for x in ls[0]];ask=[(float(x['px']),float(x['sz'])) for x in ls[1]]
    elif row['venue']=='lighter':
        bid=[(float(x['price']),float(x['remaining_base_amount'])) for x in b.get('bids',[])];ask=[(float(x['price']),float(x['remaining_base_amount'])) for x in b.get('asks',[])]
    elif row['venue']=='aster':
        bid=[(float(x[0]),float(x[1])) for x in b.get('bids',[])];ask=[(float(x[0]),float(x[1])) for x in b.get('asks',[])]
    elif row['venue']=='dydx':
        bid=[(float(x['price']),float(x['size'])) for x in b.get('bids',[])];ask=[(float(x['price']),float(x['size'])) for x in b.get('asks',[])]
    else:raise ValueError(row['venue'])
    bid=sorted(((p,q) for p,q in bid if p>0 and q>0),reverse=True);ask=sorted((p,q) for p,q in ask if p>0 and q>0)
    if not bid or not ask or bid[0][0]>=ask[0][0]:raise ValueError('empty or crossed book')
    return bid,ask

def consume(book,q):
    """Return total quote currency for exact base quantity, or None if insufficient."""
    if q<=0:return None
    left=q;total=0
    for price,size in book:
        take=min(left,size);total+=price*take;left-=take
        if left<=max(1e-12,q*1e-10):return total
    return None

def fee_bps(m,premium=False):
    if m['venue']=='lighter':return 2.8 if premium else 0.0
    if m['venue']=='aster':return 4.0
    if m['venue']=='dydx':return 5.0
    if m['kind']=='spot':return 7.0 # no staking / referral / quote-token discount assumed
    if not m.get('dex'):return 4.5
    d=float(m.get('fee_scale') or 1)
    return 4.5*(d+1 if d<1 else 2*d)*(.1 if m.get('growth_mode')=='enabled' else 1)

def age_ms(r):
    t=r.get('venue_time_ms')
    return r['received_ms']-t if t else None

def analyze_run(run,notionals=(1000,10000,100000)):
    plan=json.loads((run/'plan.json').read_text());meta={(m['venue'],str(m['market'])):m for m in plan}
    rounds=collections.defaultdict(dict);quality=collections.Counter();ages=[];requests=[]
    for line in (run/'books.jsonl').open():
        r=json.loads(line);quality['requests']+=1;requests.append(r['received_ms'])
        if 'error'in r:quality['http_errors']+=1;continue
        try:r['_levels']=levels(r)
        except (ValueError,KeyError,TypeError):quality['invalid_books']+=1;continue
        age=age_ms(r)
        if age is not None:ages.append(age)
        if age is not None and (age>5000 or age< -2000):quality['stale_books']+=1;continue
        rounds[r['round']][(r['venue'],str(r['market']))]=r
    obs=[];depth=[];reject=[]
    for i,books in rounds.items():
        groups=collections.defaultdict(list)
        for key,r in books.items():
            m=meta[key];groups[m['asset']].append((m,r));b,a=r['_levels'];mid=(b[0][0]+a[0][0])/2
            depth.append({'round':i,'asset':m['asset'],'category':m['category'],'venue':m['venue'],'market':m['market'],'mid':mid,
                'spread_bps':(a[0][0]/b[0][0]-1)*10000,
                'bid_depth_10bps':sum(p*q for p,q in b if p>=mid*.999),
                'ask_depth_10bps':sum(p*q for p,q in a if p<=mid*1.001),
                'returned_bid_notional':sum(p*q for p,q in b),'returned_ask_notional':sum(p*q for p,q in a),
                'venue_age_ms':age_ms(r),'request_ms':r['received_ms']-r['request_start_ms']})
        for asset,ms in groups.items():
            for (buy,br),(sell,sr) in itertools.permutations(ms,2):
                skew=abs(br['received_ms']-sr['received_ms'])
                if skew>5000:quality['skew_pair_rejections']+=1;continue
                bb,ba=br['_levels'];sb,sa=sr['_levels'];bm=(bb[0][0]+ba[0][0])/2;sm=(sb[0][0]+sa[0][0])/2
                if not .95<sm/bm<1.05:
                    reject.append({'round':i,'asset':asset,'buy':f'{buy["venue"]}:{buy["market"]}','sell':f'{sell["venue"]}:{sell["market"]}','ratio':sm/bm,'reason':'greater than 5% midpoint mismatch; units/oracle/depeg/dislocation unverified'});continue
                dec=min(x['sz_decimals'] for x in (buy,sell) if x.get('sz_decimals') is not None)
                for n in notionals:
                    q=math.floor((n/bm)*10**dec)/10**dec
                    if any(q<float(x.get('min_base_amount',0)) for x in (buy,sell)):quality['minimum_size_rejections']+=1;continue
                    bc=consume(ba,q);sp=consume(sb,q)
                    if bc is None or sp is None:quality['insufficient_depth']+=1;continue
                    fb=fee_bps(buy);fs=fee_bps(sell);fees=bc*fb/10000+sp*fs/10000
                    net=(sp-bc-fees)/bc*10000
                    premfees=bc*fee_bps(buy,True)/10000+sp*fee_bps(sell,True)/10000
                    borrow=sell['kind']=='spot'
                    obs.append({'round':i,'timestamp_ms':max(br['received_ms'],sr['received_ms']),'asset':asset,
                        'category':sell['category'] if buy['category']=='spot' else buy['category'],
                        'buy_venue':buy['venue'],'buy_market':buy['market'],'sell_venue':sell['venue'],'sell_market':sell['market'],
                        'buy_kind':buy['kind'],'sell_kind':sell['kind'],'target_notional':n,'base_quantity':q,'buy_cost':bc,'sell_proceeds':sp,
                        'gross_entry_bps':(sp/bc-1)*10000,'entry_fee_bps':fees/bc*10000,'net_entry_bps':net,
                        'premium_account_net_bps':(sp-bc-premfees)/bc*10000,'net_with_5bp_other_cost':net-5,'net_with_10bp_other_cost':net-10,
                        'quote_skew_ms':skew,'buy_collateral':buy['collateral'],'sell_collateral':sell['collateral'],
                        'requires_spot_borrow_or_inventory':borrow,'economic_mapping':'ticker/price-unit candidate; settlement rules need review',
                        'both_venue_timestamps':bool(br.get('venue_time_ms') and sr.get('venue_time_ms'))})
    quality.update(rounds_observed=len(rounds),markets_planned=len(plan),valid_size_observations=len(obs))
    q=dict(quality);q.update(start_ms=min(requests),end_ms=max(requests),duration_minutes=(max(requests)-min(requests))/60000,
        age_ms_p50=quantile(ages,.5),age_ms_p95=quantile(ages,.95),age_ms_max=max(ages) if ages else None)
    return obs,depth,reject,q

def summarize(obs):
    groups=collections.defaultdict(list)
    for r in obs:groups[(r['asset'],r['buy_venue'],r['buy_market'],r['sell_venue'],r['sell_market'],r['target_notional'])].append(r)
    rows=[]
    for key,rs in groups.items():
        rs.sort(key=lambda r:r['round']);x=[r['net_entry_bps'] for r in rs]; streak=best=0;prev=None
        for r in rs:
            streak=streak+1 if r['net_entry_bps']>0 and prev is not None and r['round']==prev+1 else int(r['net_entry_bps']>0)
            best=max(best,streak);prev=r['round']
        rows.append(dict(zip(('asset','buy_venue','buy_market','sell_venue','sell_market','target_notional'),key))|{
            'category':rs[0]['category'],'samples':len(rs),'net_min_bps':min(x),'net_p05_bps':quantile(x,.05),'net_median_bps':statistics.median(x),
            'net_p95_bps':quantile(x,.95),'net_max_bps':max(x),'positive_samples':sum(v>0 for v in x),'positive_fraction':sum(v>0 for v in x)/len(x),
            'positive_after_5bp_fraction':sum(v>5 for v in x)/len(x),'positive_after_10bp_fraction':sum(v>10 for v in x)/len(x),
            'premium_net_median_bps':statistics.median(r['premium_account_net_bps'] for r in rs),'longest_positive_consecutive_samples':best,
            'median_buy_cost':statistics.median(r['buy_cost'] for r in rs),'max_quote_skew_ms':max(r['quote_skew_ms'] for r in rs),
            'requires_spot_borrow_or_inventory':rs[0]['requires_spot_borrow_or_inventory']})
    return sorted(rows,key=lambda r:(r['target_notional'],-r['net_median_bps']))

def robinhood(run):
    inventory=list(csv.DictReader(open(sorted((ROOT/'data/raw/hyperliquid').glob('*/inventory.csv'))[-1])))
    lookup={r['coin']:r for r in inventory};out=[];quality=collections.Counter();times=[]
    for line in (run/'quotes.jsonl').open():
        r=json.loads(line)
        if r.get('type')=='registry':continue
        quality['requests']+=1
        if 'error'in r:quality['errors']+=1;continue
        if not r.get('hl_book'):quality['without_direct_hl_hedge']+=1;continue
        b=r['hl_book'];t=r['end_ms'];times.append(t);skew=abs(b['time']-r['block_time_ms'])
        if skew>5000:quality['stale_or_skew_rejections']+=1;continue
        m=lookup[b['coin']];hb,ha=levels({'venue':'hyperliquid','body':b});mul=float(r['multiplier'])
        fees=fee_bps({'venue':'hyperliquid','kind':'perp','dex':m['dex'],'fee_scale':m['deployer_fee_scale'],'growth_mode':m['growth_mode']})
        for qs in r['quoter']:
            for q in qs['quotes']:
                # AMM token amount maps to fractional shares. Model exact delta for survey;
                # separately expose rounding residual required at actual HL size precision.
                shares=float(q['tokenQuantity'])*mul;n=float(q['targetUsd']);usd=float(q['usdAmount']);side=q['side']
                hedge=consume(hb if side=='buy' else ha,shares)
                if hedge is None:quality['insufficient_hl_depth']+=1;continue
                bc,sp=(usd,hedge) if side=='buy' else (hedge,usd)
                fee=hedge*fees/10000
                net=(sp-bc-fee)/bc*10000
                lot=10**(-int(m['sz_decimals']));residual=shares-math.floor(shares/lot)*lot
                out.append({'round':r['round'],'timestamp_ms':t,'symbol':r['symbol'],'pool':r['pool'],'pool_fee_bps':qs['fee']/100,
                    'direction':'buy_RH_sell_HL' if side=='buy' else 'buy_HL_sell_RH','target_notional':n,'shares':shares,'token_quantity':float(q['tokenQuantity']),
                    'multiplier':mul,'buy_cost':bc,'sell_proceeds':sp,'net_entry_bps':net,'gross_entry_bps':(sp/bc-1)*10000,
                    'hl_fee_bps':fees,'hl_size_rounding_residual_shares':residual,'rounding_residual_usd_upper':residual*ha[0][0],
                    'net_after_1usd_gas_bps':net-10000/bc,'net_after_5usd_total_cost_bps':net-50000/bc,
                    'requires_spot_inventory_or_borrow':side=='sell','quote_skew_ms':skew,'block_number':r['block_number'],
                    'USDG_USDC_parity_assumed':True})
    groups=collections.defaultdict(list)
    for r in out:groups[(r['symbol'],r['direction'],r['target_notional'])].append(r)
    summaries=[]
    for key,rs in groups.items():
        x=[r['net_entry_bps'] for r in rs]
        summaries.append({'symbol':key[0],'direction':key[1],'target_notional':key[2],'samples':len(x),'median_bps':statistics.median(x),
            'p05_bps':quantile(x,.05),'p95_bps':quantile(x,.95),'min_bps':min(x),'max_bps':max(x),
            'positive_samples':sum(a>0 for a in x),'positive_fraction':sum(a>0 for a in x)/len(x),'max_skew_ms':max(r['quote_skew_ms'] for r in rs)})
    return out,summaries,dict(quality)|{'start_ms':min(times) if times else None,'end_ms':max(times) if times else None}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--live-run',type=pathlib.Path);ap.add_argument('--rh-run',type=pathlib.Path);args=ap.parse_args()
    run=args.live_run or sorted((ROOT/'data/raw/live').glob('*/manifest.json'))[-1].parent
    obs,depth,reject,quality=analyze_run(run);csvwrite(OUT/'live_observations.csv',obs);csvwrite(OUT/'live_summary.csv',summarize(obs));csvwrite(OUT/'live_depth.csv',depth);csvwrite(OUT/'live_quarantined.csv',reject)
    rr=args.rh_run or sorted((ROOT/'data/raw/robinhood_live').glob('*/manifest.json'))[-1].parent
    rh,summary,rq=robinhood(rr);csvwrite(OUT/'robinhood_observations.csv',rh);csvwrite(OUT/'robinhood_summary.csv',summary)
    quality={'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'live_source':str(run.relative_to(ROOT)),'robinhood_source':str(rr.relative_to(ROOT)),'live':quality,'robinhood':rq}
    (OUT/'live_quality.json').write_text(json.dumps(quality,indent=2)+'\n');print(json.dumps(quality,indent=2))
if __name__=='__main__':main()
