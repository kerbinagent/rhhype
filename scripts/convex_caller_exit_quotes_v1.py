"""Reproduce one harvest and quote four post-harvest exits; default dry."""
import argparse
import copy
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/convex_caller_exit_quotes_v1.py'
TEST='tests/test_convex_caller_exit_quotes_v1.py'
BASE='reports/convex-caller-exit-quotes-v1/'
PLAN,DESIGN,OUT=(BASE+x for x in ('plan.json','design.txt','run-v1'))
ALLOCATION='reports/experiment-storage/convex-caller-exit-quotes-allocation-v1.json'
REWARD_SOURCE='scripts/convex_caller_incentive_v1.py'
QUOTE_SOURCE='scripts/uniswap_fee_cash_screen_v1.py'
PRIOR_BASE='reports/convex-caller-incentive-v1/'
PRIOR_PLAN=PRIOR_BASE+'plan.json'
PRIOR_SHA='7c74a936feece3e1b05d95cc9589048475510aa68ddea95096a3d68594a2a3c7'
PRIOR_PROJECTION=PRIOR_BASE+'run-v1/projection.json'
PRIOR_REVIEW=PRIOR_BASE+'root-review.json'
PRIOR_HEADER=PRIOR_BASE+'run-v1/raw/02.body'
PRIOR_BRANCH=PRIOR_BASE+'run-v1/raw/15.body'
PRIOR_NOTES='reports/sky-psm-fixed-quotes-v1/source-notes.json'
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
FEES=[100,500,3000,10000]
AMOUNT=50723731689102433
SLOTS=[('chain',4096),('factory',512),('simulation',32768),('recheck',24576)]
CAPS=dict(requests=4,body_bytes=65536,raw_bytes=65536,request_bytes=8192,projection_bytes=8192,
          request_seconds=20,work_seconds=105,wall_seconds=120,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=16600000)


def module(name,path,digest):
    p=ROOT/path
    if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
    with p.open('rb') as f:raw=f.read(32769)
    if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('helper_pin')
    v=types.ModuleType(name);v.__file__=str(p);exec(compile(raw,v.__file__,'exec'),v.__dict__);return v


r=module('convex_reward',REWARD_SOURCE,'8008b31faaed2d385bf8701f7feb0c5aa80811fe0f68c9e2011b4a32321bf8b3')
q=module('convex_quote',QUOTE_SOURCE,'60f4af6b42de5f618f0b8a11c5a66df0df1e9ae6d6a04aa48d3f136bc4134c34')
c,h,t,s,encode,decode,read,sha=r.c,r.h,r.t,r.s,r.encode,r.decode,r.read,r.sha


class Refusal(r.Refusal):pass


def inputs():
    r.verify(PRIOR_SHA)
    p=decode(read(ROOT/PRIOR_PROJECTION,8192));review=decode(read(ROOT/PRIOR_REVIEW,2048))
    if review.get('status')!='passed_scope_limited' or review.get('projection_sha256')!=sha(read(ROOT/PRIOR_PROJECTION,8192)):
        raise Refusal('prior_review')
    block=c.rpc_result(read(ROOT/PRIOR_HEADER,24576),2,False)
    prefix=c.rpc_result(read(ROOT/PRIOR_BRANCH,32768),15,False)
    if p['block']!=c.header(block) or p['hypothetical_context']!=r.target_context(block) or p['plan_sha256']!=PRIOR_SHA:
        raise Refusal('prior_anchor')
    receipt=r.parsed_branch(prefix,p['hypothetical_context'])
    if p['branches'][0]!=dict(pid=0,**receipt) or receipt['receipt_raw']!=str(AMOUNT) or not receipt['available']:
        raise Refusal('prior_receipt')
    return dict(block=block,context=p['hypothetical_context'],prefix=prefix,receipt=receipt)


def params(setup):
    value=r.sim_params(setup['block'],setup['context'],0)
    calls=value[0]['blockStateCalls'][0]['calls']
    for fee in FEES:
        call=r.tx(q.q.QUOTER,'factory()',gas=3000000)
        call['input']=q.calldata(False,r.CRV,WETH,AMOUNT,fee);calls.append(call)
    calls.append(r.tx(r.CRV,'balanceOf(address)',[r.ACTOR],100000))
    if sum(h.quantity(x['gas']) for x in calls)!=16300000:raise Refusal('simulation_gas')
    return value


def normalized(call):
    return dict(status=h.quantity(call.get('status')),gas=h.quantity(call.get('gasUsed')),
                data=h.hexdata(call.get('returnData')),logs=[s.o.log_content(x) for x in call.get('logs',[])],error=call.get('error'))


def simulation(value,setup):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'],quotes=[])
    if not isinstance(value,list) or len(value)!=1 or not isinstance(value[0],dict):raise Refusal('simulation_blocks')
    calls=value[0].get('calls')
    if not isinstance(calls,list) or len(calls)!=8:raise Refusal('eight_calls_required')
    prefix=copy.deepcopy(value);prefix[0]['calls']=calls[:3]
    receipt=r.parsed_branch(prefix,setup['context'])
    if receipt!=setup['receipt'] or [normalized(x) for x in calls[:3]]!=[normalized(x) for x in setup['prefix'][0]['calls']]:
        raise Refusal('original_harvest_prefix_changed')
    gas_reference=int(receipt['simulated_gas_used'][1])*h.quantity(setup['context']['baseFeePerGas'])
    rows=[]
    for fee,call in zip(FEES,calls[3:7]):
        if not isinstance(call,dict) or not isinstance(call.get('logs'),list):raise Refusal('quote_call_schema')
        z=normalized(call)
        if z['status'] not in (0,1) or not 21000<=z['gas']<=3000000:raise Refusal('quote_status_or_gas')
        if z['logs'] or (z['status']==1 and z['error'] is not None):raise Refusal('quote_logs_or_error')
        answer=q.quote(z['data']) if z['status']==1 else dict(available=False,reason='quote_reverted')
        complete=None;difference=None
        if answer['available']:
            limit=q.MIN_PRICE+1 if int(r.CRV,16)<int(WETH,16) else q.MAX_PRICE-1
            complete=int(answer['sqrt_price_after'])!=limit
            if complete:difference=str(int(answer['amount'])-gas_reference)
        rows.append(dict(fee=fee,quote=answer,full_input_source_conditional=complete,
                         quote_minus_simulated_harvest_gas_wei=difference))
    last=calls[7]
    if not isinstance(last,dict) or not isinstance(last.get('logs'),list):raise Refusal('final_balance_schema')
    z=normalized(last)
    if z['status']!=1 or z['error'] is not None or z['logs'] or not 21000<=z['gas']<=100000 or r.uint(z['data'])!=int(receipt['balance_after_raw']):
        raise Refusal('quotes_changed_actor_crv')
    return dict(available=True,original_harvest_prefix_matched=True,receipt=receipt,quotes=rows,
                actor_crv_after_quotes_raw=receipt['balance_after_raw'],conditional_harvest_gas_reference_wei=str(gas_reference),
                complete_quotes=sum(x['full_input_source_conditional'] is True for x in rows),
                unavailable_or_partial_quotes=sum(x['full_input_source_conditional'] is not True for x in rows))


def collect(rpc,setup):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    state=dict(blockHash=setup['block']['hash'],requireCanonical=True)
    factory=rpc('factory','eth_call',[r.tx(q.q.QUOTER,'factory()'),state])
    if c.address_word(factory)!=q.FACTORY:raise Refusal('quoter_factory')
    value=simulation(rpc('simulation','eth_simulateV1',params(setup),allow_unavailable=True),setup)
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[setup['block']['number'],False]),setup['block'])
    return dict(schema='convex-caller-exit-quotes-projection-v1',status='fixed_exit_check_complete',
        anchor=c.header(setup['block']),hypothetical_context=setup['context'],pid=0,crv_amount_raw=str(AMOUNT),
        quote_token=WETH,quoter=q.q.QUOTER,factory=q.FACTORY,result=value,
        validation=False,gas_price=0,state_overrides=False,post_harvest_quotes_are_not_sales=True,
        gas_reference_is_not_paid_cost_or_lower_bound=True,exit_costs_included=False,
        actor_control_claimed=False,cash_closed=False,economics=False,repeatable_profit=False)


def required_paths():return [SOURCE,TEST,DESIGN,ALLOCATION,REWARD_SOURCE,QUOTE_SOURCE,PRIOR_PLAN,PRIOR_PROJECTION,PRIOR_REVIEW,PRIOR_HEADER,PRIOR_BRANCH,PRIOR_NOTES]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('fees')!=FEES
        or p.get('amount')!=str(AMOUNT) or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN))>24576:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design=24576,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=8192,raw=65536)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=114688:raise Refusal('funding')
    if 300000+16300000!=CAPS['total_supplied_gas'] or len(SLOTS)!=CAPS['requests']:raise Refusal('gas_or_slots')
    setup=inputs()
    if p.get('anchor')!=c.header(setup['block']):raise Refusal('anchor')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return setup


def replay(path,setup):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,setup);reader.finish();return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        setup=verify(digest);out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,r.m.reason);p=collect(capture.rpc,setup)
                check,body,raw=replay(out/'raw',setup)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes']);status='fixed_exit_check_complete'
        except BaseException as exc:error=r.m.reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_exit_check_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        setup=verify(a.plan_sha256);v,b,rw=replay(ROOT/OUT/'raw',setup);print(encode(dict(status=v['status'],result=v['result'],body_bytes=b,raw_bytes=rw)).decode());return 0
    if not a.run:print('dry: zero requests; fixed Convex post-harvest quotes');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
