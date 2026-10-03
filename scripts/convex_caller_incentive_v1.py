"""Four independent public Convex caller-reward diagnostics; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/convex_caller_incentive_v1.py'
TEST='tests/test_convex_caller_incentive_v1.py'
BASE='reports/convex-caller-incentive-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment-v1.json','run-v1'))
ALLOCATION='reports/experiment-storage/convex-caller-incentive-allocation-v1.json'
PREP='reports/experiment-storage/convex-caller-incentive-preparation-v1.json'
BUDGET=BASE+'category-amendment-v1.json'
HELPER='scripts/sky_psm_discovery_v1.py'
HELPER_SHA='c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
BOOSTER='0xf403c135812408bfbe8713b5a23a04b3d48aae31'
STAKER='0x989aeb4d175e16225e39e87d0d97a3360524ad80'
CRV='0xd533a949740bb3306d119cc777fa900ba034cd52'
ACTOR='0x000000000000000000000000000000000000c0de'
FIELDS=[('crv',BOOSTER,'crv()'),('staker',BOOSTER,'staker()'),('operator',STAKER,'operator()'),
        ('shutdown',BOOSTER,'isShutdown()'),('denominator',BOOSTER,'FEE_DENOMINATOR()'),
        ('incentive',BOOSTER,'earmarkIncentive()'),('length',BOOSTER,'poolLength()'),('decimals',CRV,'decimals()')]
SLOTS=[('chain',4096),('block',24576)]+[(x[0],512) for x in FIELDS]+[
    ('pool_'+str(i),2048) for i in range(4)]+[('branch_'+str(i),32768) for i in range(4)]+[('recheck',24576)]
CAPS=dict(requests=19,body_bytes=196608,raw_bytes=104448,request_bytes=8192,projection_bytes=8192,
          request_seconds=20,work_seconds=105,wall_seconds=120,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=20400000)


raw=(ROOT/HELPER).read_bytes()
if (ROOT/HELPER).is_symlink() or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
m=types.ModuleType('convex_transport');m.__file__=str(ROOT/HELPER);exec(compile(raw,m.__file__,'exec'),m.__dict__)
c,h,t,s,encode,decode,read,sha=m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha
TRANSFER=c.keccak_hex('Transfer(address,address,uint256)')


class Refusal(m.Refusal):pass


def uint(value):return int(h.hexdata(value,32),16)


def pool_ids(n):
    if not 4<=n<=4096:raise Refusal('pool_length_cap')
    return [i*(n-1)//3 for i in range(4)]


def tx(to,signature,args=(),gas=300000):
    data=s.selector(signature)+''.join(s.word_address(x) if isinstance(x,str) else format(x,'064x') for x in args)
    return {'from':ACTOR,'to':to,'input':data,'value':'0x0','gasPrice':'0x0','gas':hex(gas)}


def pool_info(value,pid):
    data=h.hexdata(value,192)[2:];words=['0x'+data[i:i+64] for i in range(0,384,64)]
    row=dict(zip(('lptoken','token','gauge','crvRewards','stash'),map(c.address_word,words[:5])))
    if any(int(row[k],16)==0 for k in ('lptoken','token','gauge','crvRewards')):raise Refusal('pool_zero_identity')
    flag=uint(words[5])
    if flag not in (0,1):raise Refusal('pool_boolean')
    return dict(pid=pid,shutdown=bool(flag),**row)


def target_context(block):
    context=s.o.context(block)
    context.update(number=hex(h.quantity(context['number'])+1),time=hex(h.quantity(context['time'])+12))
    if h.quantity(context['gasLimit'])<4200000:raise Refusal('block_gas_limit')
    return context


def sim_params(block,context,pid):
    calls=[tx(CRV,'balanceOf(address)',[ACTOR],100000),tx(BOOSTER,'earmarkRewards(uint256)',[pid],4000000),
           tx(CRV,'balanceOf(address)',[ACTOR],100000)]
    return [dict(blockStateCalls=[dict(blockOverrides=context,calls=calls)],
                 validation=False,traceTransfers=True,returnFullTransactions=False),block['number']]


def parsed_branch(value,context):
    if not isinstance(value,list) or len(value)!=1 or not isinstance(value[0],dict):raise Refusal('simulation_blocks')
    block=value[0]
    for field,expected in context.items():
        aliases={'time':('timestamp','time'),'feeRecipient':('miner','feeRecipient'),'prevRandao':('mixHash','prevRandao')}.get(field,(field,))
        present=[k for k in aliases if k in block]
        if not present:raise Refusal('simulation_context_missing')
        for key in present:
            actual=h.hexdata(block[key],20 if field=='feeRecipient' else 32) if field in ('feeRecipient','prevRandao') else hex(h.quantity(block[key]))
            if actual!=expected:raise Refusal('simulation_context_changed')
    calls=block.get('calls')
    if not isinstance(calls,list) or len(calls)!=3:raise Refusal('simulation_call_count')
    statuses=[];gas=[];logs=[]
    for call,limit in zip(calls,(100000,4000000,100000)):
        if not isinstance(call,dict) or not isinstance(call.get('logs'),list):raise Refusal('simulation_call_schema')
        status=h.quantity(call.get('status'));used=h.quantity(call.get('gasUsed'))
        if status not in (0,1) or not 21000<=used<=limit:raise Refusal('status_or_gas')
        if status==1 and call.get('error') is not None:raise Refusal('success_with_error')
        h.hexdata(call.get('returnData'))
        statuses.append(status);gas.append(str(used));logs.append([s.o.log_content(x) for x in call['logs']])
    if statuses[0]!=1 or statuses[2]!=1 or logs[0] or logs[2]:raise Refusal('balance_probe_failed')
    before,after=uint(calls[0]['returnData']),uint(calls[2]['returnData'])
    if statuses[1]==0:
        if logs[1] or after!=before:raise Refusal('revert_changed_state')
        return dict(available=False,reason='harvest_reverted',simulated_gas_used=gas,receipt_raw=None)
    if uint(calls[1]['returnData'])!=1:raise Refusal('harvest_return_not_true')
    net=0;count=0
    for log in logs[1]:
        if log['address']!=CRV or not log['topics'] or log['topics'][0]!=TRANSFER:continue
        if len(log['topics'])!=3:raise Refusal('crv_transfer_topics')
        sender,recipient=map(c.address_word,log['topics'][1:]);amount=uint(log['data'])
        net+=amount*(int(recipient==ACTOR)-int(sender==ACTOR));count+=1
    if net!=after-before:raise Refusal('balance_transfer_disagreement')
    return dict(available=True,balance_before_raw=str(before),balance_after_raw=str(after),receipt_raw=str(net),
                positive_receipt=net>0,simulated_gas_used=gas,crv_transfer_events=count,transfer_balance_agree=True)


def branch(value,context):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'],receipt_raw=None)
    try:return parsed_branch(value,context)
    except (m.Refusal,s.Refusal,s.o.Refusal,c.Refusal,h.Refusal,TypeError,ValueError,KeyError) as exc:
        return dict(available=False,reason='invalid_simulation:'+m.reason(exc),receipt_raw=None)


def collect(rpc):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    block=rpc('block','eth_getBlockByNumber',['finalized',False]);header=c.header(block);context=target_context(block)
    state=dict(blockHash=header['hash'],requireCanonical=True)
    metadata={name:rpc(name,'eth_call',[tx(to,sig),state]) for name,to,sig in FIELDS}
    for name,expected in [('crv',CRV),('staker',STAKER),('operator',BOOSTER)]:
        if c.address_word(metadata[name])!=expected:raise Refusal('source_wiring_mismatch')
    vals={key:uint(metadata[key]) for key in ('shutdown','denominator','incentive','length','decimals')}
    if vals['shutdown'] not in (0,1) or vals['denominator']!=10000 or vals['incentive']>10000 or vals['decimals']!=18:
        raise Refusal('metadata_units_or_width')
    ids=pool_ids(vals['length'])
    pools=[pool_info(rpc('pool_'+str(i),'eth_call',[tx(BOOSTER,'poolInfo(uint256)',[pid]),state]),pid) for i,pid in enumerate(ids)]
    branches=[dict(pid=pid,**branch(rpc('branch_'+str(i),'eth_simulateV1',sim_params(block,context,pid),allow_unavailable=True),context)) for i,pid in enumerate(ids)]
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[block['number'],False]),block)
    return dict(schema='convex-caller-incentive-projection-v1',status='fixed_branches_complete',block=header,
        hypothetical_context=context,booster=BOOSTER,staker=STAKER,crv=CRV,diagnostic_actor=ACTOR,
        metadata=vals,pools=pools,branches=branches,available_branches=sum(x['available'] for x in branches),
        separate_same_state_branches_never_add_rewards=True,validation=False,state_overrides=False,
        simulated_gas_price=0,actor_control_claimed=False,paid_execution_verified=False,runtime_equivalence_proved=False,
        reward_value_in_cash=None,cash_closed=False,economics=False,repeatable_profit=False)


def required_paths():return [SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,HELPER,BUDGET]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('fields')!=[list(x) for x in FIELDS]
        or p.get('actor')!=ACTOR or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] not in (HELPER,ALLOCATION,BUDGET))>26624:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=26624,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=8192,raw=104448)
    amend=decode(read(ROOT/BUDGET,2048))
    if amend['categories_bytes']!=expected or amend['total_experiment_reservation_bytes']!=155648 or a['total_experiment_reservation_bytes']!=155648:raise Refusal('funding')
    if 12*300000+4*4200000!=CAPS['total_supplied_gas'] or len(SLOTS)!=CAPS['requests']:raise Refusal('gas_or_slots')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,m.reason);p=collect(capture.rpc)
                check,body,raw=replay(out/'raw')
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes']);status='fixed_branches_complete'
        except BaseException as exc:error=m.reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_branches_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw');print(encode(dict(status=v['status'],available=v['available_branches'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; four independent Convex reward diagnostics');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
