"""Prospectively larger Beefy response capture; retains the capped v1."""
import hashlib
from pathlib import Path
import sys
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/beefy_caller_reward_v2.py'
TEST='tests/test_beefy_caller_reward_v2.py'
BASE='reports/beefy-caller-reward-v2/'
PLAN,DESIGN,OUT=(BASE+x for x in ('plan.json','design.txt','run-v1'))
PREP='reports/experiment-storage/beefy-caller-reward-v2-preparation.json'
ALLOCATION='reports/experiment-storage/beefy-caller-reward-v2-allocation.json'
OLD='scripts/beefy_caller_reward_v1.py'
OLD_SHA='da99aff547f5f5a221c03f057e205e390cdf1da38fef6f27ef512e45fbd83c9f'
OLD_PLAN_SHA='0dea7b8d0d60e456a9c10162c5ce3bbdf65fa25a3b45031baeacb966e9397ce8'
OLD_BASE='reports/beefy-caller-reward-v1/'
OLD_CLOSE='reports/experiment-storage/beefy-caller-reward-closeout-v1.json'
CAPS=dict(requests=13,body_bytes=393216,raw_bytes=286720,request_bytes=8192,projection_bytes=8192,
          request_seconds=20,work_seconds=105,wall_seconds=120,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=10800000)

p=ROOT/OLD
if p.is_symlink() or not p.is_file():raise RuntimeError('old_source_path')
with p.open('rb') as f:raw=f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=OLD_SHA:raise RuntimeError('old_source_pin')
b=types.ModuleType('beefy_v1_pinned');b.__file__=str(p);exec(compile(raw,b.__file__,'exec'),b.__dict__)
old_plan=b.verify(OLD_PLAN_SHA)
SLOTS=[(name,131072 if name.startswith('branch_') else cap) for name,cap in b.SLOTS]
encode,decode,read,sha=b.encode,b.decode,b.read,b.sha
Refusal=b.Refusal
old_collect=b.collect


def collect(rpc):
    value=old_collect(rpc)
    value.update(schema='beefy-caller-reward-projection-v2',prior_capture_unavailable=True,
                 prior_terminal_path=OLD_BASE+'run-v1/terminal.json',prospective_larger_response_limit=True)
    return value


def required_paths():
    return [SOURCE,TEST,DESIGN,PREP,ALLOCATION,OLD,OLD_BASE+'plan.json',OLD_BASE+'run-v1/terminal.json',
            OLD_BASE+'audit.json',OLD_BASE+'root-review.json',OLD_CLOSE]


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=b.h.runtime() or p.get('output_dir')!=OUT or p.get('vaults')!=[list(x) for x in b.VAULTS]
        or p.get('prior_plan_sha256')!=OLD_PLAN_SHA or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):
        raise Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise Refusal('pins')
    for x in pins+old_plan['pins']:
        data=read(ROOT/x['path'],65536)
        if len(data)!=x['bytes'] or sha(data)!=x['sha256']:raise Refusal('input_pin')
    if sum((ROOT/x).stat().st_size for x in (SOURCE,TEST,DESIGN,PREP))>16384:raise Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096))
    if (a['categories_bytes']!=dict(source_tests_design_preparation=16384,plan_and_claim=8192,
        controls_reviews_readout=8192,projection=8192,raw=286720) or a['total_experiment_reservation_bytes']!=327680):
        raise Refusal('funding')
    terminal=decode(read(ROOT/(OLD_BASE+'run-v1/terminal.json'),2048))
    if (terminal['status']!='unavailable' or terminal['error']!='response_cap_sentinel_retained'
        or terminal['requests_attempted']!=11 or terminal['raw_bytes']!=61601):raise Refusal('prior_failure')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


b.CAPS,b.SLOTS,b.BASE,b.PLAN,b.OUT=CAPS,SLOTS,BASE,PLAN,OUT
b.verify,b.collect=verify,collect
replay=b.replay


if __name__=='__main__':raise SystemExit(b.main())
