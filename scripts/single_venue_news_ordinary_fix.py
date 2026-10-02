"""Separately frozen, bounded offline correction of the news ordinary feed."""
import datetime,gzip,hashlib,json,subprocess,sys,time
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_news as news
from scripts import single_venue_ordinary_events as ordinary
from scripts import single_venue_compact_evidence as compact
from scripts.core_rh_small_shortterm import Archive
from scripts.run_single_venue_study import encode
PLAN=ROOT/'reports/experiment-storage/single-venue-news-ordinary-feed-fix-v1.json'
RESEARCH=ROOT/'reports/single-venue-research'
CAPTURE_PLAN_SHA='e9efab93a06e4e53fdb76b2f4b0e955f25f37a749c810062736a66f04ec90ffe'
MAX_WAIT_SECONDS=14*3600
TERMINAL_DEADLINE=news.EVENT+600
ANALYSIS_SECONDS=3600
BOUNDS=dict(decoded_bytes=1073741824,records=1000000,trade_ids=500000,metadata_bytes=131072,raw_bytes=50593792)
CAPS=dict(per_directory=131072,trace=98304,summary=16384,metrics=8192,audit=8192,
    comparison_gzip_per_family=16384,comparison_csv_per_family=32768,controls=65536,readout=16384)

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(path,cap=262144):
    path=Path(path);assert not path.is_symlink() and path.stat().st_size<=cap
    return json.loads(path.read_bytes())
def tree_bytes(path):
    total=0;count=0
    for p in path.rglob('*'):
        count+=1;assert count<=256 and not p.is_symlink()
        if p.is_file():total+=p.stat().st_size
    return total
def publish(path,data,cap,*,directory_cap=None,replace=False):
    assert isinstance(data,bytes) and len(data)<=cap,'output_byte_cap'
    path=Path(path);assert not path.is_symlink()
    if directory_cap is not None:
        prior=path.stat().st_size if replace and path.exists() else 0
        assert tree_bytes(path.parent)-prior+len(data)<=directory_cap,'directory_byte_cap'
    with path.open('wb' if replace else 'xb') as f:f.write(data)
def control(plan,name,value,*,replace=False):
    publish(ROOT/plan['control_root']/name,encode(value),8192,directory_cap=CAPS['controls'],replace=replace)

def verify(family='relative'):
    # Validate the original capture contract before changing any runtime route.
    assert sha(news.PLAN)==CAPTURE_PLAN_SHA
    original=news.verify(family);p=read(PLAN,16384)
    assert p['status']=='frozen','analysis_protocol_not_frozen'
    assert p['original_capture_plan_sha256']==CAPTURE_PLAN_SHA
    assert p['capture_plan']==str(news.PLAN.relative_to(ROOT))
    assert p['capture_root']=='reports/single-venue-news/capture'
    assert p['control_root']=='reports/single-venue-news-ordinary-fix-v1'
    assert p['output_stem']=='single-venue-news-ordinary-fix'
    for k in ('assets','selected','families','execution_parameters','duration_seconds',
              'capture_hard_bytes','scheduled_start_epoch','event_epoch'):
        assert p[k]==original[k],k
    assert p['adapter_bounds']==BOUNDS and p['output_caps']==CAPS
    assert p['source_pins']
    for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256'],pin['path']
    configure(p,family);return p

def configure(plan,family):
    assert family in ('relative','depth')
    news.configure(family);study=news.study
    study.PLAN=PLAN;study.NAMES={a:plan['output_stem']+'-'+family+'-'+a.lower() for a in news.ASSETS}
    # The metadata market plan remains the exact original capture plan.
    study.capture.PLAN=news.PLAN
    ordinary.HARD_BYTES=BOUNDS['raw_bytes'];ordinary.HARD_SECONDS=600
    ordinary.METADATA_MAX_BYTES=BOUNDS['metadata_bytes']
    ordinary.MAX_DECODED_BYTES=BOUNDS['decoded_bytes'];ordinary.MAX_RECORDS=BOUNDS['records']
    ordinary.MAX_TRADE_IDS=BOUNDS['trade_ids'];study.iter_events=events
    return study

def events(source,*,expected_manifest_sha256,max_raw_bytes):
    assert max_raw_bytes==BOUNDS['raw_bytes']
    p=read(PLAN,16384);provenance=read(ROOT/p['control_root']/'input-pins.json',8192)
    assert provenance['manifest_sha256']==expected_manifest_sha256 and provenance['analysis_plan_sha256']==sha(PLAN)
    return ordinary.iter_events(source,expected_manifest_sha256=expected_manifest_sha256,
        expected_raw_sha256=provenance['raw_sha256'],max_raw_bytes=max_raw_bytes,
        max_decoded_bytes=BOUNDS['decoded_bytes'],max_records=BOUNDS['records'],max_ids=BOUNDS['trade_ids'])

def require_terminal(terminal):
    assert terminal['state']=='finished' and terminal['normal_endpoint'] and terminal['event_coverage_valid'],'capture_incomplete_no_evaluation'
    assert terminal['plan_sha256']==CAPTURE_PLAN_SHA
def await_terminal(heartbeat,wall=time.time,mono=time.monotonic,sleep=time.sleep):
    deadline=mono()+MAX_WAIT_SECONDS;path=news.OUT/'terminal.json'
    while not path.exists():
        if wall()>TERMINAL_DEADLINE or mono()>=deadline:raise TimeoutError('capture_terminal_missing_no_retry')
        heartbeat();sleep(min(30,max(0,deadline-mono())))
    terminal=read(path);require_terminal(terminal);return terminal

def input_snapshot(plan):
    terminal=read(news.OUT/'terminal.json');require_terminal(terminal)
    cap=ROOT/plan['capture_root'];manifest=read(cap/'manifest.json')
    assert manifest['market_plan_sha256']==CAPTURE_PLAN_SHA
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated'] and news.coverage(manifest)
    assert manifest['selected_markets']==news.SELECTED
    capture_terminal=read(cap/'terminal.json')
    assert capture_terminal['plan_sha256']==CAPTURE_PLAN_SHA and capture_terminal['status']=='capture_completed'
    assert capture_terminal['end_reason']=='duration_limit'
    digest=sha(cap/'manifest.json');raw=sha(cap/'frames.jsonl.gz')
    assert raw==manifest['frames_sha256'] and digest==capture_terminal['manifest_sha256']==terminal['terminal']['manifest_sha256']
    names=[f'metadata/{name}{suffix}' for name in news.study.capture.REQUESTS for suffix in ('.json.gz','.request.json')]
    names+=['metadata/market_plan.json','metadata/normalized.json','manifest.json','frames.jsonl.gz','terminal.json']
    assert set(str(p.relative_to(cap)) for p in cap.rglob('*') if p.is_file())==set(names),'capture_inventory_changed'
    assert tree_bytes(cap)<=BOUNDS['raw_bytes']
    metadata=ordinary._metadata(cap,manifest,ordinary._epoch_ns(manifest['started_utc']))[0]
    assert metadata['market_plan_sha256']==CAPTURE_PLAN_SHA
    assert sum((cap/n).stat().st_size for n in names if n.startswith('metadata/'))<=BOUNDS['metadata_bytes']
    files=[cap/n for n in names]+[news.OUT/'terminal.json',news.PLAN,PLAN]
    return dict(manifest_sha256=digest,raw_sha256=raw,analysis_plan_sha256=sha(PLAN),capture_plan_sha256=CAPTURE_PLAN_SHA,
        files={str(p.relative_to(ROOT)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in files})
def require_pins(plan,digest=None):
    pinned=read(ROOT/plan['control_root']/'input-pins.json',8192)
    current=input_snapshot(plan);assert current==pinned,'frozen_input_changed'
    if digest is not None:assert current['manifest_sha256']==digest
    return current

def replay(family,digest):
    plan=verify(family);require_pins(plan,digest);study=news.study;compact.configure()
    source=study.capture.OUT;manifest=read(source/'manifest.json')
    metadata=read(source/'metadata/normalized.json')['markets']
    start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
    studies={};traces={};outputs={};error=None;end=None
    try:
        for asset in news.ASSETS:
            out=RESEARCH/study.NAMES[asset];out.mkdir(parents=True,exist_ok=False);outputs[asset]=out
            traces[asset]=Archive(out/'trace.jsonl.gz',CAPS['trace'])
            studies[asset]=study.Study(study.market_alias(metadata,asset),start,traces[asset].add)
        for event in events(source,expected_manifest_sha256=digest,max_raw_bytes=BOUNDS['raw_bytes']):
            for asset,s in studies.items():s.process(study.dispatch(event,asset))
            if event['type']=='end':end=event
    except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
    finally:
        for trace in traces.values():trace.close()
    for asset,s in studies.items():
        out=outputs[asset]
        result=dict(schema='single-venue-depth-research-v1',sample=study.NAMES[asset],asset=asset,retrospective=False,
            actual_pnl=None,error=error,complete_capture_verified=end is not None,source=str(source.relative_to(ROOT)),
            manifest_sha256=digest,plan_sha256=sha(PLAN),trace_sha256=sha(out/'trace.jsonl.gz'),
            trace_bytes=traces[asset].bytes,end=end,**s.summary())
        publish(out/'summary.json.gz',gzip.compress(encode(result),mtime=0),CAPS['summary'],directory_cap=CAPS['per_directory'])
        metrics={}
        for arm,r in result['arms'].items():
            metrics[arm]={k:r[k] for k in ('attempts','closed','complete','unknown','cash')}
            metrics[arm].update(wins=sum(D(e['cash_after_capital'])>0 for e in r['episodes']),
                cash_after_capital_sum=str(sum((D(e['cash_after_capital']) for e in r['episodes']),D(0))),
                stressed_sum=str(sum((D(e['stressed_net']) for e in r['episodes']),D(0))))
        report=dict(asset=asset,error=error,complete_capture_verified=end is not None,arms=metrics,feature_counts=result['feature_counts'])
        publish(out/'metrics.json',encode(report),CAPS['metrics'],directory_cap=CAPS['per_directory'])
    require_pins(plan,digest);verify(family)
    if error or end is None:raise RuntimeError('replay_incomplete_no_retry '+str(error))

def audit(family,asset,digest):
    assert asset in news.ASSETS
    plan=verify(family);require_pins(plan,digest);compact.configure()
    from scripts import audit_single_venue_study as cash
    cash.PLAN=PLAN;cash.inputs=news.study.multi_inputs;cash.match_book=compact.match_compact
    target=RESEARCH/news.study.NAMES[asset]/'independent-audit.json'
    original=Path.write_text
    def bounded_write(path,data,*args,**kwargs):
        assert path==target,'unexpected_audit_write'
        publish(path,data.encode('utf-8'),CAPS['audit'],directory_cap=CAPS['per_directory']);return len(data)
    Path.write_text=bounded_write
    try:
        if family=='relative':cash.audit(news.study.NAMES[asset],digest)
        else:
            from scripts.audit_single_venue_depth import run_audit
            run_audit(asset,digest)
    finally:Path.write_text=original
    require_pins(plan,digest);verify(family)

def commands(digest):
    for family in ('relative','depth'):
        yield ['scripts/single_venue_news_ordinary_fix.py','replay',family,digest]
        for asset in news.ASSETS:yield ['scripts/single_venue_news_ordinary_fix.py','audit',family,asset,digest]
        yield ['scripts/single_venue_news_ordinary_fix_readout.py',family]
def command(args,deadline,mono=time.monotonic,heartbeat=lambda:None):
    remaining=deadline-mono()
    if remaining<=0:raise TimeoutError('analysis_deadline_no_retry')
    child_deadline=mono()+min(600,remaining)
    child=subprocess.Popen(['nice','-n','19',sys.executable,*args],cwd=ROOT,stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        while True:
            remaining=child_deadline-mono()
            if remaining<=0:raise TimeoutError('command_deadline_no_retry')
            try:code=child.wait(timeout=min(30,remaining));break
            except subprocess.TimeoutExpired:heartbeat()
        if code:raise RuntimeError('command_failed_no_retry '+repr(args))
    finally:
        if child.poll() is None:child.kill();child.wait()
def make_readout(plan):
    from scripts.single_venue_news_ordinary_fix_readout import combined_readout
    combined_readout(plan)
def supervise():
    plan=verify();out=ROOT/plan['control_root'];assert out.exists() and not (out/'analysis-terminal.json').exists()
    state=dict(state='waiting_for_capture_terminal',started_utc=utc(),plan_sha256=sha(PLAN),economic_evaluation=False)
    def heartbeat():state.update(heartbeat_utc=utc());control(plan,'analysis-status.json',state,replace=True)
    heartbeat()
    try:
        await_terminal(heartbeat);plan=verify();snapshot=input_snapshot(plan)
        control(plan,'input-pins.json',snapshot);digest=snapshot['manifest_sha256'];deadline=time.monotonic()+ANALYSIS_SECONDS
        state.update(state='evaluating_completed_capture',economic_evaluation=True,manifest_sha256=digest,completed_commands=0)
        for args in commands(digest):
            state.update(command=args);heartbeat();command(args,deadline,heartbeat=heartbeat)
            state['completed_commands']+=1;heartbeat()
        assert time.monotonic()<deadline,'analysis_deadline_no_retry'
        verify();require_pins(plan,digest);make_readout(plan);verify();require_pins(plan,digest)
        assert time.monotonic()<deadline,'analysis_deadline_no_retry'
        state.update(state='finished',success=True)
    except Exception as exc:state.update(state='finished',success=False,error=type(exc).__name__+': '+str(exc)[:2500])
    state.update(ended_utc=utc());control(plan,'analysis-terminal.json',state);control(plan,'analysis-status.json',state,replace=True)
    if not state['success']:raise SystemExit(1)
def launch():
    plan=verify();assert time.time()<=TERMINAL_DEADLINE
    out=ROOT/plan['control_root'];out.mkdir(parents=True,exist_ok=False)
    args=[sys.executable,str(Path(__file__).resolve()),'supervise']
    child=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=args,launched_utc=utc(),plan_sha256=sha(PLAN),public_data_only=True,
        offline_after_capture=True,terminal_deadline_epoch=TERMINAL_DEADLINE,max_wait_seconds=MAX_WAIT_SECONDS,
        max_analysis_seconds=ANALYSIS_SECONDS,no_retry=True)
    control(plan,'analysis-process.json',record);print(json.dumps(record))
def main(action,*args):
    assert action in ('launch','supervise','verify','replay','audit')
    globals()[action](*args)
if __name__=='__main__':main(*sys.argv[1:])
