"""Descriptive replay of the exact capped LIT prefix; no completed-run claim."""
import datetime,gzip,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth_replication as replication
from scripts import single_venue_depth as study
from scripts import single_venue_compact_evidence as compact
from scripts import audit_single_venue_depth_prefix as auditor
from scripts.audit_single_venue_depth import SignalAudit,tracked
PLAN=ROOT/'reports/experiment-storage/single-venue-depth-prefix-v1.json'
NAME='single-venue-depth-incomplete-prefix-lit'
MANIFEST='5316899734a8ad3792595515998079b376a092d6f71bbe2eb95be33d856fee84'

def verify():
    replication.configure();replication.verify()
    p=json.loads(PLAN.read_bytes())
    for pin in p['source_pins']:assert study.sha(ROOT/pin['path'])==pin['sha256'],pin['path']
    return p

def inputs(plan,name,digest):
    assert name==NAME and digest==MANIFEST
    source=study.capture.OUT
    assert study.sha(source/'manifest.json')==digest
    m=json.loads((source/'manifest.json').read_bytes())
    assert m['end_reason']=='compressed_size_cap' and m['truncated'] is True
    assert m['configured_seconds']==600
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    start=int(datetime.datetime.fromisoformat(m['started_utc']).timestamp()*10**9)
    events=study.iter_events(source,expected_manifest_sha256=digest,max_raw_bytes=study.capture.HARD_BYTES)
    return source,digest,study.market_alias(metadata,'LIT'),start,study.asset_events(events,'LIT')

def replay():
    plan=verify();compact.configure()
    source,digest,metadata,start,events=inputs(plan,NAME,MANIFEST)
    out=ROOT/'reports/single-venue-research'/NAME;out.mkdir(exist_ok=False)
    trace=study.Archive(out/'trace.jsonl.gz',98304)
    engine=study.Study(metadata,start,trace.add);error=None;end=None
    try:
        for event in events:
            engine.process(event)
            if event['type']=='end':end=event
    except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
    finally:trace.close()
    result=dict(schema='single-venue-depth-incomplete-prefix-v1',sample=NAME,asset='LIT',
        retrospective=True,actual_pnl=None,error=error,complete_capture_verified=False,
        observed_prefix_verified=end is not None,source=str(source.relative_to(ROOT)),
        manifest_sha256=digest,plan_sha256=study.sha(PLAN),trace_sha256=study.sha(out/'trace.jsonl.gz'),
        trace_bytes=trace.bytes,end=end,**engine.summary())
    packed=gzip.compress(study.encode(result),mtime=0);assert len(packed)<=16384
    (out/'summary.json.gz').write_bytes(packed)
    arms={}
    for label,r in result['arms'].items():
        arms[label]={k:r[k] for k in ('attempts','closed','complete','unknown','cash')}
        arms[label].update(wins=sum(D(e['cash_after_capital'])>0 for e in r['episodes']),
            cash_after_capital_sum=str(sum((D(e['cash_after_capital']) for e in r['episodes']),D(0))),
            stressed_sum=str(sum((D(e['stressed_net']) for e in r['episodes']),D(0))))
    metrics=dict(complete_capture_verified=False,observed_prefix_verified=end is not None,
        retrospective=True,error=error,arms=arms,feature_counts=result['feature_counts'])
    blob=study.encode(metrics);assert len(blob)<=8192
    (out/'metrics.json').write_bytes(blob);print(json.dumps(metrics,indent=2))
    if error or end is None:raise SystemExit(1)

def audit():
    verify();compact.configure();tracker=SignalAudit()
    def audit_inputs(*args):
        source,digest,metadata,start,events=inputs(*args)
        return source,digest,metadata,start,tracked(events,tracker)
    auditor.PLAN=PLAN;auditor.inputs=audit_inputs;auditor.verify_signal=tracker.verify
    auditor.match_book=compact.match_compact
    auditor.audit(NAME,MANIFEST)

if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('replay','audit')
    {'replay':replay,'audit':audit}[sys.argv[1]]()
