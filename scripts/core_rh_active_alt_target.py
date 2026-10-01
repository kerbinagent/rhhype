"""Prospective PONS/CASHCAT repetition of the frozen confirmed-target comparison."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import core_rh_target_margin as study
PLAN=ROOT/'reports/experiment-storage/core-rh-active-alt-target-allocation-v1.json'
original_normalise=study.normalise
def normalise(data,venue,now):
 rows=[r for r in data['order_book_details'] if r['symbol'] in ('PONS','CASHCAT')];assert len(rows)==2
 for r in rows:
  assert not r.get('is_frozen',False) and not r.get('market_config',{}).get('force_reduce_only',False)
  assert float(r['index_price'])>0 and float(r['mark_price'])>0
 return original_normalise(data,venue,now)
async def main():
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert study.sha(ROOT/pin['path'])==pin['sha256']
 study.PLAN=PLAN;study.OUT=ROOT/'reports/core-rh-active-alt-target';study.ASSETS=['PONS','CASHCAT'];study.IDS={'lighter':{},'rh_lighter':{}};study.normalise=normalise
 await study.run()
if __name__=='__main__':asyncio.run(main())
