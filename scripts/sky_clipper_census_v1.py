"""One fixed ETH-A Clipper census; anonymous views, default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/sky_clipper_census_v1.py'
TEST='tests/test_sky_clipper_census_v1.py'
BASE='reports/sky-clipper-keeper-v1/'
PLAN,DESIGN,NOTES,AMEND,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-scope-amendment-v1.json','run-v1'))
ALLOCATION='reports/experiment-storage/sky-clipper-census-allocation-v1.json'
PREP='reports/experiment-storage/sky-clipper-keeper-preparation-v1.json'
HELPER='scripts/sky_psm_discovery_v1.py'
HELPER_SHA='c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
MODEL='scripts/peer_clipper_census_v1.py'
MODEL_SHA='53603883391ba48d4b316e2292b449afc94ccab952a739f318a76bd571bf8d2e'
PRIOR_PLAN='research/peer-clipper-census-v1.json'
PRIOR_REVIEW='reports/peer-clipper-census-v1-root-review.json'
PRIOR_DESIGN='research/peer-clipper-census-v1-design.txt'
PRIOR_PROVENANCE='research/peer-clipper-source-provenance-v1.txt'
SLOTS=[('chain',4096),('block',32768),('ilk',512),('count',512),('list',8192),('count_recheck',512),('recheck',32768)]
CAPS=dict(requests=7,body_bytes=81920,raw_bytes=65536,request_bytes=8192,
          projection_bytes=4096,request_seconds=20,work_seconds=105,wall_seconds=120,
          cpu_seconds=20,ram_bytes=536870912,total_supplied_gas=800000,max_active_ids=64)


def module(name,path,digest):
    p=ROOT/path
    if p.is_symlink() or not p.is_file():raise RuntimeError('helper_path')
    with p.open('rb') as f:b=f.read(32769)
    if len(b)>32768 or hashlib.sha256(b).hexdigest()!=digest:raise RuntimeError('helper_pin')
    v=types.ModuleType(name);v.__file__=str(p);exec(compile(b,v.__file__,'exec'),v.__dict__);return v


m=module('clipper_transport_helpers',HELPER,HELPER_SHA)
q=module('clipper_offline_model',MODEL,MODEL_SHA)
c,h,t,s,encode,decode,read,sha=m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha


class Refusal(m.Refusal):pass


def ids(value,count):
    if not 0<=count<=CAPS['max_active_ids']:raise Refusal('complete_census_over_cap')
    if count==0:
        if h.hexdata(value,64)!='0x'+format(32,'064x')+format(0,'064x'):raise Refusal('empty_list_abi')
        return []
    return q.decode_ids(value,count)


def collect(rpc):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('chain')
    block=rpc('block','eth_getBlockByNumber',['finalized',False]);header=c.header(block)
    state=dict(blockHash=header['hash'],requireCanonical=True)
    def view(name,signature):
        tx=dict(q.call_object(signature),gasPrice='0x0')
        return rpc(name,'eth_call',[tx,state])
    if h.hexdata(view('ilk','ilk()'),32)!=q.ILK:raise Refusal('candidate_ilk_mismatch')
    count=q.uint(view('count','count()'))
    if count>CAPS['max_active_ids']:raise Refusal('complete_census_over_cap')
    active=ids(view('list','list()'),count)
    if q.uint(view('count_recheck','count()'))!=count:raise Refusal('anchored_count_changed')
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[hex(header['number']),False]),block)
    return dict(schema='sky-clipper-census-projection-v1',status='fixed_candidate_census_complete',
        clipper=q.CLIPPER,ilk=q.ILK,block=header,context=s.o.context(block),count=count,active_ids=[str(x) for x in active],
        provider_returned_complete_list=True,count_and_header_rechecked=True,
        runtime_code_observed=False,deployed_source_equivalence_proved=False,
        reset_eligibility_observed=False,reward_observed=False,gas_cost_observed=False,
        cash_closed=False,economics=False,repeatable_profit=False,
        scope='One prior selected ETH-A candidate at one finalized state; empty list is not continuing absence or protocol-wide census.')


def required_paths():
    return [SOURCE,TEST,DESIGN,NOTES,AMEND,ALLOCATION,PREP,HELPER,MODEL,PRIOR_PLAN,PRIOR_REVIEW,PRIOR_DESIGN,PRIOR_PROVENANCE]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('clipper')!=q.CLIPPER
        or p.get('ilk')!=q.ILK or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins:
        b=read(ROOT/x['path'],65536)
        if len(b)!=x['bytes'] or sha(b)!=x['sha256']:raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES,AMEND,PREP))>24576:raise Refusal('source_cap')
    prior=decode(read(ROOT/PRIOR_PLAN,8192));review=decode(read(ROOT/PRIOR_REVIEW,8192));q.validate_plan(prior)
    if (review.get('status')!='offline_source_package_reviewed_no_live_authority'
        or not any(x['path']==MODEL and x['sha256']==MODEL_SHA for x in review['files'])):raise Refusal('prior_review')
    if 4*200000!=CAPS['total_supplied_gas']:raise Refusal('gas_cap')
    for signature,selector in q.SELECTORS.items():
        if s.selector(signature)!='0x'+selector:raise Refusal('selector')
    a=decode(read(ROOT/ALLOCATION,4096));expected=dict(source_tests_design_notes=24576,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=4096,raw=65536)
    if a['categories_bytes']!=expected or a['total_experiment_reservation_bytes']!=110592:raise Refusal('funding')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def reason(exc):
    return (exc.category+':'+str(exc))[:160] if isinstance(exc,q.GateError) else m.reason(exc)


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
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);p=collect(capture.rpc)
                check,body,raw=replay(out/'raw')
                if p!=check or (body,raw)!=(capture.body_bytes,capture.raw_bytes):raise Refusal('replay')
                verify(digest);p['plan_sha256']=digest;s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_candidate_census_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_candidate_census_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256);v,b,r=replay(ROOT/OUT/'raw');print(encode(dict(status=v['status'],count=v['count'],body_bytes=b,raw_bytes=r)).decode());return 0
    if not a.run:print('dry: zero requests; fixed ETH-A candidate metadata only');return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
