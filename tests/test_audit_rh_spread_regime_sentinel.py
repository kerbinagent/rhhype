"""Synthetic independent-auditor checks; no collector imports, network or live study access."""
import csv,gzip,hashlib,io,json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from scripts import audit_rh_spread_regime_sentinel as a

def encode(value):return json.dumps(value,separators=(',',':')).encode()
def decimal(value):
 from decimal import Decimal,localcontext
 with localcontext() as c:c.prec=60;return format(Decimal(value.numerator)/Decimal(value.denominator),'f')

def publication(path):
 refs=json.loads((a.ROOT/list(a.HASHES)[4]).read_bytes())['selected'];by={r['asset']:r for r in refs}
 inputs={str(a.ROOT/n):h for n,h in a.HASHES.items()};limits={'control':90000,'metadata':280000,'samples':80000,'derived':40000,'logs':10000};categories={}
 def put(name,body,category='control'):
  (path/name).write_bytes(body if isinstance(body,bytes) else encode(body));categories[name]=category
 archives={}
 for name,source in a.ARCHIVES.items():
  raw=(a.ROOT/source).read_bytes();packed=gzip.compress(raw,mtime=0);put(name,packed)
  archives[name]={'input':str(a.ROOT/source),'decoded_bytes':len(raw),'decoded_sha256':a.digest(raw),'compressed_bytes':len(packed),'compressed_sha256':a.digest(packed)}
 put('source-freeze.json',{'input_hashes':inputs,'resource_wrapper':'sentinel_compact_provenance_v1','overrides':['Store','dependencies'],'archived_sources':archives,'limits':limits,'network_calls_before_freeze':0,'python':a.sys.version,'aiohttp':a.version('aiohttp')})
 requests={}
 for name in a.META:
  put(name+'.json',b'{}','metadata');requests[name]={'status':200,'bytes':2,'sha256':a.digest(b'{}'),'started_ns':100*a.NS,'completed_ns':100*a.NS,'completed_mono_ns':200*a.NS}
 put('requests.json',requests)
 markets=[{'asset':asset,'eligible':True,'reason':None,'reference':{k:by[asset][k] for k in ('asset','rh_market','hl_market','unit','rh_price_tick','rh_size_step','hl_size_step','common_step')},'market':by[asset]} for asset in a.ASSETS];put('eligibility.json',markets)
 prepared={'status':'prepared','metadata_attempts':3,'metadata_successes':3,'rows':1680,'inputs':inputs,'no_quote_connection':True,'prepared_hashes':{n:a.digest((path/n).read_bytes()) for n in categories}}
 put('prepared.json',prepared);put('root-freeze.json',{'inputs':inputs,'prepared_sha256':a.digest((path/'prepared.json').read_bytes()),'stage_hashes':{n:a.digest((path/n).read_bytes()) for n in categories}})
 schedule={'run_activation_utc_ns':100*a.NS,'run_activation_mono_ns':200*a.NS,'t0_utc_ns':110*a.NS,'t0_mono_ns':210*a.NS,'endpoint_utc_ns':1310*a.NS,'endpoint_mono_ns':1410*a.NS,'slot_count':20,'interval_ns':60*a.NS,'max_dispatch_lateness_ns':250000000};put('schedule.json',schedule)
 samples=[];rows=[];bounds={}
 for k in range(20):
  for asset in a.ASSETS:
   utc=(110+k*60)*a.NS;mono=(210+k*60)*a.NS;sample={'k':k,'asset':asset,'planned_utc_ns':utc,'planned_mono_ns':mono,'sample_utc_ns':utc,'sample_mono_ns':mono,'reason':None if asset=='LIT' else 'missing_ticker','ticker':None}
   if asset=='LIT':sample['ticker']={'source_ns':utc,'receipt_ns':utc,'receipt_mono_ns':mono,'generation':'rh:1','raw':json.dumps({'type':'update/ticker','channel':'ticker:'+by[asset]['rh_market'],'ticker':{'s':asset,'last_updated_at':utc//1000,'b':{'price':'3.7783','size':'100'},'a':{'price':'3.7813','size':'100'}}})}
   samples.append(sample)
   for budget in a.BUDGETS:
    row={'k':k,'asset':asset,'budget':budget,'valid':'False','reason':'missing_ticker','quantity':'','optimistic_budget':'','positive':'','paired_hedge_status':'unknown'}
    if asset=='LIT':
     q=(a.Q(budget)/a.Q('3.7813')).__floor__();bound=a.Q(q)*a.Q('.003')-a.Q('.1')-a.Q('.0005')*q*a.Q('3.7783');bounds[budget]=bound
     row.update(valid='True',reason='',quantity=str(q),optimistic_budget=decimal(bound),positive=str(bound>0))
    rows.append(row)
 put('samples.jsonl.gz',gzip.compress(b'\n'.join(encode(s) for s in samples)+b'\n',mtime=0),'samples')
 def csv_rows():
  stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=a.FIELDS);writer.writeheader();writer.writerows(rows);return gzip.compress(stream.getvalue().encode(),mtime=0)
 put('observations.csv.gz',csv_rows(),'derived');groups=[]
 for asset in a.ASSETS:
  for budget in a.BUDGETS:
   valid=asset=='LIT';bound=bounds[budget] if valid else None;passes=valid and bound>0
   groups.append({'asset':asset,'budget':budget,'possible':20,'valid':20 if valid else 0,'positive':20 if passes else 0,'exclusions':{} if valid else {'missing_ticker':20},'median':decimal(bound) if valid else None,'maximum':decimal(bound) if valid else None,'blocks':[{'block':k,'possible':5,'valid':5 if valid else 0,'median':decimal(bound) if valid else None,'passes':passes} for k in range(4)],'primary_prerequisite':asset=='LIT' and budget==1000})
 put('summary.json.gz',gzip.compress(encode({'scope':'prospective_RH_only_ex_funding_ex_credits_necessary_static_budget','planned_rows':1680,'actual_rows':1680,'unknown_paired_hedge_rows':1680,'economics_evaluated':True,'valid_rh_size_observations':80,'profit_or_fill_claim':False,'automatic_followup':False,'status':'completed','planned_asset_references':420,'sampled_asset_references':420,'metadata_ineligible_assets':[],'groups':groups,'later_cost_screen_candidates':['LIT']}),mtime=0),'derived');put('readout.md',b'synthetic only','logs')
 def finalize():
  outputs={n:a.digest((path/n).read_bytes()) for n in categories if n!='manifest.json'}
  put('manifest.json',{'status':'completed','completed_utc_ns':1310*a.NS,'economic_endpoint_reached':True,'input_hashes':inputs,'input_hashes_unchanged':True,'metadata_attempts':3,'websocket_attempts':1,'cap_bytes':a.CAP,'no_automatic_followup':True,'failure_denominator_rows':1680,'source_study':'new_sampled_public_network_evidence','output_hashes':outputs})
  (path/'storage.json').write_bytes(encode({n:{'bytes':(path/n).stat().st_size,'sha256':a.digest((path/n).read_bytes()),'category':c} for n,c in categories.items()}))
 finalize();return rows,csv_rows,finalize

class AuditorTests(unittest.TestCase):
 def test_missing_manifest_and_both_endpoint_clocks(self):
  with TemporaryDirectory() as t:
   path=Path(t)
   with self.assertRaisesRegex(ValueError,'missing_terminal_manifest'):a.audit(path)
   (path/'manifest.json').write_bytes(encode({'status':'completed','economic_endpoint_reached':True,'completed_utc_ns':10}))
   (path/'schedule.json').write_bytes(encode({'endpoint_utc_ns':10,'endpoint_mono_ns':20}))
   for utc,mono in ((9,20),(10,19)):
    with self.assertRaisesRegex(ValueError,'pre_endpoint'):a.audit(path,now_utc=utc,now_mono=mono)
 def test_exact_complete_synthetic_publication_and_tampered_math(self):
  with TemporaryDirectory() as t:
   path=Path(t);rows,csv_rows,finalize=publication(path);result=a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
   self.assertEqual((result['rows'],result['sample_references'],result['valid_rh_size_rows']),(1680,420,80));self.assertEqual(result['primary_candidates'],['LIT'])
   row=next(r for r in rows if r['asset']=='LIT' and r['budget']==1000)
   for field,value in (('optimistic_budget','0'),('quantity','265')):
    old=row[field];row[field]=value;(path/'observations.csv.gz').write_bytes(csv_rows());finalize()
    with self.assertRaisesRegex(ValueError,'independent_exact_quantity_U'):a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
    row[field]=old
 def test_missing_rows_and_hash_corruption_are_not_repaired(self):
  with TemporaryDirectory() as t:
   path=Path(t);rows,csv_rows,finalize=publication(path)
   row=next(r for r in rows if r['asset']=='BTC');row.update(valid='True',quantity='1',optimistic_budget='999',positive='True')
   (path/'observations.csv.gz').write_bytes(csv_rows());finalize()
   with self.assertRaisesRegex(ValueError,'censored_rows_remain_missing'):a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
   (path/'readout.md').write_bytes(b'corrupted')
   with self.assertRaisesRegex(ValueError,'terminal_output_hashes'):a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
 def test_block_median_gate_and_quote_clock_mutations(self):
  with TemporaryDirectory() as t:
   path=Path(t);_,_,finalize=publication(path);packed=(path/'summary.json.gz').read_bytes();summary=json.loads(gzip.decompress(packed));block=next(g for g in summary['groups'] if g['asset']=='LIT' and g['budget']==1000)['blocks'][0]
   for field,value,error in (('median','0','block_exact_median'),('passes',False,'block_coverage_gate')):
    old=block[field];block[field]=value;(path/'summary.json.gz').write_bytes(gzip.compress(encode(summary),mtime=0));finalize()
    with self.assertRaisesRegex(ValueError,error):a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
    block[field]=old
   (path/'summary.json.gz').write_bytes(packed)
   samples=[json.loads(line) for line in gzip.decompress((path/'samples.jsonl.gz').read_bytes()).splitlines()];tick=next(s['ticker'] for s in samples if s['asset']=='LIT')
   for field,delta,error in (('source_ns',-1000,'ticker_source_symbol'),('receipt_ns',1,'quote_causal_freshness')):
    old=tick[field];tick[field]+=delta;(path/'samples.jsonl.gz').write_bytes(gzip.compress(b'\n'.join(encode(sample) for sample in samples)+b'\n',mtime=0));finalize()
    with self.assertRaisesRegex(ValueError,error):a.audit(path,now_utc=1310*a.NS,now_mono=1410*a.NS)
    tick[field]=old
 def test_zero_strict_boundary_even_median_and_numeric_bounds(self):
  sample={'k':0,'asset':'LIT','reason':None};market={'reference':{'common_step':'1'},'market':{'rh_min_qty':'1','rh_size_step':'1','rh_min_notional':'10','rh_max_quote':'10000'}}
  result,reason=a.expected_row(sample,market,101,(a.Q('100'),a.Q('100.15')),True)
  self.assertEqual(result[1],0);self.assertIsNone(reason);self.assertEqual(a.med([a.Q('-0.1'),a.Q('.3')]),a.Q('.1'))
  self.assertEqual(a.output_number('0.00000000000000000005'),a.Q('0.00000000000000000005'))
  for value in ('1e99999999','1e-99999999','9'*129):
   with self.assertRaises(ValueError):a.output_number(value)

if __name__=='__main__':unittest.main()
