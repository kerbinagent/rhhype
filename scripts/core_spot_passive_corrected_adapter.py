"""Schema-only repair; preserve failed v1 replay and every original frozen source."""
import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_events_v2 import iter_events
from scripts.core_spot_passive_capture import sha
AMEND=ROOT/'reports/experiment-storage/core-spot-passive-adapter-repair-v1.json'
def main():
 p=json.loads(AMEND.read_bytes())
 for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 assert sha(ROOT/p['manifest_path'])==p['manifest_sha256']
 action=sys.argv[1]
 if action=='replay':
  import scripts.replay_core_spot_passive as mod
 elif action=='audit':
  import scripts.audit_core_spot_passive as mod
 elif action=='boundaries':
  import scripts.audit_core_spot_passive_boundaries as mod
 else:raise ValueError(action)
 mod.iter_events=iter_events;mod.R=ROOT/'reports/core-spot-passive/corrected-result'
 if action=='replay':mod.run(p['manifest_sha256'])
 else:mod.run()
if __name__=='__main__':main()
