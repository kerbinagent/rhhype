"""Single network-enabled launch correction; preserve the zero-data DNS failure."""
from pathlib import Path
import hashlib
import sys
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/beefy_caller_reward_v2_network.py'
BASE='reports/beefy-caller-reward-v2/'
PLAN=BASE+'launch-correction-plan.json'
OUT=BASE+'run-v2'
ORIGINAL='scripts/beefy_caller_reward_v2.py'
ORIGINAL_PLAN='108a006111520c539e9b7f6db86a189850e29615a3b28e6f76df598d2bf84797'
p=ROOT/ORIGINAL
if p.is_symlink():raise RuntimeError('source_symlink')
raw=p.read_bytes()
if len(raw)>16384:raise RuntimeError('source_cap')
m=types.ModuleType('beefy_v2_pinned');m.__file__=str(p);exec(compile(raw,m.__file__,'exec'),m.__dict__)
old_verify=m.verify
CAPS=dict(m.CAPS,raw_bytes=286408)
PINS=[SOURCE,ORIGINAL,BASE+'launch-correction-allocation.json',BASE+'run-v1/claim.json',
      BASE+'run-v1/terminal.json',BASE+'run-v1/raw/01.request.json',BASE+'run-v1/raw/01.receipt.json',BASE+'run-v1/raw/01.body']


def verify(digest):
    old_verify(ORIGINAL_PLAN)
    data=m.read(ROOT/PLAN,4096)
    if m.sha(data)!=digest:raise m.Refusal('correction_plan_sha')
    v=m.decode(data)
    if (v.get('caps')!=CAPS or v.get('output_dir')!=OUT or v.get('original_plan_sha256')!=ORIGINAL_PLAN
        or v.get('status')!='frozen' or v.get('runtime')!=m.b.h.runtime()
        or v.get('slots')!=[list(x) for x in m.SLOTS]):raise m.Refusal('correction_scope')
    pins=v.get('pins',[])
    if len(pins)!=len(PINS) or {x['path'] for x in pins}!=set(PINS):raise m.Refusal('correction_pins')
    for x in pins:
        b=m.read(ROOT/x['path'],16384)
        if len(b)!=x['bytes'] or m.sha(b)!=x['sha256']:raise m.Refusal('correction_input_pin')
    if sum((ROOT/x).stat().st_size for x in (m.SOURCE,m.TEST,m.DESIGN,m.PREP,SOURCE))>16384:raise m.Refusal('correction_source_cap')
    prior=m.decode(m.read(ROOT/(BASE+'run-v1/terminal.json'),2048))
    if (prior['error']!='gaierror' or prior['body_bytes']!=0 or prior['requests_attempted']!=1
        or prior['raw_bytes']!=312 or (ROOT/(BASE+'run-v1/projection.json')).exists()):raise m.Refusal('prior_not_zero_data_dns_failure')
    if (ROOT/OUT).is_symlink():raise m.Refusal('correction_output_symlink')
    return v


m.b.CAPS,m.b.OUT,m.b.verify=CAPS,OUT,verify
replay=m.b.replay
if __name__=='__main__':raise SystemExit(m.b.main())
