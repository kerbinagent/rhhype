"""Synthetic derived fixtures; no raw or engine imports."""
import copy
from fractions import Fraction as F
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import audit_core_rh_delayed_taker as audit


def rows_fixture():
 rows=list(audit.expected_grid())
 for r in rows:
  r.update(status='anchor_missing_book',funding_unknown=True,funding_inclusive_net=None,legality_unknown=True,rule_spec_refs={v:f"{r['archive']}:{v}:{r['asset']}" for v in audit.VENUES})
 r=next(r for r in rows if r['asset']=='BTC' and r['long_venue']=='rh_lighter' and r['budget']==1000)
 anchor=r['anchor_ns'];entry=anchor+audit.NS//2;exit_ns=entry+10*audit.NS+audit.NS//2
 def references(at):
  return {v:dict(source_ns=at,receipt_ns=at,generation='g1',sequence=1) for v in audit.VENUES}
 checks={v:dict(price_grid='unknown',quantity_grid='known_pass',minimum_quantity='known_pass',minimum_notional='known_pass',maximum_quote='unknown',maximum_base='unknown') for v in audit.VENUES}
 r.update(status='conditional_quote_complete',quantity='10',anchor_long_best_ask='100',common_lot='.00001',
  anchor_long_buy='1000',anchor_short_sell='999',anchor_notional_exceeds_budget=False,anchor_refs=references(anchor),
  entry_refs=references(entry),entry_selected_ns=entry,entry_ns=entry,entry_long_buy='1000',entry_short_sell='999',
  entry_notional_exceeds_budget=False,entry_drift_from_anchor_walk='0',
  exit_refs=references(exit_ns),exit_selected_ns=exit_ns,exit_ns=exit_ns,exit_long_sell='1003',exit_short_buy='1000',
  anchor_rules=copy.deepcopy(checks),entry_rules=copy.deepcopy(checks),exit_rules=copy.deepcopy(checks),
  gross='2',entry_long_fee='0',entry_short_fee='0',exit_long_fee='0',exit_short_fee='0',fee_only_net='2',stress='.5',
  capital=str(F(1999,20)*F(21,2)/(365*86400)),
  adjusted_quote_net_ex_funding=str(F(3,2)-F(1999,20)*F(21,2)/(365*86400)),
  funding_unknown=True,funding_inclusive_net=None,legality_unknown=True,
  utc_hour_boundary_crossed=entry//(3600*audit.NS)!=exit_ns//(3600*audit.NS),
  funding_boundary_tie=entry%(3600*audit.NS)==0 or exit_ns%(3600*audit.NS)==0)
 tail=next(x for x in rows if x['asset']=='BTC' and x['long_venue']=='rh_lighter' and x['budget']==1000 and x['anchor_ns']==anchor+415*audit.NS)
 identity=tail.copy();tail.update(copy.deepcopy(r));tail.update(identity);tail['status']='exit_eof'
 for k in ('entry_ns','entry_selected_ns'):tail[k]+=415*audit.NS
 for stage in ('anchor','entry'):
  for ref in tail[stage+'_refs'].values():
   for clock in ('source_ns','receipt_ns'):ref[clock]+=415*audit.NS
 for k in audit.ECON+('exit_refs','exit_selected_ns','exit_ns','exit_long_sell','exit_short_buy','exit_rules'):tail.pop(k,None)
 return rows

def publication_fixture(root):
 def body(x):return (json.dumps(x,sort_keys=True,default=str)+'\n').encode()
 names=list(audit.PINS)+list(audit.NEW)
 for n in names:
  p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture source\n')
 for name in audit.ARCHIVES:
  (root/f'data/raw/maker-capture/20260929T{name}/manifest.json').write_bytes(body(dict(generations=[dict(venue=v,generation='g1') for v in (*audit.VENUES,'hyperliquid')])))
  (root/f'data/raw/maker-capture/20260929T{name}/frames.jsonl.gz').write_bytes(b'x')
 hashes={str(root/n):audit.digest((root/n).read_bytes()) for n in names};rules={}
 for name,(_,assets,*_) in audit.ARCHIVES.items():
  plan=root/('reports/maker-roundtrip-v1/market-plan.json' if name=='1939Z' else 'reports/maker-equity-v2/market-plan.json')
  for asset in assets:
   for v in audit.VENUES:
    values=audit.expected_rule_values(asset,v);meta={('max_qty' if k=='max_base' else k):(None if x is None else str(x)) for k,x in values.items()}
    meta['market']={'BTC':('1','1'),'ETH':('0','0'),'NVDA':('15','110'),'XAG':('41','93')}[asset][audit.VENUES.index(v)]
    prov={}
    for rule,field in dict(price_grid='price_tick',quantity_grid='size_step',minimum_quantity='min_qty',minimum_notional='min_notional',maximum_quote='max_quote',maximum_base='max_qty').items():
     value=meta[field];source=plan;f=f'pairs[{asset}].other.'+dict(quantity_grid='step',minimum_quantity='min_qty',minimum_notional='min_notional').get(rule,'')
     if rule in ('price_grid','maximum_quote'):source=root/'reports/maker-equity-v2/unit-provenance.json';f=f'{v}.selected_market_details[{asset}].'+('supported_price_decimals' if rule=='price_grid' else 'order_quote_limit')
     prov[rule]=dict(value=value,source_path=None if value is None else str(source),source_sha256=None if value is None else hashes[str(source)],field=None if value is None else f)
    meta.update(provenance=prov,fee_provenance=dict(value='0',source_path=str(plan),source_sha256=hashes[str(plan)],field=f'pairs[{asset}].other.fee_bps'));rules[f'{name}:{v}:{asset}']=meta
 stage=root/'derived';stage.mkdir();rows=rows_fixture();summary=audit.summary_expectation(rows)
 summary.update(schema=audit.SCHEMA,status='complete_quote_diagnostic',classification='exploratory_post_capture_quote_feasibility',actual_fills_observed=False,private_ack_observed=False,executable_profit_claim=False,clock_sync_performed=False,funding_inclusive_net=None,summed_portfolio_net=None,terminals={name:dict(verified=True,gzip_eof=True,records=s[2],decoded_bytes=1,raw_sha256=s[4],manifest_sha256=hashes[str(root/f'data/raw/maker-capture/20260929T{name}/manifest.json')]) for name,s in audit.ARCHIVES.items()})
 freeze=dict(schema=audit.SCHEMA,classification='exploratory_post_capture',prospective_freeze_claimed=False,actual_dependency_and_small_input_sha256=hashes,source_inventory_count=11,clock_sync_performed=False,rule_specs=rules,expected_raw_sha256={str(root/f'data/raw/maker-capture/20260929T{name}/frames.jsonl.gz'):s[4] for name,s in audit.ARCHIVES.items()})
 freeze.update(runtime=dict(python=audit.sys.version,aiohttp=audit.version('aiohttp'),dont_write_bytecode=audit.sys.dont_write_bytecode),raw_reads=0,
  captures=[dict(name=n,directory=str(root/f'data/raw/maker-capture/20260929T{n}'),start=s[0],assets=list(s[1]),records=s[2],bytes=s[3],raw_sha=s[4]) for n,s in audit.ARCHIVES.items()],
  grid=dict(candidates=1008,primary=672,smaller=336,horizon_seconds=10,quote_delay_ms=500,hard_deadline_ms=2000,wall_seconds=900,total_new_physical_bytes_cap=600000,reserved_external_bytes=40000,raw_reads=0,raw_traversals=0,network_calls=0))
 freeze['owned_archive_inventory']={name:{p.name:p.stat().st_size for p in (root/f'data/raw/maker-capture/20260929T{name}').iterdir()} for name in audit.ARCHIVES}
 copies=[dict(path=str(root/n),sha256=hashes[str(root/n)],text=(root/n).read_text()) for n in audit.NEW]
 files={'freeze.json':body(freeze),'summary.json.gz':gzip.compress(body(summary)), 'quotes.jsonl.gz':gzip.compress(b''.join(body(r) for r in rows)),'sources.jsonl.gz':gzip.compress(b''.join(body(c) for c in copies))}
 baseline=sum((root/n).stat().st_size for n in audit.NEW)
 external=len(files['freeze.json'])
 external_path=root/'reports/core-rh-delayed-taker/freeze.json';external_path.parent.mkdir(parents=True);external_path.write_bytes(files['freeze.json'])
 manifest=dict(schema=audit.SCHEMA,status='complete_quote_diagnostic',classification='exploratory_post_capture',outputs={n:dict(bytes=len(b),sha256=audit.digest(b)) for n,b in files.items()},source_repository_bytes=baseline,new_physical_bytes_before_manifest=baseline+sum(map(len,files.values()))+external,category_bytes_before_manifest=dict(source=baseline+len(files['sources.jsonl.gz']),rows=len(files['quotes.jsonl.gz']),summary=len(files['summary.json.gz']),provenance=2*external,failure=0),reserved_external_bytes=40000,total_new_bytes_cap=600000,wall_seconds=1,terminal_verified=True,original_candidates=1008,external_freeze_bytes=external,external_freeze_sha256=audit.digest(files['freeze.json']))
 manifest['external_freeze_path']=str(external_path)
 for n,b in files.items():(stage/n).write_bytes(b)
 (stage/'manifest.json').write_bytes(body(manifest));return stage,{n:hashes[str(root/n)] for n in audit.PINS}


class DerivedAuditTests(unittest.TestCase):
 def setUp(self):
  archive_patch=patch.object(audit,'ARCHIVES',{n:(s[0],s[1],s[2],1,s[4]) for n,s in audit.ARCHIVES.items()});archive_patch.start();self.addCleanup(archive_patch.stop)
  self.rows=rows_fixture()

 def test_exact_grid_costs_and_denominator(self):
  audit.audit_rows(self.rows)
  summary=audit.summary_expectation(self.rows)
  self.assertEqual(list(summary['stratum_denominators'].values()),[264,240,264,240])
  self.assertEqual(list(summary['archive_denominators'].values()),[504,504])
  self.assertEqual(summary['conditional_quote_complete'],1)
  self.assertEqual(summary['target_positive'],1)
  self.assertEqual(summary['fully_verified_executable_count'],0)
  self.assertEqual(len(summary['groups']),32)
  self.assertEqual(sum(g['original_candidates'] for g in summary['groups']),1008)

 def test_four_cash_flows_fees_stress_and_actual_elapsed(self):
  for field,value in [('gross','3'),('entry_long_fee','.001'),('stress','.4995'),('capital','0'),('adjusted_quote_net_ex_funding','1.5')]:
   with self.subTest(field=field):
    rows=copy.deepcopy(self.rows);r=next(r for r in rows if r['status']=='conditional_quote_complete');r[field]=value
    with self.assertRaises(ValueError):audit.audit_rows(rows)

 def test_quantity_clocks_generation_and_null_censoring(self):
  mutations=[lambda r:r.update(quantity='10.00001'),
   lambda r:r['entry_refs']['lighter'].update(source_ns=r['anchor_ns']),
   lambda r:r['exit_refs']['lighter'].update(generation='g2'),
   lambda r:r.update(exit_selected_ns=r['entry_ns']+12*audit.NS+1),
   lambda r:r.update(status='exit_eof'),
   lambda r:r['exit_rules']['lighter'].update(maximum_base='known_pass')]
  for mutate in mutations:
   rows=copy.deepcopy(self.rows);r=next(r for r in rows if r['status']=='conditional_quote_complete');mutate(r)
   with self.assertRaises(ValueError):audit.audit_rows(rows)

 def test_identity_rule_unknown_and_budget_drift(self):
  for mutate in [lambda r:r.update(stratum=1),lambda r:r.update(anchor_notional_exceeds_budget=True),
      lambda r:r['entry_rules']['lighter'].update(price_grid='known_pass'),lambda r:r.update(funding_unknown=False)]:
   rows=copy.deepcopy(self.rows);r=next(r for r in rows if r['status']=='conditional_quote_complete');mutate(r)
   with self.assertRaises(ValueError):audit.audit_rows(rows)

 def test_numeric_limits_before_fraction(self):
  self.assertEqual(audit.number('1/73'),F(1,73))
  self.assertEqual(audit.number('1.2345678901234567890123456789'),F('1.2345678901234567890123456789'))
  for bad in [True,None,'1e999999','NaN','Infinity','9'*161,'1/0','1/'+'1'*65]:
   with self.subTest(bad=str(bad)):
    with self.assertRaises(ValueError):audit.number(bad)

 def test_completed_publication_and_corrupted_attestation(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);stage,pins=publication_fixture(root)
   with patch.object(audit,'ROOT',root),patch.object(audit,'PINS',pins):
    self.assertEqual(audit.publication(stage)['status'],'PASS')
    manifest=json.loads((stage/'manifest.json').read_bytes());original=copy.deepcopy(manifest);manifest['outputs']['quotes.jsonl.gz']['sha256']='0'*64
    (stage/'manifest.json').write_text(json.dumps(manifest))
    with self.assertRaisesRegex(ValueError,'published_output_hashes'):audit.publication(stage)
    summary=json.loads(gzip.decompress((stage/'summary.json.gz').read_bytes()));summary['terminals']['1939Z']['records']-=1
    packed=gzip.compress(json.dumps(summary).encode());delta=len(packed)-(stage/'summary.json.gz').stat().st_size;(stage/'summary.json.gz').write_bytes(packed)
    original['outputs']['summary.json.gz']=dict(bytes=len(packed),sha256=audit.digest(packed));original['new_physical_bytes_before_manifest']+=delta;original['category_bytes_before_manifest']['summary']+=delta
    (stage/'manifest.json').write_text(json.dumps(original))
    with self.assertRaisesRegex(ValueError,'terminal_attestation'):audit.publication(stage)

 def test_summary_mutations_and_input_hash_refusal(self):
  expected=audit.summary_expectation(self.rows)
  for key in ('adjusted_median','adjusted_max'):
   altered=copy.deepcopy(expected);next(g for g in altered['groups'] if g['conditional_quote_complete'])[key]='999'
   with self.assertRaises(ValueError):audit.compare(altered,expected)
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);stage,pins=publication_fixture(root)
   (root/audit.NEW[0]).write_bytes(b'changed source')
   with patch.object(audit,'ROOT',root),patch.object(audit,'PINS',pins):
    with self.assertRaisesRegex(ValueError,'actual_input_hash'):audit.publication(stage)


if __name__=='__main__':unittest.main()
