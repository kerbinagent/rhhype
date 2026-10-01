"""Bounded lower-fee pool existence/liquidity inventory, not a profit screen."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from Crypto.Hash import keccak

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/rh-low-fee-pool-preflight-allocation-v1.json'
OUT=ROOT/'reports/rh-low-fee-pool-preflight'
FACTORY='0x1f7d7550B1b028f7571E69A784071F0205FD2EfA'
STATE='0xf3334192d15450cdd385c8b70e03f9a6bd9e673b'
USDG='0x5fc5360d0400a0fd4f2af552add042d716f1d168'


def word(x):
    return f'{x:064x}' if isinstance(x,int) else x[2:].lower().zfill(64)


def sel(s):
    return '0x'+keccak.new(digest_bits=256,data=s.encode()).hexdigest()[:8]


def main():
    plan_bytes=PLAN.read_bytes();p=json.loads(plan_bytes)
    for pin in p['source_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    OUT.mkdir(exist_ok=False)
    (OUT/'claim.json').write_text(json.dumps({'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2))
    trace=[];rows=[];terminal={'status':'failed_no_retry','requests':0}

    def rpc(method,params):
        assert method in ('eth_chainId','eth_getBlockByNumber','eth_call','eth_getCode')
        assert terminal['requests']<64;terminal['requests']+=1
        payload={'jsonrpc':'2.0','id':terminal['requests'],'method':method,'params':params}
        rec={'request':payload,'sent_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            time.sleep(.5)
            req=urllib.request.Request(p['rpc_url'],data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req,timeout=10) as response:raw=response.read(2_097_153)
            assert len(raw)<=2_097_152
            obj=json.loads(raw);rec['raw_response_sha256']=hashlib.sha256(raw).hexdigest()
            if method=='eth_getBlockByNumber' and isinstance(obj.get('result'),dict):
                rec['block_projection']={k:obj['result'][k] for k in ('number','hash','parentHash','timestamp','stateRoot')}
                rec['transaction_hashes_not_retained']=True
            else:rec['response']=obj
            assert obj.get('id')==payload['id'] and 'error' not in obj and obj.get('result') is not None,str(obj.get('error'))
            return obj['result']
        except Exception as exc:
            rec['error']=type(exc).__name__+': '+str(exc)[:400];raise
        finally:
            rec['received_utc']=dt.datetime.now(dt.timezone.utc).isoformat();trace.append(rec)
            b=gzip.compress(json.dumps(trace).encode(),mtime=0);assert len(b)<=49152
            (OUT/'trace.json.gz').write_bytes(b)

    def call(to,data,block):
        return rpc('eth_call',[{'to':to,'data':data},block])

    try:
        assert int(rpc('eth_chainId',[]),16)==4663
        head=rpc('eth_getBlockByNumber',['latest',False]);tag=head['number']
        assert 0<=time.time()-int(head['timestamp'],16)<=60
        for contract in (FACTORY,STATE):assert len(rpc('eth_getCode',[contract,tag]))>2
        for symbol,token in p['tokens'].items():
            for fee,spacing in ((100,1),(500,10)):
                result=call(FACTORY,sel('getPool(address,address,uint24)')+''.join(map(word,(USDG,token,fee))),tag)
                assert len(result)==66
                address='0x'+result[-40:]
                row={'symbol':symbol,'token':token,'version':'v3','fee':fee,'address':address,'exists':int(address,16)!=0,'block':tag}
                if row['exists']:
                    slot=call(address,sel('slot0()'),tag);assert len(slot)==450
                    liquidity=call(address,sel('liquidity()'),tag);assert len(liquidity)==66
                    assert int(call(address,sel('fee()'),tag),16)==fee
                    row.update(sqrt_price_x96=str(int(slot[2:66],16)),active_liquidity=str(int(liquidity,16)))
                rows.append(row)
                currencies=sorted((USDG,token.lower()))
                encoded=bytes.fromhex(''.join(map(word,(*currencies,fee,spacing,0))))
                pool_id=keccak.new(digest_bits=256,data=encoded).hexdigest()
                slot=call(STATE,sel('getSlot0(bytes32)')+pool_id,tag);assert len(slot)==258
                liquidity=call(STATE,sel('getLiquidity(bytes32)')+pool_id,tag);assert len(liquidity)==66
                words=[int(slot[i:i+64],16) for i in range(2,len(slot),64)]
                rows.append({'symbol':symbol,'token':token,'version':'v4','fee':fee,'tick_spacing':spacing,'hooks':'0x'+'0'*40,'currencies':currencies,'address':'0x'+pool_id,'initialized':words[0]!=0,'sqrt_price_x96':str(words[0]),'active_liquidity':str(int(liquidity,16)),'protocol_fee_packed':words[2],'lp_fee':words[3],'block':tag})
        check=rpc('eth_getBlockByNumber',[tag,False]);assert check['hash']==head['hash'],'block hash changed'
        terminal['status']='completed_inventory'
        terminal['block_hash_recheck_passed']=True
    except Exception as exc:terminal['error']=type(exc).__name__+': '+str(exc)[:400]
    data=(json.dumps({'actual_pnl':None,'quote_outcomes':None,'scope':'Pool existence and current active liquidity only. Zero active liquidity is not proof that every possible swap is impossible. Tokens reused from the recently verified canonical registry at the pinned prior study, not a fresh registry request.','rows':rows},indent=2)+'\n').encode()
    assert len(data)<=16384
    (OUT/'summary.json').write_bytes(data)
    terminal.update(ended_utc=dt.datetime.now(dt.timezone.utc).isoformat(),summary_sha256=hashlib.sha256(data).hexdigest())
    (OUT/'terminal.json').write_text(json.dumps(terminal,indent=2)+'\n');print(json.dumps(terminal))


if __name__=='__main__':main()
