"""One fixed public capture for the frozen multi-asset directional study."""
import datetime,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_multi import verify,PLAN,capture,sha

def main():
    p=verify();assert p['duration_seconds']==600 and not capture.OUT.exists()
    record=ROOT/'reports/single-venue-multi-process.json';assert not record.exists()
    command=[sys.executable,str(ROOT/'scripts/single_venue_multi.py'),'capture']
    with (ROOT/'reports/single-venue-multi.stdout.txt').open('xb') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,
            stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    r=dict(pid=child.pid,command=command,launched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
           fixed_capture_seconds=600,public_read_only=True,plan_sha256=sha(PLAN))
    record.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))

if __name__=='__main__':main()
