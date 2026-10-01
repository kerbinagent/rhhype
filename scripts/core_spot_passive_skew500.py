"""Prospective one-tick-inside LIT spot bid with same-market perp short hedge."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_spot_passive_capture as capture
import scripts.core_spot_passive_events_v2 as events
PLAN=ROOT/'reports/experiment-storage/core-spot-passive-skew500-v1.json'
OUT=ROOT/'reports/core-spot-passive-skew500/capture'
R=ROOT/'reports/core-spot-passive-skew500/result'
ASSETS=['LIT']
SELECTED={'lighter':{'LIT_spot':'2049','LIT_perp':'120'}}
HARD_BYTES=3407872

def configure():
 capture.PLAN=PLAN;capture.OUT=OUT;capture.ASSETS=ASSETS;capture.SELECTED=SELECTED;capture.HARD_BYTES=HARD_BYTES
 events.HARD_BYTES=HARD_BYTES

def main():
 configure();plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert capture.sha(ROOT/pin['path'])==pin['sha256']
 action=sys.argv[1]
 if action=='capture':asyncio.run(capture.main());return
 if action=='replay':
  import scripts.replay_core_spot_passive_skew500 as mod
  from scripts.core_spot_passive_hysteresis_branch import CashRetentionSpotBranch
  mod.SpotPassiveBranch=CashRetentionSpotBranch
  mod.ASSETS=ASSETS;mod.SELECTED=SELECTED
 elif action=='audit':
  import scripts.audit_core_spot_passive_skew500 as mod
 elif action=='boundaries':
  import scripts.audit_core_spot_passive_boundaries as mod
 else:raise ValueError(action)
 mod.PLAN=PLAN;mod.OUT=OUT;mod.R=R;mod.HARD_BYTES=HARD_BYTES;mod.iter_events=events.iter_events
 if action=='replay':mod.run(sys.argv[2])
 else:mod.run()
if __name__=='__main__':main()
