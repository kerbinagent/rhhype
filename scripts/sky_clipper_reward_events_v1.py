"""Fixed-window auction reward event signatures; public reads, default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/sky_clipper_reward_events_v1.py'
TEST='tests/test_sky_clipper_reward_events_v1.py'
BASE='reports/sky-clipper-reward-events-v1/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/sky-clipper-reward-events-allocation-v1.json'
HELPER='scripts/uniswap_fee_release_history_v1.py'
HELPER_SHA='0e1437b87d2943347f6c611a5daa15e5ce562c81c7e6abdcdeb27453ddcd04b9'
PRIOR='reports/sky-clipper-keeper-v1/'
PRIOR_PLAN='38644dd52caff7613510c29ac0f9a443d58246fcf412d86339b9cf0502c349f7'
ANCHOR=26108863
WINDOW=4096
SLOTS=[('chain',4096),('events',16384),('recheck',24576)]
CAPS=dict(requests=3,body_bytes=49152,raw_bytes=49152,request_bytes=8192,
          projection_bytes=8192,request_seconds=20,work_seconds=105,wall_seconds=120,
          cpu_seconds=20,ram_bytes=536870912,max_events=8)
p=ROOT/HELPER
if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
with p.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
k=types.ModuleType('clipper_event_helpers');k.__file__=str(p)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
c,h,t,s,encode,decode,read,sha=k.c,k.h,k.t,k.s,k.encode,k.decode,k.read,k.sha
TOPICS={c.keccak_hex(name+'(uint256,uint256,uint256,uint256,address,address,uint256)'):name for name in ('Kick','Redo')}


class Refusal(k.Refusal):pass


def inputs():
    projection=read(ROOT/(PRIOR+'run-v1/projection.json'),4096);p=decode(projection)
    r=decode(read(ROOT/(PRIOR+'root-review.json'),2048))
    if (r.get('status')!='passed_scope_limited' or r.get('plan_sha256')!=PRIOR_PLAN
        or r.get('projection_sha256')!=sha(projection) or p.get('plan_sha256')!=PRIOR_PLAN
        or p.get('status')!='fixed_candidate_census_complete' or not p.get('count_and_header_rechecked')
        or not p.get('provider_returned_complete_list')):raise Refusal('prior_census_admission')
    raw=read(ROOT/(PRIOR+'run-v1/raw/02.body'),32768);v=decode(raw)
    meta=decode(read(ROOT/(PRIOR+'run-v1/raw/02.receipt.json'),2048))
    if (meta.get('http_status')!=200 or meta.get('error') is not None or meta.get('dispatch_attempted') is not True
        or meta.get('response_bytes')!=len(raw) or meta.get('response_sha256')!=sha(raw)
        or v.get('jsonrpc')!='2.0' or v.get('id')!=2 or 'error' in v):raise Refusal('retained_header_identity')
    header=v['result']
    if (c.header(header)!=p['block'] or p['block']['number']!=ANCHOR
        or s.o.context(header)!=p['context']):raise Refusal('retained_anchor_identity')
    return header


def events(value,header):
    if not isinstance(value,list):raise Refusal('event_list_unavailable')
    if len(value)>CAPS['max_events']:raise Refusal('complete_event_census_over_cap')
    rows=[];order=[];blocks={};transactions={}
    for log in value:
        ident=k.log_identity(log);b=ident['block_number'];txindex=ident['transaction_index'];index=ident['log_index']
        if not ANCHOR-WINDOW+1<=b<=ANCHOR:raise Refusal('event_window')
        if txindex>=100000 or index>=1000000:raise Refusal('event_index_domain')
        if b==ANCHOR and ident['block_hash']!=header['hash']:raise Refusal('anchor_event_hash')
        if b in blocks and blocks[b]!=ident['block_hash']:raise Refusal('conflicting_block_hash')
        blocks[b]=ident['block_hash'];txkey=(b,txindex)
        if txkey in transactions and transactions[txkey]!=ident['transaction_hash']:raise Refusal('conflicting_transaction_hash')
        transactions[txkey]=ident['transaction_hash'];order.append((b,txindex,index))
        topics=log.get('topics')
        if not isinstance(topics,list) or len(topics)!=4 or topics[0] not in TOPICS:raise Refusal('event_topic_shape')
        auction_id=int(h.hexdata(topics[1],32),16)
        if auction_id==0:raise Refusal('zero_auction_id')
        usr,kpr=c.address_word(topics[2]),c.address_word(topics[3])
        data=h.hexdata(log.get('data'),128)[2:];top,tab,lot,coin=[int(data[i:i+64],16) for i in range(0,256,64)]
        rows.append([b,ident['block_hash'],txindex,index,ident['transaction_hash'],ident['address'],
            TOPICS[topics[0]],str(auction_id),usr,kpr,str(top),str(tab),str(lot),str(coin)])
    log_order=[(b,index) for b,_,index in order]
    if order!=sorted(set(order)) or log_order!=sorted(set(log_order)):raise Refusal('event_order_or_duplicate')
    return rows


def collect(rpc,header):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    query=dict(fromBlock=hex(ANCHOR-WINDOW+1),toBlock=hex(ANCHOR),topics=[list(TOPICS)])
    rows=events(rpc('events','eth_getLogs',[query]),header)
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[hex(ANCHOR),False]),header)
    return dict(schema='sky-clipper-reward-events-projection-v1',status='fixed_signature_census_complete',
        anchor=c.header(header),window_blocks=WINDOW,query=query,event_count=len(rows),
        columns=['block_number','block_hash','transaction_index','log_index','transaction_hash','emitter',
                 'kind','auction_id','vault','keeper','top_ray','tab_rad','lot_wad','claimed_incentive_rad'],
        events=rows,kind_counts={kind:sum(r[6]==kind for r in rows) for kind in TOPICS.values()},
        positive_claimed_incentive_events=sum(int(r[-1])>0 for r in rows),
        provider_returned_complete_signature_list=True,sky_emitter_identity_proved=False,
        actual_reward_credit_observed=False,external_dai_observed=False,cash_closed=False,economics=False,repeatable_profit=False,
        scope='All emitters with these two event signatures in one fixed window; ABI matches and claimed incentive words are not Sky attribution, credited assets or cash.')


def required_paths():
    return [SOURCE,TEST,DESIGN,NOTES,ALLOCATION,HELPER,PRIOR+'run-v1/projection.json',PRIOR+'root-review.json',
        PRIOR+'run-v1/raw/02.body',PRIOR+'run-v1/raw/02.receipt.json',PRIOR+'source-notes.json']


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('anchor_number')!=ANCHOR
        or p.get('window_blocks')!=WINDOW or p.get('topics')!=TOPICS
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>20480:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=20480,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=8192,raw=49152)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=94208:raise Refusal('funding')
    if p.get('anchor_hash')!=inputs()['hash']:raise Refusal('anchor')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,header):
    r=t.Reader(path,SLOTS,CAPS,c);p=collect(r.rpc,header);r.finish();return p,r.body_bytes,r.raw_bytes


def run(digest):
    started=time.monotonic();capture=None;status='unavailable';error=None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest);header=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,k.reason);p=collect(capture.rpc,header)
                check,body,raw=replay(out/'raw',header)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_signature_census_complete'
        except BaseException as exc:error=k.reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_signature_census_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],event_count=v['event_count'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; fixed auction event signatures only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
