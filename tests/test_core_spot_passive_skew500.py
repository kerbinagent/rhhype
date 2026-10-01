import sys
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_hysteresis_branch import CashRetentionSpotBranch as SpotPassiveBranch
from scripts.core_passive_hedged_base import Config,NS,Book
from scripts.replay_core_spot_passive import role_event

def make():
 rules=dict(price_tick='.01',qty_step='.01',min_qty='.01',min_notional='10',max_qty=None,max_quote='100000',maker_fee_bps='0',taker_fee_bps='0')
 md={'maker':{'UNI':dict(rules,venue='lighter',market='2051',market_kind='spot')},'hedge':{'UNI':dict(rules,venue='lighter',market='30',market_kind='perp')}}
 cfg=Config('UNI',D(100),'fixed_best',maker_latency_ns=100_000_000,max_pair_skew_ns=500_000_000,hedge_limit_bps=D(1),take_profit_usd=D('.01'))
 b=SpotPassiveBranch(cfg,md,exit_policy='control10s');b.capture_start_ns=0
 return b

def book(role,t,bid,ask,qty='20'):
 return dict(type='book',venue='lighter' if role=='spot' else 'rh_lighter',asset='UNI',received_ns=t,source_ns=t,generation='g',clock_valid=True,bids=[[str(bid),qty]],asks=[[str(ask),qty]])

def warm(b,t):
 b.books={'maker':Book.parse(book('spot',t,100,'100.2')), 'hedge':Book.parse(book('perp',t,'100.25','100.27'))}
 b.references.extend((t-i*NS,D(0)) for i in range(120,1,-2));b.last_sample=t-2*NS

def test_sixty_past_references_forecast_and_missing_span():
 b=make();t=200*NS;warm(b,t)
 d=b.model(t);assert d['reason']=='quote' and d['reference_count']==60 and D(d['forecast_cash_after_capital'])>D('.01')
 b._on_diagnostic({},t);assert b.quote and b.quote.price==D("100.01") and b.quote.qty==D('.99')
 c=make();warm(c,t);c.references.clear();c.references.extend((t-i*NS//2,D(0)) for i in range(120,1,-2));assert c.model(t)['reason']=='reference_warmup'

def test_spot_cash_does_not_count_perp_proceeds_as_cash():
 b=make();t=200*NS
 b._apply_fill('maker','buy',D('.99'),D(99),t,True)
 b._apply_fill('hedge','sell',D('.99'),D('99.2475'),t)
 s=b.cash_state();assert D(s['actual_cash_usdc'])==501 and D(s['perp_margin_usdc'])==D('99.2475')
 b._apply_fill('maker','sell',D('.99'),D('99.1'),t)
 b._apply_fill('hedge','buy',D('.99'),D('99.2'),t)
 assert D(b.cash_state()['actual_cash_usdc'])==D('600.1475')

def test_partial_public_flow_below_hedge_minimum_retains_inventory_unknown():
 b=make();t=200*NS;warm(b,t);b._on_diagnostic({},t)
 b.process(book('spot',t+100_000_000,100,'100.2',qty='.20'))
 # Better bid has zero displayed queue at activation; first public sell fills.
 trade=dict(type='trade',venue='lighter',asset='UNI',received_ns=t+200_000_000,source_ns=t+200_000_000,generation='g',clock_valid=True,side='sell',price='100',qty='.20',trade_id=1)
 trade.update(qty='.05');b.process(trade);assert b.maker_pos==D('.05') and b.hedge_pos==0
 b.process(book('perp',t+600_000_000,'100.25','100.27'))
 assert b.counts.get('hedge_lot_or_min_reject')==1 and b.hedge_pos==0
 b.process(book('spot',t+1_000_000_000,100,'100.2'))
 assert b.unknown_reason=='exit_order_lot_or_minimum_unknown' and b.maker_pos==D('.05')
 assert D(b.cash_state()['actual_cash_usdc'])<595

def test_real_source_identity_survives_internal_role_alias():
 raw=dict(type='book',venue='lighter',asset='UNI_perp',market='30')
 e=role_event(raw);assert e['venue']=='rh_lighter' and e['source_venue']=='lighter' and e['source_market']=='30' and e['market_kind']=='perp' and e['asset']=='UNI'

def test_independent_audit_complete_profitable_synthetic_cycle():
 import tempfile,json,gzip,datetime
 from unittest.mock import patch
 import scripts.audit_core_spot_passive_skew500 as audit
 from scripts.core_spot_passive_capture import sha
 b=make();trace=[];b.audit_sink=lambda r:trace.append({'branch':'UNI',**r})
 raw=[]
 def send(e):
  e=dict(e);kind='spot' if e.get('venue')=='lighter' else 'perp'
  if e.get('asset'):e.update(venue='lighter',asset='UNI_'+kind,market='2051' if kind=='spot' else '30')
  raw.append(e);r=role_event(e);b.process(r,{} if r['type']=='book' else None)
 for sec in range(1,122):
  send(book('spot',sec*NS,100,'100.2'));send(book('perp',sec*NS,'100.21','100.22'))
 t=122*NS;send(book('spot',t,100,'100.2'));send(book('perp',t,'100.35','100.37'))
 assert b.quote
 send(book('perp',t+50_000_000,'100.25','100.27'))
 send(book('spot',t+100_000_000,100,'100.2',qty='20'))
 send(dict(type='trade',venue='lighter',asset='UNI',received_ns=t+200_000_000,source_ns=t+200_000_000,generation='g',clock_valid=True,side='sell',price='100',qty='1.19',trade_id=1))
 send(book('perp',t+600_000_000,'100.25','100.27'));send(book('spot',t+600_000_000,100,'100.2'))
 send(book('perp',123*NS,'100.05','100.07'));send(book('spot',123*NS,100,'100.2'))
 send(book('spot',123*NS+400_000_000,100,'100.2'));send(book('perp',123*NS+400_000_000,'100.05','100.07'))
 send(book('spot',125*NS,100,'100.2'));send(book('perp',125*NS,'100.05','100.07'))
 assert any(r['event']=='inside_quote_check' and r['reason']=='quote' and D(r['excursion_bps'])<5 for r in trace)
 assert len(b.episodes)==1 and D(b.episodes[0]['stressed_net'])>0 and b.maker_pos==b.hedge_pos==0
 end=dict(type='end',received_ns=125*NS,stopped_ns=125*NS);raw.append(end);b.process(end)
 with tempfile.TemporaryDirectory(prefix='spot-passive-audit-') as tmp:
  out=Path(tmp)/'capture';r=Path(tmp)/'result';(out/'metadata').mkdir(parents=True);r.mkdir();plan=Path(tmp)/'plan.json';plan.write_text(json.dumps({'source_pins':[]}))
  (out/'manifest.json').write_text(json.dumps({'started_utc':datetime.datetime.fromtimestamp(0,datetime.timezone.utc).isoformat()}))
  (out/'metadata/normalized.json').write_text(json.dumps({'markets':b.metadata}))
  (r/'audit.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(x) for x in trace)+'\n').encode(),mtime=0))
  s=dict(error=None,completion_marker_received=True,plan_sha256=sha(plan),manifest_sha256=sha(out/'manifest.json'),audit_sha256=sha(r/'audit.jsonl.gz'),audit_records=len(trace),branches={'UNI':b.summary()})
  (r/'summary.json.gz').write_bytes(gzip.compress(json.dumps(s).encode(),mtime=0))
  with patch.object(audit,'OUT',out),patch.object(audit,'R',r),patch.object(audit,'PLAN',plan),patch.object(audit,'iter_events',lambda *a,**kw:iter(raw)):audit.run()
  result=json.loads((r/'independent-audit.json').read_bytes());assert result['audit']=='passed' and result['checks']['taker_walks']==3 and result['checks']['maker_flow_matches']==1 and result['checks']['take_profit_marks']==1


def test_inside_cost_and_resting_price_policy():
 from scripts.core_spot_passive_branch import SpotPassiveBranch as Join
 b=make();t=200*NS;warm(b,t)
 baseline=Join.model(b,t);inside=b.model(t)
 assert D(baseline['forecast_cash_after_capital'])-D(inside['forecast_cash_after_capital'])>D('.0099')
 b._on_diagnostic({},t)
 e=book('spot',t+100_000_000,'100.02','100.2');e['bids'].append(['100','20']);b.process(e,{})
 assert b.quote.activated_ns and b.quote.cancel_due_ns is None and b.quote.price==D('100.01')
 b.process(book('perp',t+200_000_000,'99.99','100.01'),{})
 assert b.quote.cancel_reason=='model_reprice_or_threshold'

def test_strict_postonly_and_retained_depth():
 b=make();t=200*NS;warm(b,t)
 b.books['maker']=Book.parse(book('spot',t,100,'100.01'))
 assert b.model(t)['reason']=='post_only_cross'
 b=make();warm(b,t);b._on_diagnostic({},t)
 b.process(book('spot',t+100_000_000,'100.02','100.2'))
 assert b.unknown_reason=='activation_price_outside_retained_depth'


def test_active_quote_keeps_cash_edge_below_entry_excursion_gate():
 b=make();t=200*NS;warm(b,t);b._on_diagnostic({},t)
 b.references.clear();b.references.extend((t-i*NS,D('11.5')) for i in range(120,1,-2))
 b.process(book('spot',t+100_000_000,100,'100.2'),{})
 diag=b.model(t+100_000_000)
 assert 0<D(diag['excursion_bps'])<5 and D(diag['forecast_cash_after_capital'])>=D('.01')
 assert diag['reason']=='quote' and b.quote.cancel_due_ns is None
 c=make();warm(c,t);c.references.clear();c.references.extend((t-i*NS,D('11.5')) for i in range(120,1,-2))
 c._on_diagnostic({},t);assert c.quote is None and c.model(t)['reason']=='under_5bp_excursion'


def test_500ms_skew_bound_and_unchanged_absolute_age():
 from dataclasses import replace
 b=make();t=200*NS;warm(b,t)
 b.books['maker']=Book.parse(book('spot',t-490_000_000,100,'100.2'))
 assert b._fresh_pair(t)
 original=replace(b.cfg,max_pair_skew_ns=250_000_000);saved=b.cfg;b.cfg=original
 assert not b._fresh_pair(t);b.cfg=saved
 b.books['maker']=Book.parse(book('spot',t-501_000_000,100,'100.2'))
 assert not b._fresh_pair(t)
 b.books['maker']=Book.parse(book('spot',t-2*NS-1,100,'100.2'))
 b.books['hedge']=Book.parse(book('perp',t-2*NS-1,'100.25','100.27'))
 assert not b._fresh_pair(t)
