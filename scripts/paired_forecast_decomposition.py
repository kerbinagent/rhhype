"""Retrospective algebraic diagnosis of sealed, fully paired paper trades."""
import gzip,hashlib,json
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/paired-forecast-decomposition'
OUT.mkdir(exist_ok=False)
out={'scope':'Retrospective paired-only decomposition. Forecast is a model expectation, not promised profit. Separate independent branches; do not sum overlapping arms. No active-run outcomes.','studies':{}}
for study in ('core-rh-persistent-entry','core-rh-equity-open'):
 path=ROOT/'reports'/study/'events.jsonl.gz';raw=path.read_bytes()
 records=[json.loads(x) for x in gzip.decompress(raw).splitlines()]
 result=[];skipped=[]
 for row in records:
  if row['kind']!='terminal_position':continue
  p=row['data'];legs=p['legs']
  if not all(l['quantity']>0 for l in legs):skipped.append(p['id']);continue
  assert p['status']=='CLOSED' and not any(l['remaining'] for l in legs)
  buy=next(l for l in legs if l['side']=='long');sell=next(l for l in legs if l['side']=='short')
  assert buy['quantity']==sell['quantity']==p['signal']['quantity']
  dec=lambda x:D(str(x))
  signal=p['signal'];forecast=dec(signal['forecast_gross'])
  signal_entry=dec(signal['sell_value'])-dec(signal['buy_value'])
  actual_entry=dec(sell['entry_value'])-dec(buy['entry_value'])
  actual_exit=dec(buy['exit_value'])-dec(sell['exit_value'])
  forecast_exit=forecast-signal_entry
  entry_change=actual_entry-signal_entry;exit_miss=actual_exit-forecast_exit
  gross=actual_entry+actual_exit
  assert abs(gross-dec(p['price_pnl']))<D('1e-8')
  assert abs(forecast+entry_change+exit_miss-gross)<D('1e-20')
  cash=gross-sum((dec(l['fees_usd']) for l in legs),D(0))
  result.append({'id':p['id'],'branch':row['branch'],'asset':p['asset'],'forecast_gross':str(forecast),'entry_price_change':str(entry_change),'exit_forecast_miss':str(exit_miss),'actual_gross':str(gross),'cash':str(cash),'exit_reason':p['exit_reason'],'holding_seconds_after_paired_entry':p['closed_at']-p['opened_at']})
 totals={}
 for label in sorted({r['branch'] for r in result}):
  selected=[r for r in result if r['branch']==label]
  totals[label]={'paired_count':len(selected),**{k:str(sum((D(r[k]) for r in selected),D(0))) for k in ('forecast_gross','entry_price_change','exit_forecast_miss','actual_gross','cash')}}
 out['studies'][study]={'raw_sha256':hashlib.sha256(raw).hexdigest(),'excluded_rescue_ids':skipped,'paired_trades':result,'paired_branch_totals':totals}
data=(json.dumps(out,indent=2)+'\n').encode();assert len(data)<16384
(OUT/'decomposition.json').write_bytes(data)
print(json.dumps({k:v['paired_branch_totals'] for k,v in out['studies'].items()},indent=2))
