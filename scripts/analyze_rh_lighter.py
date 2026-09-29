#!/usr/bin/env python3
"""Analyze the separate Robinhood Lighter instance with explicit spot-unit models.
Primary perp results do not depend on stock-token unit assumptions.
"""
import argparse,collections,csv,json,math,pathlib,statistics
from analyze_live import analyze_run,summarize,csvwrite,levels,consume,fee_bps
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'data/derived'

def normalize(run,spot_mode):
    inv={r['coin']:r for r in csv.DictReader(open(sorted((ROOT/'data/raw/hyperliquid').glob('*/inventory.csv'))[-1]))}
    regpath=sorted((ROOT/'data/raw').glob('robinhood_snapshot_*.json'))[-1]
    reg={a['tokenSymbol']:a for a in json.loads(regpath.read_text())['registry']['assets']}
    plan={};records={};multipliers=[]
    for line in (run/'paired_books.jsonl').open():
        r=json.loads(line)
        if r['kind']=='spot' and spot_mode=='exclude':continue
        sym=r['asset'];mul=float(reg[sym]['currentMultiplier']) if r['kind']=='spot' and spot_mode=='raw_token' else 1.0
        if 'rh_body'not in r or 'hl_body'not in r:continue
        mid=str(r['market_id']);key=('rh_lighter',mid)
        if key not in plan:
            plan[key]={'venue':'rh_lighter','market':mid,'symbol':r['market'],'asset':sym,'category':inv[r['hl_market']]['category'],'kind':r['kind'],
                'collateral':'USDG','sz_decimals':r['rh_size_decimals'],
                'min_base_amount':float(r['rh_min_base_amount'])*mul,'fee_metadata':r['rh_taker_fee_metadata'],'unit_model':spot_mode if r['kind']=='spot' else 'perp','unit_multiplier':mul}
        rb=json.loads(json.dumps(r['rh_body']))
        if mul!=1:
            for side in ('bids','asks'):
                for x in rb[side]:
                    x['price']=str(float(x['price'])/mul);x['remaining_base_amount']=str(float(x['remaining_base_amount'])*mul)
        records[(r['round'],*key)]={'round':r['round'],'venue':'rh_lighter','market':mid,'asset':sym,'body':rb,
            'request_start_ms':r['request_start_ms'],'received_ms':r['rh_received_ms']}
        h=inv[r['hl_market']];hk=('hyperliquid',h['coin'])
        plan[hk]={'venue':'hyperliquid','market':h['coin'],'asset':sym,'category':h['category'],'kind':'perp','dex':h['dex'],
            'collateral':h['collateral_token'],'sz_decimals':int(h['sz_decimals']),'fee_scale':h['deployer_fee_scale'],'growth_mode':h['growth_mode']}
        records[(r['round'],*hk)]={'round':r['round'],'venue':'hyperliquid','market':h['coin'],'asset':sym,'body':r['hl_body'],
            'request_start_ms':r['rh_received_ms'],'received_ms':r['hl_received_ms'],'venue_time_ms':r['hl_venue_time_ms']}
    return list(plan.values()),list(records.values())

def unwind(obs,plan,records,horizons=(5,10)):
    meta={(m['venue'],str(m['market'])):m for m in plan};books={}
    for r in records:
        try:books[(r['round'],r['venue'],str(r['market']))]=(r,levels(r))
        except (KeyError,ValueError):pass
    out=[]
    for r in obs:
        if r['net_entry_bps']<=0 or r['requires_spot_borrow_or_inventory']:continue
        lk=(r['buy_venue'],str(r['buy_market']));sk=(r['sell_venue'],str(r['sell_market']))
        for mins in horizons:
            i=r['round']+mins;lb=books.get((i,*lk));sb=books.get((i,*sk))
            if not lb or not sb:continue
            end=max(lb[0]['received_ms'],sb[0]['received_ms'])
            if end//3600000!=r['timestamp_ms']//3600000:continue
            if abs(lb[0]['received_ms']-sb[0]['received_ms'])>5000:continue
            cl=consume(lb[1][0],r['base_quantity']);cs=consume(sb[1][1],r['base_quantity'])
            if cl is None or cs is None:continue
            bc=r['buy_cost'];sp=r['sell_proceeds'];fl=fee_bps(meta[lk])/10000;fs=fee_bps(meta[sk])/10000
            edge=(sp-bc+cl-cs-(bc+cl)*fl-(sp+cs)*fs)/bc*10000
            out.append({'asset':r['asset'],'buy_venue':lk[0],'buy_market':lk[1],'sell_venue':sk[0],'sell_market':sk[1],
                'target_notional':r['target_notional'],'entry_round':r['round'],'horizon_minutes':mins,'four_leg_net_bps':edge})
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=pathlib.Path);a=ap.parse_args()
    run=a.run or sorted((ROOT/'data/raw/comparators/rh_lighter').glob('*/manifest.json'))[-1].parent
    quality={}
    for mode in ('exclude','raw_token','shares'):
        plan,records=normalize(run,mode);obs,depth,reject,q=analyze_run(run,plan_override=plan,records_override=records)
        prefix='rh_lighter_perps' if mode=='exclude' else 'rh_lighter_spot_'+mode
        if mode!='exclude':obs=[r for r in obs if r['buy_kind']=='spot' or r['sell_kind']=='spot']
        csvwrite(OUT/(prefix+'_observations.csv'),obs);csvwrite(OUT/(prefix+'_summary.csv'),summarize(obs));csvwrite(OUT/(prefix+'_depth.csv'),depth)
        if mode=='exclude':csvwrite(OUT/'rh_lighter_roundtrip_scenarios.csv',unwind(obs,plan,records))
        quality[mode]=q
    (OUT/'rh_lighter_quality.json').write_text(json.dumps({'source':str(run.relative_to(ROOT)),'spot_modes_are_hypotheses_pending_venue_unit_verification':True,'quality':quality},indent=2)+'\n')
    print(json.dumps(quality,indent=2))
if __name__=='__main__':main()
