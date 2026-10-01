"""Public metadata and simulated-margin checks for staked-ETH carry; no accounts."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/derive-staked-eth-preflight-allocation-v1.json'
OUT=ROOT/'reports/derive-staked-eth-preflight'


def main():
    pb=PLAN.read_bytes();p=json.loads(pb)
    assert hashlib.sha256((ROOT/p['previous']).read_bytes()).hexdigest()==p['previous_sha256']
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    claim={'plan_sha256':hashlib.sha256(pb).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    terminal={'status':'failed_no_retry','requests':0,'provenance':[]};packed_total=0;data={}
    def fetch(name,url,body,cap):
        nonlocal packed_total
        if terminal['requests']:time.sleep(.5)
        terminal['requests']+=1;assert terminal['requests']<=16
        req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
                                   headers={'Content-Type':'application/json','User-Agent':'rhhype-public-research/1.0'})
        try:r=urllib.request.urlopen(req,timeout=15)
        except urllib.error.HTTPError as e:r=e
        with r:raw=r.read(cap+1);code=r.status
        assert len(raw)<=cap
        z=gzip.compress(raw,mtime=0);assert packed_total+len(z)<=65536
        with (OUT/(name+'.gz')).open('xb') as f:f.write(z)
        packed_total+=len(z)
        terminal['provenance'].append({'name':name,'url':url,'body':body,'http_status':code,
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'gzip_bytes':len(z),'received_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
        assert code==200, f'HTTP{code}'
        return raw
    try:
        for name,url,body,cap in p['requests']:
            data[name]=fetch(name,url,body,cap)
        eth=json.loads(data['eth_currency'])['result'];wst=json.loads(data['wsteth_currency'])['result']
        inst=json.loads(data['eth_perp'])['result']
        assert inst['instrument_name']=='ETH-PERP' and inst['is_active'] and inst['quote_currency']=='USDC'
        eprice,wprice=D(eth['spot_price']),D(wst['spot_price'])
        assert eprice>0 and wprice>eprice and wprice<2*eprice
        step=D(inst['amount_step']);q=(D(1000)/eprice/step).to_integral_value(rounding=ROUND_DOWN)*step
        assert q>=D(inst['minimum_amount'])
        principal=q*eprice;wq=(principal/wprice).quantize(D('.000000000000000001'),rounding=ROUND_DOWN)
        scenarios=[]
        for mode in ('SM','PM2'):
            for fraction in ('0','.1','.25','.5'):
                cash=principal*D(fraction)
                body={'margin_type':mode,'simulated_collaterals':[{'asset_name':'WSTETH','amount':str(wq)},
                      {'asset_name':'USDC','amount':str(cash)}],'simulated_positions':[],
                      'simulated_position_changes':[{'instrument_name':'ETH-PERP','amount':str(-q)}]}
                if mode=='PM2':body['market']='ETH'
                name=mode+'_'+fraction.replace('.','p')
                raw=fetch(name,p['margin_url'],body,65536);obj=json.loads(raw)
                scenarios.append({'mode':mode,'cash_fraction':fraction,'cash_usdc':str(cash),'result':obj.get('result'),
                                  'error':obj.get('error')})
        summary={'eth_spot':str(eprice),'wsteth_spot':str(wprice),'short_eth_quantity':str(q),
                 'wsteth_quantity':str(wq),'spot_principal_target_usdc':str(principal),'scenarios':scenarios,
                 'hedge_uses_current_price_ratio_not_verified_steth_per_token':True,
                 'present_simulated_margin_not_future_solvency':True,'actual_pnl':None,
                 'staking_apr_is_current_only':True,'funding_history_is_rate_OHLC_not_cash_payments':True}
        b=(json.dumps(summary,indent=2)+'\n').encode();assert len(b)<=16384
        with (OUT/'summary.json').open('xb') as f:f.write(b)
        terminal.update(status='completed_public_simulations',summary_sha256=hashlib.sha256(b).hexdigest())
        print(json.dumps(summary))
    except Exception as e:terminal['error']=str(e)[:300]
    b=(json.dumps(terminal,indent=2)+'\n').encode();assert len(b)+len(pb)+(OUT/'claim.json').stat().st_size<=16384
    assert Path(__file__).stat().st_size<=16384
    with (OUT/'terminal.json').open('xb') as f:f.write(b)
    print(json.dumps({'status':terminal['status'],'requests':terminal['requests'],'error':terminal.get('error')}))


if __name__=='__main__':main()
