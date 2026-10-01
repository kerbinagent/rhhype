"""Post-outcome input-completion audit; preserves all frozen collector outputs."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LIMITS={4295128740,1461446703485210103287273052203988822378723970341}
STUDIES=('base-atomic-cycle-slow-transport','rh-atomic-stock-cycle','rh-nvda-low-fee-cycle')


def main():
    result={}
    for name in STUDIES:
        path=ROOT/'reports'/name/'trace.json.gz'
        trace=json.loads(gzip.decompress(path.read_bytes()))
        quote_ids=[];boundary=[];v4_ids=[]
        for row in trace:
            req=row.get('request') or row.get('payload')
            if not req or req['method']!='eth_call':continue
            data=req['params'][0]['data'];answer=(row.get('response') or {}).get('result')
            if not answer:continue
            words=[int(answer[i:i+64],16) for i in range(2,len(answer),64)]
            if data.startswith('0xc6a5026a'):
                assert len(words)==4
                quote_ids.append(req['id'])
                if words[1] in LIMITS:boundary.append(req['id'])
            elif data.startswith('0xcdca1753'):
                quote_ids.append(req['id']);offset=words[1]//32
                assert words[offset]==2
                if any(x in LIMITS for x in words[offset+1:offset+3]):boundary.append(req['id'])
            elif data.startswith('0xaa9d21cb'):
                assert len(words)==2
                v4_ids.append(req['id'])
        result[name]={'trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'v3_quote_count':len(quote_ids),'v3_price_limit_request_ids':boundary,'v4_quote_count':len(v4_ids),'full_input_status':'not_established_at_v3_limit' if boundary else 'v3_limits_not_reached_v4_standard_implementation_enforces_amount'}
    assert len(result[STUDIES[0]]['v3_price_limit_request_ids'])==0
    assert len(result[STUDIES[1]]['v3_price_limit_request_ids'])==0
    assert len(result[STUDIES[2]]['v3_price_limit_request_ids'])==12
    output={'scope':'Post-outcome quality correction, no new requests or changes to original data. Boundary attainment cannot establish that all requested input was consumed. Quoted output minus full requested input is not a valid wallet P&L when an input remainder may exist.','studies':result,'low_fee_nvda_complete_cycles':0,'low_fee_nvda_unknown_cycles':12,'low_fee_nvda_validated_profit_or_loss':None,'implementation_basis':['https://github.com/Uniswap/v3-periphery/blob/main/contracts/lens/QuoterV2.sol','https://github.com/Uniswap/v3-core/blob/main/contracts/UniswapV3Pool.sol','https://github.com/Uniswap/v4-periphery/blob/main/src/base/BaseV4Quoter.sol'],'v4_assumption':'Official standard BaseV4Quoter._swap checks the input-side BalanceDelta equals amountSpecified and reverts NotEnoughLiquidity otherwise. No hook pools only; deployment identity assumed from official contract list. Full transaction/transfer eligibility remains unverified.'}
    path=ROOT/'reports/rh-nvda-low-fee-cycle/input-completion-audit.json'
    with path.open('x') as f:json.dump(output,f,indent=2);f.write('\n')
    print(json.dumps({k:v['full_input_status'] for k,v in result.items()}))


if __name__=='__main__':main()
