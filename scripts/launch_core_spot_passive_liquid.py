"""Launch one bounded read-only capture independently of an interactive tool turn."""
import datetime,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/core-spot-passive-liquid-v1.json'
OUT=ROOT/'reports/core-spot-passive-liquid'
LOG=ROOT/'reports/core-spot-passive-liquid.stdout.txt'
RECORD=ROOT/'reports/core-spot-passive-liquid-process.json'
def main():
 plan=json.loads(PLAN.read_bytes());assert plan['duration_seconds']==600
 for pin in plan['source_pins']:assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
 assert not OUT.exists() and not RECORD.exists()
 command=[sys.executable,str(ROOT/'scripts/core_spot_passive_liquid.py'),'capture']
 with LOG.open('xb') as log:
  child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
 record={'pid':child.pid,'command':command,'launched_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'fixed_capture_seconds':600,'public_read_only':True,'log':str(LOG.relative_to(ROOT))}
 with RECORD.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
 print(json.dumps(record))
if __name__=='__main__':main()
