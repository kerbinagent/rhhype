"""Compact historical native balance diff; anonymous reads, default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/uniswap_fee_release_native_flow_v1.py'
TEST='tests/test_uniswap_fee_release_native_flow_v1.py'
BASE='reports/uniswap-fee-release-native-flow-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment.json','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-fee-release-native-flow-allocation-v1.json'
PREP='reports/experiment-storage/uniswap-fee-release-native-flow-preparation-v1.json'
BUDGET=BASE+'budget-amendment-v1.json'
HELPER='scripts/uniswap_fee_release_receipt_v2.py'
HELPER_SHA='6e4c4d0e2b0d9530293dc526962ed99d17a2ce5438f943e2ac895dc95894a20e'
RECEIPT_PLAN='f5d3dfee52c7d66cd00dc8c4517cf4a99d7d45bc9d9d2c18680b0b7be1e69536'
SLOTS=[('chain',4096),('native_diff',32768),('recheck',32768)]
CAPS=dict(requests=3,body_bytes=69632,raw_bytes=45056,request_bytes=8192,
          projection_bytes=12288,request_seconds=20,work_seconds=105,wall_seconds=120,
          cpu_seconds=20,ram_bytes=536870912,max_changed_addresses=32)
OPTIONS=dict(tracer='prestateTracer',tracerConfig=dict(diffMode=True,disableCode=True,disableStorage=True),timeout='10s',reexec=0)
p=ROOT/HELPER
if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
with p.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
k=types.ModuleType('native_receipt_helpers');k.__file__=str(p)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
m,c,h,t,s,encode,decode,read,sha=k.m,k.c,k.h,k.t,k.s,k.encode,k.decode,k.read,k.sha
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
DEPOSIT=c.keccak_hex('Deposit(address,uint256)')
WITHDRAWAL=c.keccak_hex('Withdrawal(address,uint256)')


class Refusal(k.k.Refusal):pass


def uint(value,bits=256):
    n=h.quantity(value)
    if not 0<=n<2**bits:raise Refusal('uint_width')
    return n


def inputs():
    old=k.inputs();base=k.BASE
    projection=read(ROOT/(base+'run-v1/projection.json'),16384);prior=decode(projection)
    review=decode(read(ROOT/(base+'root-review.json'),2048))
    terminal=decode(read(ROOT/(base+'run-v1/terminal.json'),2048))
    if (review.get('status')!='passed_scope_limited' or review.get('plan_sha256')!=RECEIPT_PLAN
        or review.get('projection_sha256')!=sha(projection) or prior.get('plan_sha256')!=RECEIPT_PLAN
        or prior.get('status')!='fixed_release_receipt_complete'
        or terminal.get('status')!='fixed_release_receipt_complete' or terminal.get('error') is not None
        or terminal.get('plan_sha256')!=RECEIPT_PLAN or terminal.get('requests_attempted')!=3):
        raise Refusal('receipt_admission')
    raw=read(ROOT/(base+'run-v1/raw/02.body'),196608)
    receipt_meta=decode(read(ROOT/(base+'run-v1/raw/02.receipt.json'),2048));response=decode(raw)
    if (receipt_meta.get('http_status')!=200 or receipt_meta.get('error') is not None
        or receipt_meta.get('dispatch_attempted') is not True or receipt_meta.get('response_bytes')!=len(raw)
        or receipt_meta.get('response_sha256')!=sha(raw) or response.get('id')!=2
        or response.get('jsonrpc')!='2.0' or 'error' in response):raise Refusal('retained_receipt_identity')
    receipt=response['result'];r=k.k.receipt(receipt,old['event'],old['transaction'],old['original'])
    if (r!=prior.get('receipt') or old['event']!=prior.get('selected_event')
        or old['transaction']!=prior.get('transaction') or c.header(old['header'])!=prior.get('event_block')
        or s.o.context(old['header'])!=prior.get('event_context')):raise Refusal('retained_projection_identity')
    tx=k.old_result(4,65536)
    if old['transaction']['transaction_type']!=2 or 'authorizationList' in tx or tx.get('blobVersionedHashes'):
        raise Refusal('transaction_fee_scope')
    return dict(old,receipt=receipt,ledger=r,tx_nonce=uint(tx['nonce'],64))


def account(value,pre):
    if not isinstance(value,dict) or set(value)-{'balance','nonce','codeHash','code','storage'}:
        raise Refusal('account_shape')
    if value.get('code','0x')!='0x' or value.get('storage',{})!={}:raise Refusal('disabled_payload_present')
    if 'codeHash' in value:h.hexdata(value['codeHash'],32)
    if pre and 'balance' not in value:raise Refusal('missing_pre_balance')
    balance=uint(value['balance']) if 'balance' in value else None
    nonce=value.get('nonce',0)
    if type(nonce) is not int or not 0<=nonce<2**64:raise Refusal('nonce_domain')
    return balance,nonce


def native_diff(value,old):
    if not isinstance(value,dict) or set(value)!={'pre','post'}:raise Refusal('trace_unavailable_or_shape')
    sides=[]
    for name in ('pre','post'):
        source=value[name]
        if not isinstance(source,dict) or len(source)>CAPS['max_changed_addresses']:raise Refusal('account_count')
        result={}
        for address,state in source.items():
            normalized=k.k.addr(address)
            if address!=normalized or normalized in result:raise Refusal('canonical_account_address')
            result[normalized]=account(state,name=='pre')
        sides.append(result)
    pre,post=sides;addresses=sorted(pre.keys()|post.keys())
    if len(addresses)>CAPS['max_changed_addresses']:raise Refusal('account_union_cap')
    sender=old['transaction']['sender']
    if (sender not in pre or sender not in post or pre[sender][1]!=old['tx_nonce']
        or post[sender][1]!=old['tx_nonce']+1):raise Refusal('sender_nonce_transition')
    rows=[];deltas={}
    for address in addresses:
        before=pre[address][0] if address in pre else 0
        after=(post[address][0] if post[address][0] is not None else before) if address in post else 0
        # A created account with omitted balance has zero native value.
        if after is None:raise Refusal('native_balance_missing')
        deltas[address]=after-before
        rows.append([address,str(before),str(after),str(after-before)])
    gas=old['ledger']['gas_used'];price=int(old['ledger']['effective_gas_price_wei'])
    context=s.o.context(old['header']);basefee=uint(context['baseFeePerGas'])
    if price<basefee or sum(deltas.values())!=-gas*basefee:raise Refusal('gas_conservation')
    recipient=old['event']['recipient'];fee_recipient=k.k.addr(context['feeRecipient'])
    members=sorted({sender,recipient});tip=gas*(price-basefee)
    return dict(account_columns=['address','before_wei','after_wei','delta_wei'],accounts=rows,
        gas_used=gas,effective_gas_price_wei=str(price),base_fee_per_gas_wei=str(basefee),
        charged_gas_wei=str(gas*price),burned_basefee_wei=str(gas*basefee),priority_fee_wei=str(tip),
        total_native_delta_wei=str(sum(deltas.values())),gas_already_included_in_deltas=True,
        sender_delta_wei=str(deltas.get(sender,0)),executor_delta_wei=str(deltas.get(recipient,0)),
        fee_recipient=fee_recipient,fee_recipient_delta_wei=str(deltas.get(fee_recipient,0)),
        fee_recipient_delta_excluding_priority_fee_wei=str(deltas.get(fee_recipient,0)-tip),
        conditional_group_members=members,conditional_group_delta_wei=str(sum(deltas.get(a,0) for a in members)),
        omitted_unchanged_accounts_assumed_zero_after_conservation=True,
        group_ownership_proved=False,internal_call_paths_observed=False)


def weth_adjustment(old):
    owners=set(old['ledger']['roles'].values())-{None};wrapped={a:[0,0] for a in owners};events=[]
    for log in old['receipt']['logs']:
        if k.k.addr(log['address'])!=WETH:continue
        topics=log.get('topics')
        if not isinstance(topics,list) or not topics:raise Refusal('weth_topics')
        if topics[0] not in (DEPOSIT,WITHDRAWAL):continue
        if len(topics)!=2:raise Refusal('weth_wrap_shape')
        address=c.address_word(topics[1]);amount=int(h.hexdata(log['data'],32),16)
        kind='deposit' if topics[0]==DEPOSIT else 'withdrawal'
        events.append([h.quantity(log['logIndex']),kind,address,str(amount)])
        if address in wrapped:wrapped[address][0 if kind=='deposit' else 1]+=amount
    transfers={(r[0],r[1]):int(r[4]) for r in old['ledger']['transfer_ledger']}
    rows=[[a,str(transfers.get((a,WETH),0)),str(d),str(w),str(transfers.get((a,WETH),0)+d-w)]
          for a,(d,w) in sorted(wrapped.items())]
    others=[r for r in old['ledger']['transfer_ledger'] if r[1]!=WETH]
    return dict(token=WETH,event_columns=['log_index','kind','address','amount_wei'],events=events,
        columns=['address','transfer_net_wei','deposits_wei','withdrawals_wei','conditional_balance_delta_wei'],rows=rows,
        other_transfer_ledger_rows=len(others),other_transfer_net_nonzero_rows=[r for r in others if int(r[4])!=0],
        standard_weth_semantics_assumed=True,deployed_runtime_verified=False,other_token_balance_completeness_proved=False)


def collect(rpc,old):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    e=old['event'];native=native_diff(rpc('native_diff','debug_traceTransaction',[e['transaction_hash'],OPTIONS]),old)
    check=rpc('recheck','eth_getBlockByNumber',[hex(e['block_number']),False]);s.o.same_header(check,old['header'])
    return dict(schema='uniswap-fee-release-native-flow-projection-v1',status='fixed_native_diff_complete',
        selected_event=e,event_block=c.header(old['header']),native=native,weth=weth_adjustment(old),
        provider_trace_is_not_cryptographic_proof=True,private_external_payments_observed=False,
        historical_sample_is_not_prospective_selection=True,cash_closed=False,economics=False,repeatable_profit=False)


def required_paths():
    return [SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,BUDGET,HELPER,k.HELPER,k.k.HELPER,k.k.INPUT,k.k.REVIEW,
        k.OLD+'root-review.json',k.OLD+'run-v1/terminal.json',k.BASE+'root-review.json',
        k.BASE+'run-v1/projection.json',k.BASE+'run-v1/terminal.json',
        k.BASE+'run-v1/raw/02.body',k.BASE+'run-v1/raw/02.receipt.json']+[
        k.OLD+'run-v1/raw/'+format(i,'02d')+ext for i in (2,3,4) for ext in ('.body','.receipt.json')]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('trace_options')!=OPTIONS or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],196608)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES,AMEND,PREP))>28672:
        raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=24576,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=12288,raw=49152)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=102400:raise Refusal('funding')
    effective=dict(expected,source_tests_design_notes=28672,raw=45056)
    if decode(read(ROOT/BUDGET,2048)).get('categories_bytes')!=effective:raise Refusal('budget_amendment')
    if p.get('selected_event')!=inputs()['event']:raise Refusal('selection_identity')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,old):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc,old);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);old=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,k.k.reason);p=collect(capture.rpc,old)
                check,body,raw=replay(out/'raw',old)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_native_diff_complete'
        except BaseException as exc:error=k.k.reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_native_diff_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; fixed historical native account diff only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
