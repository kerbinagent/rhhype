"""Bounded fresh V2 protocol-fee LP inventory and source model; default dry."""
import argparse
import hashlib
import math
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/uniswap_v2_fee_harvest_v1.py'
TEST='tests/test_uniswap_v2_fee_harvest_v1.py'
BASE='reports/uniswap-v2-fee-harvest-v1/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-v2-fee-harvest-allocation-v1.json'
CAP_AMEND='reports/experiment-storage/uniswap-v2-fee-harvest-cap-amendment-v1.json'
PREP='reports/experiment-storage/uniswap-v2-fee-harvest-preparation-v1.json'
EVENT_BODY='reports/uniswap-fee-release-history-v1/run-v1/raw/02.body'
EVENT_RECEIPT='reports/uniswap-fee-release-history-v1/run-v1/raw/02.receipt.json'
EVENT_REVIEW='reports/uniswap-fee-release-history-v1/root-review.json'
HISTORY_PLAN='52f71abaaa8b47a6a2bb47cdfb8d0ba1171cd7056d2f35d44fe17d0f3cfa248c'
HELPER='scripts/uniswap_fee_release_history_v1.py'
HELPER_SHA='0e1437b87d2943347f6c611a5daa15e5ce562c81c7e6abdcdeb27453ddcd04b9'
FACTORY='0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f'
ZERO='0x'+'0'*40
DIAGNOSTIC='0x'+'0'*39+'1'
MAX256,MAX112=2**256-1,2**112-1
CONFIG=[('fee_to',FACTORY,'feeTo()','pool'),
        ('releaser','0xf38521f130fccf29db1961597bc5d2b60f995f85','releaser()','pool'),
        ('threshold','0x0d5cd355e2abeb8fb1552f56c965b867346d6721','threshold()','uint'),
        ('nonce','0x0d5cd355e2abeb8fb1552f56c965b867346d6721','nonce()','uint')]
PAIR_FIELDS=['token0','token1','canonical_pair','reserves','supply','k_last','pair_lp','balance0','balance1']
SLOTS=[('chain',4096),('block',32768)]+[(x[0],1024) for x in CONFIG]+[
    ('jar_'+str(i),1024) for i in range(20)]+[
    ('pair_'+str(i)+'_'+field,1024) for i in range(4) for field in PAIR_FIELDS]+[('recheck',32768)]
CAPS=dict(requests=63,body_bytes=139264,raw_bytes=172032,request_bytes=8192,
          projection_bytes=12288,request_seconds=20,work_seconds=165,wall_seconds=180,
          cpu_seconds=20,ram_bytes=536870912,total_supplied_gas=17700000)
path=ROOT/HELPER
if path.is_symlink() or not path.is_file():raise RuntimeError('helper_path')
with path.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
k=types.ModuleType('v2_fee_history_helpers');k.__file__=str(path)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
m,c,h,t,s,encode,decode,read,sha=k.m,k.c,k.h,k.t,k.s,k.encode,k.decode,k.read,k.sha
JAR,FIREPIT=k.JAR,k.FIREPIT


class Refusal(Exception):pass


def inputs():
    raw=read(ROOT/EVENT_BODY,8192);receipt=decode(read(ROOT/EVENT_RECEIPT,2048));review=decode(read(ROOT/EVENT_REVIEW,2048))
    if (receipt.get('error') is not None or receipt.get('http_status')!=200 or receipt.get('response_bytes')!=len(raw)
        or receipt.get('response_sha256')!=sha(raw) or review.get('status')!='passed_unavailable'
        or review.get('plan_sha256')!=HISTORY_PLAN):raise Refusal('event_admission')
    value=decode(raw)
    if value.get('id')!=2 or value.get('jsonrpc')!='2.0':raise Refusal('event_rpc')
    e=k.select_event(value.get('result'));assets=e['assets']
    if len(assets)!=20 or len(set(assets))!=20 or ZERO not in assets or ZERO in assets[:4]:raise Refusal('asset_selection')
    return assets


def value(r,kind='uint'):
    if kind!='reserves':return m.result(r,kind)
    if isinstance(r,dict) and 'rpc_unavailable' in r:return dict(available=False,reason='rpc_error')
    try:
        data=h.hexdata(r,96)[2:];v=[int(data[i:i+64],16) for i in (0,64,128)]
        if v[0]>MAX112 or v[1]>MAX112 or v[2]>=2**32:raise Refusal('reserve_width')
        return dict(available=True,value=[str(x) for x in v])
    except (Refusal,h.Refusal,TypeError,ValueError):return dict(available=False,reason='reserve_abi')


def native_value(r):
    if isinstance(r,dict) and 'rpc_unavailable' in r:return dict(available=False,reason='rpc_error')
    try:return dict(available=True,value=str(h.quantity(r)))
    except (h.Refusal,TypeError,ValueError):return dict(available=False,reason='native_quantity')


def checked(n):
    if not 0<=n<=MAX256:raise Refusal('source_uint256_overflow')
    return n


def pending_fee(supply,r0,r1,klast):
    root,old=math.isqrt(r0*r1),math.isqrt(klast)
    return checked(supply*(root-old))//(5*root+old) if klast and root>old else 0


def model(pair,jar,configuration,candidates):
    def fail(reason):return dict(admitted=False,reason=reason)
    if not configuration:return fail('configuration_not_admitted')
    if not jar['available'] or not all(pair[x]['available'] for x in ('reserves','supply','k_last','pair_lp','balance0','balance1')):
        return fail('unknown_input')
    if pair['token0'] in candidates or pair['token1'] in candidates:return fail('cross_candidate_lp_underlying')
    r0,r1,_=map(int,pair['reserves']['value']);supply=int(pair['supply']['value']);klast=int(pair['k_last']['value'])
    lp=int(jar['value']);balances=[int(pair['balance0']['value']),int(pair['balance1']['value'])]
    if not r0 or not r1 or supply<1000 or not 0<=lp<=supply-1000 or klast>MAX112**2:return fail('inconsistent_source_domain')
    if balances!=[r0,r1]:return fail('balances_differ_from_reserves')
    if int(pair['pair_lp']['value'])!=0:return fail('preexisting_pair_lp')
    try:
        fee=pending_fee(supply,r0,r1,klast);fee_supply=checked(supply+fee)
        deposits=[(r+fee_supply-1)//fee_supply for r in (r0,r1)]
        added=min(checked(deposits[i]*fee_supply)//r for i,r in enumerate((r0,r1)))
        after=[r+d for r,d in zip((r0,r1),deposits)];total=checked(fee_supply+added)
        if added<=0 or any(x>MAX112 for x in after):return fail('mint_domain')
        jar_after=checked(lp+fee);burn=checked(jar_after+added)
        outputs=[checked(burn*b)//total for b in after]
        if min(outputs)<=0:return fail('burn_would_round_to_zero')
        # Mint reset kLast to after[0]*after[1]; burn's fee growth is zero.
        assert pending_fee(total,*after,after[0]*after[1])==0
        return dict(admitted=True,source_conditional=True,fee_lp=str(fee),jar_lp_after_mint=str(jar_after),
            deposit_native=[str(x) for x in deposits],caller_lp_minted=str(added),lp_burned=str(burn),
            supply_at_burn=str(total),underlying_out_native=[str(x) for x in outputs],
            net_underlying_after_deposit=[str(x-d) for x,d in zip(outputs,deposits)],
            additional_burn_fee_lp='0',resource_payment_included=False,gas_included=False,cash_closed=False)
    except Refusal as exc:return fail(str(exc))


def collect(rpc,assets):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    header=rpc('block','eth_getBlockByNumber',['finalized',False]);block,context=c.header(header),s.o.context(header)
    state=dict(blockHash=block['hash'],requireCanonical=True)
    def call(name,to,signature,args=()):
        data=s.selector(signature)+''.join(s.word_address(x) if isinstance(x,str) else format(x,'064x') for x in args)
        tx=dict(to=to,input=data,gas=hex(300000),gasPrice='0x0',value='0x0',**{'from':DIAGNOSTIC})
        return rpc(name,'eth_call',[tx,state],allow_unavailable=True)
    config={name:value(call(name,to,signature),kind) for name,to,signature,kind in CONFIG}
    expected={'fee_to':JAR,'releaser':FIREPIT}
    matches=False if any(config[z]['available'] and config[z]['value']!=v for z,v in expected.items()) else (
        True if all(config[z]['available'] for z in expected) else None)
    inventory=[]
    for i,address in enumerate(assets):
        name='jar_'+str(i)
        balance=native_value(rpc(name,'eth_getBalance',[JAR,state],allow_unavailable=True)) if address==ZERO else value(call(name,address,'balanceOf(address)',[JAR]))
        inventory.append(dict(address=address,balance=balance))
    pairs=[]
    for i,address in enumerate(assets[:4]):
        pre='pair_'+str(i)+'_';t0=value(call(pre+'token0',address,'token0()'),'address');t1=value(call(pre+'token1',address,'token1()'),'address')
        if not t0['available'] or not t1['available']:raise Refusal('candidate_underlying_unavailable')
        a,b=t0['value'],t1['value']
        if not int(a,16)<int(b,16) or address in (a,b):raise Refusal('candidate_underlying_identity')
        canonical=value(call(pre+'canonical_pair',FACTORY,'getPair(address,address)',[a,b]),'pool')
        if not canonical['available'] or canonical['value']!=address:raise Refusal('candidate_not_canonical_pair')
        p=dict(address=address,token0=a,token1=b,canonical_pair=canonical['value'])
        p['reserves']=value(call(pre+'reserves',address,'getReserves()'),'reserves')
        for name,signature,args in [('supply','totalSupply()',[]),('k_last','kLast()',[]),('pair_lp','balanceOf(address)',[address])]:
            p[name]=value(call(pre+name,address,signature,args))
        p['balance0']=value(call(pre+'balance0',a,'balanceOf(address)',[address]));p['balance1']=value(call(pre+'balance1',b,'balanceOf(address)',[address]))
        p['model']=model(p,inventory[i]['balance'],matches,assets[:4]);pairs.append(p)
    check=rpc('recheck','eth_getBlockByNumber',[hex(block['number']),False]);s.o.same_header(check,header)
    return dict(schema='uniswap-v2-fee-harvest-projection-v1',status='fixed_lp_inventory_complete',block=block,context=context,
        configuration=config,expected_configuration_matches=matches,inventory=inventory,pairs=pairs,
        assets_selected_from_prior_event=True,complete_fee_source_census=False,state_queries=60,eth_call_slots=59,
        modeled_pairs=sum(x['model']['admitted'] for x in pairs),runtime_equivalence_verified=False,
        token_transfer_verified=False,release_or_mint_or_burn_simulated=False,old_v3_state_combined=False,
        cash_closed=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,CAP_AMEND,PREP,HELPER,k.HELPER,EVENT_BODY,EVENT_RECEIPT,EVENT_REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('block_selector')!='finalized'
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x['path'] for x in pins}!=required:raise Refusal('pins')
    for x in pins:
        data=read(ROOT/x['path'],65536)
        if len(data)!=x['bytes'] or sha(data)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>28672:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096))
    amended=decode(read(ROOT/CAP_AMEND,2048))
    if (a['total_experiment_reservation_bytes']!=229376 or amended['allocation_sha256']!=sha(read(ROOT/ALLOCATION,4096))
        or amended['categories_bytes']['raw']!=CAPS['raw_bytes'] or sum(amended['categories_bytes'].values())!=229376):raise Refusal('funding')
    if p.get('assets')!=inputs() or p.get('factory')!=FACTORY or p.get('jar')!=JAR:raise Refusal('selection_identity')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):return str(exc)[:160] if isinstance(exc,(Refusal,k.Refusal)) else m.reason(exc)


def replay(path,assets):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc,assets);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);assets=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);p=collect(capture.rpc,assets)
                check,body,raw=replay(out/'raw',assets)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_lp_inventory_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_lp_inventory_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; V2 LP state and source-conditional arithmetic only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
