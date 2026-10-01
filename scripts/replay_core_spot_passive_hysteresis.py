"""Frozen one-tick-inside LIT $100 spot/perp scenario; run only after fixed capture endpoint."""
import gzip,json,sys,datetime
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_spot_passive_capture import OUT,PLAN,ASSETS,HARD_BYTES,SELECTED,verify_metadata,sha
from scripts.core_spot_passive_events import iter_events
from scripts.core_spot_passive_branch import SpotPassiveBranch
from scripts.core_passive_hedged_base import Config,NS
from scripts.core_rh_small_shortterm import Archive
R=ROOT/'reports/core-spot-passive/result'
def role_event(event):
 e=dict(event)
 if e.get('asset'):
  asset,kind=e['asset'].rsplit('_',1);assert kind in ('spot','perp') and e['venue']=='lighter'
  e.update(asset=asset,source_venue='lighter',source_market=e['market'],market_kind=kind,venue='lighter' if kind=='spot' else 'rh_lighter',internal_role_alias=True)
 return e

def run(manifest_hash):
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 assert sha(OUT/'manifest.json')==manifest_hash
 m=json.loads((OUT/'manifest.json').read_bytes());assert m['end_reason']=='duration_limit' and not m['truncated']
 metadata=verify_metadata(OUT/'metadata',SELECTED,sha(PLAN))['markets']
 R.mkdir(exist_ok=False);audit=Archive(R/'audit.jsonl.gz',1572864)
 branches=[];counts=Counter();ended=None;error=None
 for asset in ASSETS:
  cfg=Config(asset,D(100),'fixed_best',maker_latency_ns=100_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,quote_rest_ns=5*NS,hold_ns=10*NS,max_pair_skew_ns=250_000_000,max_book_age_ns=2*NS,hedge_limit_bps=D(1),reserve_bps=D(5),take_profit_usd=D('.01'),max_audit=32,max_episodes=64)
  def sink(row,label=asset):audit.add({'branch':label,**row})
  b=SpotPassiveBranch(cfg,metadata,exit_policy='control10s',audit_sink=sink)
  b.capture_start_ns=int(datetime.datetime.fromisoformat(m['started_utc']).timestamp()*NS);branches.append(b)
 try:
  for raw in iter_events(OUT,expected_manifest_sha256=manifest_hash,max_raw_bytes=HARD_BYTES):
   e=role_event(raw);counts[e['type']]+=1
   if e['type']=='end':ended=e
   for b in branches:
    if e.get('asset') not in (None,b.cfg.asset):continue
    b.process(e,{} if e['type']=='book' else None)
 except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
 finally:audit.close()
 summary={'schema':'core-spot-passive-v1','error':error,'completion_marker_received':ended is not None,'manifest_sha256':manifest_hash,'plan_sha256':sha(PLAN),'audit_sha256':sha(R/'audit.jsonl.gz'),'audit_records':audit.count,'audit_bytes':audit.bytes,'counts':dict(counts),'adapter_end':ended,'branches':{b.cfg.asset:b.summary() for b in branches},'actual_pnl':None,'scope':'One LIT $600 USDC portfolio, $100 per leg. One tick inside bid at admission; keep existing quote price only while fresh cash forecast passes;5bp excursion gate applies only at admission. Spot-long only, no borrow. Public queue/trade/ACK assumptions are conditional, not real fills. Perp uses same Core USDC, no parity conversion. Published minima enforced. Internal rh_lighter event alias means hedge role only; source remains Core.'}
 packed=gzip.compress((json.dumps(summary,default=str,separators=(',',':'))+'\n').encode(),mtime=0);assert len(packed)<=131072
 (R/'summary.json.gz').write_bytes(packed)
 metrics={}
 for label,b in summary['branches'].items():
  eps=b['episodes'];known=[e for e in eps if not e.get('execution_unknown') and not e['funding_unknown'] and D(e['maker_attributed'])>0]
  paired=[e for e in known if D(e['entry_hedge_qty'])==D(e['maker_attributed'])]
  metrics[label]={'attempts':b['counts'].get('quote_requested',0),'episodes':len(eps),'known_flow_closes':len(known),'paired_flow_closes':len(paired),'rescue_closes':len(known)-len(paired),'cash_sum':str(sum((D(e['fee_only_net']) for e in known),D(0))),'stressed_sum':str(sum((D(e['stressed_net']) for e in known),D(0))),'cash_wins':sum(D(e['fee_only_net'])>0 for e in known),'stressed_wins':sum(D(e['stressed_net'])>0 for e in known),'unknown_episodes':sum(bool(e.get('execution_unknown') or e['funding_unknown']) for e in eps),'branch_unknown_reason':b['unknown_reason'],'spot_inventory':b['maker_position'],'perp_inventory':b['hedge_position'],'actual_cash_usdc':b['actual_cash_usdc'],'counts':b['counts']}
 result={'error':error,'completion_marker_received':ended is not None,'metrics':metrics,'summary_sha256':sha(R/'summary.json.gz')}
 (R/'metrics.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':run(sys.argv[1])
