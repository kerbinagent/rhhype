"""Exploratory replay of sealed LIT capture under published IOC minimum rule."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.replay_core_maker_lit as original
from scripts.core_maker_ioc_minimum_scenario import IocMinimumScenarioBranch
PLAN=ROOT/'reports/experiment-storage/core-maker-lit-ioc-scenario-v1.json'
if __name__=='__main__':
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert original.sha(ROOT/pin['path'])==pin['sha256']
 assert len(sys.argv)==2 and sys.argv[1]==p['manifest_sha256']
 original.RetirementGuardPassiveExitBranch=IocMinimumScenarioBranch
 original.RESULT=ROOT/'reports/core-maker-lit-ioc-scenario'
 original.run(sys.argv[1])
 (original.RESULT/'scenario.json').write_text(json.dumps({'exploratory':True,'prospective_validation':False,'deployed_API_acceptance_verified':False,'plan_sha256':original.sha(PLAN),'difference':'Only IOC minimum base/quote checks exempted; maker resting minima, all latency, queue/unknown and cash rules retained.'},indent=2)+'\n')
