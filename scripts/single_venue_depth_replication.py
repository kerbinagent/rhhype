"""Configuration-only LIT replication; identical depth signal and cash engine."""
import datetime,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth as study
from scripts import single_venue_depth_events as events
PLAN=ROOT/'reports/experiment-storage/single-venue-depth-replication-v1.json'
SELECTED={'rh_lighter':{'LIT':'5'},'lighter':{'LIT':'120'}}
HARD_BYTES=2228224

def configure():
    study.PLAN=PLAN;study.ASSETS=('LIT',);study.NAMES={'LIT':'single-venue-depth-replication-lit'}
    study.capture.PLAN=PLAN;study.capture.OUT=ROOT/'reports/single-venue-depth-replication/capture'
    study.capture.SELECTED=SELECTED;study.capture.HARD_BYTES=HARD_BYTES
    # Adapter imported the hard bound by value; bind the same new capture bound.
    events.HARD_BYTES=HARD_BYTES

def verify():
    p=study.verify()
    assert p['selected']==SELECTED and p['duration_seconds']==600
    assert p['capture_hard_bytes']==HARD_BYTES and p['categories_bytes']['raw']==2097152
    return p

def main(action,*args):
    configure();verify()
    if action=='launch':
        assert not study.capture.OUT.exists()
        record=ROOT/'reports/single-venue-depth-replication-process.json';assert not record.exists()
        command=[sys.executable,str(Path(__file__).resolve()),'capture']
        with (ROOT/'reports/single-venue-depth-replication.stdout.txt').open('xb') as log:
            child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,
                stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        result=dict(pid=child.pid,command=command,launched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            fixed_capture_seconds=600,public_read_only=True,plan_sha256=study.sha(PLAN))
        record.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    else:study.main(action,*args)

if __name__=='__main__':main(*sys.argv[1:])
