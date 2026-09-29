#!/usr/bin/env python3
"""Cost-hurdle decomposition of the stopped fixed-quantity quote snapshot.

No refit, fills, trade P&L, or dynamic exit optimization is inferred.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'reports/fixed-markout-v1/fixed_markout_snapshot.json.gz'
OUTPUT=ROOT/'reports/strategy-convergence-followup/fixed-horizon-hurdle.json'
MAX_INPUT_BYTES=20_000_000
MAX_DECODED_BYTES=10_000_000
MAX_ROWS=5000
TARGET=.10


def load_snapshot(path, *, max_decoded_bytes=MAX_DECODED_BYTES):
    """Read a stopped snapshot with bounds on compressed and expanded bytes."""
    path=Path(path)
    if not 0<max_decoded_bytes<=MAX_DECODED_BYTES:
        raise ValueError('invalid decoded input bound')
    if path.stat().st_size>MAX_INPUT_BYTES:
        raise ValueError('snapshot exceeds compressed input bound')
    with gzip.open(path,'rb') as f:
        raw=f.read(max_decoded_bytes+1)
    if len(raw)>max_decoded_bytes:
        raise ValueError('snapshot exceeds decoded input bound')
    return json.loads(raw)


def _finite(value,label):
    x=float(value)
    if not math.isfinite(x):raise ValueError(f'nonfinite {label}')
    return x


def _summary(values):
    if not values:return {'n':0,'p10':None,'median':None,'p90':None,'mean':None}
    a=sorted(values)
    def quant(p):
        t=(len(a)-1)*p;lo=int(t);hi=min(lo+1,len(a)-1)
        return a[lo]+(a[hi]-a[lo])*(t-lo)
    return {'n':len(a),'p10':quant(.1),'median':quant(.5),'p90':quant(.9),
            'mean':sum(a)/len(a)}


def analyze(snapshot):
    fixed=snapshot['fixed_markout'];counts=fixed['counts']
    if snapshot.get('status')!='stopped' or fixed.get('finished') is not True:
        raise ValueError('snapshot must be stopped and finished')
    if _finite(fixed.get('extra_cost_bps'),'extra_cost_bps')!=5:
        raise ValueError('unexpected reserve assumption')
    margin=_finite(fixed.get('margin_fraction'),'margin_fraction')
    capital_rate=_finite(fixed.get('capital_rate'),'capital_rate')
    if margin<0 or capital_rate<0:raise ValueError('invalid capital assumption')
    rows=fixed['terminal_rows']
    if not isinstance(rows,list) or len(rows)>MAX_ROWS:raise ValueError('oversized terminal export')
    if (counts['anchors']!=len(rows)+counts.get('terminal_export_dropped',0)
            or counts['matched_anchors']!=sum(r['status']=='matched' for r in rows)
            or counts['censored_anchors']!=sum(r['status']=='censored' for r in rows)):
        raise ValueError('terminal conservation mismatch')
    if counts.get('terminal_export_dropped'):
        raise ValueError('retained rows truncated; this diagnostic requires all anchors')
    metrics={name:[] for name in ('opening_spread','anchor_closing_liability','instant_gross',
       'instant_four_fee_net','instant_after_reserve','fee_required_gain',
       'reserve_required_gain','realized_gain_fee','realized_gain_after_reserve',
       'future_four_fee_net','future_after_reserve','fees_now','reserve_now')}
    censor=Counter();by_route={};matched=0;four_fee_positive=0;four_fee_target=0
    reserve_positive=0;reserve_target=0;open_positive=0;open_gt_cost=0
    instant_gross_positive=0;instant_fee_positive=0;instant_reserve_positive=0
    matched_instant=[];matched_required=[]
    opening_cohort={'anchors':0,'matched':0,'censored':0,
                    'future_four_fee_ge_target':0,'future_after_reserve_ge_target':0}
    opening_cohort_gains=[];opening_cohort_requirements=[]
    for i,r in enumerate(rows):
        route=r.get('route')
        if not isinstance(route,str) or not route:raise ValueError('missing route')
        a=_finite(r['entry_buy_value'],f'{i}.buy_entry')
        b=_finite(r['entry_sell_value'],f'{i}.sell_entry')
        q=_finite(r['quantity'],f'{i}.original_quantity')
        l=_finite(r['anchor_long_liquidation_value'],f'{i}.long_exit')
        s=_finite(r['anchor_short_buyback_value'],f'{i}.short_exit')
        br=_finite(r['buy_fee_bps'],f'{i}.buy_fee')/10000
        sr=_finite(r['sell_fee_bps'],f'{i}.sell_fee')/10000
        if min(q,a,b,l,s)<=0 or not 0<=br<=1 or not 0<=sr<=1:raise ValueError('invalid economics')
        opening=b-a;closing=s-l;gross0=opening-closing
        fees0=(a+l)*br+(b+s)*sr
        reserve0=5/10000*max(a,b)
        fee0=gross0-fees0
        reserved0=fee0-reserve0
        for name,value in [('opening_spread',opening),('anchor_closing_liability',closing),
          ('instant_gross',gross0),('instant_four_fee_net',fee0),
          ('instant_after_reserve',reserved0),('fee_required_gain',TARGET-fee0),
          ('reserve_required_gain',TARGET-reserved0),('fees_now',fees0),('reserve_now',reserve0)]:
            metrics[name].append(value)
        open_positive+=opening>0
        instant_gross_positive+=gross0>0
        instant_fee_positive+=fee0>0
        instant_reserve_positive+=reserved0>0
        opening_screen=opening>fees0+reserve0+TARGET
        open_gt_cost+=opening_screen
        if opening_screen:
            opening_cohort['anchors']+=1
            opening_cohort_requirements.append(TARGET-reserved0)
        if r['status']=='censored':
            censor[r.get('censor_reason') or 'unknown']+=1
            if opening_screen:opening_cohort['censored']+=1
            continue
        if r['status']!='matched':raise ValueError('invalid terminal status')
        matched+=1
        matched_instant.append(reserved0)
        matched_required.append(TARGET-reserved0)
        if opening_screen:opening_cohort['matched']+=1
        fee_future=_finite(r['net_after_four_fees_usd'],f'{i}.future_fee')
        reserve_future=_finite(r['net_after_reserves_usd'],f'{i}.future_reserved')
        gross_future=_finite(r['gross_capture_usd'],f'{i}.future_gross')
        long_exit=_finite(r['exit_long_value'],f'{i}.exit_long')
        short_exit=_finite(r['exit_short_buyback_value'],f'{i}.exit_short')
        if min(long_exit,short_exit)<=0:raise ValueError('invalid future exit notional')
        if abs(gross_future-(b-a+long_exit-short_exit))>1e-6:
            raise ValueError('future cash identity mismatch')
        expected_fees={'buy_entry_fee_usd':a*br,'sell_entry_fee_usd':b*sr,
                       'buy_exit_fee_usd':long_exit*br,
                       'sell_exit_fee_usd':short_exit*sr}
        for name,expected in expected_fees.items():
            if abs(_finite(r[name],f'{i}.{name}')-expected)>1e-6:
                raise ValueError(f'{name} not charged on own notional')
        total_fees=_finite(r['total_four_fees_usd'],f'{i}.future_fees')
        if abs(total_fees-sum(expected_fees.values()))>1e-6:
            raise ValueError('four fee total mismatch')
        if abs(fee_future-(gross_future-total_fees))>1e-6:
            raise ValueError('future fee identity mismatch')
        actual_reserve=_finite(r['extra_cost_reserve_usd'],f'{i}.future_reserve')
        age=_finite(r['capital_elapsed_seconds'],f'{i}.capital_elapsed')
        capital=_finite(r['capital_reserve_usd'],f'{i}.capital_reserve')
        if age<0 or capital<0 or abs(actual_reserve-reserve0)>1e-6:
            raise ValueError('future reserve identity mismatch')
        if abs(age-(_finite(r['outcome_time'],'outcome_time')-
                    _finite(r['anchor_time'],'anchor_time')))>1e-6:
            raise ValueError('capital elapsed time mismatch')
        expected_capital=(a+b)*margin*capital_rate*age/(365*86400)
        if abs(capital-expected_capital)>1e-6:
            raise ValueError('capital reserve identity mismatch')
        if abs(reserve_future-(fee_future-actual_reserve-capital))>1e-6:
            raise ValueError('future after-reserve identity mismatch')
        metrics['future_four_fee_net'].append(fee_future)
        metrics['future_after_reserve'].append(reserve_future)
        metrics['realized_gain_fee'].append(fee_future-fee0)
        metrics['realized_gain_after_reserve'].append(reserve_future-reserved0)
        four_fee_positive+=fee_future>0
        four_fee_target+=fee_future>=TARGET
        reserve_positive+=reserve_future>0
        reserve_target+=reserve_future>=TARGET
        if opening_screen:
            opening_cohort['future_four_fee_ge_target']+=fee_future>=TARGET
            opening_cohort['future_after_reserve_ge_target']+=reserve_future>=TARGET
            opening_cohort_gains.append(reserve_future-reserved0)
        state=by_route.setdefault(route,{'matched':0,'four_fee_target':0,'reserve_target':0})
        state['matched']+=1;state['four_fee_target']+=fee_future>=TARGET
        state['reserve_target']+=reserve_future>=TARGET
    return {'classification':'stopped quote-only fixed 12-16s horizon; not fills or actual P&L',
      'target_usd':TARGET,'retained_all_anchor_count':len(rows),'all_run_counts':dict(counts),
      'censor_reasons':dict(censor),'oracle_on_observed_matched_only':{
        'matched':matched,'four_fee_positive':four_fee_positive,'four_fee_ge_target':four_fee_target,
        'after_reserve_positive':reserve_positive,'after_reserve_ge_target':reserve_target,
        'not_a_bound_for_censored_outcomes':True},
      'opening_spread_positive_anchors':open_positive,
      'instantaneous_liquidation_positive_counts':{'gross':instant_gross_positive,
           'after_four_fees':instant_fee_positive,'after_reserve':instant_reserve_positive},
      'opening_spread_gt_instant_fees_reserve_target_anchors':open_gt_cost,
      'opening_screen_cohort':{**opening_cohort,
          'required_gain_after_reserve_usd':_summary(opening_cohort_requirements),
          'realized_gain_after_reserve_usd_matched_only':_summary(opening_cohort_gains)},
      'matched_only_instant_after_reserve_usd':_summary(matched_instant),
      'matched_only_required_gain_after_reserve_usd':_summary(matched_required),
      'distributions_usd':{k:_summary(v) for k,v in metrics.items()},
      'by_route_oracle_counts':by_route,
      'limitations':['Instantaneous liquidation uses the original anchor book and same original quantity; no order latency.',
                     'Future outcome is the first eligible 12-16s paired quote only; no intervening path or stop rule.',
                     'Censored future depth/timing is unknown, never scored as zero or a loss.',
                     '5bp reserve is a risk allowance, not an exchange fee.',
                     'Overlapping horizons and opposite directions share books.']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=INPUT)
    ap.add_argument('--output',type=Path,default=OUTPUT)
    args=ap.parse_args()
    snapshot=load_snapshot(args.input)
    sha=hashlib.sha256()
    with args.input.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):
            sha.update(chunk)
    digest=sha.hexdigest()
    result=analyze(snapshot)
    result['input_sha256']=digest
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
