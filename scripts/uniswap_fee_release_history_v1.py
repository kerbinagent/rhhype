"""Bounded last-nonce release event and receipt probe; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/uniswap_fee_release_history_v1.py'
TEST='tests/test_uniswap_fee_release_history_v1.py'
BASE='reports/uniswap-fee-release-history-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment.json','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-fee-release-history-allocation-v1.json'
PREP='reports/experiment-storage/uniswap-fee-release-history-preparation-v1.json'
INPUT='reports/uniswap-fee-auction-inventory-v2/run-v1/projection.json'
REVIEW='reports/uniswap-fee-auction-inventory-v2/root-review.json'
INPUT_PLAN='3bd7fbd2edca1cb6ed63ceacfb331ca41e48855ae46a58e91a0ca7f7f78ed320'
HELPER='scripts/sky_psm_discovery_v1.py'
HELPER_SHA='c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
FIREPIT='0x0d5cd355e2abeb8fb1552f56c965b867346d6721'
JAR='0xf38521f130fccf29db1961597bc5d2b60f995f85'
ANCHOR=26108195
NONCE=1387
WINDOW=4096
SLOTS=[('chain',4096),('events',8192),('event_header',32768),('transaction',65536),
       ('receipt',131072),('recheck',24576)]
CAPS=dict(requests=6,body_bytes=245760,raw_bytes=262144,request_bytes=8192,
          projection_bytes=16384,request_seconds=20,work_seconds=165,wall_seconds=180,
          cpu_seconds=20,ram_bytes=536870912,max_receipt_logs=512)
path=ROOT/HELPER
if path.is_symlink() or not path.is_file():raise RuntimeError('helper_path')
with path.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
m=types.ModuleType('release_history_helpers');m.__file__=str(path)
exec(compile(raw,m.__file__,'exec'),m.__dict__)
c,h,t,s,encode,decode,read,sha=m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha
RELEASED=c.keccak_hex('Released(uint256,address,address[])')
TRANSFER=c.keccak_hex('Transfer(address,address,uint256)')


class Refusal(Exception):pass


def addr(value):return h.hexdata(value,20).lower()


def word_address(value):return c.address_word(value)


def inputs():
    p=decode(read(ROOT/INPUT,8192));r=decode(read(ROOT/REVIEW,1536))
    if (p['plan_sha256']!=INPUT_PLAN or r.get('plan_sha256')!=INPUT_PLAN or r.get('status')!='passed'
        or r.get('projection_sha256')!=sha(read(ROOT/INPUT,8192))
        or p['block']['number']!=ANCHOR or p['firepit']!=FIREPIT or p['token_jar']!=JAR
        or not p['documented_configuration_matches'] or not p['expected_units_match']
        or p['configuration']['nonce']['value']!=str(NONCE+1)):
        raise Refusal('inventory_admission')
    return p


def log_identity(log):
    if not isinstance(log,dict) or log.get('removed') is not False:raise Refusal('removed_or_malformed_log')
    return dict(address=addr(log['address']),block_number=h.quantity(log['blockNumber']),
        block_hash=h.hexdata(log['blockHash'],32),transaction_hash=h.hexdata(log['transactionHash'],32),
        transaction_index=h.quantity(log['transactionIndex']),log_index=h.quantity(log['logIndex']))


def event(log):
    ident=log_identity(log);topics=log.get('topics')
    if (ident['address']!=FIREPIT or not isinstance(topics,list) or len(topics)!=3
        or topics[0]!=RELEASED or h.hexdata(topics[1],32)!='0x'+format(NONCE,'064x')
        or not ANCHOR-WINDOW+1<=ident['block_number']<=ANCHOR):raise Refusal('event_filter_mismatch')
    recipient=word_address(topics[2]);data=h.hexdata(log.get('data'))[2:]
    if len(data)<128 or len(data)%64:raise Refusal('event_array_abi')
    words=[data[i:i+64] for i in range(0,len(data),64)]
    offset,count=int(words[0],16),int(words[1],16)
    if offset!=32 or not 0<=count<=20 or len(words)!=2+count:raise Refusal('event_array_abi')
    assets=[word_address('0x'+x) for x in words[2:]]
    return dict(ident,nonce=NONCE,recipient=recipient,assets=assets)


def select_event(value):
    if isinstance(value,dict) and 'rpc_unavailable' in value:raise Refusal('event_query_unavailable')
    if not isinstance(value,list):raise Refusal('event_list')
    if len(value)==0:raise Refusal('no_matching_last_nonce_event')
    if len(value)!=1:raise Refusal('ambiguous_last_nonce_events')
    return event(value[0])


def transaction(value,e):
    if not isinstance(value,dict):raise Refusal('transaction_unavailable')
    if (h.hexdata(value.get('hash'),32)!=e['transaction_hash']
        or h.hexdata(value.get('blockHash'),32)!=e['block_hash']
        or h.quantity(value.get('blockNumber'))!=e['block_number']
        or h.quantity(value.get('transactionIndex'))!=e['transaction_index']):raise Refusal('transaction_identity')
    data=h.hexdata(value.get('input'))
    return dict(sender=addr(value['from']),target=None if value.get('to') is None else addr(value['to']),
        value_wei=str(h.quantity(value['value'])),gas_limit=h.quantity(value['gas']),
        transaction_type=h.quantity(value['type']),input_bytes=(len(data)-2)//2,input_sha256=sha(bytes.fromhex(data[2:])))


def receipt(value,e,tx,original):
    if not isinstance(value,dict):raise Refusal('receipt_unavailable')
    if (h.hexdata(value.get('transactionHash'),32)!=e['transaction_hash']
        or h.hexdata(value.get('blockHash'),32)!=e['block_hash']
        or h.quantity(value.get('blockNumber'))!=e['block_number']
        or h.quantity(value.get('transactionIndex'))!=e['transaction_index']
        or addr(value['from'])!=tx['sender']
        or (None if value.get('to') is None else addr(value['to']))!=tx['target']
        or h.quantity(value.get('status'))!=1):raise Refusal('receipt_identity_or_status')
    gas=h.quantity(value['gasUsed']);price=h.quantity(value['effectiveGasPrice'])
    if not 0<gas<=tx['gas_limit']:raise Refusal('gas_domain')
    logs=value.get('logs')
    if not isinstance(logs,list) or len(logs)>CAPS['max_receipt_logs']:raise Refusal('receipt_log_cap')
    roles={'sender':tx['sender'],'recipient':e['recipient'],'target':tx['target']}
    owners={x for x in roles.values() if x is not None};totals={};jar_payouts=[]
    matched=[];indices=[];transfer_count=0;other_count=0
    for log in logs:
        ident=log_identity(log);indices.append(ident['log_index'])
        if any(ident[k]!=e[k] for k in ('block_number','block_hash','transaction_hash','transaction_index')):
            raise Refusal('receipt_log_identity')
        if ident['log_index']==e['log_index']:matched.append(event(log))
        topics=log.get('topics')
        if isinstance(topics,list) and len(topics)==3 and topics[0]==TRANSFER:
            sender,target=word_address(topics[1]),word_address(topics[2]);amount=int(h.hexdata(log.get('data'),32),16)
            transfer_count+=1;token=ident['address']
            for owner in owners:
                if owner in (sender,target):
                    row=totals.setdefault((owner,token),[0,0])
                    if owner==target:row[0]+=amount
                    if owner==sender:row[1]+=amount
            if sender==JAR:jar_payouts.append([ident['log_index'],token,target,str(amount)])
        else:other_count+=1
    if matched!=[e] or indices!=sorted(set(indices)):raise Refusal('receipt_event_or_log_order')
    known={x['address']:{'label':x['label'],'decimals':x['expected_decimals']} for x in original['inventory'][:6]}
    ledger=[[owner,token,str(v[0]),str(v[1]),str(v[0]-v[1])] for (owner,token),v in sorted(totals.items())]
    return dict(roles=roles,logs=len(logs),erc20_shaped_transfer_logs=transfer_count,other_logs=other_count,
        ledger_columns=['address','token','in_native','out_native','net_native'],transfer_ledger=ledger,
        jar_transfer_columns=['log_index','token','recipient','amount_native'],jar_transfers=jar_payouts,
        known_units=known,gas_used=gas,effective_gas_price_wei=str(price),gas_fee_wei=str(gas*price),
        ledger_covers_balance_changes=False,internal_native_transfers_observed=False,
        deposit_withdrawal_rebase_tax_effects_included=False,related_addresses_share_ownership_proved=False)


def collect(rpc,original):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    params=dict(address=FIREPIT,fromBlock=hex(ANCHOR-WINDOW+1),toBlock=hex(ANCHOR),
                topics=[RELEASED,'0x'+format(NONCE,'064x')])
    e=select_event(rpc('events','eth_getLogs',[params],allow_unavailable=True))
    header=rpc('event_header','eth_getBlockByNumber',[hex(e['block_number']),False])
    b=c.header(header)
    if b['hash']!=e['block_hash'] or b['number']!=e['block_number']:raise Refusal('event_header_identity')
    tx=transaction(rpc('transaction','eth_getTransactionByHash',[e['transaction_hash']],allow_unavailable=True),e)
    r=receipt(rpc('receipt','eth_getTransactionReceipt',[e['transaction_hash']],allow_unavailable=True),e,tx,original)
    check=rpc('recheck','eth_getBlockByNumber',[hex(ANCHOR),False])
    if c.header(check)!=original['block'] or s.o.context(check)!=original['context']:raise Refusal('anchor_changed')
    return dict(schema='uniswap-fee-release-history-projection-v1',status='fixed_release_history_complete',
        anchor=original['block'],window_blocks=WINDOW,selected_event=e,event_block=b,event_context=s.o.context(header),
        transaction=tx,receipt=r,exploratory_latest_nonce_selection=True,event_is_not_profit=True,
        modeled_release_not_executed=True,cash_closed=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,HELPER,INPUT,REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('anchor_number')!=ANCHOR
        or p.get('nonce')!=NONCE or p.get('window_blocks')!=WINDOW
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
    if p.get('anchor_hash')!=original['block']['hash'] or p.get('event_topic')!=RELEASED:raise Refusal('anchor_topic')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


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
                status='fixed_release_history_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_release_history_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; last nonce event and receipt only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
