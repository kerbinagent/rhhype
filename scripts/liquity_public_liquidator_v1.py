"""Fixed recent Liquity liquidation event and receipt attribution; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/liquity_public_liquidator_v1.py'
TEST='tests/test_liquity_public_liquidator_v1.py'
BASE='reports/liquity-public-liquidator-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment.json','run-v1'))
ALLOCATION='reports/experiment-storage/liquity-public-liquidator-allocation-v1.json'
PREP='reports/experiment-storage/liquity-public-liquidator-source-preparation-v1.json'
HELPER='scripts/uniswap_fee_release_history_v1.py'
HELPER_SHA='0e1437b87d2943347f6c611a5daa15e5ce562c81c7e6abdcdeb27453ddcd04b9'
ANCHOR=26108195
WINDOW=16384
BRANCHES=[
    ('WETH','0x7bcb64b2c9206a5b699ed43363f6f98d4776cf5a','0x7b9ab3de4036cae51f1fa4ec0a2c2fd606bcf921','0xeb5a8c825582965f1d84606e078620a84ab16afe','0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'),
    ('wstETH','0xa2895d6a3bf110561dfe4b71ca539d84e1928b22','0x8c44fba379d8a8608c0e29b2729deb75a981db1f','0x531a8f99c70d6a56a7cee02d6b4281650d7919a0','0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0'),
    ('rETH','0xb2b2abeb5c357a234363ff5d180912d319e3e19e','0x45c81dce308389e1bee63ae30a04fb1e148dad41','0x9074d72cc82dad1e13e454755aa8f144c479532f','0xae78736cd615f374d3085123a210448e74fc6393'),
]
WETH=BRANCHES[0][4]
EVENT_FIELDS=['debt_offset','debt_redistributed','weth_reserve','collateral_reward','collateral_to_sp',
              'collateral_redistributed','collateral_surplus','L_collateral','L_debt','price']
SLOTS=[('chain',4096),('events',65536),('event_header',32768),('transaction',16384),
       ('receipt',98304),('recheck',24576)]
CAPS=dict(requests=6,body_bytes=245760,raw_bytes=262144,request_bytes=8192,
          projection_bytes=16384,request_seconds=20,work_seconds=165,wall_seconds=180,
          cpu_seconds=20,ram_bytes=536870912,max_receipt_logs=512,max_events=64)
path=ROOT/HELPER
if path.is_symlink() or not path.is_file():raise RuntimeError('helper_path')
with path.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
k=types.ModuleType('liquidator_history_helpers');k.__file__=str(path)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
m,c,h,t,s,encode,decode,read,sha=k.m,k.c,k.h,k.t,k.s,k.encode,k.decode,k.read,k.sha
LIQUIDATION=c.keccak_hex('Liquidation('+','.join(['uint256']*10)+')')
TRANSFER=k.TRANSFER
BATCH_SELECTOR=c.keccak_hex('batchLiquidateTroves(uint256[])')[:10]


class Refusal(Exception):pass


def inputs():
    original=k.inputs()
    if original['block']['number']!=ANCHOR:raise Refusal('anchor')
    return original


def event(log):
    ident=k.log_identity(log);topics=log.get('topics')
    if (ident['address'] not in [x[1] for x in BRANCHES] or topics!=[LIQUIDATION]
        or not ANCHOR-WINDOW+1<=ident['block_number']<=ANCHOR):raise Refusal('event_filter')
    data=h.hexdata(log.get('data'),320)[2:]
    values=[str(int(data[i:i+64],16)) for i in range(0,640,64)]
    return dict(ident,values=dict(zip(EVENT_FIELDS,values)))


def select_events(value):
    if not isinstance(value,list) or len(value)>CAPS['max_events']:raise Refusal('events_unavailable_or_cap')
    if not value:raise Refusal('no_liquidation_events_returned')
    events=[event(x) for x in value]
    keys=[(x['block_number'],x['transaction_index'],x['log_index']) for x in events]
    if keys!=sorted(set(keys)):raise Refusal('event_order_or_duplicate')
    blocks={}
    for x in events:
        if blocks.setdefault(x['block_number'],x['block_hash'])!=x['block_hash']:raise Refusal('event_block_conflict')
    return events,events[-1]


def transaction(value,e):
    tx=k.transaction(value,e)
    data=h.hexdata(value['input']);direct=tx['target']==e['address'] and data[:10]==BATCH_SELECTOR
    ids=None
    if direct:
        words=data[10:]
        if len(words)>=128 and len(words)%64==0:
            count=int(words[64:128],16)
            if int(words[:64],16)==32 and 0<count<=128 and len(words)==128+64*count:
                ids=[str(int(words[i:i+64],16)) for i in range(128,len(words),64)]
    return dict(tx,direct_batch_selector_matches=direct,canonical_trove_ids=ids)


def receipt(value,e,tx):
    if not isinstance(value,dict):raise Refusal('receipt_unavailable')
    if (h.hexdata(value.get('transactionHash'),32)!=e['transaction_hash']
        or h.hexdata(value.get('blockHash'),32)!=e['block_hash']
        or h.quantity(value.get('blockNumber'))!=e['block_number']
        or h.quantity(value.get('transactionIndex'))!=e['transaction_index']
        or k.addr(value['from'])!=tx['sender']
        or (None if value.get('to') is None else k.addr(value['to']))!=tx['target']
        or h.quantity(value.get('status'))!=1):raise Refusal('receipt_identity_or_status')
    gas=h.quantity(value['gasUsed']);price=h.quantity(value['effectiveGasPrice'])
    if not 0<gas<=tx['gas_limit']:raise Refusal('gas_domain')
    logs=value.get('logs')
    if not isinstance(logs,list) or len(logs)>CAPS['max_receipt_logs']:raise Refusal('receipt_log_cap')
    indices=[];matched=[];transfers=[];gas_transfers=[];other=0;events=[]
    for log in logs:
        ident=k.log_identity(log);indices.append(ident['log_index'])
        if any(ident[z]!=e[z] for z in ('block_number','block_hash','transaction_hash','transaction_index')):
            raise Refusal('receipt_log_identity')
        if ident['log_index']==e['log_index']:matched.append(event(log))
        topics=log.get('topics')
        if topics==[LIQUIDATION] and ident['address'] in [x[1] for x in BRANCHES]:events.append(event(log))
        if isinstance(topics,list) and len(topics)==3 and topics[0]==TRANSFER:
            sender,target=k.word_address(topics[1]),k.word_address(topics[2]);amount=int(h.hexdata(log.get('data'),32),16)
            row=[ident['log_index'],ident['address'],sender,target,str(amount)];transfers.append(row)
            if ident['address']==WETH and sender in [x[2] for x in BRANCHES]:gas_transfers.append(row)
        else:other+=1
    if matched!=[e] or indices!=sorted(set(indices)):raise Refusal('receipt_event_or_log_order')
    branch=next(x for x in BRANCHES if x[1]==e['address'])
    candidates=[x for x in gas_transfers if x[2]==branch[2] and x[4]==e['values']['weth_reserve']
                and int(x[4])>0 and x[0]>e['log_index']]
    recipient=candidates[0][3] if len(candidates)==1 else None
    collateral=[x for x in transfers if x[1]==branch[4] and x[2]==branch[3] and x[3]==recipient
                and x[4]==e['values']['collateral_reward'] and int(x[4])>0 and x[0]>e['log_index']]
    roles={'sender':tx['sender'],'target':tx['target'],'candidate_reward_recipient':recipient}
    owners={x for x in roles.values() if x is not None};totals={}
    for _,token,sender,target,amount in transfers:
        amount=int(amount)
        for owner in owners:
            if owner in (sender,target):
                row=totals.setdefault((owner,token),[0,0])
                if owner==target:row[0]+=amount
                if owner==sender:row[1]+=amount
    ledger=[[a,token,str(v[0]),str(v[1]),str(v[0]-v[1])] for (a,token),v in sorted(totals.items())]
    return dict(roles=roles,logs=len(logs),erc20_shaped_transfer_logs=len(transfers),other_logs=other,
        liquidation_events=events,matched_reserve_transfer=candidates[0] if len(candidates)==1 else None,
        reserve_matching_transfers=len(candidates),collateral_matching_transfers=collateral,
        gas_pool_weth_transfers=gas_transfers,transfer_columns=['log_index','token','from','to','amount_native'],
        transfer_ledger=ledger,ledger_columns=['address','token','in_native','out_native','net_native'],
        gas_used=gas,effective_gas_price_wei=str(price),gas_fee_wei=str(gas*price),
        ledger_covers_balance_changes=False,internal_native_transfers_observed=False,
        deposit_withdrawal_rebase_tax_effects_included=False,related_addresses_share_ownership_proved=False)


def collect(rpc,original):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    params=dict(address=[x[1] for x in BRANCHES],fromBlock=hex(ANCHOR-WINDOW+1),toBlock=hex(ANCHOR),topics=[LIQUIDATION])
    events,e=select_events(rpc('events','eth_getLogs',[params],allow_unavailable=True))
    header=rpc('event_header','eth_getBlockByNumber',[hex(e['block_number']),False]);b=c.header(header)
    if b['hash']!=e['block_hash'] or b['number']!=e['block_number']:raise Refusal('event_header_identity')
    tx=transaction(rpc('transaction','eth_getTransactionByHash',[e['transaction_hash']],allow_unavailable=True),e)
    r=receipt(rpc('receipt','eth_getTransactionReceipt',[e['transaction_hash']],allow_unavailable=True),e,tx)
    check=rpc('recheck','eth_getBlockByNumber',[hex(ANCHOR),False])
    if c.header(check)!=original['block'] or s.o.context(check)!=original['context']:raise Refusal('anchor_changed')
    counts={x[0]:sum(e['address']==x[1] for e in events) for x in BRANCHES}
    return dict(schema='liquity-public-liquidator-projection-v1',status='fixed_liquidation_history_complete',
        anchor=original['block'],window_blocks=WINDOW,events_returned=len(events),branch_event_counts=counts,
        selected_event=e,event_block=b,event_context=s.o.context(header),transaction=tx,receipt=r,
        exploratory_latest_event_selection=True,all_census_events_independently_verified=False,
        runtime_equivalence_verified=False,token_inventory_is_not_cash=True,cash_closed=False,
        economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,HELPER,k.HELPER,k.INPUT,k.REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('anchor_number')!=ANCHOR
        or p.get('window_blocks')!=WINDOW or p.get('branches')!=[list(x) for x in BRANCHES]
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x['path'] for x in pins}!=required:raise Refusal('pins')
    for x in pins:
        data=read(ROOT/x['path'],65536)
        if len(data)!=x['bytes'] or sha(data)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>32768:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096))
    if a['total_experiment_reservation_bytes']!=327680 or a['categories_bytes']['raw']!=CAPS['raw_bytes']:raise Refusal('funding')
    original=inputs()
    if p.get('anchor_hash')!=original['block']['hash'] or p.get('event_topic')!=LIQUIDATION:raise Refusal('anchor_topic')
    if decode(read(ROOT/NOTES,8192))['branches']!=[list(x) for x in BRANCHES]:raise Refusal('documented_branches')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):return str(exc)[:160] if isinstance(exc,(Refusal,k.Refusal)) else m.reason(exc)


def replay(path,original):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc,original);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);original=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);p=collect(capture.rpc,original)
                check,body,raw=replay(out/'raw',original)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_liquidation_history_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_liquidation_history_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; recent liquidation event and receipt only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
