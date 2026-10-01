"""Frozen prospective policies; offline replay only after the fixed capture endpoint."""
import gzip,hashlib,json,math,sys
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_hedged_base import Config,NS,floor_step
from scripts.core_passive_lit_branch import CorePassiveBranch
from scripts.core_passive_lit_events import iter_events
from scripts.core_passive_lit_capture import verify_metadata,SELECTED,PLAN,OUT,sha
from scripts.core_rh_small_shortterm import Archive
RESULT=ROOT/'reports/core-passive-lit/result'

def encode(x):return (json.dumps(x,default=str,separators=(',',':'),allow_nan=False)+'\n').encode()
def common_step(a,b):
 places=max(-a.as_tuple().exponent,-b.as_tuple().exponent,0);scale=D(10)**places
 return D(math.lcm(int(a*scale),int(b*scale)))/scale

def quote_diagnostic(branch,maker,hedge):
 if branch.quote is not None:return {'reason':'quote','price':str(branch.quote.price),'quantity':str(branch.quote.qty)}
 px=floor_step(D(str(maker['bids'][0][0]))*(1-D(branch.offset)/10000),branch.maker.price_tick)
 hp=D(str(hedge['bids'][0][0]));step=common_step(branch.maker.qty_step,branch.hedge.qty_step)
 qty=floor_step(branch.cfg.budget_usd/max(px,hp),step)
 reason='quote' if px>=D(str(maker['bids'][-1][0])) else 'book_depth_does_not_cover_better_queue'
 return {'reason':reason,'price':str(px),'quantity':str(qty)}

def run(manifest_hash):
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 manifest=json.loads((OUT/'manifest.json').read_bytes());assert sha(OUT/'manifest.json')==manifest_hash
 assert manifest['end_reason'] in ('duration_limit','compressed_size_cap','one_venue_ended','clock_shift')
 metadata=verify_metadata(OUT/'metadata',SELECTED,sha(PLAN))
 RESULT.mkdir(exist_ok=False);audit=Archive(RESULT/'audit.jsonl.gz',180224)
 branches=[];metadata=metadata['markets']
 for size in plan['budgets']:
  for activation_ms in plan['maker_activation_ms']:
   offset=10
   policy='control10s'
   label=f'{size}-{offset}bp-{activation_ms}ms-{policy}'
   def sink(row,label=label):audit.add({'branch':label,**row})
   cfg=Config('LIT',D(size),'adaptive',maker_latency_ns=activation_ms*1_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,quote_rest_ns=5*NS,hold_ns=10*NS,max_pair_skew_ns=250_000_000,max_book_age_ns=2*NS,reserve_bps=D(5),take_profit_usd=D(size)/10000,max_audit=32,max_episodes=256)
   branch=CorePassiveBranch(cfg,metadata,exit_policy=policy,audit_sink=sink)
   branch.label=label;branch.offset=offset;branches.append(branch)
 latest={};counts=Counter();ended=None;start=None;error=None
 try:
  import datetime
  start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
  for b in branches:b.capture_start_ns=start
  for event in iter_events(OUT,expected_manifest_sha256=manifest_hash,hedge_venue='rh_lighter',max_raw_bytes=3276800,max_decoded_bytes=128*1024*1024,max_records=100000,max_ids=100000):
   counts[event['type']]+=1
   if event['type']=='book':latest[event['venue']]=event
   elif event['type']=='invalidate':latest.pop(event['venue'],None)
   if event['type']=='end':ended=event
   now=event.get('received_ns',start)
   for b in branches:
    diag=None
    if event['type']=='book' and set(latest)==set(SELECTED):
     maker,hedge=latest['lighter'],latest['rh_lighter']
     diag=quote_diagnostic(b,maker,hedge)
     if b.quote is None:
      if not 10*NS<=now-start<480*NS:diag['reason']='outside_admission_window'
      elif b.episode_no>=100:diag['reason']='attempt_cap'
      elif now//(3600*NS)!=(now+120*NS)//(3600*NS):diag['reason']='funding_boundary_guard'
    b.process(event,diag)
 except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
 finally:audit.close()
 summary={'schema':'core-passive-lit-paper-v1','paper_conditional_only':True,'actual_pnl':None,'error':error,'completion_marker_received':ended is not None,'manifest_sha256':manifest_hash,'plan_sha256':sha(PLAN),'audit_sha256':sha(RESULT/'audit.jsonl.gz'),'audit_records':audit.count,'audit_bytes':audit.bytes,'counts':dict(counts),'adapter_end':ended,'branches':{b.label:b.summary() for b in branches},'scope':'Two independent maker-activation counterfactual ledgers with common10bp offset; do not sum overlapping policies/sizes. Public-flow queue allocation does not establish private fills/ACKs. Combined USDG/USDC cash conditional on parity. Fee-only excludes capital and5bp stress; all unknowns and open obligations retained.'}
 packed=gzip.compress(encode(summary),mtime=0);assert len(packed)<=49152
 (RESULT/'summary.json.gz').write_bytes(packed)
 metrics={}
 for label,b in summary['branches'].items():
  eps=b['episodes'];known=[e for e in eps if not e.get('execution_unknown') and not e['funding_unknown'] and D(e['maker_attributed'])>0]
  paired=[e for e in known if D(e.get('entry_hedge_qty','0'))==D(e['maker_attributed'])]
  metrics[label]={'attempts':b['counts'].get('quote_requested',0),'episodes':len(eps),'known_flow_closes':len(known),'paired_flow_closes':len(paired),'rescue_closes':len(known)-len(paired),'positive_fee_only':sum(D(e['fee_only_net'])>0 for e in known),'positive_stressed':sum(D(e['stressed_net'])>0 for e in known),'fee_only_sum':str(sum((D(e['fee_only_net']) for e in known),D(0))),'stressed_sum':str(sum((D(e['stressed_net']) for e in known),D(0))),'no_flow':sum(D(e['maker_attributed'])==0 for e in eps),'unknown_episodes':sum(bool(e.get('execution_unknown') or e['funding_unknown']) for e in eps),'branch_unknown_reason':b['unknown_reason'],'maker_position':b['maker_position'],'hedge_position':b['hedge_position'],'branch_complete_net':b['complete_net']}
 result={'error':error,'completion_marker_received':ended is not None,'metrics':metrics,'summary_sha256':sha(RESULT/'summary.json.gz')}
 (RESULT/'metrics.json').write_bytes(encode(result));print(json.dumps(result,indent=2))
if __name__=='__main__':
 if len(sys.argv)==2:run(sys.argv[1])
 else:print('Pass the externally pinned completed manifest SHA256.')
