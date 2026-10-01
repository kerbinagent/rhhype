"""Prospective exit-target-only comparison with unchanged immediate entries."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import core_rh_persistent_entry as study
from core_rh_active_alt_confirmation import normalise
PLAN=ROOT/'reports/experiment-storage/core-rh-exit-target-allocation-v1.json'
class ExitTargetBranch(study.Branch):
 def __init__(self,pairs,budget,horizon,shared,target_bps):
  assert target_bps in (1,6)
  super().__init__(pairs,budget,horizon,shared,0)
  self.config.take_profit_usd=budget*target_bps/10000
  self.target_bps=target_bps;self.label=f'{budget}-{horizon}-exit{target_bps}bp'
async def main():
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert study.sha(ROOT/pin['path'])==pin['sha256']
 assert p['confirmation_seconds']==[0,0] and p['exit_targets_bps']==[1,6]
 targets=iter(p['exit_targets_bps'])
 def branch(pairs,budget,horizon,shared,confirm):
  assert confirm==0
  return ExitTargetBranch(pairs,budget,horizon,shared,next(targets))
 study.Branch=branch;study.PLAN=PLAN;study.OUT=ROOT/'reports/core-rh-exit-target'
 study.ASSETS=['PONS','CASHCAT'];study.IDS={'lighter':{},'rh_lighter':{}};study.normalise=normalise
 await study.run()
if __name__=='__main__':asyncio.run(main())
