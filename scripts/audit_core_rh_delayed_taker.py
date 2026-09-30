#!/usr/bin/env python3
"""Independent completed-derived-only audit; no raw opens or engine imports."""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction as F
import gzip
import hashlib
import io
import json
import math
from importlib.metadata import version
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NS = 10**9
VENUES = ('rh_lighter', 'lighter')
SCHEMA = 'core-rh-delayed-taker-quote-diagnostic-v1'
CAP = 600000
ARCHIVES = {
 '1939Z': (1790710744105998000, ('BTC','ETH'), 64081, 23644715,
  '5f6ade0523703efe0ecd40c17ead0782eccc3bf7f780ae17364d8c26fc56567d'),
 '2022Z': (1790713376780854000, ('NVDA','XAG'), 10619, 3755149,
  '3a1ffe9e3578899df800bf8fceec7beda8fc82b136a6c00edc64a20a8316f775')}
# Historical values are independently transcribed from the frozen method.
RULES = {
 'BTC': ('.00001','.00001','.0002','.00007',None,None,None),
 'ETH': ('.0001','.0001','.005','.002',None,None,None),
 'NVDA': ('.0001','.001','.04','.025','.01','.001','25000000'),
 'XAG': ('.01','.01','.15','.08','.0001','.0001','5000000')}
CHECKS = {'price_grid','quantity_grid','minimum_quantity','minimum_notional','maximum_quote','maximum_base'}
ECON = ('gross','entry_long_fee','entry_short_fee','exit_long_fee','exit_short_fee',
        'fee_only_net','stress','capital','adjusted_quote_net_ex_funding')
NOTIONALS = ('entry_long_buy','entry_short_sell','exit_long_sell','exit_short_buy')
PINS = {
 'scripts/maker_book_archive.py':'8c9b86a8024298b78f6a6890cb2ad97a267dacd357ee992432a52f9a9c756dd2',
 'scripts/paper_streams.py':'c601270e365cc11ce04124095650a4bc79ceaffa8d4792bdd83cf7d9382a3734',
 'scripts/maker_capture.py':'a4930f7a672ca668e9286eb2d270bc246cf7d672c44415b1a33d54532e0fd9b9',
 'scripts/analyze_maker_equity.py':'85d4de8cfd523b4a4497e3e2f6411b05f3737f2133d4c167ddce708af363843f',
 'scripts/analyze_maker_capture.py':'d87ce8f116e039976b7afac20ede5704d14b3d49eb626473d214a7d47811b359',
 'scripts/analyze_maker_roundtrip.py':'d7d23b255fcffc294069a77486cc944a9a64a32d6755cc515a960d1ae03a9c93',
 'data/raw/maker-capture/20260929T1939Z/manifest.json':'163f2ea666025b5661becb51fbe27a5050df3e8564d37aa2159143db87e5e351',
 'data/raw/maker-capture/20260929T2022Z/manifest.json':'a3f83c319f5e71938ffa9ae6ec170eb48b3024123147e554ee4c20296cade898',
 'reports/maker-roundtrip-v1/market-plan.json':'e4f059ae0fc9b3957779b42c5b35a04aa42fc220f2a74fb76a68d3669f06e2fe',
 'reports/maker-roundtrip-v1/market-plan-provenance.json':'62bfe2f5139782ed9b83c84b94c985e36859ef293575abfa04f0d5d4b599157b',
 'reports/maker-roundtrip-v1/frozen-method-manifest.json':'2dc9709c5fae1af2c8fad650102fc8c2e3212bc8240ef2c0261c616fc5fecd00',
 'reports/maker-equity-v2/market-plan.json':'8764b8c656ab1ebf6772eedfb22ab541eef28b81c9fa116056fea67366e5c93f',
 'reports/maker-equity-v2/unit-provenance.json':'dd2fd61f18e7ae6558ec6dd4f7fa0e618e71da3eaa8610635a69971879470094',
 'reports/maker-equity-v2/frozen-manifest.json':'fcffad0124a2679afd2e2e73c6aa28390ebe3b46ddbeccb69b1fd17f284da3f0'}
NEW = ('scripts/analyze_core_rh_delayed_taker.py','tests/test_analyze_core_rh_delayed_taker.py',
 'research/core-rh-delayed-taker-quote-plan.md','scripts/audit_core_rh_delayed_taker.py',
 'tests/test_audit_core_rh_delayed_taker.py')

def require(ok, label):
 if not ok: raise ValueError(label)

def number(value):
 """Bound representation before Decimal/Fraction allocation, including rational capital."""
 require(not isinstance(value,bool) and value is not None,'numeric_type')
 text=str(value);require(len(text)<=160,'numeric_token_cap')
 if '/' in text:
  parts=text.split('/');require(len(parts)==2,'rational_shape')
  require(all(p.lstrip('-').isdigit() and len(p.lstrip('-'))<=64 for p in parts),'rational_digit_cap')
  require(int(parts[1])>0,'rational_denominator');q=F(int(parts[0]),int(parts[1]))
 else:
  x=Decimal(text)
  require(x.is_finite() and len(x.as_tuple().digits)<=64 and abs(x.as_tuple().exponent)<=40 and abs(x.adjusted())<=40,'decimal_bound')
  q=F(x)
 require(abs(q)<=10**60,'numeric_magnitude_cap');return q

def integer(value):
 require(type(value) is int and len(str(abs(value)))<=32,'integer_shape');return value

def eq(value, expected, label):
 require(number(value)==expected,label)

def digest(raw): return hashlib.sha256(raw).hexdigest()

def bounded(path, limit):
 require(path.is_file() and not path.is_symlink() and path.stat().st_size<=limit,'bounded_regular_file')
 return path.read_bytes()

def decoded(raw, limit):
 with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream: result=stream.read(limit+1)
 require(len(result)<=limit,'decoded_cap');return result

def load_json(raw):
 def bad(x): raise ValueError('nonfinite_json')
 return json.loads(raw, parse_constant=bad)

def verify_inputs(hashes):
 hashes={str(Path(p).relative_to(ROOT)):h for p,h in hashes.items()}
 require(set(hashes)==set(PINS)|set(NEW),'exact_actual_input_inventory')
 require(all(hashes[name]==value for name,value in PINS.items()),'historical_source_and_metadata_pins')
 for name,value in hashes.items():
  require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value),'sha_shape')
  require(digest(bounded(ROOT/name,1_000_000))==value,'actual_input_hash:'+name)
 return {name:hashes[name] for name in NEW}

def owned_inventory():
 result={}
 for name,spec in ARCHIVES.items():
  files=list((ROOT/f'data/raw/maker-capture/20260929T{name}').iterdir())
  require(len(files)<=16 and all(p.is_file() and not p.is_symlink() for p in files),'owned_archive_paths')
  sizes={p.name:p.stat().st_size for p in files}
  require(sum(sizes.values())<=25000000 and sizes.get('frames.jsonl.gz')==spec[3],'owned_archive_stat_cap')
  result[name]=sizes
 return result

def expected_grid():
 for name,(start,assets,*_) in ARCHIVES.items():
  for offset in range(0,420,5):
   for asset in assets:
    for budget in (100,250,500,1000):
     if budget!=1000 and offset%30:continue
     for long in VENUES:
      yield dict(id=f'{name}:{asset}:{long}:{budget}:{offset}',archive=name,
        asset=asset,long_venue=long,budget=budget,anchor_ns=start+offset*NS,stratum=offset//105)

def refs(row, stage, at, baseline=None, due=None):
 pair=row[stage+'_refs'];require(set(pair)==set(VENUES),'paired_reference_keys')
 for venue,r in pair.items():
  require(set(r)=={'source_ns','receipt_ns','generation','sequence'},'reference_fields')
  source,receipt=integer(r['source_ns']),integer(r['receipt_ns'])
  require(0<source<=receipt<=at and at-source<=2*NS and at-receipt<=2*NS,'causal_fresh_references')
  require(isinstance(r['generation'],str) and 0<len(r['generation'])<=128,'generation_shape')
  require(integer(r['sequence'])>=0,'nonnegative_sequence')
  if baseline:
   require(r['generation']==baseline[venue]['generation'],'generation_changed')
   require(all(r[k]>=due and r[k]>baseline[venue][k] for k in ('source_ns','receipt_ns')),'reference_advance_or_due')
 for clock in ('source_ns','receipt_ns'):
  require(abs(pair[VENUES[0]][clock]-pair[VENUES[1]][clock])<=NS,'paired_clock_skew')
 if stage!='anchor':require(at==max(r['receipt_ns'] for r in pair.values()),'selected_pair_receipt')
 return pair

def expected_rule_values(asset, venue):
 values=RULES[asset];i=VENUES.index(venue)
 return dict(size_step=number(values[i]),min_qty=number(values[i+2]),min_notional=F(10),
  price_tick=None if values[i+4] is None else number(values[i+4]),
  max_quote=None if values[6] is None else number(values[6]),max_base=None,taker_fee_bps=F(0))

def rule_checks(row, stage, notionals=None, successful=False):
 checks=row.get(stage+'_rules',{});require(set(checks)<=set(VENUES),'rule_venue_keys')
 if successful:require(set(checks)==set(VENUES),'complete_rules')
 q=number(row['quantity']);any_fail=False
 for venue,check in checks.items():
  require(set(check)==CHECKS and set(check.values())<={'known_pass','known_fail','unknown'},'six_rule_statuses')
  values=expected_rule_values(row['asset'],venue)
  require(check['maximum_base']=='unknown','maximum_base_must_remain_unknown')
  if values['price_tick'] is None:require(check['price_grid']=='unknown','unknown_crypto_price_grid')
  else:require(check['price_grid'] in ('known_pass','known_fail'),'known_price_grid_flag')
  if values['max_quote'] is None:require(check['maximum_quote']=='unknown','unknown_crypto_max_quote')
  require(check['minimum_quantity']==('known_pass' if q>=values['min_qty'] else 'known_fail'),'minimum_quantity_rule')
  require(check['quantity_grid'] in ('known_pass','known_fail'),'known_quantity_grid_flag')
  if (q/values['size_step']).denominator!=1:require(check['quantity_grid']=='known_fail','quantity_grid_rule')
  if notionals is not None:
   v=notionals[venue]
   require(check['minimum_notional']==('known_pass' if v>=10 else 'known_fail'),'minimum_notional_rule')
   if values['max_quote'] is not None:
    require(check['maximum_quote']==('known_pass' if v<=values['max_quote'] else 'known_fail'),'maximum_quote_rule')
  any_fail|='known_fail' in check.values()
 if successful:require(not any_fail,'complete_has_known_rule_failure')
 return any_fail

def audit_rows(rows):
 grid=list(expected_grid());require(len(rows)==1008,'1008_rows')
 for row,identity in zip(rows,grid):
  require(all(row.get(k)==v and type(row.get(k)) is type(v) for k,v in identity.items()),'exact_ordered_grid')
  status=row.get('status');require(isinstance(status,str) and len(status)<=256,'terminal_status_shape')
  require(row.get('funding_unknown') is True and row.get('funding_inclusive_net') is None and row.get('legality_unknown') is True,'unknown_costs_and_legality')
  allowed={'conditional_quote_complete'}|{'anchor_'+s for s in ('missing_book','stale_source_or_receipt','cross_venue_skew','quantity','known_rule_violation','depth')}|{stage+'_'+s for stage in ('entry','exit') for s in ('missing','eof','known_rule_violation','depth')}
  require(status in allowed or status.startswith(('entry_gap:','exit_gap:')),'terminal_status')
  long=row['long_venue'];short=next(v for v in VENUES if v!=long)
  require(row.get('rule_spec_refs')=={v:f"{row['archive']}:{v}:{row['asset']}" for v in VENUES},'rule_spec_refs')
  if 'quantity' in row:
   step_values=[expected_rule_values(row['asset'],v)['size_step'] for v in VENUES]
   denominator=math.lcm(*(s.denominator for s in step_values))
   step=F(math.lcm(*(int(s*denominator) for s in step_values)),denominator)
   ask=number(row['anchor_long_best_ask']);require(ask>0,'positive_anchor_ask')
   eq(row['common_lot'],step,'common_lot')
   q=(F(row['budget'])/ask/step).__floor__()*step;eq(row['quantity'],q,'fixed_quantity_floor')
   require(q>=0,'nonnegative_quantity')
  if 'anchor_refs' in row:
   refs(row,'anchor',row['anchor_ns'])
  if 'anchor_long_buy' in row:
   a,b=number(row['anchor_long_buy']),number(row['anchor_short_sell'])
   require(a>0 and b>0,'positive_anchor_walks')
   require(row['anchor_notional_exceeds_budget'] is (a>row['budget']),'anchor_budget_drift')
   rule_checks(row,'anchor',{long:a,short:b},True)
  elif 'anchor_rules' in row:rule_checks(row,'anchor')
  if 'entry_refs' in row:
   at=integer(row['entry_selected_ns']);require(row['anchor_ns']+NS//2<=at<=min(row['anchor_ns']+2*NS,ARCHIVES[row['archive']][0]+420*NS),'entry_window')
   refs(row,'entry',at,row['anchor_refs'],row['anchor_ns']+NS//2)
  if 'entry_ns' in row:
   require(row['entry_ns']==row['entry_selected_ns'],'shared_entry_time')
   a,b=number(row['entry_long_buy']),number(row['entry_short_sell'])
   require(a>0 and b>0,'positive_entry_walks')
   require(row['entry_notional_exceeds_budget'] is (a>row['budget']),'entry_budget_drift')
   eq(row['entry_drift_from_anchor_walk'],a-number(row['anchor_long_buy']),'entry_drift')
   rule_checks(row,'entry',{long:a,short:b},True)
  elif 'entry_rules' in row:rule_checks(row,'entry')
  if 'exit_refs' in row:
   at=integer(row['exit_selected_ns']);entry=integer(row['entry_ns'])
   require(entry+10*NS+NS//2<=at<=min(entry+12*NS,ARCHIVES[row['archive']][0]+420*NS),'exit_window')
   refs(row,'exit',at,row['entry_refs'],entry+10*NS+NS//2)
  if status!='conditional_quote_complete':
   require(all(row.get(k) is None for k in ECON+('exit_long_sell','exit_short_buy','exit_ns')),'censored_economics_null')
   if 'exit_rules' in row:rule_checks(row,'exit')
   cutoff=ARCHIVES[row['archive']][0]+420*NS
   if status=='entry_eof':require(row['anchor_ns']+2*NS>cutoff,'entry_eof_window')
   if status=='exit_eof':require(row['entry_ns']+12*NS>cutoff,'exit_eof_window')
   if status=='entry_missing':require(row['anchor_ns']+2*NS<=cutoff,'entry_deadline_before_cutoff')
   if status=='exit_missing':require(row['entry_ns']+12*NS<=cutoff,'exit_deadline_before_cutoff')
   for stage in ('anchor','entry','exit'):
    if status==stage+'_known_rule_violation':require(rule_checks(row,stage),'known_rule_failure_flag')
   continue
  require(row['exit_ns']==row['exit_selected_ns'],'shared_exit_time')
  a,b,c,d=(number(row[k]) for k in NOTIONALS)
  require(all(v>0 for v in (a,b,c,d)),'positive_four_walks')
  rule_checks(row,'exit',{long:c,short:d},True)
  # Frozen public Standard taker fees are zero on both venues, but each
  # leg is checked individually instead of replacing four fee fields by one.
  fees=[v*expected_rule_values(row['asset'],venue)['taker_fee_bps']/10000
        for v,venue in zip((a,b,c,d),(long,short,long,short))]
  gross=b-a+c-d;fee_only=gross-sum(fees);stress=max(a,b)/2000
  elapsed=integer(row['exit_ns'])-integer(row['entry_ns'])
  capital=(a+b)*F(1,20)*F(elapsed,365*86400*NS)
  values=(gross,*fees,fee_only,stress,capital,fee_only-stress-capital)
  for key,value in zip(ECON,values):eq(row[key],value,'four_leg_identity:'+key)
  require(row['utc_hour_boundary_crossed'] is (row['entry_ns']//(3600*NS)!=row['exit_ns']//(3600*NS)),'utc_hour_cross')
  require(row['funding_boundary_tie'] is (row['entry_ns']%(3600*NS)==0 or row['exit_ns']%(3600*NS)==0),'funding_tie')
 return rows

def counts(rows):
 complete=[r for r in rows if r['status']=='conditional_quote_complete']
 values=sorted(number(r['adjusted_quote_net_ex_funding']) for r in complete);n=len(values)
 rule_counts=Counter()
 for row in rows:
  for stage in ('anchor','entry','exit'):
   for check in row.get(stage+'_rules',{}).values():rule_counts.update(check.values())
 middle=None if not n else values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2
 return dict(original_candidates=len(rows),conditional_quote_complete=n,statuses=dict(Counter(r['status'] for r in rows)),
  rule_check_status_counts=dict(rule_counts),known_rule_violation_candidates=sum(r['status'].endswith('_known_rule_violation') for r in rows),
  entry_pair_selected=sum('entry_selected_ns' in r for r in rows),entry_quote_complete=sum('entry_ns' in r for r in rows),
  exit_pair_selected=sum('exit_selected_ns' in r for r in rows),
  fee_only_positive=sum(number(r['fee_only_net'])>0 for r in complete),
  adjusted_positive=sum(v>0 for v in values),target_positive=sum(v>=F(1,10) for v in values),
  historical_legality_unknown=n,fully_verified_executable_count=0,
  adjusted_min=values[0] if n else None,adjusted_median=middle,adjusted_max=values[-1] if n else None)

def summary_expectation(rows):
 groups={};strata={}
 for row in rows:
  key=(row['asset'],row['long_venue'],row['budget']);groups.setdefault(key,[]).append(row)
  strata.setdefault(key+(row['stratum'],),[]).append(row)
 return dict(**counts(rows),primary_candidates=672,smaller_candidates=336,
  archive_denominators=dict(Counter(r['archive'] for r in rows)),
  stratum_denominators={str(k):sum(r['stratum']==k for r in rows) for k in range(4)},
  groups=[dict(key=list(k),**counts(v)) for k,v in sorted(groups.items())],
  stratum_groups=[dict(key=list(k),**counts(v)) for k,v in sorted(strata.items())])

def compare(actual,expected):
 if isinstance(expected,F):eq(actual,expected,'summary_exact_numeric')
 elif isinstance(expected,dict):
  require(isinstance(actual,dict) and set(expected)<=set(actual),'summary_keys')
  for key in ('statuses','rule_check_status_counts','archive_denominators','stratum_denominators'):
   if key in expected:require(actual[key]==expected[key],'exact_summary_counter_keys')
  for k,v in expected.items():compare(actual[k],v)
 elif isinstance(expected,list):
  require(isinstance(actual,list) and len(actual)==len(expected),'summary_group_denominator')
  for a,e in zip(actual,expected):compare(a,e)
 else:require(type(actual) is type(expected) and actual==expected,'summary_counts_or_identity')

def publication(path):
 path=Path(path);require(path.is_dir() and not path.is_symlink(),'publication_directory')
 require((path/'manifest.json').is_file(),'missing_completed_manifest')
 files={'manifest.json','freeze.json','sources.jsonl.gz','quotes.jsonl.gz','summary.json.gz'}
 require({p.name for p in path.iterdir()}==files,'publication_inventory')
 limits={'manifest.json':60000,'freeze.json':60000,'sources.jsonl.gz':190000,'quotes.jsonl.gz':250000,'summary.json.gz':30000}
 bodies={name:bounded(path/name,limits[name]) for name in files};before={n:digest(b) for n,b in bodies.items()}
 manifest=load_json(bodies['manifest.json']);freeze=load_json(bodies['freeze.json']);summary=load_json(decoded(bodies['summary.json.gz'],256*1024))
 require(manifest['schema']==freeze['schema']==summary['schema']==SCHEMA and manifest['status']==summary['status']=='complete_quote_diagnostic','completed_schema')
 require(manifest['classification']==freeze['classification']=='exploratory_post_capture' and freeze['prospective_freeze_claimed'] is False,'post_capture_classification')
 require(manifest['outputs']=={n:dict(bytes=len(b),sha256=before[n]) for n,b in bodies.items() if n!='manifest.json'},'published_output_hashes')
 external_path=Path(manifest['external_freeze_path'])
 require(external_path.parent.resolve()==(ROOT/'reports/core-rh-delayed-taker').resolve(),'external_freeze_location')
 external_body=bounded(external_path,30000);require(external_body==bodies['freeze.json'],'actual_external_freeze_copy')
 hashes=freeze['actual_dependency_and_small_input_sha256'];new=verify_inputs(hashes)
 require(freeze['source_inventory_count']==11 and freeze['clock_sync_performed'] is False,'freeze_scope')
 require(freeze['runtime']==dict(python=sys.version,aiohttp=version('aiohttp'),dont_write_bytecode=sys.dont_write_bytecode) and freeze['raw_reads']==0,'prepared_runtime_identity')
 captures=[dict(name=n,directory=str(ROOT/f'data/raw/maker-capture/20260929T{n}'),start=s[0],assets=list(s[1]),records=s[2],bytes=s[3],raw_sha=s[4]) for n,s in ARCHIVES.items()]
 require(freeze['captures']==captures,'frozen_capture_identity')
 owned=owned_inventory();require(freeze['owned_archive_inventory']==owned,'frozen_owned_archive_inventory')
 compare(freeze['grid'],dict(candidates=1008,primary=672,smaller=336,horizon_seconds=10,quote_delay_ms=500,hard_deadline_ms=2000,wall_seconds=900,total_new_physical_bytes_cap=CAP,reserved_external_bytes=40000,raw_reads=0,raw_traversals=0,network_calls=0))
 expected_raw={str(ROOT/f'data/raw/maker-capture/20260929T{name}/frames.jsonl.gz'):spec[4] for name,spec in ARCHIVES.items()}
 require(freeze['expected_raw_sha256']==expected_raw,'raw_digest_declarations')
 copies=[load_json(line) for line in decoded(bodies['sources.jsonl.gz'],200000).splitlines()]
 require(len(copies)==5 and {c['path'] for c in copies}=={str(ROOT/n) for n in NEW},'archived_source_inventory')
 for c in copies:
  name=str(Path(c['path']).relative_to(ROOT))
  require(c['sha256']==new[name]==digest(c['text'].encode()),'archived_source_hash')
 specs=freeze['rule_specs'];require(set(specs)=={f'{name}:{v}:{a}' for name,(_,assets,*_) in ARCHIVES.items() for v in VENUES for a in assets},'eight_rule_specs')
 for key,meta in specs.items():
  name,venue,asset=key.split(':');expected=expected_rule_values(asset,venue)
  market={'BTC':('1','1'),'ETH':('0','0'),'NVDA':('15','110'),'XAG':('41','93')}[asset][VENUES.index(venue)]
  require(meta['market']==market,'own_market_identity')
  for field,value in expected.items():
   field='max_qty' if field=='max_base' else field
   if value is None:require(meta[field] is None,'missing_rule_not_unlimited')
   else:eq(meta[field],value,'historical_rule_value')
  provenance=meta['provenance'];require(set(provenance)==CHECKS,'six_rule_provenance')
  fields=dict(price_grid='price_tick',quantity_grid='size_step',minimum_quantity='min_qty',minimum_notional='min_notional',maximum_quote='max_quote',maximum_base='max_qty')
  for rule,record in provenance.items():
   require(record['value']==meta[fields[rule]],'rule_value_provenance')
   if record['value'] is None:require(all(record[k] is None for k in ('source_path','source_sha256','field')),'unknown_rule_provenance')
   else:
    plan=ROOT/('reports/maker-roundtrip-v1/market-plan.json' if name=='1939Z' else 'reports/maker-equity-v2/market-plan.json')
    if rule in ('price_grid','maximum_quote'):
     source=ROOT/'reports/maker-equity-v2/unit-provenance.json';field=f'{venue}.selected_market_details[{asset}].'+('supported_price_decimals' if rule=='price_grid' else 'order_quote_limit')
    else:source=plan;field=f'pairs[{asset}].other.'+{'quantity_grid':'step','minimum_quantity':'min_qty','minimum_notional':'min_notional'}[rule]
    require(record['source_path']==str(source) and record['source_sha256']==hashes[str(source)] and record['field']==field,'rule_source_provenance')
  fee=meta['fee_provenance'];eq(fee['value'],F(0),'standard_fee_provenance')
  plan=ROOT/('reports/maker-roundtrip-v1/market-plan.json' if name=='1939Z' else 'reports/maker-equity-v2/market-plan.json')
  require(fee['source_path']==str(plan) and fee['source_sha256']==hashes[str(plan)] and fee['field']==f'pairs[{asset}].other.fee_bps','fee_source_provenance')
 raw=decoded(bodies['quotes.jsonl.gz'],8*1024*1024);lines=raw.splitlines()
 require(len(lines)==1008 and all(len(line)<=65536 for line in lines),'bounded1008row_roster')
 rows=audit_rows([load_json(line) for line in lines]);compare(summary,summary_expectation(rows))
 require(summary['classification']=='exploratory_post_capture_quote_feasibility' and all(summary[k] is False for k in ('actual_fills_observed','private_ack_observed','executable_profit_claim','clock_sync_performed')) and summary['funding_inclusive_net'] is None and summary['summed_portfolio_net'] is None,'quote_only_scope')
 terminals=summary['terminals'];require(set(terminals)==set(ARCHIVES),'both_archive_terminals');expanded=0
 for name,(start,assets,records,size,h) in ARCHIVES.items():
  mpath=ROOT/f'data/raw/maker-capture/20260929T{name}/manifest.json';archive=load_json(bounded(mpath,1000000));t=terminals[name]
  require(t['verified'] is True and t['gzip_eof'] is True and t['records']==records and t['raw_sha256']==h and t['manifest_sha256']==digest(bounded(mpath,1000000)),'terminal_attestation')
  expanded+=integer(t['decoded_bytes']);require(0<t['decoded_bytes']<=256*1024*1024,'archive_decoded_cap')
  gens={g['venue']:g['generation'] for g in archive['generations']}
  for r in rows:
   if r['archive']==name:
    for stage in ('anchor','entry','exit'):
     if stage+'_refs' in r:require(all(x['generation']==gens[v] for v,x in r[stage+'_refs'].items()),'manifest_generation_binding')
 require(expanded<=512*1024*1024 and manifest['terminal_verified'] is True and manifest['original_candidates']==1008 and manifest['total_new_bytes_cap']==CAP and number(manifest['wall_seconds'])<=900,'run_scope_and_limits')
 baseline=sum((ROOT/n).stat().st_size for n in NEW);published=sum(len(b) for b in bodies.values())
 external=integer(manifest['external_freeze_bytes'])
 require(external==len(bodies['freeze.json'])<=30000 and manifest['external_freeze_sha256']==before['freeze.json'],'prepared_external_freeze_copy')
 require(manifest['source_repository_bytes']==baseline and manifest['new_physical_bytes_before_manifest']==baseline+published-len(bodies['manifest.json'])+external,'physical_byte_identity')
 categories={'source':baseline+len(bodies['sources.jsonl.gz']),'rows':len(bodies['quotes.jsonl.gz']),'summary':len(bodies['summary.json.gz']),'provenance':len(bodies['freeze.json'])+external,'failure':0}
 require(manifest['category_bytes_before_manifest']==categories and categories['source']<=190000 and categories['provenance']+len(bodies['manifest.json'])<=60000 and manifest['reserved_external_bytes']==40000 and baseline+published+external+40000<=CAP,'all_artifact_caps')
 verify_inputs(hashes)
 require(owned_inventory()==owned,'owned_archive_stats_unchanged_after')
 require(bounded(external_path,30000)==external_body,'external_freeze_unchanged_after')
 require(all(digest(bounded(path/n,limits[n]))==h for n,h in before.items()),'publication_unchanged_after')
 return dict(status='PASS',auditor_sha256=digest(bounded(Path(__file__),28000)),publication=str(path),
  original_candidates=1008,primary_candidates=672,smaller_candidates=336,
  stratum_denominators=[264,240,264,240],conditional_quote_complete=summary['conditional_quote_complete'],
  statuses=summary['statuses'],fully_verified_executable_count=0,
  published_bytes=published,repository_source_bytes=baseline,external_freeze_bytes=external,
  verified=['output/source hashes','1008 identities and summary conservation','endpoint clocks and fixed q','four own fees/stress/elapsed capital','unknown rule/cost labels'],
  limitations=['No raw opened: raw terminal/hashes rely on reviewed run attestations.','Endpoint references cannot prove first eligible pair, intermediate validity, raw collision handling or depth walks.','Historical metadata values are checked against frozen method, not independently reselected.'])

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('publication',type=Path);parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
 require(not args.out.exists() and not args.out.is_symlink() and args.out.parent.is_dir() and not args.out.parent.is_symlink(),'new_external_report_required')
 require(args.publication.resolve() not in args.out.resolve().parents,'report_outside_publication')
 report=publication(args.publication);body=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();require(len(body)<8000,'report8kb_cap')
 with args.out.open('xb') as handle:handle.write(body)
 print(json.dumps(dict(status='PASS',original_candidates=1008,conditional_quote_complete=report['conditional_quote_complete'],report_bytes=len(body))))

if __name__=='__main__':main()
