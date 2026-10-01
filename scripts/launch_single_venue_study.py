"""Launch exactly one fixed, public-data-only capture after protocol freeze."""
import datetime,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/single-venue-research-v1.json'
OUT=ROOT/'reports/single-venue-capture'
LOG=ROOT/'reports/single-venue-capture.stdout.txt'
RECORD=ROOT/'reports/single-venue-capture-process.json'

def main():
    plan=json.loads(PLAN.read_bytes());assert plan['duration_seconds']==600
    for pin in plan['source_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256'],pin['path']
    assert not OUT.exists() and not RECORD.exists()
    command=[sys.executable,str(ROOT/'scripts/capture_single_venue_study.py')]
    with LOG.open('xb') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,
            stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=command,launched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                fixed_capture_seconds=600,public_read_only=True,
                plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest())
    with RECORD.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
    print(json.dumps(record))

if __name__=='__main__':main()
