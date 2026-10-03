"""One larger receipt for an already selected fee release; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/uniswap_fee_release_receipt_v2.py'
TEST='tests/test_uniswap_fee_release_receipt_v2.py'
BASE='reports/uniswap-fee-release-receipt-v2/'
PLAN,DESIGN,NOTES,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','run-v1'))
ALLOCATION='reports/experiment-storage/uniswap-fee-release-receipt-v2-allocation.json'
PREP='reports/experiment-storage/uniswap-fee-release-receipt-v2-preparation.json'
OLD='reports/uniswap-fee-release-history-v1/'
OLD_PLAN_SHA='52f71abaaa8b47a6a2bb47cdfb8d0ba1171cd7056d2f35d44fe17d0f3cfa248c'
HELPER='scripts/uniswap_fee_release_history_v1.py'
HELPER_SHA='0e1437b87d2943347f6c611a5daa15e5ce562c81c7e6abdcdeb27453ddcd04b9'
SLOTS=[('chain',4096),('receipt',196608),('recheck',32768)]
CAPS=dict(requests=3,body_bytes=245760,raw_bytes=237568,request_bytes=8192,
          projection_bytes=16384,request_seconds=20,work_seconds=105,wall_seconds=120,
          cpu_seconds=20,ram_bytes=536870912,max_receipt_logs=512)
p=ROOT/HELPER
if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
with p.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise RuntimeError('helper_pin')
k=types.ModuleType('receipt_history_helpers');k.__file__=str(p)
exec(compile(raw,k.__file__,'exec'),k.__dict__)
m,c,h,t,s,encode,decode,read,sha=k.m,k.c,k.h,k.t,k.s,k.encode,k.decode,k.read,k.sha


class Refusal(k.Refusal):pass


def old_result(slot,cap):
    pre=OLD+'run-v1/raw/'+format(slot,'02d')
    raw=read(ROOT/(pre+'.body'),cap);r=decode(read(ROOT/(pre+'.receipt.json'),2048));v=decode(raw)
    if (r.get('http_status')!=200 or r.get('error') is not None or r.get('response_bytes')!=len(raw)
        or r.get('response_sha256')!=sha(raw) or v.get('id')!=slot or v.get('jsonrpc')!='2.0'
        or 'error' in v or 'result' not in v):raise Refusal('retained_response_identity')
    return v['result']


def inputs():
    review=decode(read(ROOT/(OLD+'root-review.json'),2048))
    terminal=decode(read(ROOT/(OLD+'run-v1/terminal.json'),2048))
    if (review.get('status')!='passed_unavailable' or review.get('plan_sha256')!=OLD_PLAN_SHA
        or terminal.get('plan_sha256')!=OLD_PLAN_SHA or terminal.get('requests_attempted')!=5
        or terminal.get('status')!='unavailable' or terminal.get('error')!='response_cap_sentinel_retained'):
        raise Refusal('prior_failure_admission')
    e=k.select_event(old_result(2,8192));header=old_result(3,32768);b=c.header(header)
    if b['hash']!=e['block_hash'] or b['number']!=e['block_number']:raise Refusal('retained_header_identity')
    tx=k.transaction(old_result(4,65536),e)
    return dict(event=e,header=header,transaction=tx,original=k.inputs())


def collect(rpc,old):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    e,tx=old['event'],old['transaction']
    r=k.receipt(rpc('receipt','eth_getTransactionReceipt',[e['transaction_hash']],allow_unavailable=True),e,tx,old['original'])
    check=rpc('recheck','eth_getBlockByNumber',[hex(e['block_number']),False]);s.o.same_header(check,old['header'])
    return dict(schema='uniswap-fee-release-receipt-projection-v2',status='fixed_release_receipt_complete',
        selected_event=e,event_block=c.header(old['header']),event_context=s.o.context(old['header']),
        transaction=tx,receipt=r,prior_receipt_remains_capped=True,exploratory_latest_nonce_selection=True,
        reused_future_unit_metadata_is_annotation_only=True,internal_native_flows_observed=False,
        related_owner_grouping_proved=False,cash_closed=False,economics=False,repeatable_profit=False)


def required_paths():
    return [SOURCE,TEST,DESIGN,NOTES,ALLOCATION,PREP,HELPER,k.HELPER,k.INPUT,k.REVIEW,
        OLD+'root-review.json',OLD+'run-v1/terminal.json',OLD+'source-notes.json',OLD+'source-scope-amendment.json']+[
        OLD+'run-v1/raw/'+format(i,'02d')+ext for i in (2,3,4) for ext in ('.body','.receipt.json')]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
        or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>16384:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=16384,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=16384,raw=237568)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=286720:raise Refusal('funding')
    old=inputs()
    if p.get('selected_event')!=old['event']:raise Refusal('selection_identity')
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
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,k.reason);p=collect(capture.rpc,old)
                check,body,raw=replay(out/'raw',old)
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_release_receipt_complete'
        except BaseException as exc:error=k.reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_release_receipt_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw',inputs());print(encode(dict(status=v['status'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; prior selected release receipt only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
