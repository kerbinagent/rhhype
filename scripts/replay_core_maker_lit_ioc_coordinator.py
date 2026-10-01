"""Exploratory IOC scenario with quote selection/gates at actual post-event decision state."""
import datetime,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.replay_core_maker_lit as original
from scripts.core_maker_ioc_minimum_scenario import IocMinimumScenarioBranch
NS=10**9
PLAN=ROOT/'reports/experiment-storage/core-maker-lit-ioc-coordinator-v1.json'
class CoordinatedIocBranch(IocMinimumScenarioBranch):
 capture_start_ns=None
 def _on_diagnostic(self,ignored,now_ns):
  # process() has already advanced deadlines and applied the current book.
  # A quote can retire in those steps, so pre-process quote state is insufficient.
  if set(self.books)!={'maker','hedge'}:return super()._on_diagnostic({'reason':'missing_book'},now_ns)
  maker={'bids':self.books['maker'].bids};hedge={'bids':self.books['hedge'].bids}
  if not maker['bids'] or not hedge['bids']:return super()._on_diagnostic({'reason':'missing_depth'},now_ns)
  diag=original.quote_diagnostic(self,maker,hedge)
  if self.quote is None:
   assert self.capture_start_ns is not None
   if not 10*NS<=now_ns-self.capture_start_ns<480*NS:diag['reason']='outside_admission_window'
   elif self.episode_no>=100:diag['reason']='attempt_cap'
   elif now_ns//(3600*NS)!=(now_ns+120*NS)//(3600*NS):diag['reason']='funding_boundary_guard'
  return super()._on_diagnostic(diag,now_ns)
if __name__=='__main__':
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert original.sha(ROOT/pin['path'])==pin['sha256']
 assert len(sys.argv)==2 and sys.argv[1]==p['manifest_sha256']
 manifest=json.loads((ROOT/'reports/core-maker-lit-offset/capture/manifest.json').read_bytes())
 CoordinatedIocBranch.capture_start_ns=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
 original.RetirementGuardPassiveExitBranch=CoordinatedIocBranch
 original.RESULT=ROOT/'reports/core-maker-lit-ioc-coordinator'
 original.run(sys.argv[1])
 (original.RESULT/'scenario.json').write_text(json.dumps({'exploratory':True,'prospective_validation':False,'deployed_API_acceptance_verified':False,'plan_sha256':original.sha(PLAN),'difference':'IOC minimum exemption plus actual-state quote planner/cutoff repair; all economic parameters unchanged.'},indent=2)+'\n')
