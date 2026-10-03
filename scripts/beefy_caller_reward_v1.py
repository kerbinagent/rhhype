"""Two source-selected public Beefy caller reward diagnostics; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/beefy_caller_reward_v1.py'
TEST='tests/test_beefy_caller_reward_v1.py'
BASE='reports/beefy-caller-reward-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment-v1.json','run-v1'))
ALLOCATION='reports/experiment-storage/beefy-caller-reward-allocation-v1.json'
PREP='reports/experiment-storage/beefy-caller-reward-preparation-v1.json'
HELPER='scripts/convex_caller_incentive_v1.py'
HELPER_SHA='8008b31faaed2d385bf8701f7feb0c5aa80811fe0f68c9e2011b4a32321bf8b3'
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
VAULTS=[('yb-cbbtc','0xde2cda87d8c9efce4c363edcbc74fd3857e0cfd7'),
        ('stakedao-susg-reusd','0x84e6a8374658fdab50cb6c39e92b83c51f84fa28')]
FIELDS=[('strategy','strategy()','address'),('native','native()','pool'),('paused','paused()','boolean'),('callReward','callReward()','uint')]
SLOTS=[('chain',4096),('block',24576)]+[(str(i)+'_'+x[0],2048) for i in range(2) for x in FIELDS]+[
    ('branch_'+str(i),32768) for i in range(2)]+[('recheck',24576)]
CAPS=dict(requests=13,body_bytes=196608,raw_bytes=106496,request_bytes=8192,projection_bytes=8192,
          request_seconds=20,work_seconds=105,wall_seconds=120,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=10800000)


p=ROOT/HELPER
if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
with p.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
r=types.ModuleType('beefy_transport');r.__file__=str(p);exec(compile(raw,r.__file__,'exec'),r.__dict__)
c,h,t,s,encode,decode,read,sha=r.c,r.h,r.t,r.s,r.encode,r.decode,r.read,r.sha


class Refusal(r.Refusal):pass


def sim_params(block,context,strategy):
    calls=[r.tx(WETH,'balanceOf(address)',[r.ACTOR],100000),r.tx(strategy,'harvest(address)',[r.ACTOR],4000000),
           r.tx(WETH,'balanceOf(address)',[r.ACTOR],100000)]
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
        h.hexdata(call.get('returnData'));statuses.append(status);gas.append(str(used));logs.append([s.o.log_content(x) for x in call['logs']])
    if statuses[0]!=1 or statuses[2]!=1 or logs[0] or logs[2]:raise Refusal('balance_probe_failed')
    before,after=r.uint(calls[0]['returnData']),r.uint(calls[2]['returnData'])
    if statuses[1]==0:
        if logs[1] or after!=before:raise Refusal('revert_changed_state')
        return dict(available=False,reason='harvest_reverted',simulated_gas_used=gas,weth_receipt_raw=None)
    net=0;count=0
    for log in logs[1]:
        if log['address']!=WETH or not log['topics'] or log['topics'][0]!=r.TRANSFER:continue
        if len(log['topics'])!=3:raise Refusal('weth_transfer_topics')
        sender,recipient=map(c.address_word,log['topics'][1:]);amount=r.uint(log['data'])
        net+=amount*(int(recipient==r.ACTOR)-int(sender==r.ACTOR));count+=1
    if net!=after-before:raise Refusal('balance_transfer_disagreement')
    reference=int(gas[1])*h.quantity(context['baseFeePerGas'])
    return dict(available=True,balance_before_raw=str(before),balance_after_raw=str(after),weth_receipt_raw=str(net),
        positive_weth_receipt=net>0,simulated_gas_used=gas,weth_transfer_events=count,transfer_balance_agree=True,
        harvest_return_bytes=(len(calls[1]['returnData'])-2)//2,conditional_harvest_gas_reference_wei=str(reference),
        weth_receipt_minus_unpaid_reference_wei=str(net-reference),other_token_or_native_receipts_not_measured=True)


def branch(value,context):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'],weth_receipt_raw=None)
    try:return parsed_branch(value,context)
    except (r.m.Refusal,s.Refusal,s.o.Refusal,c.Refusal,h.Refusal,TypeError,ValueError,KeyError) as exc:
        return dict(available=False,reason='invalid_simulation:'+r.m.reason(exc),weth_receipt_raw=None)


def collect(rpc):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    block=rpc('block','eth_getBlockByNumber',['latest',False]);header=c.header(block);context=r.target_context(block)
    state=dict(blockHash=header['hash'],requireCanonical=True);rows=[]
    for i,(name,vault) in enumerate(VAULTS):
        metadata={};strategy=None
        for field,signature,kind in FIELDS:
            target=vault if field=='strategy' else strategy
            value=rpc(str(i)+'_'+field,'eth_call',[r.tx(target,signature),state],allow_unavailable=field!='strategy')
            parsed=r.m.result(value,kind);metadata[field]=parsed
            if field=='strategy':
                if not parsed['available']:raise Refusal('strategy_address_unavailable')
                strategy=parsed['value']
        native=metadata['native']
        rows.append(dict(id=name,vault=vault,strategy=strategy,metadata=metadata,
            reported_native_matches_weth=native['value']==WETH if native['available'] else None))
    for i,row in enumerate(rows):
        row['simulation']=branch(rpc('branch_'+str(i),'eth_simulateV1',sim_params(block,context,row['strategy']),allow_unavailable=True),context)
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[block['number'],False]),block)
    return dict(schema='beefy-caller-reward-projection-v1',status='fixed_branches_complete',block=header,
        hypothetical_context=context,diagnostic_actor=r.ACTOR,weth=WETH,vaults=rows,
        available_branches=sum(x['simulation']['available'] for x in rows),requested_anchor_tag='latest',
        independent_same_state_branches=True,validation=False,state_overrides=False,simulated_gas_price=0,
        actor_control_claimed=False,paid_execution_verified=False,runtime_equivalence_proved=False,
        gas_reference_is_not_paid_cost_or_lower_bound=True,native_cash_exit_verified=False,cash_closed=False,
        economics=False,repeatable_profit=False)


def required_paths():return [SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,HELPER]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('fields')!=[list(x) for x in FIELDS]
        or p.get('vaults')!=[list(x) for x in VAULTS] or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] not in (HELPER,ALLOCATION))>28672:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=28672,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=8192,raw=106496)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=159744:raise Refusal('funding')
    notes=decode(read(ROOT/NOTES,8192));chosen=[(x['id'],x['vault']) for x in notes['source_candidates'][:2]]
    if chosen!=VAULTS or len(notes['sources'])!=8:raise Refusal('source_selection')
    if 8*300000+2*4200000!=CAPS['total_supplied_gas'] or len(SLOTS)!=CAPS['requests']:raise Refusal('gas_or_slots')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc);reader.finish();return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,r.m.reason);p=collect(capture.rpc)
                check,body,raw=replay(out/'raw')
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes']);status='fixed_branches_complete'
        except BaseException as exc:error=r.m.reason(exc)
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
        verify(a.plan_sha256);v,b,rw=replay(ROOT/OUT/'raw');print(encode(dict(status=v['status'],available=v['available_branches'],body_bytes=b,raw_bytes=rw)).decode());return 0
    if not a.run:print('dry: zero requests; two public Beefy reward diagnostics');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
