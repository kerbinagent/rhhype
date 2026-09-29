#!/usr/bin/env python3
"""Consecutive public L2 snapshots. No credentials or trading endpoints.
Usage: python scripts/live_collect.py --rounds 60 --interval 30
The market plan is saved before collection; all raw books retain local request times.
"""
import argparse, concurrent.futures as cf, csv, datetime as dt, json, pathlib, time
import requests
ROOT=pathlib.Path(__file__).resolve().parents[1]
HL='https://api.hyperliquid.xyz/info'
LI='https://mainnet.zklighter.elliot.ai/api/v1/'
# Price-unit aliases are candidates; different oracle/settlement rules still require review.
ALIASES={'GOLD':'XAU','SILVER':'XAG','PLATINUM':'XPT','PALLADIUM':'XPD','CL':'WTI',
         'SP500':'US500','XYZ100':'US100','JPY':'USDJPY','EUR':'EURUSD','GBP':'GBPUSD',
         '10Y':'US10Y','UBTC':'BTC','UETH':'ETH','USOL':'SOL'}

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()
def write(path,obj): path.write_text(json.dumps(obj,indent=2)+'\n')
def latest_inventory(): return sorted((ROOT/'data/raw/hyperliquid').glob('*/inventory.csv'))[-1]
def build_plan(inv, lighter_max):
    rows=list(csv.DictReader(open(inv)))
    lr=requests.get(LI+'orderBookDetails',timeout=30).json()
    light={x['symbol']:x for x in lr['order_book_details'] if x['status']=='active'}
    groups={}
    for r in rows:
        sym=r['coin'].split(':')[-1] if r['venue']=='perp' else r['spot_base']
        key=ALIASES.get(sym,sym)
        vol=float(r['day_volume_usd'] or 0)
        if r['active']!='True': continue
        if r['venue']=='spot':
            if r['spot_quote'] not in ('USDC','USDH','USDT') or sym not in ('HYPE','UBTC','UETH','USOL','PURR','PAXG'):continue
            if vol<100000:continue
        elif vol<1000000 and r['category'] not in ('fx','rates') and sym not in ('2Y','30Y'):continue
        groups.setdefault(key,[]).append({'venue':'hyperliquid','market':r['coin'],'asset':key,'category':r['category'],
            'kind':r['venue'],'dex':r['dex'],'volume_24h':vol,'collateral':r['spot_quote'] if r['venue']=='spot' else r['collateral_token'],
            'sz_decimals':int(r['sz_decimals']) if r['sz_decimals'] else None,
            'fee_scale':r.get('deployer_fee_scale',''),'growth_mode':r['growth_mode'],'symbol':sym,'mapping':'exact ticker' if key==sym else 'price-unit alias, specs require review'})
    for key, markets in list(groups.items()):
        li=light.get(key)
        if li and (float(li['daily_quote_token_volume'])>=100000 or markets[0]['category'] in ('fx','rates')):
            markets.append({'venue':'lighter','market':li['market_id'],'asset':key,'category':markets[0]['category'],'kind':'perp',
                'volume_24h':li['daily_quote_token_volume'],'collateral':'USDC','sz_decimals':li['supported_size_decimals'],
                'fee_metadata':li['taker_fee'],'min_base_amount':li['min_base_amount'],'multiplier':li['multiplier'],'symbol':key,
                'mapping':'candidate; contract specification review required'})
        # Include liquid HL markets unmatched to Lighter for Robinhood matching and coverage.
        if len(markets)<2 and markets[0]['category']=='crypto': del groups[key]
    plan=[m for ms in groups.values() for m in ms]
    # Reserve representation across asset classes, then select highest turnover.
    candidates=[m for m in plan if m['venue']=='lighter']
    forced={'BTC','ETH','SOL','HYPE','ZEC','NVDA','TSLA','META','AAPL','GOOGL','AMZN','MSFT','XAU','XAG','WTI','BRENTOIL','US500','US100','USDJPY','EURUSD','GBPUSD','US10Y'}
    selected=sorted(candidates,key=lambda m:(m['asset'] in forced,m['volume_24h']),reverse=True)[:lighter_max]
    ids={m['market'] for m in selected}
    return [m for m in plan if m['venue']!='lighter' or m['market'] in ids],lr

def fetch(m,round_id):
    begin=time.time()
    row={'round':round_id,'venue':m['venue'],'market':m['market'],'asset':m['asset'],'request_start_ms':int(begin*1000),'received_ms':None}
    try:
        if m['venue']=='hyperliquid':
            r=requests.post(HL,json={'type':'l2Book','coin':m['market']},timeout=18)
        else:r=requests.get(LI+'orderBookOrders',params={'market_id':m['market'],'limit':100},timeout=18)
        row.update(http_status=r.status_code,received_ms=int(time.time()*1000))
        r.raise_for_status(); body=r.json(); row['body']=body
        if not isinstance(body,dict): raise ValueError('Expected book object')
        if m['venue']=='hyperliquid':
            if body.get('coin')!=m['market']:raise ValueError('Book identity mismatch')
            row['venue_time_ms']=body.get('time')
        elif body.get('code')!=200:raise ValueError('Lighter code not 200')
    except Exception as e:row['error']=f'{type(e).__name__}: {e}'
    row['received_ms']=row['received_ms'] or int(time.time()*1000)
    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--rounds',type=int,default=60);ap.add_argument('--interval',type=float,default=30)
    ap.add_argument('--lighter-max',type=int,default=30);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--inventory',type=pathlib.Path);ap.add_argument('--out',type=pathlib.Path)
    args=ap.parse_args();inv=args.inventory or latest_inventory();out=args.out or ROOT/'data/raw/live'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=True)
    plan,lr=build_plan(inv,args.lighter_max);write(out/'plan.json',plan);write(out/'lighter_initial.json',lr)
    manifest={'started_utc':utc(),'inventory':str(inv.relative_to(ROOT)),'rounds_requested':args.rounds,'interval_seconds':args.interval,'market_count':len(plan),'rounds_completed':0,'errors':0,'read_only':True}
    write(out/'manifest.json',manifest);print(f'{out} markets={len(plan)} assets={len(set(m["asset"] for m in plan))}',flush=True)
    start=time.monotonic()
    with (out/'books.jsonl').open('a') as f,cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i in range(args.rounds):
            round_start=time.monotonic()
            results=list(pool.map(lambda m:fetch(m,i),plan))
            for row in results:f.write(json.dumps(row,separators=(',',':'))+'\n')
            f.flush();errors=sum('error' in r for r in results);manifest['errors']+=errors;manifest['rounds_completed']=i+1;manifest['updated_utc']=utc()
            write(out/'manifest.json',manifest)
            print(f'round={i+1}/{args.rounds} elapsed={time.monotonic()-start:.1f}s round_seconds={time.monotonic()-round_start:.1f} errors={errors}',flush=True)
            if i+1<args.rounds:time.sleep(max(0,args.interval-(time.monotonic()-round_start)))
    manifest['finished_utc']=utc();write(out/'manifest.json',manifest)
if __name__=='__main__': main()
