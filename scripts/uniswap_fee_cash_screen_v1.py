"""One bounded same-state fee-basket acquisition/exit quote screen; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
HELPER='scripts/sky_psm_quotes_v1.py'
HELPER_SHA='92f35908525d6e4a040b60b365f584a8cd0a98705c0ac0021e1dec9544d505e7'
SOURCE='scripts/uniswap_fee_cash_screen_v1.py'
TEST='tests/test_uniswap_fee_cash_screen_v1.py'
BASE='reports/uniswap-fee-cash-screen-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment.json','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-fee-cash-screen-allocation-v1.json'
FUNDING='reports/experiment-storage/uniswap-fee-cash-screen-source-cap-amendment-v1.json'
COLLECTION='reports/uniswap-fee-collect-v1/run-v1/projection.json'
REVIEW='reports/uniswap-fee-collect-v1/root-review.json'
INVENTORY='reports/uniswap-fee-auction-inventory-v2/run-v1/projection.json'
POOLS='reports/uniswap-fee-pool-discovery-v1/run-v1/projection.json'
PRIOR_NOTES='reports/sky-psm-fixed-quotes-v1/source-notes.json'
PRIOR_SHA='70c8d2df1284b335374ced1c979830d2de2c05333b4bae354c293c35d4b45bfd'
FACTORY='0x1f98431c8ad98523631ae4a59f267346ea31f984'
MIN_PRICE=4295128739
MAX_PRICE=1461446703485210103287273052203988822378723970342
ROUTES=[('uni_exit','UNI','WETH',3000),('weth_exit','WETH','USDC',500),
        ('dai_exit','DAI','USDC',100),('usdt_exit','USDT','USDC',100),
        ('wbtc_exit','WBTC','USDC',3000),('purchase','USDC','UNI',3000)]
SLOTS=[('chain',4096),('factory',4096)]+[(x[0],4096) for x in ROUTES]+[('recheck',24576)]
CAPS=dict(requests=9,body_bytes=40960,raw_bytes=49152,request_bytes=8192,projection_bytes=4096,
          request_seconds=20,work_seconds=165,wall_seconds=180,cpu_seconds=20,
          ram_bytes=536870912,total_supplied_gas=18300000)
path=ROOT/HELPER
if path.is_symlink() or not path.is_file():raise RuntimeError('helper_path')
with path.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
q=types.ModuleType('fee_cash_helpers');q.__file__=str(path)
exec(compile(raw,q.__file__,'exec'),q.__dict__)
c,h,t,s,encode,decode,read,sha=q.c,q.h,q.t,q.s,q.encode,q.decode,q.read,q.sha


class Refusal(Exception):pass


def inputs():
    p=decode(read(ROOT/COLLECTION,8192));r=decode(read(ROOT/REVIEW,1536))
    j=decode(read(ROOT/INVENTORY,8192));d=decode(read(ROOT/POOLS,8192))
    if (p['plan_sha256']!=PRIOR_SHA or r.get('status')!='passed' or r.get('plan_sha256')!=PRIOR_SHA
        or r.get('projection_sha256')!=sha(read(ROOT/COLLECTION,8192))
        or p['configuration_matches'] is not True or not p['collection']['available']
        or p['anchor']!=j['block'] or p['anchor']!=d['anchor'] or p['context']!=j['context']
        or p['context']!=d['context'] or not j['documented_configuration_matches']
        or not j['expected_units_match'] or j['configuration']['threshold']['value']!=str(4000*10**18)):
        raise Refusal('prior_admission')
    assets={x['label']:x['address'] for x in j['inventory'][:6]}
    stock={k:int(p['modeled_jar_after_collection_native'][v]) for k,v in assets.items()}
    selected=[]
    for name,a,b,fee in ROUTES:
        found=[]
        for pair,f,status,address,error in d['rows']:
            tokens={d['assets'][i][1] for i in d['pairs'][pair]}
            if tokens=={assets[a],assets[b]} and f==fee and status=='p':found.append(address)
        if len(found)!=1:raise Refusal('route_pool')
        selected+=found
    if len(set(selected))!=6 or any(x<=0 for x in stock.values()):raise Refusal('alias_or_stock')
    return p,assets,stock,selected


def calldata(exact_output,a,b,amount,fee):
    if not 0<amount<2**255 or not 0<fee<2**24:raise Refusal('quote_input')
    sig='quoteExact'+('Output' if exact_output else 'Input')+'Single((address,address,uint256,uint24,uint160))'
    return s.selector(sig)+s.word_address(a)+s.word_address(b)+format(amount,'064x')+format(fee,'064x')+'0'*64


def quote(value):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'])
    try:
        raw=h.hexdata(value,128)[2:];amount,price,ticks,gas=[int(raw[i:i+64],16) for i in range(0,256,64)]
        if not MIN_PRICE<price<MAX_PRICE or ticks>=2**32 or gas>3000000:raise Refusal('quote_domain')
    except (Refusal,h.Refusal,TypeError,ValueError):return dict(available=False,reason='noncanonical_quote')
    return dict(available=True,amount=str(amount),sqrt_price_after=str(price),ticks=ticks,swap_gas_estimate=gas)


def collect(rpc,p,assets,stock,selected):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    state=dict(blockHash=p['anchor']['hash'],requireCanonical=True)
    def call(name,data,gas):
        tx=dict(to=q.QUOTER,input=data,value='0x0',gasPrice='0x0',gas=hex(gas))
        tx['from']=q.m.DIAGNOSTIC
        return rpc(name,'eth_call',[tx,state],allow_unavailable=True)
    factory=q.m.result(call('factory',s.selector('factory()'),300000),'pool')
    rows=[];uni_weth=None
    for i,(name,a,b,fee) in enumerate(ROUTES):
        amount=4000*10**18 if name=='purchase' else stock[a]
        dependent=True
        if name=='weth_exit':
            dependent=uni_weth is not None
            amount+=uni_weth or 0
        z=quote(call(name,calldata(name=='purchase',assets[a],assets[b],amount,fee),3000000))
        full=None
        if z['available']:
            limit=MIN_PRICE+1 if int(assets[a],16)<int(assets[b],16) else MAX_PRICE-1
            full=(name=='purchase' or int(z['sqrt_price_after'])!=limit)
        if name=='uni_exit' and z['available'] and full:uni_weth=int(z['amount'])
        rows.append(dict(name=name,quantity=str(amount),quote=z,full_quantity_source_conditional=full,
                         dependency_available=dependent))
    block=rpc('recheck','eth_getBlockByNumber',[hex(p['anchor']['number']),False])
    if c.header(block)!=p['anchor'] or s.o.context(block)!=p['context']:raise Refusal('anchor_changed')
    complete=(factory['available'] and factory['value']==FACTORY and
              all(x['quote']['available'] and x['full_quantity_source_conditional'] and x['dependency_available'] for x in rows))
    proceeds=cost=surplus=None
    if complete:
        proceeds=stock['USDC']+sum(int(x['quote']['amount']) for x in rows[1:5])
        cost=int(rows[5]['quote']['amount']);surplus=proceeds-cost
    return dict(schema='uniswap-fee-cash-screen-projection-v1',status='fixed_cash_quotes_complete',
        anchor=p['anchor'],context=p['context'],quoter=q.QUOTER,factory=factory,pools=selected,rows=rows,
        all_quotes_admitted=complete,cash_token=assets['USDC'],cash_decimals=6,
        quoted_proceeds=None if proceeds is None else str(proceeds),quoted_purchase_cost=None if cost is None else str(cost),
        quoted_surplus_before_transaction_costs=None if surplus is None else str(surplus),
        conditional_route_nonpositive=None if surplus is None else surplus<=0,
        release_and_swaps_executed=False,token_payments_verified=False,runtime_source_verified=False,
        transaction_gas_measured=False,gas_estimates_are_swap_only=True,cash_closed=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,4096)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,FUNDING,HELPER,COLLECTION,REVIEW,INVENTORY,POOLS,PRIOR_NOTES}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('routes')!=[list(x) for x in ROUTES]
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x['path'] for x in pins}!=required:raise Refusal('pins')
    for x in pins:
        raw=read(ROOT/x['path'],32768)
        if len(raw)!=x['bytes'] or sha(raw)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>20480:raise Refusal('source_cap')
    a=decode(read(ROOT/FUNDING,4096))
    if a['total_experiment_reservation_bytes']!=86016 or a['categories_bytes']['raw']!=CAPS['raw_bytes']:raise Refusal('funding')
    prior,assets,stock,selected=inputs()
    if p.get('selected_pools')!=selected or p.get('anchor')!=prior['anchor']:raise Refusal('selection')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else q.reason(exc)


def replay(path,args):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc,*args);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);args=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);p=collect(capture.rpc,*args)
                check,body,raw=replay(out/'raw',args)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_cash_quotes_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),cash_closed=False))
    return status=='fixed_cash_quotes_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; one fixed six-pool cash screen');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
