"""Bounded one-venue replay; a retrospective sample is never prospective evidence."""
from pathlib import Path
from datetime import datetime
import gzip
import hashlib
import importlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_strategy import Study, PARAMS
from scripts.core_rh_small_shortterm import Archive

PLAN=ROOT/'reports/experiment-storage/single-venue-research-v1.json'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def encode(x):
    return (json.dumps(x,default=str,separators=(',',':'),allow_nan=False)+'\n').encode()

def inputs(plan, name, manifest_hash=None):
    if name == 'prospective':
        case=plan['prospective']
        assert manifest_hash and len(manifest_hash)==64
    else:
        case=next(c for c in plan['retrospective'] if c['name']==name)
        manifest_hash=case['manifest_sha256']
    source=ROOT/case['capture']
    assert sha(source/'manifest.json')==manifest_hash
    manifest=json.loads((source/'manifest.json').read_bytes())
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
    adapter=importlib.import_module('scripts.'+case['adapter'])
    if name == 'prospective':
        adapter.HARD_BYTES=plan['capture_hard_bytes']
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    start=int(datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
    events=adapter.iter_events(source,expected_manifest_sha256=manifest_hash,
        max_raw_bytes=plan['capture_hard_bytes'] if name=='prospective' else 3276800)
    return source,manifest_hash,metadata,start,events

def main(name, manifest_hash=None):
    plan=json.loads(PLAN.read_bytes())
    assert plan['parameters']==PARAMS
    for pin in plan['source_pins']:
        assert sha(ROOT/pin['path'])==pin['sha256'],pin['path']
    source,digest,metadata,start,events=inputs(plan,name,manifest_hash)
    out=ROOT/'reports/single-venue-research'/name
    out.mkdir(parents=True,exist_ok=False)
    trace=Archive(out/'trace.jsonl.gz',plan['prospective_trace_cap'] if name=='prospective' else 49152)
    study=Study(metadata,start,trace.add)
    end=None;error=None
    try:
        for event in events:
            study.process(event)
            if event['type']=='end':end=event
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)[:400]
    finally:
        trace.close()
    result=dict(schema='single-venue-research-v1', sample=name,
        retrospective=name!='prospective', actual_pnl=None, error=error,
        complete_capture_verified=end is not None, source=str(source.relative_to(ROOT)),
        manifest_sha256=digest, plan_sha256=sha(PLAN), trace_sha256=sha(out/'trace.jsonl.gz'),
        trace_bytes=trace.bytes, end=end, **study.summary())
    data=gzip.compress(encode(result),mtime=0)
    assert len(data)<=32768
    (out/'summary.json.gz').write_bytes(data)
    metrics={}
    for arm,r in result['arms'].items():
        from decimal import Decimal as D
        eps=r['episodes']
        metrics[arm]={k:r[k] for k in ('attempts','closed','complete','unknown','cash')}
        metrics[arm].update(wins=sum(D(e['cash_after_capital'])>0 for e in eps),
            cash_after_capital_sum=str(sum((D(e['cash_after_capital']) for e in eps),D(0))),
            stressed_sum=str(sum((D(e['stressed_net']) for e in eps),D(0))))
    report=dict(error=error,complete_capture_verified=end is not None,arms=metrics,
        feature_counts=result['feature_counts'])
    (out/'metrics.json').write_bytes(encode(report))
    print(json.dumps(report,indent=2),flush=True)
    if error or end is None:raise SystemExit(1)

if __name__=='__main__':
    main(*sys.argv[1:])
