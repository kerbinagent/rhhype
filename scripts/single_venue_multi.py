"""Apply unchanged one-venue rules to isolated LIT, VVV and ZEC portfolios."""
import asyncio,datetime,gzip,json,sys
from itertools import groupby
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_multi_capture as capture
from scripts.single_venue_multi_events import iter_events
from scripts.single_venue_strategy import Study,PARAMS
from scripts.core_rh_small_shortterm import Archive
from scripts.run_single_venue_study import sha,encode
from scripts import single_venue_compact_evidence as compact
from scripts import audit_single_venue_study as auditor
from scripts import single_venue_shock_diagnostic as diagnostic
PLAN=ROOT/'reports/experiment-storage/single-venue-multi-v1.json'
ASSETS=('LIT','VVV','ZEC')
NAMES={a:'single-venue-multi-'+a.lower() for a in ASSETS}

def verify():
    p=json.loads(PLAN.read_bytes());assert p['parameters']==PARAMS
    for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256'],pin['path']
    return p

def dispatch(event,asset):
    if event.get('asset')==asset or event['type']=='end':return event
    # Other assets advance the physical clock but supply neither a book nor flow.
    return dict(type='control',received_ns=event['received_ns'],venue=None,
                control='other_asset_clock',asset=None)

def market_alias(metadata,asset):
    # LIT is solely an unchanged constructor slot. Market identity remains real.
    return {v:{'LIT':markets[asset]} for v,markets in metadata.items()}

def asset_events(events,asset):
    # At a tied receipt stamp, native events themselves advance the clock.
    # Remove redundant other-asset clock tokens for trace matching, preserving
    # every native event and its order. Pure foreign timestamps still advance time.
    for _,group in groupby(events,key=lambda e:e['received_ns']):
        batch=list(group)
        native=[e for e in batch if e.get('asset')==asset or e['type']=='end']
        if native:yield from native
        else:yield dispatch(batch[0],asset)

def multi_inputs(plan,name,manifest_hash):
    asset=next(a for a,n in NAMES.items() if n==name)
    source=capture.OUT
    assert sha(source/'manifest.json')==manifest_hash
    manifest=json.loads((source/'manifest.json').read_bytes())
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
    events=iter_events(source,expected_manifest_sha256=manifest_hash,max_raw_bytes=capture.HARD_BYTES)
    return source,manifest_hash,market_alias(metadata,asset),start,asset_events(events,asset)

def replay(manifest_hash):
    plan=verify();compact.configure()
    source=capture.OUT;assert sha(source/'manifest.json')==manifest_hash
    manifest=json.loads((source/'manifest.json').read_bytes())
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
    studies={};traces={};outputs={};error=None;end=None
    for a in ASSETS:
        out=ROOT/'reports/single-venue-research'/NAMES[a];out.mkdir(parents=True,exist_ok=False);outputs[a]=out
        traces[a]=Archive(out/'trace.jsonl.gz',196608)
        studies[a]=Study(market_alias(metadata,a),start,traces[a].add)
    try:
        for event in iter_events(source,expected_manifest_sha256=manifest_hash,max_raw_bytes=capture.HARD_BYTES):
            for a,s in studies.items():s.process(dispatch(event,a))
            if event['type']=='end':end=event
    except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
    finally:
        for trace in traces.values():trace.close()
    reports={}
    for a,study in studies.items():
        out=outputs[a]
        result=dict(schema='single-venue-multi-research-v1',sample=NAMES[a],asset=a,retrospective=False,
            actual_pnl=None,error=error,complete_capture_verified=end is not None,
            source=str(source.relative_to(ROOT)),manifest_sha256=manifest_hash,plan_sha256=sha(PLAN),
            trace_sha256=sha(out/'trace.jsonl.gz'),trace_bytes=traces[a].bytes,end=end,**study.summary())
        packed=gzip.compress(encode(result),mtime=0);assert len(packed)<=32768
        (out/'summary.json.gz').write_bytes(packed)
        metrics={}
        for arm,r in result['arms'].items():
            metrics[arm]={k:r[k] for k in ('attempts','closed','complete','unknown','cash')}
            metrics[arm].update(wins=sum(D(e['cash_after_capital'])>0 for e in r['episodes']),
                cash_after_capital_sum=str(sum((D(e['cash_after_capital']) for e in r['episodes']),D(0))),
                stressed_sum=str(sum((D(e['stressed_net']) for e in r['episodes']),D(0))))
        report=dict(asset=a,error=error,complete_capture_verified=end is not None,arms=metrics,feature_counts=result['feature_counts'])
        (out/'metrics.json').write_bytes(encode(report));reports[a]=report
    print(json.dumps(reports,indent=2),flush=True)
    if error or end is None:raise SystemExit(1)

def main(action,*args):
    verify()
    if action=='capture':asyncio.run(capture.main())
    elif action=='replay':replay(*args)
    elif action in ('audit','diagnostic'):
        asset,manifest_hash=args;assert asset in ASSETS
        compact.configure()
        if action=='audit':
            auditor.PLAN=PLAN;auditor.inputs=multi_inputs;auditor.audit(NAMES[asset],manifest_hash)
        else:
            diagnostic.PLAN=PLAN;diagnostic.inputs=multi_inputs;diagnostic.run(NAMES[asset],manifest_hash)
    else:raise ValueError('capture, replay <hash>, audit|diagnostic <asset> <hash>')

if __name__=='__main__':main(*sys.argv[1:])
