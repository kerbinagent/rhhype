"""Fixed pool state and conditional initial-price bounds; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/sky_psm_pool_state_v1.py'
TEST='tests/test_sky_psm_pool_state_v1.py'
BASE='reports/sky-psm-pool-state-v1/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/sky-psm-pool-state-category-amendment-v1.json'
HELPER='scripts/sky_psm_discovery_v1.py'
HELPER_SHA='c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
DISCOVERY='reports/sky-psm-conversion-v1/run-v1/projection.json'
QUOTES='reports/sky-psm-fixed-quotes-v1/run-v1/projection.json'
REVIEW='reports/sky-psm-fixed-quotes-v1/root-review.json'
QUOTE_SHA='99634b36c52c566fe319a6c7e0225a8b5e21a1595e7481745149cce0fa223be6'
CAPS=dict(requests=19,body_bytes=49152,raw_bytes=65536,request_bytes=8192,projection_bytes=12288,
          request_seconds=20,work_seconds=165,wall_seconds=180,cpu_seconds=20,ram_bytes=536870912,total_supplied_gas=4800000)
FIELDS=['slot0','liquidity','dai_balance','usdc_balance']
FEES=[100,500,3000,10000]
LOTS=[1000,10000,100000,1000000]
SLOTS=[('chain',4096),('anchor',16384)]+[(str(fee)+'_'+name,4096) for fee in FEES for name in FIELDS]+[('recheck',16384)]


class Refusal(Exception):pass


path=ROOT/HELPER
if path.is_symlink() or not path.is_file():raise Refusal('helper_nonregular')
with path.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise Refusal('immutable_helper')
m=types.ModuleType('psm_pool_helpers');m.__file__=str(path)
exec(compile(raw,m.__file__,'exec'),m.__dict__)
c,h,t,s,encode,decode,read,sha=m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


def inputs():
    d=decode(read(ROOT/DISCOVERY,8192));q=decode(read(ROOT/QUOTES,24576));r=decode(read(ROOT/REVIEW,1536))
    if (q['plan_sha256']!=QUOTE_SHA or r.get('status')!='passed' or r.get('plan_sha256')!=QUOTE_SHA
            or r.get('projection_sha256')!=sha(read(ROOT/QUOTES,24576))):raise Refusal('quote_admission')
    if q['anchor']!=d['block'] or q['context']!=d['context']:raise Refusal('prior_state_mismatch')
    if [x['fee'] for x in q['pools']]!=FEES or not all(x['identity_matches'] is True for x in q['pools']):
        raise Refusal('prior_pool_identity')
    if (d['conditions']['documented_identity_matches'] is not True or d['conditions']['expected_units_match'] is not True
            or any(not d['values'][key]['available'] or not 0<=int(d['values'][key]['value'])<=m.WAD for key in ('tin','tout'))):
        raise Refusal('prior_psm_conditions')
    return d,q


def result(value,name):
    if isinstance(value,dict) and 'rpc_unavailable' in value:return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'])
    try:
        if name=='slot0':
            raw=h.hexdata(value,224)[2:];v=[int(raw[i:i+64],16) for i in range(0,448,64)]
            tick=v[1] if v[1]<2**255 else v[1]-2**256
            if not (v[0]<2**160 and -2**23<=tick<2**23 and all(x<2**16 for x in v[2:5]) and v[5]<256 and v[6] in (0,1)):
                raise Refusal('slot0_abi_width')
            parsed=dict(sqrt_price_x96=str(v[0]),tick=tick,observation_index=v[2],cardinality=v[3],next_cardinality=v[4],fee_protocol=v[5],unlocked=bool(v[6]))
        else:
            parsed=s.uint_word(value)
            if name=='liquidity' and int(parsed)>=2**128:raise Refusal('liquidity_width')
    except (Refusal,m.Refusal,c.Refusal,h.Refusal,TypeError,ValueError):return dict(available=False,reason='null_or_noncanonical_result')
    return dict(available=True,value=parsed)


def price_bound(slot,fee,conversion):
    if not slot['available'] or int(slot['value']['sqrt_price_x96'])==0:
        return dict(available=False,reason='initial_price_unavailable_or_zero')
    price=int(slot['value']['sqrt_price_x96'])**2;unit=2**192;den=1000000-fee
    # Token0 DAI/token1 USDC. Input and fee round against the trader; a swap
    # moves its marginal price adversely from this initial price.
    dai_left,dai_right=unit*1000000,conversion*price*den
    usdc_left,usdc_right=conversion*price*1000000,unit*den
    return dict(available=True,dai_cycle_nonpositive_all_positive_usdc_units=dai_left>=dai_right,
                usdc_cycle_nonpositive_all_positive_usdc_units=usdc_left>=usdc_right,
                dai_cost_vs_max_psm_return_crossproducts=[str(dai_left),str(dai_right)],
                usdc_cost_vs_psm_return_crossproducts=[str(usdc_left),str(usdc_right)],
                conditional_on_standard_v3_and_psm_source=True)


def inventories(values,d):
    rows=[];conversion=int(d['values']['conversion']['value']);tout=int(d['values']['tout']['value'])
    for lot in LOTS:
        x=lot*10**6;gross=x*conversion;y=gross+gross*tout//m.WAD
        for direction,key,need in [('dai_cycle','usdc_balance',x),('usdc_cycle','dai_balance',y)]:
            v=values[key]
            rows.append(dict(lot=lot,direction=direction,requested_output_raw=str(need),
                pool_output_inventory_sufficient=(int(v['value'])>=need if v['available'] else None)))
    return rows


def collect(rpc,d,q):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('wrong_chain')
    block=rpc('anchor','eth_getBlockByNumber',[hex(d['block']['number']),False])
    if c.header(block)!=d['block'] or s.o.context(block)!=d['context']:raise Refusal('prior_anchor_changed')
    state=dict(blockHash=d['block']['hash'],requireCanonical=True)
    rows=[]
    for pool in q['pools']:
        fee,address=pool['fee'],pool['address'];values={}
        for name in FIELDS:
            target=m.DAI if name=='dai_balance' else m.USDC if name=='usdc_balance' else address
            signature='balanceOf(address)' if name.endswith('_balance') else name+'()'
            data=s.selector(signature)+(s.word_address(address) if name.endswith('_balance') else '')
            call={'from':m.DIAGNOSTIC,'to':target,'input':data,'value':'0x0','gasPrice':'0x0','gas':hex(300000)}
            values[name]=result(rpc(str(fee)+'_'+name,'eth_call',[call,state],allow_unavailable=True),name)
        rows.append(dict(fee=fee,address=address,values=values,
            conditional_bound=price_bound(values['slot0'],fee,int(d['values']['conversion']['value'])),
            requested_output_inventory=inventories(values,d)))
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[block['number'],False]),block)
    return dict(schema='sky-psm-pool-state-projection-v1',status='fixed_pool_state_complete',anchor=d['block'],context=d['context'],rows=rows,
        active_liquidity_is_not_full_depth=True,inventory_is_not_full_execution=True,
        original_unknown_quote_rows_remain_unknown=True,underlying_quote_error_diagnosed=False,
        runtime_source_correspondence_verified=False,closed_cash=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,HELPER,DISCOVERY,QUOTES,REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
            or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('fees')!=FEES or p.get('lots')!=LOTS
            or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('frozen_scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],32768)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>32768:raise Refusal('source_package_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,d,q):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,d,q);reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        p=verify(digest);d,q=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=p['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);result=collect(capture.rpc,d,q)
                check,body,raw=replay(out/'raw',d,q)
                if result!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('exact_replay')
                verify(digest);result['plan_sha256']=digest;s.o.publish(out,'projection.json',result,CAPS['projection_bytes']);status='fixed_pool_state_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),ended_ns=time.time_ns(),economics=False))
    return status=='fixed_pool_state_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);d,q=inputs();r,b,n=replay(ROOT/OUT/'raw',d,q);print(encode(dict(status=r['status'],body_bytes=b,raw_bytes=n)).decode());return 0
    if not a.run:print('dry: zero requests; zero outputs; four fixed pool states');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
