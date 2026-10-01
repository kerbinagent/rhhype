"""Offline, prior-only four-hour basis diagnostic on an existing candle archive."""
import datetime as dt
import hashlib
import json
import statistics
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/core-rh-four-hour-basis-allocation-v1.json'
OUT = ROOT/'reports/core-rh-four-hour-basis'
HOUR = 3600


def candles(path):
    obj=json.loads(path.read_bytes(),parse_float=D);assert obj['code']==200 and obj['r']=='1h'
    out={}
    for r in obj['c']:
        t=int(r['t'])//1000;assert int(r['t'])%1000==0 and t not in out
        z={k:D(str(r.get(k,0))) for k in ('o','h','l','c','V')}
        assert all(v.is_finite() for v in z.values()) and z['V']>=0
        assert z['l']>0 and z['l']<=min(z['o'],z['c'])<=max(z['o'],z['c'])<=z['h']
        out[t]=z
    return out


def funding(path):
    obj=json.loads(path.read_bytes());assert obj['code']==200 and obj['resolution']=='1h'
    out={}
    for r in obj['fundings']:
        t=int(r['timestamp']);assert t not in out and r['direction'] in ('long','short')
        v=D(r['value']);assert v.is_finite() and v>=0
        out[t]=v*(1 if r['direction']=='long' else -1)
    return out


def analyze_asset(asset, c, f, p):
    rows=[];meta=p['assets'][asset];step=D(meta['step']);minimum=D(meta['minimum'])
    for t in range(p['evaluation_start'],p['evaluation_end'],6*HOUR):
        row={'decision_time':t,'status':'unknown_signal'}
        past=list(range(t-25*HOUR,t,HOUR))
        if not all(h in v and v[h]['V']>=1000 for v in c for h in past):
            row['reason']='missing_or_low_volume_prior_candle';rows.append(row);continue
        basis=[D(10000)*(c[0][h]['c']/c[1][h]['c']-1) for h in past]
        center=statistics.median(basis[:-1]);deviation=basis[-1]-center
        row.update(last_basis_bps=str(basis[-1]),prior_24h_median_bps=str(center),deviation_bps=str(deviation))
        if abs(deviation)<10:
            row['status']='no_signal';rows.append(row);continue
        side=1 if deviation>0 else -1  # +1 = short Core, long RH
        entry,exit=t+HOUR,t+5*HOUR
        row.update(status='unknown_outcome',short_venue='core' if side==1 else 'rh',entry_time=entry,exit_time=exit)
        # Future volume is a coverage flag only; it never suppresses a signal.
        if exit>=p['evaluation_end'] or not all(h in v and v[h]['V']>=1000 for v in c for h in (entry,exit)):
            row['reason']='missing_or_low_volume_outcome_candle';rows.append(row);continue
        payment_hours=list(range(entry,exit+HOUR,HOUR))
        if not all(h in v for v in f for h in payment_hours):
            row['reason']='missing_funding';rows.append(row);continue
        a,b=c[0][entry]['o'],c[1][entry]['o'];x,y=c[0][exit]['o'],c[1][exit]['o']
        q=(D(1000)/max(a,b)/step).to_integral_value(rounding=ROUND_DOWN)*step
        if q<minimum or min(a,b)*q<10:
            row['reason']='quantity_below_market_minimum';rows.append(row);continue
        gross=q*side*(a-x+y-b)
        # Interior hours: inferred per-unit cash. At ambiguous entry/exit
        # boundaries include possible debits and exclude possible credits,
        # separately per venue, as an explicitly adverse timing sensitivity.
        payments=[]
        for h in payment_hours:
            values=(q*side*f[0][h],-q*side*f[1][h])
            payments.append(sum((min(v,D(0)) if h in (entry,exit) else v for v in values),D(0)))
        fund=sum(payments,D(0));capital=D(2000)*D('.05')*4/D(24*365);stress=D('.5')
        row.update(status='complete_candle_proxy',quantity=str(q),entry_core=str(a),entry_rh=str(b),
                   exit_core=str(x),exit_rh=str(y),basis_cash_proxy=str(gross),funding_inferred_proxy=str(fund),
                   capital_proxy=str(capital),stress_proxy=str(stress),
                   residual_proxy=str(gross+fund-capital-stress),actual_pnl=None)
        rows.append(row)
    complete=[x for x in rows if x['status']=='complete_candle_proxy']
    gains=[D(x['residual_proxy']) for x in complete]
    counts={s:sum(x['status']==s for x in rows) for s in sorted({x['status'] for x in rows})}
    return {'asset':asset,'primary':asset=='ETH','expected_decisions':40,'counts':counts,
            'complete_proxy_sum':str(sum(gains,D(0))) if complete else None,
            'positive_proxies':sum(x>0 for x in gains),'negative_proxies':sum(x<0 for x in gains),
            'zero_proxies':sum(x==0 for x in gains),'rows':rows}


def main():
    pb=PLAN.read_bytes();p=json.loads(pb)
    for pin in p['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(pb).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    terminal={'status':'failed_no_retry','network_requests':0}
    try:
        results=[]
        for a in ('ETH','BTC','SOL'):
            c=[candles(ROOT/v/'candles_30d'/f'{a}.json') for v in p['input_roots']]
            f=[funding(ROOT/v/'fundings_30d'/f'{a}.json') for v in p['input_roots']]
            results.append(analyze_asset(a,c,f,p))
        result={'assets':results,'expected_decisions':120,'actual_pnl':None,
                'historical_development_only':True,'candle_opens_not_synchronous_or_executable':True,
                'funding_value_units_inferred':True,'fixed_cost_scenario_not_verified_all_costs':True,
                'not_a_wallet_or_margin_simulation':True,'independent_asset_diagnostics_not_one_portfolio':True}
        b=(json.dumps(result,indent=2)+'\n').encode();assert len(b)<=81920
        with (OUT/'summary.json').open('xb') as f:f.write(b)
        terminal.update(status='completed_offline',summary_sha256=hashlib.sha256(b).hexdigest())
        print(json.dumps([{k:v for k,v in x.items() if k!='rows'} for x in results]))
    except Exception as e:terminal['error']=str(e)[:300]
    tb=(json.dumps(terminal)+'\n').encode();assert len(tb)+len(pb)+(OUT/'claim.json').stat().st_size<=16384
    assert Path(__file__).stat().st_size<=16384
    with (OUT/'terminal.json').open('xb') as f:f.write(tb)
    print(json.dumps(terminal))


if __name__=='__main__':main()
