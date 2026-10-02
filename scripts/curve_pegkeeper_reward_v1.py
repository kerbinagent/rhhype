"""Fixed four-deployment PegKeeper caller-reward simulation, default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/curve_pegkeeper_reward_v1.py'
TEST='tests/test_curve_pegkeeper_reward_v1.py'
BASE='reports/curve-pegkeeper-reward-v1/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/curve-pegkeeper-reward-preparation-v1.json'
HELPER='scripts/aave_state_transition_v1.py'
HELPER_SHA='9bb451c71b62a6ee67447cf991c795877e3431b6659dc1a8344345455c9cedd1'
KEEPERS=[('USDC','0x9201da0d97caaaff53f01b2fb56767c7072de340'),
         ('USDT','0xfb726f57d251ab5c731e5c64ed4f5f94351ef9f3'),
         ('pyUSD','0x3fa20eaa107de08b38a8734063d605d5842fe09c'),
         ('frxUSD','0x338cb2d827112d989a861cde87cd9ffd913a1f9d')]
REGULATOR='0x36a04caffc681fa179558b2aaba30395cddd855f'
CRVUSD='0xf939e0a03fb07f59a73314e73794be0e57ac1b4e'
DIAGNOSTIC='0x0000000000000000000000000000000000000001'
FIELDS=[('pool','pool()',300000),('pegged','pegged()',300000),
        ('regulator','regulator()',300000),('caller_share','caller_share()',300000),
        ('last_change','last_change()',300000),('estimate','estimate_caller_profit()',1500000),
        ('update','update(address)',2000000)]
SLOTS=[('chain',4096),('block',32768)]+[(str(i)+'_'+name,4096) for i in range(4) for name,_,_ in FIELDS]+[('recheck',32768)]
CAPS=dict(requests=31,body_bytes=196608,raw_bytes=262144,request_bytes=8192,projection_bytes=16384,
          request_seconds=20,work_seconds=165,wall_seconds=180,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=20000000)


class Refusal(Exception):pass


def read(path,cap):
    if path.is_symlink() or not path.is_file():raise Refusal('nonregular_file')
    with path.open('rb') as f:raw=f.read(cap+1)
    if len(raw)>cap:raise Refusal('file_cap')
    return raw


def sha(raw):return hashlib.sha256(raw).hexdigest()


raw=read(ROOT/HELPER,32768)
if sha(raw)!=HELPER_SHA:raise Refusal('immutable_helper')
s=types.ModuleType('pegkeeper_helpers');s.__file__=str(ROOT/HELPER)
exec(compile(raw,s.__file__,'exec'),s.__dict__)
c,h,t,encode,decode=s.o.c,s.h,s.t,s.encode,s.decode


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else s.reason(exc)


def address(raw):
    value=c.address_word(raw)
    if value=='0x'+'00'*20:raise Refusal('zero_address')
    return value


def result(value,kind):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'])
    try:
        parsed=address(value) if kind in ('pool','pegged','regulator') else s.uint_word(value)
        if kind=='caller_share' and int(parsed)>100000:raise Refusal('share_out_of_documented_range')
    except (Refusal,s.Refusal,c.Refusal,h.Refusal,TypeError,ValueError):
        return dict(available=False,reason='null_or_noncanonical_result')
    return dict(available=True,value=parsed)


def collect(rpc):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('wrong_chain')
    block=rpc('block','eth_getBlockByNumber',['finalized',False])
    header=c.header(block);context=s.o.context(block)
    selector=dict(blockHash=header['hash'],requireCanonical=True)
    rows=[]
    for i,(label,keeper) in enumerate(KEEPERS):
        values={}
        for name,signature,gas in FIELDS:
            data=s.selector(signature)+(s.word_address(DIAGNOSTIC) if name=='update' else '')
            call={'from':DIAGNOSTIC,'to':keeper,'input':data,'value':'0x0','gasPrice':'0x0','gas':hex(gas)}
            value=rpc(str(i)+'_'+name,'eth_call',[call,selector],allow_unavailable=True)
            values[name]=result(value,name)
        valid=all(v['available'] for v in values.values())
        identity=(values['pegged']['value']==CRVUSD and values['regulator']['value']==REGULATOR
                  if values['pegged']['available'] and values['regulator']['available'] else None)
        reward=values['update']
        rows.append(dict(label=label,address=keeper,values=values,all_fields_available=valid,
            documented_pegged_and_regulator_match=identity,
            positive_returned_reward=(int(reward['value'])>0 if reward['available'] else None)))
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[block['number'],False]),block)
    return dict(schema='curve-pegkeeper-reward-projection-v1',status='fixed_deployment_calls_complete',
        block=header,context=context,rows=rows,attempted_deployments=4,
        update_results_available=sum(x['values']['update']['available'] for x in rows),
        positive_returned_reward_rows=sum(x['positive_returned_reward'] is True for x in rows),
        independent_state_calls=True,rewards_summed=False,gas_price_is_simulation_parameter=True,
        diagnostic_sender_control_claimed=False,lp_cash_conversion_verified=False,token_transfer_or_balance_verified=False,
        runtime_equivalence_verified=False,obtainable_inclusion_verified=False,gas_cost_measured=False,
        live_profit=False,repeatable_profit=False,zero_estimate_is_not_failure_proof=True)


def verify(digest):
    raw=read(ROOT/PLAN,16384)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    plan=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,HELPER}
    if (plan.get('status')!='frozen' or plan.get('caps')!=CAPS or plan.get('keepers')!=[list(x) for x in KEEPERS]
        or plan.get('slots')!=[list(x) for x in SLOTS] or plan.get('fields')!=[list(x) for x in FIELDS]
        or plan.get('runtime')!=h.runtime() or plan.get('output_dir')!=OUT):raise Refusal('frozen_scope')
    pins=plan.get('pins',[])
    if len(pins)!=len(required) or {p.get('path') for p in pins}!=required:raise Refusal('pins_schema')
    for p in pins:
        data=read(ROOT/p['path'],98304)
        if len(data)!=p['bytes'] or sha(data)!=p['sha256']:raise Refusal('source_pin')
    if sum(p['bytes'] for p in pins if p['path'] in (SOURCE,TEST,DESIGN))+len(raw)>98304:raise Refusal('source_package_cap')
    if sum(gas for _,_,gas in FIELDS)*len(KEEPERS)!=CAPS['total_supplied_gas']:raise Refusal('gas_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return plan


def replay(path):
    reader=t.Reader(path,SLOTS,CAPS,c);projection=collect(reader.rpc);reader.finish()
    return projection,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        plan=verify(digest);out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=plan['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason)
                projection=collect(capture.rpc);check,body,raw=replay(out/'raw')
                if projection!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('exact_replay')
                verify(digest);projection['plan_sha256']=digest
                s.o.publish(out,'projection.json',projection,CAPS['projection_bytes']);status='fixed_deployment_calls_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_deployment_calls_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    args=p.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw')
        print(encode(dict(status=result['status'],positive_rewards=result['positive_returned_reward_rows'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run:print('dry: zero requests;zero outputs;fixed four PegKeeper simulations');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
