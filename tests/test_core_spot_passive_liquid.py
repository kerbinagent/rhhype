"""Read-only native selection fixture; launch still fetches new metadata."""
import json,sys,tempfile
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_liquid import configure,SELECTED
import scripts.core_spot_passive_capture as cap
from scripts.core_spot_passive_branch import SpotPassiveBranch
from scripts.core_passive_hedged_base import Config

def test_native_liquid_selection_and_same_cash_branch():
 configure()
 with tempfile.TemporaryDirectory(prefix='spot-liquid-selection-') as td:
  td=Path(td);src=ROOT/'reports/core-spot-passive/capture/metadata'
  for name in cap.REQUESTS:
   for suffix in ('.json.gz','.request.json'):(td/(name+suffix)).write_bytes((src/(name+suffix)).read_bytes())
  (td/'market_plan.json').write_text(json.dumps({'selected':SELECTED}))
  md=cap.verify_metadata(td,SELECTED,cap.sha(td/'market_plan.json'))
  assert set(md['markets']['maker'])=={'LIT','ETH'}
  for asset in ('LIT','ETH'):
   b=SpotPassiveBranch(Config(asset,D(100),'fixed_best'),md['markets'],exit_policy='control10s')
   assert b.cash_state()['actual_cash_usdc']=='600'
if __name__=='__main__':test_native_liquid_selection_and_same_cash_branch();print('PASS')
