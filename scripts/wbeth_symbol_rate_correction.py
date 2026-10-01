"""Reuse resolved block identities; accept the exact on-chain wBETH symbol."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.request
from decimal import Decimal as D
from pathlib import Path
from wbeth_historical_rate_probe import selector

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/wbeth-symbol-rate-correction-allocation-v1.json'
OUT = ROOT / 'reports/wbeth-symbol-rate-correction'


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    old = json.loads(gzip.decompress((ROOT/plan['trace_file']).read_bytes()))
    assert old[0]['response']['result'] == '0x1'
    symbol = bytes.fromhex(old[-1]['response']['result'][2:])
    offset = int.from_bytes(symbol[:32],'big')
    size = int.from_bytes(symbol[offset:offset+32],'big')
    assert symbol[offset+32:offset+32+size].decode() == 'wBETH'
    headers = [r['block_projection'] for r in old if 'block_projection' in r]
    latest = next(r['block_projection'] for r in old if r['request']['params'] == ['latest',False])
    boundaries = []
    for target in plan['targets']:
        before = max((r for r in headers if int(r['timestamp'],16)<=target),key=lambda r:int(r['number'],16))
        after = min((r for r in headers if int(r['timestamp'],16)>target),key=lambda r:int(r['number'],16))
        assert int(after['number'],16)==int(before['number'],16)+1
        assert int(after['timestamp'],16)-int(before['timestamp'],16)<=60
        boundaries.append(dict(target=target,before=before,after=after))
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT/'claim.json').open('x') as f:
        json.dump(dict(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                       source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       plan_sha256=hashlib.sha256(p).hexdigest()),f)
    trace=[]
    result={'status':'unknown','actual_pnl':None,'ethereum_rate_not_verified_on_bnb_chain':True,
            'symbol':'wBETH','boundaries':boundaries}
    terminal={'status':'failed_no_retry','requests':0}
    try:
        calls=[('eth_chainId',[]),('eth_call',[{'to':plan['contract'],'data':selector('decimals()')},latest['number']])]
        calls += [('eth_call',[{'to':plan['contract'],'data':selector('exchangeRate()')},b['before']['number']])for b in boundaries]
        responses=[]
        for method,params in calls:
            time.sleep(.5)
            terminal['requests']+=1
            payload=dict(jsonrpc='2.0',id=terminal['requests'],method=method,params=params)
            req=urllib.request.Request(plan['rpc_url'],data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=10)as response:
                raw=response.read(8193)
                assert response.status==200 and len(raw)<=8192
            obj=json.loads(raw)
            trace.append(dict(request=payload,response=obj,raw_response_sha256=hashlib.sha256(raw).hexdigest(),received_utc=dt.datetime.now(dt.timezone.utc).isoformat()))
            packed=gzip.compress((json.dumps(trace)+'\n').encode(),mtime=0)
            assert len(packed)<=8192
            (OUT/'trace.json.gz').write_bytes(packed)
            assert obj.get('id')==payload['id'] and 'error'not in obj and obj.get('result')is not None,str(obj.get('error'))
            responses.append(obj['result'])
        assert int(responses[0],16)==1 and int(responses[1],16)==18
        assert all(len(v)==66 for v in responses[2:])
        rates=[D(int(v,16))/D(10**18)for v in responses[2:]]
        assert all(D('.5')<v<D(5)for v in rates)
        growth=rates[1]/rates[0]-1
        result.update(status='observed_onchain_rate_growth',start_rate_eth_per_wbeth=str(rates[0]),
                      end_rate_eth_per_wbeth=str(rates[1]),token_unit_growth=str(growth),
                      simple_annualized_growth=str(growth*31536000/D(plan['targets'][1]-plan['targets'][0])))
        terminal['status']='completed'
    except Exception as exc:
        terminal['error']=type(exc).__name__+':'+str(exc)[:240]
    b=(json.dumps(result,indent=2)+'\n').encode()
    assert len(b)<=8192
    with (OUT/'summary.json').open('xb')as f:f.write(b)
    terminal['summary_sha256']=hashlib.sha256(b).hexdigest()
    with (OUT/'terminal.json').open('x')as f:json.dump(terminal,f,indent=2)
    print(json.dumps(terminal));print(json.dumps(result))


if __name__=='__main__':main()
