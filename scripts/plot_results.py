#!/usr/bin/env python3
"""Publication-style static figures from derived survey tables (offline)."""
import csv,pathlib,collections,statistics,os
os.environ.setdefault("MPLCONFIGDIR","/tmp/rhhype-mpl-cache")
os.environ.setdefault("XDG_CACHE_HOME","/tmp/rhhype-cache")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1];D=ROOT/'data/derived';OUT=ROOT/'reports/figures';OUT.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150,'savefig.bbox':'tight'})

def rows(name):return list(csv.DictReader((D/name).open()))
def save(fig,name):
    fig.savefig(OUT/(name+'.png'));fig.savefig(OUT/(name+'.svg'));plt.close(fig)

def main():
    r=[x for x in rows('robinhood_summary.csv') if float(x['target_notional'])==10000];best={}
    for x in r:
        if x['symbol'] not in best or float(x['median_bps'])>float(best[x['symbol']]['median_bps']):best[x['symbol']]=x
    r=sorted(best.values(),key=lambda x:float(x['median_bps']))
    fig,ax=plt.subplots(figsize=(9,7));v=[float(x['median_bps']) for x in r];y=np.arange(len(r))
    ax.barh(y,v,color='#bf5963');ax.set_yticks(y,[x['symbol'] for x in r]);ax.axvline(0,color='black',lw=.8)
    ax.set_xlabel('Better of the two directions: median entry edge (bp)');ax.set_title('Robinhood Uniswap ↔ Hyperliquid: $10,000 size\nAfter pool fee/impact and HL entry fee; before gas and conversion',loc='left')
    ax.grid(axis='x',alpha=.2);fig.text(.12,-.01,'Reverse direction needs token inventory or borrow. Token/share multipliers applied.\nDifferent assets have different sample counts; this chart does not show realized profit.',fontsize=9)
    save(fig,'robinhood_amm')
    r=[x for x in rows('rh_lighter_perps_summary.csv') if float(x['target_notional'])==10000]
    r=sorted(r,key=lambda x:float(x['net_median_bps']),reverse=True)[:12][::-1]
    fig,ax=plt.subplots(figsize=(9,6));y=np.arange(len(r));med=np.array([float(x['net_median_bps']) for x in r]);lo=np.array([float(x['net_p05_bps']) for x in r]);hi=np.array([float(x['net_p95_bps']) for x in r]);prem=[float(x['premium_net_median_bps']) for x in r]
    ax.errorbar(med,y,xerr=[med-lo,hi-med],fmt='o',color='#087f8c',capsize=3,label='Standard: median, 5–95% observed range')
    ax.scatter(prem,y,marker='x',color='#a44646',label='Premium fee scenario: median')
    ax.set_yticks(y,[f"{x['asset']} ({x['samples']} samples)" for x in r]);ax.axvline(0,color='black',lw=.8);ax.axvline(5,color='gray',ls=':',label='5 bp additional cost')
    ax.set_xlabel('Size-aware entry edge after both opening fees (bp)');ax.set_title('Robinhood Lighter perps ↔ Hyperliquid: $10,000\nOpening positions does not realize this spread',loc='left');ax.legend(fontsize=8,loc='lower right');ax.grid(axis='x',alpha=.2)
    save(fig,'rh_lighter_entries')
    paths=sorted(D.glob('history*/history_perp_pairs.csv'));r=list(csv.DictReader(paths[-1].open()));selected=[x for x in r if x['venue']=='aster' and x['match_type']=='same_underlying']
    cash=list(csv.DictReader(sorted(D.glob('history*/history_cash_carry.csv'))[-1].open()));rs=[]
    for x in selected:rs.append((x['hl_coin']+' / Aster',float(x['gross_minus_known_fees_bps']),.05*.4*10/365*1e4))
    for x in cash:rs.append((x['perp_coin']+' spot / HL perp',float(x['gross_minus_known_fees_bps']),.05*1.2*10/365*1e4))
    fig,ax=plt.subplots(figsize=(9,6));y=np.arange(len(rs));ax.barh(y,[x[1] for x in rs],height=.65,color='#a8c9c8',label='After current taker fees');ax.scatter([x[1]-x[2] for x in rs],y,marker='D',color='#0b5351',label='Also after illustrative capital cost')
    ax.set_yticks(y,[x[0] for x in rs]);ax.axvline(0,color='black',lw=.8);ax.set_xlabel('Ten-day modeled result / initial matched notional (bp)');ax.set_title('Historical holdout: fees and capital shrink carry\nFunding plus candle-close basis change; excludes bid/ask and impact',loc='left');ax.legend(fontsize=8);ax.grid(axis='x',alpha=.2)
    fig.text(.12,-.025,'20-day training / 10-day holdout. Current fee schedule applied retrospectively.\n5% annual capital charge on 40% notional for perp pairs; 120% for spot + perp. Not realized P&L.',fontsize=9)
    save(fig,'historical_costs')
    if (D/'rh_lighter_roundtrip_scenarios.csv').exists():
        r=rows('rh_lighter_roundtrip_scenarios.csv');g=collections.defaultdict(list)
        for x in r:
            if float(x['target_notional'])==10000 and int(x['horizon_minutes'])==5:g[x['asset']].append(float(x['four_leg_net_bps']))
        if g:
            keys=sorted(g,key=lambda k:statistics.median(g[k]));fig,ax=plt.subplots(figsize=(9,5));ax.boxplot([g[k] for k in keys],orientation='horizontal',tick_labels=keys,showfliers=False)
            ax.axvline(0,color='black',lw=.8);ax.set_xlabel('Entry plus five-minute unwind, four trading fees included (bp)');ax.set_title('Did positive Robinhood Lighter entry signals cover an unwind?\n$10,000; independent overlapping scenarios, not summed profits',loc='left');ax.grid(axis='x',alpha=.2);save(fig,'rh_lighter_unwind')
    print('Figures:',', '.join(p.name for p in OUT.glob('*.png')))
if __name__=='__main__':main()
