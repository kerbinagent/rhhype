"""New fixed-endpoint LIT capture and frozen corrected IOC scenario replication."""
import asyncio,datetime,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_maker_lit_capture as capture
import scripts.replay_core_maker_lit as replay
from scripts.replay_core_maker_lit_ioc_coordinator import CoordinatedIocBranch
PLAN=ROOT/'reports/experiment-storage/core-maker-lit-retry-v1.json'
OUT=ROOT/'reports/core-maker-lit-retry'

def configure():
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert capture.sha(ROOT/pin['path'])==pin['sha256']
 capture.PLAN=PLAN;capture.OUT=OUT/'capture'
 replay.PLAN=PLAN;replay.OUT=capture.OUT;replay.RESULT=OUT/'result'
 replay.RetirementGuardPassiveExitBranch=CoordinatedIocBranch
 return p

if __name__=='__main__':
 configure()
 if sys.argv[1:]==['capture']:
  asyncio.run(capture.main())
 elif len(sys.argv)==3 and sys.argv[1]=='replay':
  manifest=json.loads((capture.OUT/'manifest.json').read_bytes())
  assert capture.sha(capture.OUT/'manifest.json')==sys.argv[2]
  CoordinatedIocBranch.capture_start_ns=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
  replay.run(sys.argv[2])
 else:raise SystemExit('Use capture or replay <sealed-manifest-sha256>')
