"""Prospective reference count comparison; synchronous signal hook only."""
import asyncio,statistics
from pathlib import Path
import core_spot_perp_limits as base
ROOT=Path(__file__).resolve().parents[1]
OriginalBranch=base.Branch
original_reference=base.basis_reference

def reference(history,now,minimum):
 prior=[(t,v) for t,v in history if now-122<=t<=now-2]
 if len(prior)<minimum or prior[-1][0]-prior[0][0]<89:return None
 return statistics.median(v for _,v in prior)

class ReferenceBranch(OriginalBranch):
 def __init__(self,*args,minimum=90,**kwargs):
  super().__init__(*args,**kwargs);assert minimum in (60,90);self.minimum=minimum
  assert self.config.entry_slippage_bps==1
  self.label=f'{self.config.notional}-{self.config.holding_seconds}-ref{minimum}-1bp'
 def _signal(self,*args,**kwargs):
  # Base engine invokes this synchronously, without await or worker threads.
  # Restore even on an exception, so every independent branch keeps its rule.
  saved=base.basis_reference
  try:
   base.basis_reference=lambda history,now:reference(history,now,self.minimum)
   return super()._signal(*args,**kwargs)
  finally:base.basis_reference=saved

def main():
 base.PLAN=ROOT/'reports/experiment-storage/spot-perp-reference-count-v1.json'
 base.OUT=ROOT/'reports/core-spot-perp-reference-count'
 base.ASSETS=['SKY','UNI','AAVE','LINK','LDO']
 counts=iter((90,60))
 def factory(*args,**kwargs):return ReferenceBranch(*args,minimum=next(counts),**kwargs)
 base.Branch=factory
 asyncio.run(base.run())
if __name__=='__main__':main()
