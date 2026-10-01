"""Independently reconcile cached exact quantities and full-input checks to raw RPCs."""
import collections, gzip, hashlib, itertools, json
from decimal import Decimal as D
from pathlib import Path
R=Path(__file__).resolve().parents[1]; O=R/'reports/rh-nvda-sub100-cycles'
s=json.loads((O/'summary.json').read_text()); t=json.loads(gzip.decompress((O/'trace.json.gz').read_bytes()))
p=json.loads((R/'reports/experiment-storage/rh-nvda-sub100-cycles-allocation-v1.json').read_text())
assert len(t)<=70 and len(s['rows'])==16
claim=json.loads((O/'claim.json').read_bytes()); assert claim['source_sha256']==hashlib.sha256((R/'scripts/rh_nvda_sub100_cycles.py').read_bytes()).hexdigest(); assert claim['plan_sha256']==hashlib.sha256((R/'reports/experiment-storage/rh-nvda-sub100-cycles-allocation-v1.json').read_bytes()).hexdigest()
quotes={}; headers=collections.defaultdict(list)
for x in t:
    q=x.get('payload')
    if not q: continue
    if q['method']=='eth_getBlockByNumber': headers[x['block_projection']['number']].append(x['block_projection']['hash'])
    if q['method']!='eth_call':continue
    data=q['params'][0]['data'];sel=data[:10]
    if sel not in ('0xc6a5026a','0xaa9d21cb'):continue
    w=[int(data[i:i+64],16) for i in range(10,len(data),64)]
    token=int(s['verified']['NVDA']['token'],16); usd=int('5fc5360d0400a0fd4f2af552add042d716f1d168',16)
    if sel=='0xc6a5026a':
        assert len(w)==5 and set(w[:2])=={token,usd} and w[4]==0
        v='v3';fee=w[3];buy=w[0]==usd;amount=w[2]
    else:
        assert len(w)==10 and w[0]==32 and w[1:3]==sorted([token,usd]) and w[5]==0 and w[-2:]==[256,0]
        v='v4';fee=w[3];buy=bool(w[6])==(usd==w[1]);amount=w[7]
        assert w[4]=={100:1,500:10}[fee]
    k=(v,fee,buy,amount,q['params'][1]);assert k not in quotes
    a=x.get('response',{}).get('result')
    if not a:quotes[k]=None;continue
    z=[int(a[i:i+64],16) for i in range(2,len(a),64)]
    assert len(z)==(4 if v=='v3' else 2)
    quotes[k]=z
expected=set(itertools.product(range(1),range(2),range(2),p['sizes_usdg']))
expected={x for x in expected if x[1]!=x[2]};observed=set();pools=s['verified']['NVDA']['pools'];idx={x['address']:i for i,x in enumerate(pools)}
limits={4295128740,1461446703485210103287273052203988822378723970341}; counts=collections.Counter();valid=[]
for r in s['rows']:
    observed.add((r['round'],idx[r['buy_pool']],idx[r['sell_pool']],r['input_usdg']))
    assert r['block_hash_recheck_passed'] and headers[r['block']]==[r['block_hash']]*2
    amount=int(D(r['input_usdg'])*10**6)
    assert D(r['unused_budget_usdg'])==100-D(r['input_usdg'])
    a=quotes[(r['buy_pool_version'],r['buy_fee'],True,amount,r['block'])]
    if not a or a[0]==0:
        assert r['status']=='unknown' and 'surplus_after_pool_fees_before_gas_usdg' not in r;counts['unknown_failed_first_quote']+=1;continue
    partial=r['buy_pool_version']=='v3' and a[1] in limits
    if not partial:
        assert int(r['first']['input_raw'])==amount and int(r['first']['output_raw'])==a[0]
        b=quotes[(r['sell_pool_version'],r['sell_fee'],False,a[0],r['block'])]
        if not b or b[0]==0:
            assert r['status']=='unknown' and 'surplus_after_pool_fees_before_gas_usdg' not in r;counts['unknown_failed_second_quote']+=1;continue
        partial=r['sell_pool_version']=='v3' and b[1] in limits
    if partial:
        assert r['status']=='unknown' and 'v3_terminal_price_limit' in r['error'] and 'surplus_after_pool_fees_before_gas_usdg' not in r
        counts['unknown_partial_input']+=1
    else:
        assert r['status']=='quote_only'
        assert int(r['second']['input_raw'])==a[0] and int(r['second']['output_raw'])==b[0]
        pnl=D(b[0])/10**6-D(r['input_usdg'])
        assert D(r['end_budget_usdg'])==100+pnl
        assert pnl==D(r['surplus_after_pool_fees_before_gas_usdg'])
        assert r['actual_pnl'] is None and r['after_gas_profit'] is None
        counts['complete_quote_cycles']+=1;counts['positive_before_gas']+=pnl>0;valid.append(r)
assert observed==expected
out={'audit':'passed','counts':dict(counts),'unique_quote_requests':len(quotes),'hashes':{x:hashlib.sha256((O/x).read_bytes()).hexdigest() for x in ('summary.json','trace.json.gz','claim.json','terminal.json')},'best_by_size':{str(size):max((r for r in valid if r['input_usdg']==size),key=lambda r:D(r['surplus_after_pool_fees_before_gas_usdg'])) for size in p['sizes_usdg'] if any(r['input_usdg']==size for r in valid)},'limitations':'Official standard no-hook v4 full-input guard assumed deployed as documented. Quotes are not full transaction simulations. Gas not deducted. Unknown cases are neither profitable nor loss-making complete cycles.'}
with (O/'audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
print(json.dumps({'counts':dict(counts),'best':{k:v['surplus_after_pool_fees_before_gas_usdg'] for k,v in out['best_by_size'].items()}}))
