#!/usr/bin/env python3
"""Independent completed-output audit. No network or collector imports; never writes the stage."""
import argparse
from collections import Counter
import csv
from decimal import Decimal
from fractions import Fraction as Q
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import sys
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[1]
ASSETS=tuple('BTC ETH LIT NVDA SOL HYPE AAPL XAG GOOGL SNDK NEAR ZEC XRP MSFT MU TSLA META CRCL AMD AMZN INTC'.split())
BUDGETS=(100,250,500,1000)
NS=10**9
CAP=500000
HASHES={
 'scripts/rh_spread_regime_sentinel.py':'d6a59773dd59caad7c20431ef62cafd2e1b6a69c5dc5826a7bbb1f48b902c7de',
 'research/rh-spread-regime-sentinel-plan.md':'cfd3bd8d50c9e5885e7af1de7e4edd5bcd9c5f71f0b97dea09832f10bb294f54',
 'tests/test_rh_spread_regime_sentinel.py':'3ec64fe58fe6198cd9e9c362248a0c4bac748e68cdb2a271b50a0daeff1adcf0',
 'scripts/passive_universe_screen.py':'71cf56d9bd91847011d30767be918130ea02cf38b2d125d1ece82cb4a09e9014',
 'reports/passive-universe-screen/20260930T0310Z/universe.json':'37fc90d4b66d8fc0aefea3c806b49ff598ab06c986a9db3cec76188da7b1fa83',
 'scripts/rh_spread_regime_sentinel_compact.py':'14c02a18a5550f6666af3cfd304cdb2874254cd10109808ea4716536ec5f693a',
 'tests/test_rh_spread_regime_sentinel_compact.py':'4725af78859b020e135a71e87f112d74a01f2be8b77adbfcf13f51f831bdb084',
 'research/rh-spread-regime-sentinel-compact-resource-method.md':'78c760b69fabdaab6c503dfb131f0d4ce264c9816a960893032be1414466d6ef',
}
ARCHIVES=dict(zip(('source.py.gz','method.md.gz','tests.py.gz','wrapper.py.gz','wrapper-tests.py.gz','resource-method.md.gz'),(list(HASHES)[0],list(HASHES)[1],list(HASHES)[2],list(HASHES)[5],list(HASHES)[6],list(HASHES)[7])))
META=('rh_order_book_details','hl_meta_native','hl_meta_xyz')
FIELDS=('k','asset','budget','valid','reason','quantity','optimistic_budget','positive','paired_hedge_status')
FILES=set(ARCHIVES)|{'source-freeze.json','requests.json','eligibility.json','prepared.json','root-freeze.json','schedule.json','samples.jsonl.gz','observations.csv.gz','summary.json.gz','readout.md','manifest.json','storage.json'}|{n+'.json' for n in META}

def require(ok,label):
 if not ok:raise ValueError(label)
def digest(data):return hashlib.sha256(data).hexdigest()
def rational(value):
 require(not isinstance(value,bool),'boolean_numeric')
 text=str(value);require(len(text)<=80,'numeric_representation_bound');decimal=Decimal(text)
 require(decimal.is_finite() and len(decimal.as_tuple().digits)<=40 and abs(decimal.as_tuple().exponent)<=18 and abs(decimal.adjusted())<=18,'numeric_magnitude_bound')
 return Q(decimal)
def output_number(value):
 text=str(value);require(len(text)<=128,'output_numeric_representation_bound');d=Decimal(text)
 require(d.is_finite() and len(d.as_tuple().digits)<=64 and abs(d.as_tuple().exponent)<=40 and abs(d.adjusted())<=40,'output_numeric_magnitude_bound');return Q(d)
def read_file(path,limit=500000):
 require(path.is_file() and not path.is_symlink() and path.stat().st_size<=limit,'bounded_regular_file');return path.read_bytes()
def numeric_equal(actual,expected,label):
 require((actual is None and expected is None) or (actual is not None and expected is not None and output_number(actual)==expected),label)
def med(values):
 values=sorted(values);n=len(values)
 return None if n==0 else values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2
def unpack(packed,limit):
 with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:raw=stream.read(limit+1)
 require(len(raw)<=limit,'decoded_size_cap');return raw

def endpoint(manifest,schedule,now_utc,now_mono):
 require(type(now_utc) is int and type(now_mono) is int,'audit_clock_shape')
 require(now_utc>=schedule['endpoint_utc_ns'] and now_mono>=schedule['endpoint_mono_ns'],'pre_endpoint_audit_forbidden')
 require(manifest['status'] in ('completed','incomplete'),'requires_terminal_manifest')
 if manifest['economic_endpoint_reached']:require(manifest['completed_utc_ns']>=schedule['endpoint_utc_ns'],'early_economic_publication')

def sample_quote(sample,market,schedule):
 """Check observable endpoint clocks and quote shape; intervening invalidations remain unobserved."""
 k=sample['k'];activation=schedule['run_activation_utc_ns'];mono0=schedule['run_activation_mono_ns']
 require(type(k) is int and 0<=k<20,'slot_identity')
 require(sample['planned_mono_ns']==schedule['t0_mono_ns']+k*60*NS and sample['planned_utc_ns']==schedule['t0_utc_ns']+k*60*NS,'fixed_sample_schedule')
 if sample['reason'] is not None:return None
 require(market['eligible'] is True and sample['ticker'] is not None,'valid_sample_metadata_ticker')
 now,mono=sample['sample_utc_ns'],sample['sample_mono_ns'];tick=sample['ticker']
 require(type(now) is int and type(mono) is int and 0<=mono-sample['planned_mono_ns']<=250000000,'valid_dispatch')
 require(abs(now-(activation+mono-mono0))<=250000000,'sample_clock_mapping')
 source,receipt,received_mono=tick['source_ns'],tick['receipt_ns'],tick['receipt_mono_ns']
 require(all(type(x) is int for x in (source,receipt,received_mono)) and 0<source<=receipt<=now and 0<=now-source<=2*NS and 0<=now-receipt<=2*NS and received_mono<=mono,'quote_causal_freshness')
 require(abs(receipt-(activation+received_mono-mono0))<=250000000 and tick['generation']=='rh:1','receipt_mapping_generation')
 require(len(tick['raw'].encode())<=32768,'raw_message_cap');payload=json.loads(tick['raw'],parse_float=Decimal)
 require(payload['type'] in ('subscribed/ticker','update/ticker') and payload['channel']=='ticker:'+market['reference']['rh_market'],'ticker_route')
 quote=payload['ticker'];require(type(quote['last_updated_at']) is int and quote['last_updated_at']*1000==source and quote['s']==sample['asset'],'ticker_source_symbol')
 values=[];rules=market['market']
 for side in ('b','a'):
  price,size=rational(quote[side]['price']),rational(quote[side]['size']);require(price>0 and size>0 and (price/rational(rules['rh_price_tick'])).denominator==1 and (size/rational(rules['rh_size_step'])).denominator==1,'quote_grid_shape');values.append(price)
 require(values[0]<values[1],'quote_uncrossed');return values

def expected_row(sample,market,budget,quote,economic):
 if not economic:return None,sample['reason'] or 'economics_unadjudicated_early_stop'
 if sample['reason'] is not None:return None,sample['reason']
 bid,ask=quote;step=rational(market['reference']['common_step']);quantity=(Q(budget)/ask/step).__floor__()*step;rules=market['market']
 if quantity<=0 or quantity<rational(rules['rh_min_qty']) or (quantity/rational(rules['rh_size_step'])).denominator!=1:return None,'rh_quantity_bounds'
 if quantity*bid<rational(rules['rh_min_notional']) or quantity*ask>rational(rules['rh_max_quote']) or quantity*ask>budget:return None,'rh_notional_bounds'
 return (quantity,quantity*(ask-bid)-Q(1,10)-Q(5,10000)*quantity*bid),None

def verify_groups(rows,summary,economic):
 require(len(summary['groups'])==84 and [(g['asset'],g['budget']) for g in summary['groups']]==[(a,b) for a in ASSETS for b in BUDGETS],'all84ordered_groups')
 candidates=[]
 for group in summary['groups']:
  selected=[r for r in rows if r['asset']==group['asset'] and int(r['budget'])==group['budget']];valid=[r for r in selected if r['valid']=='True'];values=[output_number(r['optimistic_budget']) for r in valid]
  require(group['possible']==20 and len(selected)==20 and group['valid']==len(valid) and group['positive']==sum(v>0 for v in values),'group_coverage_positive')
  require(group['exclusions']==dict(Counter(r['reason'] for r in selected if r['valid']=='False')),'group_exclusion_counts');numeric_equal(group['median'],med(values),'group_exact_median');numeric_equal(group['maximum'],max(values) if values else None,'group_exact_max')
  require(len(group['blocks'])==4,'four_fixed_blocks');passed=0
  for block,b in enumerate(group['blocks']):
   block_values=[output_number(r['optimistic_budget']) for r in valid if int(r['k'])//5==block];middle=med(block_values);gate=len(block_values)>=4 and middle>0
   require(b['block']==block and b['possible']==5 and b['valid']==len(block_values) and b['passes'] is gate,'block_coverage_gate');numeric_equal(b['median'],middle,'block_exact_median');passed+=gate
  gate=bool(economic and group['budget']==1000 and len(values)>=16 and med(values)>0 and passed>=3)
  require(group['primary_prerequisite'] is gate,'strict_primary_gate')
  if gate:candidates.append(group['asset'])
 require(summary['later_cost_screen_candidates']==candidates,'primary_candidate_list');return candidates

def audit(path,*,now_utc=None,now_mono=None):
 path=Path(path);require(path.is_dir() and not path.is_symlink(),'stage_path')
 require((path/'manifest.json').is_file(),'missing_terminal_manifest')
 # No samples, prices or rows are opened before both endpoint clocks pass.
 manifest=json.loads(read_file(path/'manifest.json'));schedule=json.loads(read_file(path/'schedule.json'));endpoint(manifest,schedule,time.time_ns() if now_utc is None else now_utc,time.monotonic_ns() if now_mono is None else now_mono)
 require({p.name for p in path.iterdir()}==FILES and all(p.is_file() and not p.is_symlink() for p in path.iterdir()),'exact_publication_inventory')
 sizes={p.name:p.stat().st_size for p in path.iterdir()};require(sum(sizes.values())<=CAP,'published500k_cap');before={p.name:digest(read_file(p)) for p in path.iterdir()};own=digest(Path(__file__).read_bytes())
 expected={str(ROOT/name):h for name,h in HASHES.items()};require(manifest['input_hashes']==expected and all(digest(read_file(Path(p),1000000))==h for p,h in expected.items()),'eight_frozen_actual_input_hashes')
 require(manifest['input_hashes_unchanged'] is True and manifest['metadata_attempts']==3 and manifest['websocket_attempts']==1 and manifest['cap_bytes']==CAP and manifest['no_automatic_followup'] is True and manifest['failure_denominator_rows']==1680 and manifest['source_study']=='new_sampled_public_network_evidence','manifest_scope')
 require(manifest['output_hashes']=={k:v for k,v in before.items() if k not in ('manifest.json','storage.json')},'terminal_output_hashes')
 index=json.loads((path/'storage.json').read_bytes());require(set(index)==FILES-{'storage.json'},'storage_exact_keys')
 totals=Counter()
 for name,record in index.items():require(record['sha256']==before[name] and record['bytes']==sizes[name],'storage_hash_bytes');totals[record['category']]+=record['bytes']
 totals['control']+=sizes['storage.json'];limits={'control':90000,'metadata':280000,'samples':80000,'derived':40000,'logs':10000};require(set(totals)<=set(limits) and all(totals[k]<=v for k,v in limits.items()),'category_caps')
 source=json.loads((path/'source-freeze.json').read_bytes());prepared=json.loads((path/'prepared.json').read_bytes());freeze=json.loads((path/'root-freeze.json').read_bytes());requests=json.loads((path/'requests.json').read_bytes())
 require(source['python']==sys.version and source['aiohttp']==version('aiohttp'),'frozen_runtime_versions')
 require(source['input_hashes']==prepared['inputs']==freeze['inputs']==expected and source['resource_wrapper']=='sentinel_compact_provenance_v1' and source['overrides']==['Store','dependencies'],'frozen_override_provenance')
 require(source['limits']==limits and len(source['archived_sources'])==6 and set(source['archived_sources'])==set(ARCHIVES),'archive_inventory');decoded_total=0
 for name,dependency in ARCHIVES.items():
  record=source['archived_sources'][name];packed=(path/name).read_bytes();raw=unpack(packed,65536);decoded_total+=len(raw)
  require(record=={'input':str(ROOT/dependency),'decoded_bytes':len(raw),'decoded_sha256':digest(raw),'compressed_bytes':len(packed),'compressed_sha256':digest(packed)} and digest(raw)==HASHES[dependency],'compressed_decoded_archive_identity')
 require(decoded_total<=262144,'all_archives_decoded_cap')
 require(freeze['prepared_sha256']==before['prepared.json'] and all(before[n]==h for n,h in freeze['stage_hashes'].items()) and all(before[n]==h for n,h in prepared['prepared_hashes'].items()),'prepared_rootfreeze_hash_chains')
 require(prepared['status']=='prepared' and prepared['metadata_attempts']==prepared['metadata_successes']==3 and prepared['rows']==1680 and prepared['no_quote_connection'] is True and source['network_calls_before_freeze']==0,'metadata_preparation_scope')
 require(set(requests)==set(META),'three_metadata_requests')
 for name,r in requests.items():
  require(r['status']==200 and r['bytes']==sizes[name+'.json'] and r['sha256']==before[name+'.json'] and r['started_ns']<=r['completed_ns'],'metadata_response_hash')
  require(all(type(r[key]) is int and 0<=target-r[key]<=120*NS for key,target in (('completed_ns',schedule['t0_utc_ns']),('completed_mono_ns',schedule['t0_mono_ns']))),'dual_metadata_freshness')
 require(schedule['t0_utc_ns']==schedule['run_activation_utc_ns']+10*NS and schedule['t0_mono_ns']==schedule['run_activation_mono_ns']+10*NS and schedule['endpoint_utc_ns']==schedule['t0_utc_ns']+1200*NS and schedule['endpoint_mono_ns']==schedule['t0_mono_ns']+1200*NS and schedule['slot_count']==20 and schedule['interval_ns']==60*NS and schedule['max_dispatch_lateness_ns']==250000000,'fixed1200s_schedule')
 samples_raw=unpack((path/'samples.jsonl.gz').read_bytes(),2000000);require(all(len(line)+1<=65536 for line in samples_raw.splitlines()),'sample_line_cap');samples=[json.loads(line) for line in samples_raw.splitlines()]
 require(len(samples)==420 and [(s['k'],s['asset']) for s in samples]==[(k,a) for k in range(20) for a in ASSETS],'420exact_sample_keys')
 markets=json.loads((path/'eligibility.json').read_bytes());require([m['asset'] for m in markets]==list(ASSETS),'21metadata_keys');by_market={m['asset']:m for m in markets}
 references={r['asset']:r for r in json.loads((ROOT/list(HASHES)[4]).read_bytes())['selected']}
 for market in markets:
  require(market['reference']=={k:references[market['asset']][k] for k in ('asset','rh_market','hl_market','unit','rh_price_tick','rh_size_step','hl_size_step','common_step')},'unchanged_original_reference_lots')
 decoded=unpack((path/'observations.csv.gz').read_bytes(),1000000).decode();reader=csv.DictReader(io.StringIO(decoded));require(tuple(reader.fieldnames)==FIELDS,'exact_row_fields');rows=list(reader)
 require(len(rows)==1680 and [(int(r['k']),r['asset'],int(r['budget'])) for r in rows]==[(k,a,b) for k in range(20) for a in ASSETS for b in BUDGETS] and all(None not in r and all(v is not None for v in r.values()) for r in rows),'1680exact_row_keys')
 economic=manifest['economic_endpoint_reached'];require(type(economic) is bool,'economic_endpoint_flag');valid_count=0;last_sources={}
 for n,sample in enumerate(samples):
  market=by_market[sample['asset']];quote=sample_quote(sample,market,schedule)
  if quote is not None:
   require(sample['ticker']['source_ns']>=last_sources.get(sample['asset'],0),'sampled_source_nonregression');last_sources[sample['asset']]=sample['ticker']['source_ns']
  for offset,budget in enumerate(BUDGETS):
   row=rows[n*4+offset];expected_row_value,reason=expected_row(sample,market,budget,quote,economic)
   require(row['paired_hedge_status']=='unknown','all_paired_hedges_unknown')
   if expected_row_value is None:require(row['valid']=='False' and row['reason']==reason and all(row[k]=='' for k in ('quantity','optimistic_budget','positive')),'censored_rows_remain_missing')
   else:
    q,bound=expected_row_value;require(row['valid']=='True' and row['reason']=='' and output_number(row['quantity'])==q and output_number(row['optimistic_budget'])==bound and row['positive']==str(bound>0),'independent_exact_quantity_U');valid_count+=1
 summary=json.loads(unpack((path/'summary.json.gz').read_bytes(),1000000))
 require(summary['planned_rows']==summary['actual_rows']==summary['unknown_paired_hedge_rows']==1680 and summary['economics_evaluated'] is economic and summary['valid_rh_size_observations']==valid_count and summary['profit_or_fill_claim'] is False and summary['automatic_followup'] is False,'summary_denominators_semantics')
 require(summary['scope']=='prospective_RH_only_ex_funding_ex_credits_necessary_static_budget','summary_bound_scope')
 require(summary['status']==manifest['status'] and summary['planned_asset_references']==420 and summary['sampled_asset_references']==sum(s['sample_mono_ns'] is not None for s in samples) and summary['metadata_ineligible_assets']==[m['asset'] for m in markets if not m['eligible']],'summary_collection_coverage')
 candidates=verify_groups(rows,summary,economic)
 require(before=={p.name:digest(p.read_bytes()) for p in path.iterdir()} and all(digest(read_file(Path(p),1000000))==h for p,h in expected.items()) and own==digest(Path(__file__).read_bytes()),'hashes_unchanged_after_audit')
 return {'status':'passed','stage':str(path),'auditor_sha256':own,'input_dependencies':8,'archives':6,'sample_references':420,'rows':1680,'groups':84,'blocks':336,'valid_rh_size_rows':valid_count,'missing_rows':1680-valid_count,'primary_candidates':candidates,'publication_status':manifest['status'],'economics_evaluated':economic,'stage_bytes':sum(sizes.values()),'published_hashes_unchanged':True,'limitations':['Sampled endpoint clocks/quotes are checked; intervening collector invalidations and source high-water updates cannot all be reconstructed because no intervening stream is retained.','U is an optimistic static budget excluding funding/credits; paired hedges, queue, fills, capital and conversion remain unknown.']}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);parser.add_argument('--report',required=True,type=Path);args=parser.parse_args()
 stage=args.stage.resolve();report=args.report.resolve();require(report.parent==stage.parent and report!=stage and not report.exists() and not report.is_symlink(),'new_report_outside_stage_required')
 result=audit(stage);body=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode();require(len(body)<8000,'audit_report8k_cap')
 own_files=(Path(__file__),ROOT/'tests/test_audit_rh_spread_regime_sentinel.py');require(result['stage_bytes']+len(body)+sum(p.stat().st_size for p in own_files)<=CAP,'study_plus_auditor500k_cap')
 with report.open('xb') as handle:handle.write(body)
 print(json.dumps({'status':result['status'],'report':str(report),'report_bytes':len(body),'samples':420,'rows':1680,'valid_rows':result['valid_rh_size_rows']}))
if __name__=='__main__':main()
