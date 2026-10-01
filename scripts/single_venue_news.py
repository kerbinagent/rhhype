"""One precommitted public-data window around a scheduled BLS release."""
import datetime,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad_relative as previous
from scripts.single_venue_strategy import Study,PARAMS
from scripts.single_venue_depth_strategy import DepthStudy
study=previous.study;events=previous.events
PLAN=ROOT/'reports/experiment-storage/single-venue-news-v1.json'
OUT=ROOT/'reports/single-venue-news'
PREDECESSOR=previous.OUT/'terminal.json'
ASSETS=previous.ASSETS;SELECTED=previous.SELECTED
RAW_BYTES=50331648;HARD_BYTES=RAW_BYTES+262144
METADATA_BYTES=131072
TARGET=datetime.datetime(2026,10,2,12,26,tzinfo=datetime.timezone.utc).timestamp()
EVENT=datetime.datetime(2026,10,2,12,30,tzinfo=datetime.timezone.utc).timestamp()
MAX_WAIT_SECONDS=14*3600;LATE_GRACE_SECONDS=30

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def configure(family='relative'):
    assert family in ('relative','depth')
    previous.configure()
    study.Study=Study if family=='relative' else DepthStudy;study.PARAMS=PARAMS
    study.PLAN=PLAN;study.ASSETS=ASSETS
    study.NAMES={a:'single-venue-news-'+family+'-'+a.lower() for a in ASSETS}
    study.capture.PLAN=PLAN;study.capture.OUT=OUT/'capture';study.capture.SELECTED=SELECTED
    study.capture.HARD_BYTES=HARD_BYTES;study.capture.METADATA_MAX_BYTES=METADATA_BYTES
    events.HARD_BYTES=HARD_BYTES;events.METADATA_MAX_BYTES=METADATA_BYTES
    study.iter_events=previous.broad_events

def verify(family='relative'):
    configure(family);p=study.verify()
    assert p['selected']==SELECTED and p['assets']==list(ASSETS)
    assert p['duration_seconds']==600 and p['capture_hard_bytes']==HARD_BYTES
    assert p['batch_categories_bytes']['raw']==RAW_BYTES
    assert p['scheduled_start_epoch']==TARGET and p['event_epoch']==EVENT
    assert p['families']==['relative','depth']
    return p

def require_predecessor():
    t=json.loads(PREDECESSOR.read_bytes());assert t['state']=='finished' and t['normal_endpoint']

def wait_for_target(target,heartbeat,wall=time.time,mono=time.monotonic,sleep=time.sleep):
    assert target-wall()<=MAX_WAIT_SECONDS,'target beyond bounded waiting period'
    deadline=mono()+MAX_WAIT_SECONDS
    while wall()<target:
        if mono()>=deadline:raise TimeoutError('bounded_wait_exhausted')
        heartbeat();sleep(min(30,target-wall(),max(0,deadline-mono())))
    if wall()-target>LATE_GRACE_SECONDS:raise TimeoutError('missed_scheduled_start_no_retry')

def coverage(manifest):
    start=datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()
    end=datetime.datetime.fromisoformat(manifest['ended_utc']).timestamp()
    return start<=EVENT-150 and end>=EVENT+300

def supervise():
    verify();require_predecessor()
    state=dict(state='waiting',started_utc=utc(),economic_evaluation=False,plan_sha256=study.sha(PLAN),
        scheduled_start_epoch=TARGET,event_epoch=EVENT)
    def heartbeat():state.update(heartbeat_utc=utc());write(OUT/'status.json',state)
    heartbeat()
    try:
        wait_for_target(TARGET,heartbeat)
        state.update(state='collecting',capture_launch_utc=utc());heartbeat()
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'capture'],cwd=ROOT,
            stdin=subprocess.DEVNULL,timeout=720,check=False)
        path=OUT/'capture/terminal.json';terminal=json.loads(path.read_bytes()) if path.exists() else None
        normal=bool(run.returncode==0 and terminal and terminal.get('end_reason')=='duration_limit')
        mpath=OUT/'capture/manifest.json'
        covered=bool(normal and mpath.exists() and coverage(json.loads(mpath.read_bytes())))
        state.update(returncode=run.returncode,normal_endpoint=normal,event_coverage_valid=covered,terminal=terminal)
    except (subprocess.TimeoutExpired,TimeoutError,AssertionError) as exc:
        state.update(normal_endpoint=False,event_coverage_valid=False,error=type(exc).__name__+': '+str(exc)[:200])
    state.update(state='finished',ended_utc=utc());write(OUT/'terminal.json',state);write(OUT/'status.json',state)

def launch():
    verify();require_predecessor();assert 0<=TARGET-time.time()<=MAX_WAIT_SECONDS
    OUT.mkdir(exist_ok=False);command=[sys.executable,str(Path(__file__).resolve()),'supervise']
    with (OUT/'stdout.txt').open('xb') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=command,launched_utc=utc(),scheduled_start_epoch=TARGET,
        event_epoch=EVENT,seconds=600,raw_cap_bytes=RAW_BYTES,max_wait_seconds=MAX_WAIT_SECONDS,
        capture_timeout_seconds=720,public_read_only=True,plan_sha256=study.sha(PLAN))
    write(OUT/'process.json',record);print(json.dumps(record))

def audit(family,asset,digest):
    assert asset in ASSETS
    from scripts import audit_single_venue_study as cash
    from scripts import single_venue_compact_evidence as compact
    cash.PLAN=PLAN;cash.inputs=study.multi_inputs;cash.match_book=compact.match_compact
    if family=='relative':cash.audit(study.NAMES[asset],digest)
    else:
        from scripts.audit_single_venue_depth import run_audit
        run_audit(asset,digest)

def main(action,*args):
    family=args[0] if action in ('replay','audit') else 'relative';verify(family)
    if action=='launch':launch()
    elif action=='supervise':supervise()
    elif action=='capture':require_predecessor();study.main('capture')
    else:
        terminal=json.loads((OUT/'terminal.json').read_bytes())
        assert terminal['state']=='finished' and terminal['normal_endpoint'] and terminal['event_coverage_valid']
        if action=='replay':study.main('replay',*args[1:])
        elif action=='audit':audit(*args)
        else:raise ValueError(action)

if __name__=='__main__':main(*sys.argv[1:])
