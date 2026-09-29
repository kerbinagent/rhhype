#!/usr/bin/env python3
"""Static-basis RH maker/taker-exit quote hurdle on a stopped, pre-pilot archive.

This computes displayed-book costs only. It does not infer maker fills, future
prices, realized cash, or profitability. The input cutoff excludes the new pilot.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'reports/maker-book-archive-v1/derived/book-events.jsonl.gz'
MANIFEST = ROOT / 'reports/maker-book-archive-v1/derived/manifest.json'
DIAGNOSTICS = ROOT / 'reports/maker-book-archive-v1/derived/rh-anchor-diagnostics.json'
MARKET_PLAN = ROOT / 'reports/maker-equity-v2/market-plan.json'
CUTOFF_NS = int(datetime(2026,9,29,21,21,32,tzinfo=timezone.utc).timestamp()*1_000_000_000)
SIZES = (100,250,500,1000)
NS = 1_000_000_000


def percentile(values, p):
    if not values: return None
    v=sorted(values); i=(len(v)-1)*p; lo=int(i); hi=min(lo+1,len(v)-1)
    return v[lo]+(v[hi]-v[lo])*(i-lo)


def walk(levels, q):
    left=q; total=0.0
    for price,size in levels:
        p,s=float(price),float(size)
        if not (math.isfinite(p) and math.isfinite(s) and p>0 and s>=0):
            raise ValueError('invalid displayed level')
        x=min(s,left); total+=p*x; left-=x
        if left<=q*1e-12: return total
    return None


def quantity(budget, ask, step):
    q=(Decimal(str(budget))/Decimal(str(ask))/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(step))
    return float(q) if q>0 else None


def cost_at_bid(p,q,rh_bid_exit,hl_bid_entry,hl_ask_exit,hl_taker_bps):
    """Projected completed cash under unchanged books and RH bid taker exit."""
    rh_entry=p*q
    gross=hl_bid_entry-rh_entry+rh_bid_exit-hl_ask_exit
    fees=(hl_bid_entry+hl_ask_exit)*hl_taker_bps/10000  # RH Standard 0/0 bp
    reserve=max(rh_entry,hl_bid_entry)*5/10000
    capital=(rh_entry+hl_bid_entry)*.05*10/(365*24*3600)
    return gross-fees-reserve-capital-.10


def required_discount(rh_best,q,rh_bid_exit,hl_bid_entry,hl_ask_exit,hl_fee):
    """Continuous-grid bid reduction from RH best to meet the $0.10 target."""
    if cost_at_bid(rh_best,q,rh_bid_exit,hl_bid_entry,hl_ask_exit,hl_fee)>=0:
        return 0.0
    if cost_at_bid(0,q,rh_bid_exit,hl_bid_entry,hl_ask_exit,hl_fee)<0:
        return None
    lo,hi=0.0,rh_best
    for _ in range(60):
        mid=(lo+hi)/2
        if cost_at_bid(mid,q,rh_bid_exit,hl_bid_entry,hl_ask_exit,hl_fee)>=0: lo=mid
        else: hi=mid
    return (rh_best-lo)/rh_best*10000


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()


def analyze(archive=ARCHIVE,manifest=MANIFEST,diagnostics=DIAGNOSTICS,market_plan=MARKET_PLAN):
    archive,manifest,diagnostics,market_plan=map(Path,(archive,manifest,diagnostics,market_plan))
    meta=json.loads(manifest.read_text())
    if archive.stat().st_size>25_000_000 or archive.stat().st_size!=meta['output_gzip_bytes'] or _sha(archive)!=meta['output_gzip_sha256']:
        raise ValueError('stopped archive size/hash mismatch')
    anchor_rows=json.loads(diagnostics.read_text())
    if len(anchor_rows)>200 or any(int(x['anchor_utc_ns'])>=CUTOFF_NS for x in anchor_rows):
        raise ValueError('anchors exceed declared pre-pilot cutoff/bound')
    plan=json.loads(market_plan.read_text())
    pairs={x['asset']:x for x in plan['pairs'] if x['asset'] in ('NVDA','XAG')}
    if set(pairs)!={'NVDA','XAG'} or int(plan['source_updated_at']*NS)>=CUTOFF_NS:
        raise ValueError('market metadata not pre-pilot')
    series=defaultdict(list); n=0
    with gzip.open(archive,'rt') as f:
        for line in f:
            n+=1
            if n>6000: raise ValueError('archive event bound exceeded')
            e=json.loads(line)
            if int(e['receipt_utc_ns'])>=CUTOFF_NS: raise ValueError('post-pilot event')
            key=(e.get('venue'),e.get('asset'))
            if key[0] in ('rh_lighter','hyperliquid') and key[1] in pairs:
                series[key].append(e)
    times={k:[int(e['receipt_utc_ns']) for e in rows] for k,rows in series.items()}
    if any(v!=sorted(v) for v in times.values()): raise ValueError('archive not receipt ordered')
    def latest(key,anchor):
        idx=bisect.bisect_right(times.get(key,()),anchor)-1
        if idx<0:return None
        e=series[key][idx]; receipt=int(e['receipt_utc_ns']); source=e.get('source_utc_ns')
        if (not e.get('valid') or not isinstance(source,int) or not 0<=receipt-source
                or not 0<=anchor-receipt<=NS or not 0<=anchor-source<=2*NS): return None
        return e
    rows=[]; counts=Counter(); rh_only=defaultdict(list)
    for a in anchor_rows:
        asset=a['asset'];anchor=int(a['anchor_utc_ns']);counts[f'{asset}:anchors']+=1
        rh=latest(('rh_lighter',asset),anchor);hl=latest(('hyperliquid',asset),anchor)
        if rh is not None:
            rb,ra=float(rh['bids'][0][0]),float(rh['asks'][0][0])
            if 0<rb<ra:
                rh_only[asset].append(10000*(ra-rb)/rb)
        if rh is None or hl is None:
            counts[f'{asset}:pair_missing_or_stale']+=1;continue
        if (abs(rh['source_utc_ns']-hl['source_utc_ns'])>NS or
                abs(rh['receipt_utc_ns']-hl['receipt_utc_ns'])>NS):
            counts[f'{asset}:pair_skew']+=1;continue
        rh_bid=float(rh['bids'][0][0]);rh_ask=float(rh['asks'][0][0])
        if rh_bid<=0 or rh_bid>=rh_ask:
            counts[f'{asset}:crossed']+=1;continue
        p=pairs[asset];step=p['rh_lighter']['step'] if 'rh_lighter' in p else p['other']['step']
        hl_fee=float(p['hl']['fee_bps'])
        for budget in SIZES:
            q=quantity(budget,rh_ask,step)
            if q is None: continue
            rh_sell=walk(rh['bids'],q);hl_sell=walk(hl['bids'],q);hl_buy=walk(hl['asks'],q)
            if None in (rh_sell,hl_sell,hl_buy):
                counts[f'{asset}:{budget}:shallow']+=1;continue
            if q*rh_bid<float(p['rh_lighter']['min_notional'] if 'rh_lighter' in p else p['other']['min_notional']) or hl_sell<float(p['hl']['min_notional']):
                counts[f'{asset}:{budget}:minimum']+=1;continue
            gap=required_discount(rh_bid,q,rh_sell,hl_sell,hl_buy,hl_fee)
            if gap is None:
                counts[f'{asset}:{budget}:no_nonnegative_bid_meets_target']+=1;continue
            rows.append({'asset':asset,'budget_usd':budget,'anchor_ns':anchor,'quantity':q,
                         'rh_spread_bps':10000*(rh_ask-rh_bid)/rh_bid,
                         'hl_walk_spread_bps':10000*(hl_buy-hl_sell)/hl_sell,
                         'required_below_rh_best_bps':gap,
                         'net_at_rh_best_after_target_usd':cost_at_bid(rh_bid,q,rh_sell,hl_sell,hl_buy,hl_fee),
                         'hypothetical_b_best_ask_after_target_usd':cost_at_bid(rh_bid,q,rh_ask*q,hl_sell,hl_buy,hl_fee),
                         'rh_best_bid':rh_bid,'rh_best_ask':rh_ask,'hl_fee_bps_each':hl_fee})
    summary={}
    for asset in ('NVDA','XAG'):
        for budget in SIZES:
            r=[x for x in rows if x['asset']==asset and x['budget_usd']==budget]
            def stats(field):
                v=[x[field] for x in r]
                return {'p10':percentile(v,.1),'median':percentile(v,.5),'p90':percentile(v,.9)}
            summary[f'{asset}|{budget}']={'n':len(r),'of_anchors':counts[f'{asset}:anchors'],
                'rh_spread_bps':stats('rh_spread_bps'),'hl_walk_spread_bps':stats('hl_walk_spread_bps'),
                'required_below_rh_best_bps':stats('required_below_rh_best_bps'),
                'net_at_rh_best_after_target_usd':stats('net_at_rh_best_after_target_usd'),
                'hypothetical_b_best_ask_after_target_usd':stats('hypothetical_b_best_ask_after_target_usd')}
    rh_only_summary={asset:{'n':len(rh_only[asset]),'of_anchors':counts[f'{asset}:anchors'],
                            'spread_bps':{'p10':percentile(rh_only[asset],.1),
                                          'median':percentile(rh_only[asset],.5),
                                          'p90':percentile(rh_only[asset],.9)}}
                     for asset in ('NVDA','XAG')}
    return {'kind':'static_displayed_quote_hurdle_not_fill_or_profit',
            'source':'stopped_pre_2026-09-29T21:21:32Z_NVDA_XAG_fullbook_archive',
            'archive_sha256':_sha(archive),'market_plan_sha256':_sha(market_plan),
            'assumptions':{'rh_standard_fees_bps':[0,0],'hl_taker_bps_each':'pre_pilot_market_plan',
                           'reserve_bps':5,'target_usd':.10,'capital_annual_rate':.05,
                           'capital_hold_seconds':10,'future_prices':'unchanged_displayed_books',
                           'quote_tick':'continuous_grid_only_not_order_validated'},
            'counts':dict(counts),'rh_only_summary':rh_only_summary,
            'summary':summary,'retained_rows':rows}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    result=analyze()
    payload=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload)
    else: print(payload,end='')


if __name__=='__main__':main()
