"""Predeclared large-flow event diagnostic, not additional trades or P&L.

Includes all observed completed bins above the past-volume threshold, even when
price, depth, clocks or reference stability reject the trading hypothesis.
"""
import gzip,json,math,sys
from pathlib import Path
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_strategy import Features,pair_fresh,mid,NS,VENUES
from scripts.run_single_venue_study import inputs,PLAN,sha
SUPPLEMENT=ROOT/'reports/experiment-storage/single-venue-shock-diagnostic-v1.json'

def run(name,manifest_hash=None):
    supplement=json.loads(SUPPLEMENT.read_bytes())
    for pin in supplement['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    plan=json.loads(PLAN.read_bytes())
    _,digest,_,_,events=inputs(plan,name.removesuffix('-compact'),manifest_hash)
    f=Features();rows=[];seen=set();generation=0;ended=None
    for event in events:
        now=event['received_ns']
        if event['type']=='invalidate':generation+=1
        signals=f.process(event)
        if event['type']=='end':ended=event
        if event['type']!='book' or not pair_fresh(f.books,now):continue
        for row in rows:
            for h in (1,5,10,30):
                if str(h) in row['horizons'] or now<row['t']+h*NS:continue
                if generation!=row['generation']:target={'status':'invalidation_crossing'}
                elif now-row['t']-h*NS>250_000_000:target={'status':'missing_fresh_pair_in_250ms'}
                else:
                    returns={v:10000*math.log(mid(f.books[v])/row['mids'][v]) for v in VENUES}
                    other=VENUES[1] if row['venue']==VENUES[0] else VENUES[0]
                    target=dict(status='matched',t=now,returns_bps=returns,
                        favorable_target_return_bps=row['direction']*returns[row['venue']],
                        favorable_relative_return_bps=row['direction']*(returns[row['venue']]-returns[other]))
                row['horizons'][str(h)]=target
        if f.last_signal!=now:continue
        bucket=now//NS-1
        for v in VENUES:
            if (v,bucket) in seen:continue
            flow=f.flows[v].get(bucket)
            baseline=sorted((k,x['notional']) for k,x in f.flows[v].items() if now//NS-122<=k<=bucket-2)
            if not flow or len(baseline)<20 or baseline[-1][0]-baseline[0][0]<60:continue
            typical=median(x for _,x in baseline)
            if flow['notional']<5*typical:continue
            seen.add((v,bucket));other=VENUES[1] if v==VENUES[0] else VENUES[0]
            imbalance=(flow['buy_qty']-flow['sell_qty'])/(flow['buy_qty']+flow['sell_qty'])
            sign=1 if imbalance>0 else -1
            pre=next((p for p in reversed(f.points) if p['t']<=bucket*NS),None)
            current={k:mid(f.books[k]) for k in VENUES}
            spread=(float(f.books[v]['asks'][0][0])-float(f.books[v]['bids'][0][0]))/current[v]*10000
            prior=[(t,b) for t,b in f.refs if now-122*NS<=t<=now-2*NS]
            ref_ready=len(prior)>=60 and prior[-1][0]-prior[0][0]>=89*NS
            residual=((10000*math.log(current['lighter']/current['rh_lighter'])-median(x for _,x in prior))
                      *(1 if v=='lighter' else -1)) if ref_ready else None
            local=10000*math.log(current[v]/pre['mids'][v]) if pre else None
            other_move=10000*math.log(current[other]/pre['mids'][other]) if pre else None
            depth=pre['depth'][v]['buy' if sign==1 else 'sell'] if pre else None
            dominant=flow['buy_qty' if sign==1 else 'sell_qty']
            gates=dict(reference_ready=ref_ready, imbalance=abs(imbalance)>=.8,
                pre_clock=bool(pre and 0<=bucket*NS-pre['t']<=250_000_000 and all(pre['sources'][k]<=flow['min_source'] for k in VENUES)),
                post_clock=f.books[v]['source_ns']>=flow['max_source'],
                depth_fraction=bool(depth and dominant>=.25*depth),
                local_move=local is not None and sign*local>=2,
                reference_stable=other_move is not None and abs(other_move)<=1,
                residual_aligned=residual is not None and sign*residual>=3,
                cost_hurdle=residual is not None and abs(residual)>=spread+4)
            rule=any(s['rule']=='local_shock_fade' and s['venue']==v for s in signals)
            assert rule==all(gates.values())
            rows.append(dict(t=now,venue=v,bucket=bucket,generation=generation,direction=-sign,
                flow=flow,baseline_median_notional=typical,flow_multiple=flow['notional']/typical,
                dominant_quantity=dominant,pre_depth_quantity=depth,pre=pre,mids=current,
                local_move_bps=local,reference_move_bps=other_move,residual_bps=residual,
                spread_bps=spread,imbalance=imbalance,gates=gates,full_signal_pass=rule,horizons={}))
    assert ended
    for row in rows:
        for h in (1,5,10,30):row['horizons'].setdefault(str(h),dict(status='capture_ended_before_match'))
    summaries={}
    for v in VENUES:
        selected=[r for r in rows if r['venue']==v]
        summary={'large_flow_bins':len(selected),'full_rule_passes':sum(r['full_signal_pass'] for r in selected),
            'failed_gates':{g:sum(not r['gates'][g] for r in selected) for g in selected[0]['gates']} if selected else {},'horizons':{}}
        for h in (1,5,10,30):
            matched=[r['horizons'][str(h)] for r in selected if r['horizons'][str(h)]['status']=='matched']
            summary['horizons'][str(h)]=dict(n=len(matched),missing=len(selected)-len(matched),
                favorable_target_count=sum(r['favorable_target_return_bps']>0 for r in matched),
                mean_favorable_target_bps=mean(r['favorable_target_return_bps'] for r in matched) if matched else None,
                mean_favorable_relative_bps=mean(r['favorable_relative_return_bps'] for r in matched) if matched else None)
        summaries[v]=summary
    output=dict(sample=name,manifest_sha256=digest,supplement_sha256=sha(SUPPLEMENT),summary=summaries,rows=rows,
        limitations='Diagnostic only. No execution, spread/fees or portfolio profit. Alllargeflowbinsretained regardlessprice/depth/referencerejection. Overlapping dependent observations; no confidenceclaim. One-secondcompletedreceiptbins maymiss fasterrecovery. Incompletepre-eventsourceclocks explicitlyflagged; timestamps do notestablishcausality. Ordinaryprints only; liquidationfeedexcluded.')
    packed=gzip.compress((json.dumps(output,separators=(',',':'),allow_nan=False)+'\n').encode(),mtime=0);assert len(packed)<=32768
    out=ROOT/'reports/single-venue-research'/name/'shock-diagnostic.json.gz';assert not out.exists();out.write_bytes(packed)
    print(json.dumps(summaries,indent=2))

if __name__=='__main__':run(*sys.argv[1:])
