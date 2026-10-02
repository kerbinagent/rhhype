"""Fixed-state regulator slots and recent maintenance-event census; default dry."""
import argparse
from pathlib import Path
import resource
import sys
import time
import types
import hashlib

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/curve_pegkeeper_census_v1.py'
TEST='tests/test_curve_pegkeeper_census_v1.py'
BASE='reports/curve-pegkeeper-census-v1/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/curve-pegkeeper-census-allocation-v1.json'
HELPER='scripts/curve_pegkeeper_reward_v1.py'
HELPER_SHA='9b30fe287e02270fd7f02932f563dffed7edf40b0de1175ff586fbee269b44f3'
INPUT='reports/curve-pegkeeper-reward-v1/run-v1/projection.json'
INPUT_SHA='3bef5cc9f0ad799f8572995a9a7a548f41f34fd8a98f71f5af35d75d44548b26'
ANCHOR=26107811
WINDOW=7200
SLOTS=[('chain',4096),('anchor',32768)]+[('registry_'+str(i),4096) for i in range(8)]+[
    ('stablecoin',4096),('paused',4096),('lower',32768),('events',65536),
    ('lower_recheck',32768),('anchor_recheck',32768)]
CAPS=dict(requests=16,body_bytes=196608,raw_bytes=262144,request_bytes=8192,projection_bytes=16384,
          request_seconds=20,work_seconds=165,wall_seconds=180,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=3000000,max_events=128)


class Refusal(Exception):pass


def read(path,cap):
    if path.is_symlink() or not path.is_file():raise Refusal('nonregular_file')
    with path.open('rb') as f:raw=f.read(cap+1)
    if len(raw)>cap:raise Refusal('file_cap')
    return raw


def sha(raw):return hashlib.sha256(raw).hexdigest()


raw=read(ROOT/HELPER,32768)
if sha(raw)!=HELPER_SHA:raise Refusal('immutable_helper')
k=types.ModuleType('keeper_census_helpers');k.__file__=str(ROOT/HELPER)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
c,h,t,encode,decode=k.c,k.h,k.t,k.encode,k.decode
TOPICS={c.keccak_hex(name+'(uint256)'):name for name in ('Provide','Withdraw')}


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else k.reason(exc)


def inputs():
    raw=read(ROOT/INPUT,16384)
    if sha(raw)!=INPUT_SHA:raise Refusal('original_projection_changed')
    return decode(raw)


def registry_result(value):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error_not_proven_absence',code=value['rpc_unavailable'])
    try:
        data=h.hexdata(value,128)[2:]
        words=['0x'+data[i:i+64] for i in range(0,256,64)]
        keeper,pool=k.address(words[0]),k.address(words[1])
        flags=[int(w,16) for w in words[2:]]
        if any(x not in (0,1) for x in flags):raise Refusal('boolean_width')
    except (Refusal,k.Refusal,k.s.Refusal,c.Refusal,h.Refusal,TypeError,ValueError):
        return dict(available=False,reason='null_or_noncanonical_registry_tuple')
    return dict(available=True,keeper=keeper,pool=pool,is_inverse=bool(flags[0]),include_index=bool(flags[1]))


def parse_events(value,addresses,low,high):
    if not isinstance(value,list) or len(value)>CAPS['max_events']:raise Refusal('event_list_cap')
    result=[];last=(-1,-1,-1);tx_ids={};positions={};blocks={}
    for row in value:
        if not isinstance(row,dict) or row.get('removed') is not False:raise Refusal('removed_event')
        address=h.hexdata(row.get('address'),20)
        topics=row.get('topics')
        if address not in addresses or not isinstance(topics,list) or len(topics)!=1:raise Refusal('event_identity')
        topic=h.hexdata(topics[0],32)
        if topic not in TOPICS:raise Refusal('event_topic')
        n,txi,logi=(h.quantity(row.get(key)) for key in ('blockNumber','transactionIndex','logIndex'))
        block_hash=h.hexdata(row.get('blockHash'),32);tx_hash=h.hexdata(row.get('transactionHash'),32)
        order=(n,txi,logi)
        if not low<=n<=high or order<=last:raise Refusal('event_range_or_order')
        if n==last[0] and logi<=last[2]:raise Refusal('block_log_order')
        if n in blocks and blocks[n]!=block_hash:raise Refusal('block_hash_conflict')
        if (n,txi) in positions and positions[n,txi]!=tx_hash:raise Refusal('transaction_position_conflict')
        if tx_hash in tx_ids and tx_ids[tx_hash]!=(n,txi,block_hash):raise Refusal('transaction_identity_conflict')
        blocks[n]=block_hash;positions[n,txi]=tx_hash
        tx_ids[tx_hash]=(n,txi,block_hash);last=order
        result.append(dict(keeper=address,kind=TOPICS[topic],amount_raw=k.s.uint_word(row.get('data')),
            block_number=n,block_hash=block_hash,transaction_index=txi,log_index=logi,transaction_hash=tx_hash))
    return result


def collect(rpc,setup):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('wrong_chain')
    anchor=rpc('anchor','eth_getBlockByNumber',[hex(ANCHOR),False])
    if c.header(anchor)!=setup['block'] or k.s.o.context(anchor)!=setup['context']:raise Refusal('anchor_changed')
    selector=dict(blockHash=setup['block']['hash'],requireCanonical=True)
    def call(name,signature,suffix=''):
        args={'from':k.DIAGNOSTIC,'to':k.REGULATOR,'input':k.s.selector(signature)+suffix,
              'value':'0x0','gasPrice':'0x0','gas':hex(300000)}
        return rpc(name,'eth_call',[args,selector],allow_unavailable=True)
    slots=[dict(index=i,**registry_result(call('registry_'+str(i),'peg_keepers(uint256)',format(i,'064x')))) for i in range(8)]
    stablecoin=k.result(call('stablecoin','stablecoin()'),'pegged')
    paused=k.result(call('paused','is_killed()'),'paused')
    if paused['available'] and int(paused['value'])>3:paused=dict(available=False,reason='enum_out_of_documented_range')
    registered=[x['keeper'] for x in slots if x['available']]
    addresses=sorted(set(registered+[address for _,address in k.KEEPERS]))
    low=ANCHOR-WINDOW+1
    lower=rpc('lower','eth_getBlockByNumber',[hex(low),False])
    if c.header(lower)['number']!=low or h.quantity(lower['timestamp'])>setup['block']['timestamp']:raise Refusal('lower_header')
    logs=rpc('events','eth_getLogs',[dict(fromBlock=hex(low),toBlock=hex(ANCHOR),address=addresses,topics=[list(TOPICS)])])
    events=parse_events(logs,addresses,low,ANCHOR)
    boundary_hashes={low:c.header(lower)['hash'],ANCHOR:setup['block']['hash']}
    if any(e['block_number'] in boundary_hashes and e['block_hash']!=boundary_hashes[e['block_number']] for e in events):
        raise Refusal('boundary_event_hash')
    selected=[];seen=set()
    for event in events:
        if event['transaction_hash'] not in seen and len(selected)<3:
            selected.append(event);seen.add(event['transaction_hash'])
    counts={address:{name:sum(e['keeper']==address and e['kind']==name for e in events) for name in TOPICS.values()} for address in addresses}
    k.s.o.same_header(rpc('lower_recheck','eth_getBlockByNumber',[hex(low),False]),lower)
    k.s.o.same_header(rpc('anchor_recheck','eth_getBlockByNumber',[hex(ANCHOR),False]),anchor)
    return dict(schema='curve-pegkeeper-census-projection-v1',status='fixed_census_complete',anchor=c.header(anchor),lower=c.header(lower),
        window_blocks=WINDOW,elapsed_block_timestamp_seconds=setup['block']['timestamp']-h.quantity(lower['timestamp']),
        registry_slots=slots,available_registry_slots=len(registered),registry_addresses_unique=len(set(registered))==len(registered),
        stablecoin=stablecoin,documented_stablecoin_match=(stablecoin['value']==k.CRVUSD if stablecoin['available'] else None),
        paused=paused,query_addresses=addresses,query_topics=TOPICS,event_count=len(events),event_counts_by_keeper=counts,
        distinct_transaction_count=len({e['transaction_hash'] for e in events}),selected_first_three_transactions=selected,
        parsed_event_projection_sha256=sha(encode(events)),registry_source_max_len=8,active_universe_proved=False,
        unavailable_registry_slot_is_not_absence_proof=True,provider_log_completeness_assumed=True,
        interior_event_headers_verified=False,historical_pool_identity_proved=False,maintenance_amount_is_caller_reward=False,
        reward_transfers_verified=False,cash_conversion_verified=False,gas_costs_collected=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,16384)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,HELPER,INPUT}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
        or p.get('anchor')!=ANCHOR or p.get('window_blocks')!=WINDOW or p.get('topics')!=TOPICS):raise Refusal('frozen_scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],65536)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN))+len(raw)>65536:raise Refusal('source_package_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,setup):
    reader=t.Reader(path,SLOTS,CAPS,c);projection=collect(reader.rpc,setup);reader.finish()
    return projection,reader.body_bytes,reader.raw_bytes


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
                projection=collect(capture.rpc,setup);check,body,raw=replay(out/'raw',setup)
                if projection!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('exact_replay')
                verify(digest);projection['plan_sha256']=digest
                k.s.o.publish(out,'projection.json',projection,CAPS['projection_bytes']);status='fixed_census_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            k.s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_census_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    args=p.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw',inputs())
        print(encode(dict(status=result['status'],events=result['event_count'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run:print('dry: zero requests;zero outputs;fixed regulator and event census');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
