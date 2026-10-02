"""Reward check for the single previously unlisted registry keeper; default dry."""
import argparse
from pathlib import Path
import hashlib
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/curve_pegkeeper_registry_reward_v1.py'
TEST='tests/test_curve_pegkeeper_registry_reward_v1.py'
BASE='reports/curve-pegkeeper-registry-reward-v1/'
PLAN,DESIGN,OUT=(BASE+x for x in ('plan.json','design.txt','run-v1'))
ALLOCATION='reports/experiment-storage/curve-pegkeeper-registry-reward-allocation-v1.json'
HELPER='scripts/curve_pegkeeper_census_v1.py'
HELPER_SHA='e2056dfaa2c67129dffcf69b6b9517c0ceb2c905f7fe3344fdc980bd9ace875f'
INPUT='reports/curve-pegkeeper-census-v1/run-v1/raw/07.body'
INPUT_SHA='b4e00d473b49e0f45b9942daa15d04ebd68c9fe610a07a1df9c9403f58f44a4c'
KEEPER='0x53876b157decf04389eed66c7c29d73863f8c50b'
POOL='0x635ef0056a597d13863b73825cca297236578595'
CAPS=dict(requests=11,body_bytes=98304,raw_bytes=131072,request_bytes=8192,projection_bytes=8192,
          request_seconds=20,work_seconds=165,wall_seconds=180,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=5300000)


class Refusal(Exception):pass


def read(path,cap):
    if path.is_symlink() or not path.is_file():raise Refusal('nonregular_file')
    with path.open('rb') as f:raw=f.read(cap+1)
    if len(raw)>cap:raise Refusal('file_cap')
    return raw


def sha(raw):return hashlib.sha256(raw).hexdigest()


raw=read(ROOT/HELPER,32768)
if sha(raw)!=HELPER_SHA:raise Refusal('immutable_helper')
m=types.ModuleType('registry_reward_helpers');m.__file__=str(ROOT/HELPER)
exec(compile(raw,m.__file__,'exec'),m.__dict__)
k,c,h,t,encode,decode=m.k,m.c,m.h,m.t,m.encode,m.decode
SLOTS=[('chain',4096),('anchor',32768),('registry_4',4096)]+[(name,4096) for name,_,_ in k.FIELDS]+[('recheck',32768)]


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


def inputs():
    data=read(ROOT/INPUT,4096)
    if sha(data)!=INPUT_SHA:raise Refusal('original_registry_response_changed')
    case=m.registry_result(c.rpc_result(data,7,False))
    if case!=dict(available=True,keeper=KEEPER,pool=POOL,is_inverse=False,include_index=True):raise Refusal('frozen_case')
    return dict(original=m.inputs(),registry=case)


def collect(rpc,setup):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('wrong_chain')
    anchor=rpc('anchor','eth_getBlockByNumber',[hex(m.ANCHOR),False]);original=setup['original']
    if c.header(anchor)!=original['block'] or k.s.o.context(anchor)!=original['context']:raise Refusal('anchor_changed')
    block=dict(blockHash=original['block']['hash'],requireCanonical=True)
    def call(name,to,signature,gas,suffix=''):
        args={'from':k.DIAGNOSTIC,'to':to,'input':k.s.selector(signature)+suffix,'value':'0x0','gasPrice':'0x0','gas':hex(gas)}
        return rpc(name,'eth_call',[args,block],allow_unavailable=True)
    registry=m.registry_result(call('registry_4',k.REGULATOR,'peg_keepers(uint256)',300000,format(4,'064x')))
    if registry!=setup['registry']:raise Refusal('registry_recheck_unavailable_or_changed')
    values={name:k.result(call(name,KEEPER,signature,gas,k.s.word_address(k.DIAGNOSTIC) if name=='update' else ''),name)
            for name,signature,gas in k.FIELDS}
    k.s.o.same_header(rpc('recheck','eth_getBlockByNumber',[hex(m.ANCHOR),False]),anchor)
    reward=values['update']
    return dict(schema='curve-pegkeeper-registry-reward-projection-v1',status='fixed_new_keeper_calls_complete',
        anchor=c.header(anchor),context=k.s.o.context(anchor),registry_index=4,registry=registry,values=values,
        all_fields_available=all(v['available'] for v in values.values()),
        pool_matches_registry=(values['pool']['value']==POOL if values['pool']['available'] else None),
        pegged_and_regulator_match=(values['pegged']['value']==k.CRVUSD and values['regulator']['value']==k.REGULATOR
                                   if values['pegged']['available'] and values['regulator']['available'] else None),
        positive_returned_reward=(int(reward['value'])>0 if reward['available'] else None),
        failed_prior_census_promoted=False,independent_state_calls=True,zero_estimate_is_not_failure_proof=True,
        diagnostic_sender_control_claimed=False,gas_price_is_simulation_parameter=True,runtime_equivalence_verified=False,
        token_transfer_or_balance_verified=False,lp_cash_conversion_verified=False,gas_cost_measured=False,
        obtainable_inclusion_verified=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,16384)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,ALLOCATION,HELPER,INPUT}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('keeper')!=KEEPER
        or p.get('pool')!=POOL or p.get('anchor')!=m.ANCHOR):raise Refusal('frozen_scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],65536)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN))+len(raw)>65536:raise Refusal('source_package_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,setup):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,setup);reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        plan=verify(digest);setup=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        k.s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=plan['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason)
                p=collect(capture.rpc,setup);check,body,raw=replay(out/'raw',setup)
                if p!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('exact_replay')
                verify(digest);p['plan_sha256']=digest
                k.s.o.publish(out,'projection.json',p,CAPS['projection_bytes']);status='fixed_new_keeper_calls_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            k.s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_new_keeper_calls_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    args=p.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw',inputs())
        print(encode(dict(status=result['status'],positive_reward=result['positive_returned_reward'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run:print('dry: zero requests;zero outputs;one new registry keeper');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
