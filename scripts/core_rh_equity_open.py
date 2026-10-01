"""Frozen four-equity opening-session replication of the persistent-entry comparison."""
import asyncio,datetime,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import core_rh_persistent_entry as study
PLAN=ROOT/'reports/experiment-storage/core-rh-equity-open-allocation-v1.json'
ASSETS=['AAPL','AMZN','NVDA','TSLA']
original_normalise=study.normalise
def normalise(data,venue,now):
 rows={r['symbol']:r for r in data['order_book_details']}
 for a in ASSETS:
  r=rows[a];assert not r.get('is_frozen',False) and not r['market_config']['force_reduce_only']
  assert float(r['index_price'])>0 and float(r['mark_price'])>0
 return original_normalise(data,venue,now)
async def main():
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert study.sha(ROOT/pin['path'])==pin['sha256']
 target=datetime.datetime.fromisoformat(plan['not_before_utc']).timestamp()
 while time.time()<target:await asyncio.sleep(min(1,target-time.time()))
 assert time.time()-target<=60,'opening_session_start_missed'
 study.PLAN=PLAN;study.OUT=ROOT/'reports/core-rh-equity-open';study.ASSETS=ASSETS;study.IDS={'lighter':{},'rh_lighter':{}};study.normalise=normalise
 await study.run()
if __name__=='__main__':asyncio.run(main())
