#!/usr/bin/env python3
"""Observed 5/15-minute hypothetical unwind of positive-entry signals.
Independent overlapping scenarios; not a portfolio backtest. Skip funding boundaries.
"""
import argparse,collections,csv,json,pathlib,statistics
from analyze_live import levels,consume,fee_bps,csvwrite,quantile
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=pathlib.Path);a=ap.parse_args()
    run=a.run or sorted((ROOT/'data/raw/live').glob('*/manifest.json'))[-1].parent
    meta={(m['venue'],str(m['market'])):m for m in json.loads((run/'plan.json').read_text())}
    book={}
    for line in (run/'books.jsonl').open():
        r=json.loads(line)
        if 'error'in r:continue
        try:r['levels_parsed']=levels(r)
        except (ValueError,KeyError):continue
        if r.get('venue_time_ms') and r['received_ms']-r['venue_time_ms']>5000:continue
        book[(r['round'],r['venue'],str(r['market']))]=r
    obs=list(csv.DictReader(open(ROOT/'data/derived/live_observations.csv')));out=[]
    interval=json.loads((run/'manifest.json').read_text())['interval_seconds']
    for r in obs:
        if float(r['net_entry_bps'])<=0 or r['requires_spot_borrow_or_inventory']=='True':continue
        i=int(r['round']);t=int(r['timestamp_ms']);q=float(r['base_quantity']);bc=float(r['buy_cost']);sp=float(r['sell_proceeds'])
        for horizon in (5,15):
            j=i+round(horizon*60/interval)
            longkey=(r['buy_venue'],str(r['buy_market']));shortkey=(r['sell_venue'],str(r['sell_market']))
            lb=book.get((j,*longkey));sb=book.get((j,*shortkey))
            if not lb or not sb:continue
            end=max(lb['received_ms'],sb['received_ms'])
            # Unknown funding cannot be silently treated as zero: admit only same UTC hour.
            if end//3600000 != t//3600000:continue
            if abs(lb['received_ms']-sb['received_ms'])>5000:continue
            close_long=consume(lb['levels_parsed'][0],q);close_short=consume(sb['levels_parsed'][1],q)
            if close_long is None or close_short is None:continue
            fl=fee_bps(meta[longkey])/10000;fs=fee_bps(meta[shortkey])/10000
            net=(sp-bc+close_long-close_short-(bc+close_long)*fl-(sp+close_short)*fs)/bc*10000
            out.append({'asset':r['asset'],'buy_venue':r['buy_venue'],'buy_market':r['buy_market'],'sell_venue':r['sell_venue'],
                'sell_market':r['sell_market'],'target_notional':r['target_notional'],'entry_round':i,'exit_round':j,
                'horizon_minutes':horizon,'actual_hold_minutes':(end-t)/60000,'entry_net_bps':float(r['net_entry_bps']),
                'four_leg_net_bps':net,'entry_ms':t,'exit_ms':end,'funding_boundary_crossed':False})
    groups=collections.defaultdict(list)
    for r in out:groups[(r['asset'],r['buy_venue'],r['buy_market'],r['sell_venue'],r['sell_market'],r['target_notional'],r['horizon_minutes'])].append(r)
    summary=[]
    for k,rs in groups.items():
        x=[r['four_leg_net_bps'] for r in rs]
        summary.append(dict(zip(('asset','buy_venue','buy_market','sell_venue','sell_market','target_notional','horizon_minutes'),k))|{
            'scenarios':len(x),'net_min_bps':min(x),'net_median_bps':statistics.median(x),'net_max_bps':max(x),
            'positive_scenarios':sum(v>0 for v in x),'positive_fraction':sum(v>0 for v in x)/len(x)})
    csvwrite(ROOT/'data/derived/roundtrip_scenarios.csv',out);csvwrite(ROOT/'data/derived/roundtrip_summary.csv',summary)
    print('Independent overlapping unwind scenarios:',len(out),'positive:',sum(r['four_leg_net_bps']>0 for r in out))
if __name__=='__main__':main()
