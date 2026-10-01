"""Compatibility repair for frozen offset policy; no outcome-dependent parameter change."""
import json,sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_hedged_maker_retirement import RetirementGuardPassiveExitBranch
from scripts.core_hedged_maker_base import NS
import scripts.replay_core_maker_lit as original
FIX=ROOT/'reports/experiment-storage/core-maker-lit-replay-compatibility-v1.json'
class OffsetControlBranch(RetirementGuardPassiveExitBranch):
 def __init__(self,config,metadata,*,exit_policy,audit_sink=None):
  if config.policy!='adaptive' or exit_policy!='control10s' or config.hold_ns!=10*NS:
   raise ValueError('Only frozen adaptive-offset entry with control10s exit is supported')
  # Parent constructor initializes passive-exit bookkeeping but only permits fixed_best.
  # It performs no market processing. Restore the intended adaptive config before any event.
  super().__init__(replace(config,policy='fixed_best'),metadata,exit_policy=exit_policy,audit_sink=audit_sink)
  self.cfg=config
if __name__=='__main__':
 fix=json.loads(FIX.read_bytes())
 for pin in fix['source_pins']:assert original.sha(ROOT/pin['path'])==pin['sha256']
 assert len(sys.argv)==2 and sys.argv[1]==fix['manifest_sha256']
 original.RetirementGuardPassiveExitBranch=OffsetControlBranch
 original.RESULT=ROOT/'reports/core-maker-lit-offset/result-corrected'
 original.run(sys.argv[1])
