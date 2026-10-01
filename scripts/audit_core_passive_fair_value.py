"""Reuse frozen raw fill auditor; independently reconstruct every forecast formula."""
import gzip,json,sys
from decimal import Decimal as D,ROUND_FLOOR
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import audit_core_passive_lit_fills as fills
from scripts.core_passive_lit_capture import sha
R=ROOT/'reports/core-passive-fair-value'
def run():
 fills.R=R;fills.run()
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()))
 a=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 quotes=[r for r in a if r['event']=='quote_requested'];forecasts=[r for r in a if r['event']=='fair_value_admission'];assert len(quotes)==len(forecasts)
 for q,f in zip(quotes,forecasts):
  assert q['ns']==f['ns'] and q['price']==f['price'] and q['qty']==f['quantity']
  refs=f['reference_rows'];now=q['ns'];assert len(refs)==f['reference_count']>=90
  assert refs[-1][0]-refs[0][0]>=89*10**9 and refs[0][0]>=now-120*10**9 and refs[-1][0]<=now-2*10**9
  assert all(b[0]-a[0]>=10**9 for a,b in zip(refs,refs[1:]));assert D(median([D(v) for _,v in refs]))==D(f['median_close_bps'])
  qty=D(q['qty']);price=D(q['price']);hv=D(f['hedge_entry_value']);close=D(f['median_close_bps'])*D(f['maker_mid'])/10000
  forecast=hv-qty*price+qty*(close-D(f['fee_unit'])-D(f['capital_unit']))
  assert abs(forecast-D(f['forecast_cash']))<D('1e-20')
  assert forecast>=max(hv,qty*price)*D('.0006')
  assert q['due_ns']-q['ns']==100_000_000
 result={'audit':'passed','forecasts_checked':len(forecasts),'summary_sha256':sha(R/'summary.json.gz'),'checks':'Saved reference timing, cadence, count/span, median, quote identity, forecast cash arithmetic,6bp threshold and100ms activation; separate frozen fill auditor reads original full raw books.','limitation':'This formula audit does not independently rebuild reference values or all model-driven cancellation decisions from raw depth; must add that check before using positive results to justify prospective testing.'}
 (R/'forecast-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':run()
