"""Independent Decimal/hash/coverage/lag audit of the frozen all-market rate screen."""
import datetime,gzip,hashlib,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports/core-rh-all-market-funding'
sha=lambda b:hashlib.sha256(b).hexdigest()
s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));p=ROOT/'reports/experiment-storage/core-rh-all-market-funding-v1.json';plan=json.loads(p.read_bytes())
assert sha(p.read_bytes())==s['plan_sha256'] and sha((ROOT/'scripts/core_rh_all_market_funding.py').read_bytes())==s['source_sha256']
requests=json.loads(gzip.decompress((R/'requests.json.gz').read_bytes()));assert sha((R/'requests.json.gz').read_bytes())==s['request_archive_sha256']
assert len(requests)==s['request_count']<=128
selected={}
for pin in plan['metadata']:
 raw=(ROOT/pin['path']).read_bytes();assert sha(raw)==pin['sha256']
 selected[pin['venue']]={r['symbol']:str(r['market_id']) for r in json.loads(gzip.decompress(raw))['order_book_details'] if r['market_type']=='perp' and r['status']=='active' and D(str(r['multiplier']))==D(str(r['quote_multiplier']))==1 and not r.get('is_frozen',False) and not r.get('market_config',{}).get('force_reduce_only',False)}
assets=sorted(set(selected['lighter'])&set(selected['rh_lighter']));assert assets==s['assets']
start=int(datetime.datetime.fromisoformat(plan['start_utc']).timestamp());end=int(datetime.datetime.fromisoformat(plan['end_utc']).timestamp());expected=set(range(start+3600,end+1,3600))
all_rates={};bytes_=0
for req in requests:
 assert req['asset'] in assets and req['params']['market_id']==selected[req['venue']][req['asset']]
 assert req['params']['resolution']=='1h' and req['params']['start_timestamp']==start and req['params']['end_timestamp']==end+3599 and req['params']['count_back']==25
 assert req['url']=={'lighter':'https://mainnet.zklighter.elliot.ai/api/v1/fundings','rh_lighter':'https://api.rh.lighter.xyz/api/v1/fundings'}[req['venue']]
 raw=gzip.decompress((R/req['file']).read_bytes());bytes_+=len(raw)
 assert sha((R/req['file']).read_bytes())==req['compressed_sha256'] and sha(raw)==req['raw_sha256'] and len(raw)==req['raw_bytes']
 assert req['status']==200 and 'error' not in req
 rates={}
 for e in json.loads(raw)['fundings']:
  t=int(e['timestamp']);bucket=t//3600*3600
  if bucket not in expected:continue
  assert bucket not in rates and 0<=t-bucket<=1 and e['direction'] in ('long','short')
  rate=D(e['rate']);assert rate.is_finite() and rate>=0
  rates[bucket]=rate*100*(1 if e['direction']=='long' else -1)
 assert set(rates)==expected
 key=req['venue'],req['asset'];assert key not in all_rates;all_rates[key]=rates
assert bytes_==s['wire_bytes']
above5=above6=lags=0;lag_credit=D(0);largest=[]
for result in s['results']:
 asset=result['asset'];assert result['status']=='complete'
 rebuilt=[]
 for t in sorted(expected):
  c=all_rates['lighter',asset][t];r=all_rates['rh_lighter',asset][t];rebuilt.append([t,str(c),str(r),str(r-c)])
 assert rebuilt==result['events'];gaps=[abs(D(r[3])) for r in rebuilt]
 assert D(result['max_abs_gap_bps'])==max(gaps)
 assert sum(g>5 for g in gaps)==result['hindsight_events_over_5bp'];assert sum(g>=6 for g in gaps)==result['hindsight_events_at_least_6bp']
 past=[(a,b) for a,b in zip(rebuilt,rebuilt[1:]) if abs(D(a[3]))>=6]
 assert len(past)==len(result['lagged_6bp_entries'])
 for (a,b),f in zip(past,result['lagged_6bp_entries']):
  value=D(b[3])*(1 if D(a[3])>0 else -1)
  assert f['event']==b[0] and D(f['previous_gap_bps'])==D(a[3]) and D(f['selected_next_credit_bps'])==value and D(f['less_5bp_stress_bps'])==value-5
  lag_credit+=value;lags+=1
 above5+=sum(g>5 for g in gaps);above6+=sum(g>=6 for g in gaps);largest.append({'asset':asset,'max_gap_bps':str(max(gaps))})
out={'audit':'passed','assets':len(assets),'joined_hourly_events':len(assets)*24,'raw_requests':len(requests),'events_over_5bp':above5,'events_at_least_6bp':above6,'lagged_entries':lags,'lagged_credit_bps':str(lag_credit),'lagged_less_5bp_per_entry':str(lag_credit-5*lags),'summary_sha256':sha((R/'summary.json.gz').read_bytes()),'checks':'Rebuilt entire matching active unit-perp universe, exact requests/raw hashes, 24 timestamps and payer signs per venue, all rate gaps, hindsight thresholds and previous-hour-only selection. Rates are not actual PnL; no quote/ownership/collateral/settlement-reference equivalence assertion.'}
with (R/'audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
print(json.dumps(out,indent=2))
