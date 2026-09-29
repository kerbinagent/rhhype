#!/usr/bin/env python3
"""Compact, canonical-identity inventory tables from frozen raw census data."""
import csv,json,pathlib,collections
from analyze_live import csvwrite
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'data/derived'

def main():
    hp=sorted((ROOT/'data/raw/hyperliquid').glob('*/inventory.csv'))[-1];hl=list(csv.DictReader(hp.open()));csvwrite(OUT/'hyperliquid_inventory.csv',hl)
    lookup={r['coin']:r for r in hl};rp=sorted((ROOT/'data/raw').glob('robinhood_all_pools_*.json'))[-1];raw=json.loads(rp.read_text());rows=[]
    for a in raw['assets']:
        pairs=[p for p in a.get('pairs',[]) if p['chainId']=='robinhood' and p['baseToken']['address'].lower()==a['contractAddress'].lower()
               and p['quoteToken']['address'].lower()=='0x5fc5360d0400a0fd4f2af552add042d716f1d168']
        top=max(pairs,key=lambda p:p.get('liquidity',{}).get('usd',0),default={});h=lookup.get('xyz:'+a['symbol'],{})
        rows.append({'symbol':a['symbol'],'name':a['name'],'canonical_token':a['contractAddress'],'shares_per_token':a['currentMultiplier'],
            'indexed_pair_count':len(a.get('pairs',[])),'indexed_USDG_pair_count':len(pairs),'top_pool':top.get('pairAddress',''),
            'top_pool_dex':top.get('dexId',''),'top_pool_version':','.join(top.get('labels',[])),
            'top_pool_indexed_liquidity_usd':top.get('liquidity',{}).get('usd',0),'top_pool_indexed_volume_24h_usd':top.get('volume',{}).get('h24',0),
            'xyz_same_ticker':h.get('coin',''),'xyz_active':h.get('active',''),'xyz_volume_24h_usd':h.get('day_volume_usd',''),
            'source_file':str(rp.relative_to(ROOT))})
    csvwrite(OUT/'robinhood_inventory.csv',rows)
    classes=collections.defaultdict(list)
    for r in hl:
        if r['venue']=='perp' and r['active']=='True':classes[r['category']].append(r)
    cr=[]
    for cat,rs in classes.items():
        liquid=[r for r in rs if float(r['day_volume_usd'])>=1e6];top=sorted(rs,key=lambda r:float(r['day_volume_usd']),reverse=True)[:5]
        cr.append({'category':cat,'active_listings':len(rs),'over_1m_volume':len(liquid),'summed_24h_volume':sum(float(r['day_volume_usd']) for r in rs),
            'top_markets':', '.join(r['coin'] for r in top),'top_volumes_musd':', '.join(f"{float(r['day_volume_usd'])/1e6:.2f}" for r in top)})
    csvwrite(OUT/'asset_class_coverage.csv',cr)
    print('Canonical RH tokens',len(rows),'HL rows',len(hl))
if __name__=='__main__':main()
