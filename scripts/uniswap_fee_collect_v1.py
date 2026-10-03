"""Bounded public fee-collection simulation; preparation only until plan freeze."""
import hashlib
import argparse
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/sky_psm_discovery_v1.py'
HELPER_SHA = 'c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
MAX128 = 2**128-1
SOURCE = 'scripts/uniswap_fee_collect_v1.py'
TEST = 'tests/test_uniswap_fee_collect_v1.py'
BASE = 'reports/uniswap-fee-collect-v1/'
PLAN,DESIGN,OUT=(BASE+x for x in ('plan.json','design.txt','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-fee-collection-allocation-v1.json'
DISCOVERY='reports/uniswap-fee-pool-discovery-v1/run-v1/projection.json'
REVIEW='reports/uniswap-fee-pool-discovery-v1/root-review.json'
INVENTORY='reports/uniswap-fee-auction-inventory-v2/run-v1/projection.json'
NOTES='reports/uniswap-fee-harvest-feasibility-v1/source-notes.json'
DISCOVERY_SHA='53ec0fd097f06e31f5e33187034732c0c28f0e6b6902c11036902c575e558081'
FACTORY='0x1f98431c8ad98523631ae4a59f267346ea31f984'
ADAPTER='0xf2371551fe3937db7c750f4dfabe5c2fffdcbf5a'
JAR='0xf38521f130fccf29db1961597bc5d2b60f995f85'
SLOTS=[('chain',4096),('owner',4096),('factory',4096),
       ('jar',4096),('collect',16384),('recheck',24576)]
CAPS=dict(requests=6,body_bytes=40960,raw_bytes=57344,request_bytes=16384,
          projection_bytes=8192,request_seconds=20,work_seconds=165,wall_seconds=180,
          cpu_seconds=20,ram_bytes=536870912,total_supplied_gas=10900000)
path = ROOT/HELPER
if path.is_symlink() or not path.is_file():
    raise RuntimeError('nonregular_helper')
with path.open('rb') as f:
    raw = f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:
    raise RuntimeError('immutable_helper')
m = types.ModuleType('fee_collect_helpers')
m.__file__ = str(path)
exec(compile(raw, m.__file__, 'exec'), m.__dict__)
c,h,t,s,encode,decode,read,sha = m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha


class Refusal(Exception):
    pass


def call_data(pools):
    """One dynamic array of fixed-size address,uint128,uint128 tuples."""
    if not 1<=len(pools)<=60 or len(set(pools))!=len(pools):
        raise Refusal('pool_count_or_alias')
    payload=s.selector('collect((address,uint128,uint128)[])')+format(32,'064x')+format(len(pools),'064x')
    for address in pools:
        h.hexdata(address,20)
        if int(address,16)==0:
            raise Refusal('zero_pool')
        payload+=s.word_address(address)+format(MAX128,'064x')*2
    return payload


def amounts(value,count):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'])
    try:
        if not 1<=count<=60:
            raise Refusal('array_count')
        raw=h.hexdata(value,64+64*count)[2:]
        words=[int(raw[i:i+64],16) for i in range(0,len(raw),64)]
        if words[:2]!=[32,count] or any(x>MAX128 for x in words[2:]):
            raise Refusal('noncanonical_tuple_array')
        pairs=[[str(words[i]),str(words[i+1])] for i in range(2,len(words),2)]
    except (Refusal,h.Refusal,TypeError,ValueError):
        return dict(available=False,reason='null_or_noncanonical_array')
    return dict(available=True,amounts=pairs)


def aggregate(bindings,result):
    """Returned values already include the pool's retained native unit."""
    if not result['available']:
        return None
    if len(bindings)!=len(result['amounts']):
        raise Refusal('binding_count')
    totals={}
    for tokens,pair in zip(bindings,result['amounts']):
        if len(tokens)!=2 or int(tokens[0],16)>=int(tokens[1],16):
            raise Refusal('token_order')
        for token,amount in zip(tokens,pair):
            totals[token]=totals.get(token,0)+int(amount)
    return {token:str(value) for token,value in sorted(totals.items())}


def inputs():
    d=decode(read(ROOT/DISCOVERY,8192));r=decode(read(ROOT/REVIEW,1536));j=decode(read(ROOT/INVENTORY,8192))
    if (d['plan_sha256']!=DISCOVERY_SHA or r.get('status')!='passed'
            or r.get('plan_sha256')!=DISCOVERY_SHA or r.get('projection_sha256')!=sha(read(ROOT/DISCOVERY,8192))
            or d['anchor']!=j['block'] or d['context']!=j['context'] or d['factory']!=FACTORY
            or d['owner']!={'status':'documented_adapter','address':ADAPTER,'error':None}
            or d['present']!=55 or d['absent']!=5 or d['unknown']!=0 or d['aliases']
            or [(x['label'],x['address']) for x in j['inventory'][:6]]!=[tuple(x) for x in d['assets']]):
        raise Refusal('discovery_admission')
    pools=[]
    for index,(pair,fee,status,address,error) in enumerate(d['rows']):
        if status=='p':
            a,b=d['pairs'][pair]
            tokens=sorted([d['assets'][a][1],d['assets'][b][1]],key=lambda x:int(x,16))
            pools.append([index,address,tokens])
    if len(pools)!=55 or len({x[1] for x in pools})!=55:raise Refusal('selected_pool_count')
    return d,j,pools


def collect(rpc,d,j,pools):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    # Reuse the audited header; all state reads require its canonical hash.
    state=dict(blockHash=d['anchor']['hash'],requireCanonical=True)
    def call(name,to,data,gas):
        tx={'from':m.DIAGNOSTIC,'to':to,'input':data,'value':'0x0','gasPrice':'0x0','gas':hex(gas)}
        return rpc(name,'eth_call',[tx,state],allow_unavailable=True)
    config={}
    for name,target,signature in [('owner',FACTORY,'owner()'),('factory',ADAPTER,'FACTORY()'),('jar',ADAPTER,'TOKEN_JAR()')]:
        # Generic address decoder retains a canonical zero as a known mismatch.
        config[name]=m.result(call(name,target,s.selector(signature),300000),'pool')
    expected={'owner':ADAPTER,'factory':FACTORY,'jar':JAR}
    matches=not any(v['available'] and v['value']!=expected[k] for k,v in config.items())
    if matches and not all(v['available'] for v in config.values()):matches=None
    result=amounts(call('collect',ADAPTER,call_data([x[1] for x in pools]),10000000),len(pools))
    block=rpc('recheck','eth_getBlockByNumber',[hex(d['anchor']['number']),False])
    if c.header(block)!=d['anchor'] or s.o.context(block)!=d['context']:raise Refusal('anchor_changed')
    total=aggregate([x[2] for x in pools],result) if matches is True else None
    combined=None
    if total is not None:
        stock={x['address']:int(x['balance']['value']) for x in j['inventory'][:6]}
        combined={k:str(stock[k]+int(total.get(k,'0'))) for k in sorted(stock)}
    return dict(schema='uniswap-fee-collect-projection-v1',status='fixed_collection_probe_complete',
        anchor=d['anchor'],context=d['context'],adapter=ADAPTER,token_jar=JAR,
        configuration=config,configuration_matches=matches,selected_discovery_rows=[x[0] for x in pools],
        collection=result,collected_native=total,modeled_jar_after_collection_native=combined,
        source_conditional_token_order=True,call_effects_discarded=True,release_simulated=False,
        full_token_payment_proof=False,runtime_source_correspondence_verified=False,
        gas_cost_measured=False,cash_closed=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,4096)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,ALLOCATION,HELPER,DISCOVERY,REVIEW,INVENTORY,NOTES}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
            or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
            or p.get('endpoint')!='https://ethereum-rpc.publicnode.com' or p.get('adapter')!=ADAPTER):
        raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x['path'] for x in pins}!=required:raise Refusal('pins')
    for x in pins:
        data=read(ROOT/x['path'],32768)
        if len(data)!=x['bytes'] or sha(data)!=x['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN))>20480:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096))
    if (a.get('total_experiment_reservation_bytes')!=98304
            or a.get('categories_bytes')!={'source_tests_design':20480,'plan_and_claim':4096,
                'controls_reviews_readout':8192,'projection':8192,'raw':CAPS['raw_bytes']}):
        raise Refusal('allocation')
    d,j,pools=inputs()
    if p.get('pool_manifest_sha256')!=sha(encode(pools)) or p.get('anchor')!=d['anchor']:raise Refusal('pool_manifest')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


def replay(path,d,j,pools):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,d,j,pools);reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);d,j,pools=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        # The plan hash binds all input/source pins without duplicating them here.
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);p=collect(capture.rpc,d,j,pools)
                check,body,raw=replay(out/'raw',d,j,pools)
                if p!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_collection_probe_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_collection_probe_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);d,j,pools=inputs();v,b,r=replay(ROOT/OUT/'raw',d,j,pools)
        print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; one fixed public collect simulation');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
