"""Prospective one-tick-inside ETH spot bid with same-market perp short hedge."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_spot_passive_capture as capture
import scripts.core_spot_passive_events_v2 as events
PLAN=ROOT/'reports/experiment-storage/core-spot-passive-eth-cash-v1.json'
OUT=ROOT/'reports/core-spot-passive-eth-cash/capture'
R=ROOT/'reports/core-spot-passive-eth-cash/result'
ASSETS=['ETH']
SELECTED={'lighter':{'ETH_spot':'2048','ETH_perp':'0'}}
HARD_BYTES=4456448

def configure():
 capture.PLAN=PLAN;capture.OUT=OUT;capture.ASSETS=ASSETS;capture.SELECTED=SELECTED;capture.HARD_BYTES=HARD_BYTES
 events.HARD_BYTES=HARD_BYTES

def main():
 configure();plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert capture.sha(ROOT/pin['path'])==pin['sha256']
 action=sys.argv[1]
 if action=='capture':asyncio.run(capture.main());return
 if action=='replay':
  import scripts.replay_core_spot_passive_eth_cash as mod
  from scripts.core_spot_passive_cashentry_branch import CashEntrySpotBranch
  mod.SpotPassiveBranch=CashEntrySpotBranch
  mod.ASSETS=ASSETS;mod.SELECTED=SELECTED
 elif action=='audit':
  import scripts.audit_core_spot_passive_cashentry as mod
  from scripts.audit_core_spot_passive_cashentry_v2 import mutable_walk
  mod.walk=mutable_walk
 elif action=='boundaries':
  import scripts.audit_core_spot_passive_boundaries as mod
 else:raise ValueError(action)
 mod.PLAN=PLAN;mod.OUT=OUT;mod.R=R;mod.HARD_BYTES=HARD_BYTES;mod.iter_events=events.iter_events
 if action=='replay':mod.run(sys.argv[2])
 else:mod.run()
if __name__=='__main__':main()
