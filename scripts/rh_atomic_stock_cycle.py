"""Fixed same-block v3/v4 stock-token cycles; public simulations, no transactions."""
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.request
from decimal import Decimal as D
from pathlib import Path
from Crypto.Hash import keccak
import rh_small_canonical_amm as prior

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/rh-atomic-stock-cycle-allocation-v1.json'
OUT = ROOT/'reports/rh-atomic-stock-cycle'


def selector(signature):
    return '0x'+keccak.new(digest_bits=256,data=signature.encode()).hexdigest()[:8]


def quote_calldata(pool, token, buy, amount):
    assert 0 < amount < 2**128
    token_in, token_out = (prior.USDG, token) if buy else (token, prior.USDG)
    if pool['version']=='v3':
        return prior.rh.V3_QUOTER, '0x'+prior.rh.QUOTE_SELECTOR+''.join(map(prior.rh.word,(token_in,token_out,amount,pool['fee'],0)))
    currencies=pool['currencies']
    return prior.rh.V4_QUOTER,'0x'+prior.rh.V4_QUOTE_SELECTOR+''.join(map(prior.rh.word,(32,*currencies,pool['fee'],pool['tick_spacing'],0,int(token_in.lower()==currencies[0]),amount,256,0)))


def selftest():
    assert selector('quoteExactInputSingle((address,address,uint256,uint24,uint160))')=='0x'+prior.rh.QUOTE_SELECTOR
    assert selector('quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))')=='0x'+prior.rh.V4_QUOTE_SELECTOR
    token='0x'+'1'*40
    for version in ('v3','v4'):
        pool={'version':version,'fee':500,'tick_spacing':10,'currencies':sorted((token,prior.USDG))}
        for buy,amount in ((True,100000000),(False,123456789012345678)):
            _,data=quote_calldata(pool,token,buy,amount)
            words=[int(data[i:i+64],16) for i in range(10,len(data),64)]
            assert words[2 if version=='v3' else 7]==amount
            if version=='v4':assert words[0]==32 and words[-2:]==[256,0]
    print('v3/v4 selectors, dynamic offsets, exact chained token quantities passed')


def main():
    plan_bytes=PLAN.read_bytes();p=json.loads(plan_bytes)
    for pin in p['source_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    selected=p['selected']
    OUT.mkdir(exist_ok=False)
    (OUT/'claim.json').write_text(json.dumps({'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2))
    trace=[];rows=[];verified={};terminal={'status':'failed_no_retry','requests':0}

    def request(url,payload=None):
        assert terminal['requests']<p['max_requests'];terminal['requests']+=1
        record={'url':url,'payload':payload,'sent_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            time.sleep(.5)
            req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload else None,headers={'Content-Type':'application/json','User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=12) as response:
                raw=response.read(2_097_153)
            assert len(raw)<=2_097_152,'response limit'
            obj=json.loads(raw);record['raw_response_sha256']=hashlib.sha256(raw).hexdigest()
            if payload and payload['method']=='eth_getBlockByNumber' and isinstance(obj.get('result'),dict):
                record['block_projection']={k:obj['result'][k] for k in ('number','hash','parentHash','timestamp','stateRoot')}
                record['transaction_hashes_not_retained']=True
            else:record['response']=obj
            if payload:
                assert obj.get('id')==payload['id'] and 'error' not in obj and obj.get('result') is not None,str(obj.get('error'))
                return obj['result']
            return obj
        except Exception as exc:
            record['error']=type(exc).__name__+': '+str(exc)[:400]
            raise
        finally:
            record['received_utc']=dt.datetime.now(dt.timezone.utc).isoformat();trace.append(record)
            packed=gzip.compress(json.dumps(trace).encode(),mtime=0)
            assert len(packed)<=131072,'raw storage cap'
            (OUT/'trace.json.gz').write_bytes(packed)

    def rpc(method,params):
        assert method in ('eth_chainId','eth_getBlockByNumber','eth_getCode','eth_call')
        return request(prior.rh.RPC,{'jsonrpc':'2.0','id':terminal['requests']+1,'method':method,'params':params})

    def call(to,data,block):
        return rpc('eth_call',[{'to':to,'data':data},block])

    def quote(pool,token,buy,amount,block):
        contract,data=quote_calldata(pool,token,buy,amount)
        result=call(contract,data,block)
        raw=bytes.fromhex(result[2:]);assert len(raw)==(128 if pool['version']=='v3' else 64)
        amount_out=int.from_bytes(raw[:32],'big');assert amount_out>0
        return {'pool':pool['address'],'version':pool['version'],'input_raw':str(amount),'output_raw':str(amount_out),'quote_gas_estimate':int.from_bytes(raw[-32:],'big')}

    try:
        assert int(rpc('eth_chainId',[]),16)==4663
        registry=request(prior.rh.ASSETS);by_symbol={x['tokenSymbol']:x for x in registry['assets']}
        head=rpc('eth_getBlockByNumber',['latest',False]);tag=head['number']
        assert 0<=time.time()-int(head['timestamp'],16)<=60
        for contract in (prior.rh.V3_FACTORY,prior.rh.V3_QUOTER,prior.rh.V4_QUOTER):
            assert len(rpc('eth_getCode',[contract,tag]))>2
        assert int(call(prior.USDG,selector('decimals()'),tag),16)==6
        # Override only the prior verification helper's public RPC transport.
        prior.rh.eth_call=call
        for symbol,item in selected.items():
            asset=by_symbol[symbol]
            assert asset['status']=='ASSET_STATUS_ACTIVE'
            deployment=next(d for d in asset['deployments'] if d['chainId']==4663)
            assert deployment['contractAddress'].lower()==item['token'].lower()
            assert int(call(item['token'],selector('decimals()'),tag),16)==18
            pools=[prior.verify_pool(pool,item['token'],tag) for pool in item['pools']]
            v3=pools[0];assert v3['version']=='v3' and pools[1]['version']=='v4'
            result=call(prior.rh.V3_FACTORY,selector('getPool(address,address,uint24)')+''.join(map(prior.rh.word,(prior.USDG,item['token'],v3['fee']))),tag)
            assert result[-40:].lower()==v3['address'][2:].lower()
            verified[symbol]={'token':item['token'],'pools':pools}
        start=time.monotonic()
        for round_i in range(3):
            while time.monotonic()<start+60*round_i:time.sleep(min(1,start+60*round_i-time.monotonic()))
            for symbol,item in verified.items():
                head=rpc('eth_getBlockByNumber',['latest',False]);tag=head['number']
                assert 0<=time.time()-int(head['timestamp'],16)<=60
                group=[]
                for forward in (True,False):
                    a,b=item['pools'] if forward else item['pools'][::-1]
                    for size in (100,1000):
                        row={'round':round_i,'symbol':symbol,'block':tag,'block_hash':head['hash'],'input_usdg':size,'buy_pool_version':a['version'],'sell_pool_version':b['version'],'actual_pnl':None,'after_gas_profit':None}
                        try:
                            first=quote(a,item['token'],True,size*10**6,tag);row['first']=first
                            second=quote(b,item['token'],False,int(first['output_raw']),tag);row['second']=second
                            row.update(status='quote_only',output_usdg=str(D(second['output_raw'])/10**6),surplus_after_pool_fees_before_gas_usdg=str(D(second['output_raw'])/10**6-size))
                        except Exception as exc:row.update(status='unknown',error=type(exc).__name__+': '+str(exc)[:400])
                        group.append(row)
                check=rpc('eth_getBlockByNumber',[tag,False]);valid=check['hash']==head['hash']
                for row in group:
                    row['block_hash_recheck_passed']=valid
                    if not valid:row['status']='unknown_reorg'
                rows.extend(group)
        terminal['status']='completed_fixed_screen'
    except Exception as exc:terminal['error']=type(exc).__name__+': '+str(exc)[:400]
    summary={'actual_pnl':None,'gas_not_subtracted':True,'scope':'Same-block exact chained input through independent v3/v4 no-hook pools, with no persistent state changes. Necessary gross-profit screen only; complete router transaction simulation, transfer eligibility, gas, inclusion and first-use approval costs unresolved. USDG amounts are not a bank-dollar redemption claim.','verified':verified,'rows':rows}
    data=(json.dumps(summary,indent=2)+'\n').encode();assert len(data)<=98304
    (OUT/'summary.json').write_bytes(data)
    terminal.update(ended_utc=dt.datetime.now(dt.timezone.utc).isoformat(),summary_sha256=hashlib.sha256(data).hexdigest())
    (OUT/'terminal.json').write_text(json.dumps(terminal,indent=2)+'\n');print(json.dumps(terminal))


if __name__=='__main__':
    if sys.argv[1:]==['selftest']:selftest()
    elif sys.argv[1:]==['run']:main()
    else:print('Use selftest or run explicitly')
