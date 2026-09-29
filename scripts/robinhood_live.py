#!/usr/bin/env python3
"""Fixed-block Robinhood v3 pool quotes with immediately adjacent Hyperliquid L2.
Quoter calls simulate swaps only. Hedge shares = token quantity * registry multiplier.
"""
import argparse, concurrent.futures as cf, datetime as dt, json, pathlib, time
from decimal import Decimal
import robinhood_probe as rh
ROOT=pathlib.Path(__file__).resolve().parents[1]

def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def save(p,o):p.write_text(json.dumps(o,indent=2)+'\n')
def snapshot_plan():
    src=sorted((ROOT/'data/raw').glob('robinhood_snapshot_*.json'))[-1]
    s=json.loads(src.read_text());plan=[]
    for symbol,o in s['selected'].items():
        token=next(d['contractAddress'] for d in o['asset']['deployments'] if d['chainId']==4663)
        candidates=[p for p in o['dex'].get('pairs',[]) if p['chainId']=='robinhood' and p.get('dexId')=='uniswap' and 'v3' in p.get('labels',[])
                    and p['baseToken']['address'].lower()==token.lower() and p['quoteToken']['address'].lower()==rh.USDG.lower()]
        candidates.sort(key=lambda p:float(p.get('liquidity',{}).get('usd',0)),reverse=True)
        if not candidates:continue
        p=candidates[0]
        if float(p.get('liquidity',{}).get('usd',0))<100000:continue
        q=o['quote']['quotes'][0]
        plan.append({'symbol':symbol,'token':token,'pool':p['pairAddress'],'registry':o['asset'],
                     'multiplier':o['asset']['currentMultiplier'],'initial_mid':str((Decimal(q['tokenBid'])+Decimal(q['tokenAsk']))/2),
                     'hl_market': 'xyz:'+symbol if symbol not in ('QQQ','SPY') else None})
    return plan,str(src.relative_to(ROOT))

def collect(m,i):
    r={'round':i,'symbol':m['symbol'],'start_ms':int(time.time()*1000),'pool':m['pool'],'multiplier':m['multiplier']}
    try:
        block=rh.rpc('eth_getBlockByNumber',['latest',False]);r['block_number']=int(block['number'],16);r['block_time_ms']=int(block['timestamp'],16)*1000
        # Refresh quote + multiplier every round rather than assume no corporate actions.
        # Registry refreshed globally each round in main; indicative price sizes sell amounts only.
        r['reference_quote']=rh.get_json('https://api.robinhood.com/rhj/prices/'+m['symbol'])
        q=r['reference_quote']['quotes'][0];mid=(Decimal(q['tokenBid'])+Decimal(q['tokenAsk']))/2
        r['quoter']=[rh.quote_v3_pool(m['pool'],m['token'],(Decimal(n),mid),block['number']) for n in (1000,10000,100000)]
        r['quotes_received_ms']=int(time.time()*1000)
        if m['hl_market']:
            r['hl_start_ms']=int(time.time()*1000)
            r['hl_book']=rh.get_json('https://api.hyperliquid.xyz/info',{'type':'l2Book','coin':m['hl_market']})
            r['hl_received_ms']=int(time.time()*1000)
        r['gas_price_wei']=int(rh.rpc('eth_gasPrice',[]),16)
    except Exception as e:r['error']=f'{type(e).__name__}: {e}'
    r['end_ms']=int(time.time()*1000)
    return r

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--rounds',type=int,default=60);ap.add_argument('--interval',type=float,default=30);args=ap.parse_args()
    out=ROOT/'data/raw/robinhood_live'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');out.mkdir(parents=True)
    plan,source=snapshot_plan();save(out/'plan.json',plan)
    man={'started_utc':utc(),'source':source,'rounds_requested':args.rounds,'interval_seconds':args.interval,'symbols':[m['symbol'] for m in plan],'rounds_completed':0,'errors':0,'read_only':True};save(out/'manifest.json',man)
    print(str(out),man['symbols'],flush=True)
    with (out/'quotes.jsonl').open('a') as f, cf.ThreadPoolExecutor(max_workers=3) as pool:
        for i in range(args.rounds):
            start=time.monotonic()
            try:
                registry=rh.get_json(rh.ASSETS);f.write(json.dumps({'round':i,'type':'registry','received_ms':int(time.time()*1000),'body':registry})+'\n')
                mult={a['tokenSymbol']:a['currentMultiplier'] for a in registry['assets']}
                for m in plan:m['multiplier']=mult[m['symbol']]
                rows=list(pool.map(lambda m:collect(m,i),plan))
            except Exception as e:rows=[{'round':i,'error':str(e)}]
            for r in rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
            f.flush();man['rounds_completed']=i+1;man['errors']+=sum('error'in r for r in rows);man['updated_utc']=utc();save(out/'manifest.json',man)
            print(f'round {i+1}/{args.rounds}: {time.monotonic()-start:.1f}s errors={sum("error" in r for r in rows)}',flush=True)
            if i+1<args.rounds:time.sleep(max(0,args.interval-(time.monotonic()-start)))
    man['finished_utc']=utc();save(out/'manifest.json',man)
if __name__=='__main__':main()
