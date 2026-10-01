"""Compare saved take-profit request marks with eventual cash, including delay."""
import gzip,hashlib,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=[]
for name in ('core-rh-persistent-entry','core-rh-equity-open'):
 path=ROOT/'reports'/name/'events.jsonl.gz';raw=path.read_bytes()
 for row in (json.loads(x) for x in gzip.decompress(raw).splitlines()):
  if row['kind']!='terminal_position':continue
  p=row['data']
  if p.get('exit_reason')!='take_profit':continue
  assert all(l['quantity']>0 for l in p['legs']) and p['funding_usd']==p['other_costs_usd']==0
  when=D(str(p['exit_requested_at']));capital=D(0);cash=D(0)
  for l in p['legs']:
   assert int(when//3600)==int(D(str(l['entry_time']))//3600)
   assert not l['remaining']
   capital+=D(str(l['entry_value']))*(when-D(str(l['entry_time'])))*D('.05')/D(365*86400)
   cash+=(D(str(l['exit_value']))-D(str(l['entry_value'])))*(1 if l['side']=='long' else -1)-D(str(l['fees_usd']))
  mark=D(str(p['exit_trigger_pnl_usd']))+capital
  out.append({'study':name,'branch':row['branch'],'id':p['id'],'asset':p['asset'],'cash_mark_at_exit_request':str(mark),'actual_cash':str(cash),'exit_execution_change':str(cash-mark),'request_to_flat_seconds':p['closed_at']-p['exit_requested_at'],'raw_sha256':hashlib.sha256(raw).hexdigest()})
result={'scope':'Retrospective diagnostic using recorded request mark, adding back modeled capital. This does not independently reconstruct mark depth because full idle books are not retained. Actual fills independently audited separately. Delay change includes market movement and bid/ask costs between request and fill. Max-hold exits excluded because no trigger mark stored.','trades':out}
path=ROOT/'reports/paired-forecast-decomposition/exit-decomposition.json'
with path.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(out,indent=2))
