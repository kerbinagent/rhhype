"""Fixed August historical replication of the exploratory ETH collateral design."""
import datetime as dt
import gzip,hashlib,json,time,urllib.request,urllib.parse
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/core-eth-august-replication-allocation-v1.json'
OUT=ROOT/'reports/core-eth-august-replication'


def analyze(data):
    start,end=1785542400,1788220800
    candles={}
    for name in ('spot','perp','mark'):
        obj=json.loads(data[name],parse_float=D);assert obj['code']==200 and obj['r']=='1d'
        rows=sorted(obj['c'],key=lambda r:r['t'])
        assert [r['t'] for r in rows]==list(range(start*1000,end*1000,86400000))
        for r in rows:
            for k in 'ohlc':
                r[k]=D(r[k]);assert r[k].is_finite() and r[k]>0
            assert r['l']<=min(r['o'],r['c'])<=max(r['o'],r['c'])<=r['h']
        candles[name]=rows
    f=json.loads(data['funding']);assert f['code']==200 and f['resolution']=='1h'
    f=sorted(f['fundings'],key=lambda r:r['timestamp'])
    assert [r['timestamp'] for r in f]==list(range(start,end,3600))
    results=[]
    for i,j in ((0,31),(0,7),(7,14),(14,21),(21,28),(28,31)):
        s0,p0=candles['spot'][i]['o'],candles['perp'][i]['o']
        q=(D(1000)/s0).quantize(D('.0001'),rounding=ROUND_DOWN)
        principal=q*s0;cash=principal*D('.1');signed=[]
        for r in f:
            if start+i*86400<int(r['timestamp'])<start+j*86400:
                assert r['direction'] in ('long','short')
                v=D(r['value']);rate=D(r['rate'])
                assert v.is_finite() and rate.is_finite() and v>=0 and rate>=0
                signed.append((v,rate,D(1) if r['direction']=='long' else D(-1)))
        assert len(signed)==(j-i)*24-1
        funding=q*sum(v*sign for v,_,sign in signed)
        rates=sum(rate*sign*100 for _,rate,sign in signed)
        basis=q*(candles['spot'][j-1]['c']-s0+p0-candles['perp'][j-1]['c'])
        capital=(principal+cash)*D('.05')*(j-i)/365;stress=principal*D('.0005')
        initial=[];maintenance=[]
        for k in range(i,j):
            low,high=candles['spot'][k]['l'],candles['mark'][k]['h']
            portfolio=cash+q*(p0-high)
            initial.append(portfolio+D('.7')*q*low-D('.05')*q*high)
            maintenance.append(portfolio+D('.85')*q*low-D('.012')*q*high)
        results.append({'primary':i==0 and j==31,'start_day':i+1,'end_day':j,
            'funding_events':len(signed),'quantity_eth':str(q),'principal_usdc':str(principal),
            'funding_rate_sum_bps':str(rates),'inferred_funding_usdc':str(funding),
            'candle_basis_usdc':str(basis),'capital_usdc':str(capital),'stress_usdc':str(stress),
            'candle_residual_usdc':str(funding+basis-capital-stress),
            'price_only_imr_headroom_proxy':str(min(initial)),
            'price_only_mmr_headroom_proxy':str(min(maintenance))})
    return {'actual_pnl':None,'funding_value_units_inferred':True,'candles_not_executable':True,
            'current_margin_rules_not_verified_for_history':True,
            'full_month_overlaps_weekly_blocks':True,'results':results}


def main():
    p=PLAN.read_bytes();plan=json.loads(p)
    assert plan['requests_max']==4 and plan['retries']==0 and Path(__file__).stat().st_size<=8192
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(p).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    terminal={'status':'failed_no_retry','requests':0};data={};prov=[];size=0
    try:
        for name,endpoint,market,resolution,count in plan['requests']:
            if data:time.sleep(2)
            params={'market_id':market,'resolution':resolution,'start_timestamp':plan['window'][0],
                    'end_timestamp':plan['window'][1],'count_back':count}
            url='https://mainnet.zklighter.elliot.ai/api/v1/'+endpoint+'?'+urllib.parse.urlencode(params)
            terminal['requests']+=1
            req=urllib.request.Request(url,headers={'User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=15) as r:
                raw=r.read(262145);assert r.status==200 and len(raw)<=262144
            z=gzip.compress(raw,mtime=0);assert size+len(z)<=32768
            with (OUT/(name+'.json.gz')).open('xb') as f:f.write(z)
            size+=len(z);data[name]=raw
            prov.append({'name':name,'url':url,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                         'received_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'gzip_bytes':len(z)})
        result=analyze(data);result['provenance']=prov
        b=(json.dumps(result,indent=2)+'\n').encode();assert len(b)<=8192
        with (OUT/'summary.json').open('xb') as f:f.write(b)
        terminal.update(status='completed',summary_sha256=hashlib.sha256(b).hexdigest())
        print(json.dumps(result))
    except Exception as e:terminal['error']=str(e)[:300]
    b=(json.dumps(terminal)+'\n').encode()
    assert len(p)+(OUT/'claim.json').stat().st_size+len(b)<=8192
    with (OUT/'terminal.json').open('xb') as f:f.write(b)
    print(json.dumps(terminal))


if __name__=='__main__':main()
