"""One exploratory fair-value policy on an already completed, retained capture."""
import datetime,gzip,json,sys
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_fair_value import FairValueBranch
from scripts.core_passive_hedged_base import Config,NS
from scripts.core_passive_lit_capture import OUT,PLAN as CAPTURE_PLAN,SELECTED,sha,verify_metadata
from scripts.core_passive_lit_events import iter_events
from scripts.core_rh_small_shortterm import Archive
PLAN=ROOT/'reports/experiment-storage/core-passive-fair-value-v1.json'
RESULT=ROOT/'reports/core-passive-fair-value';LABEL='100-fair6bp-100ms-control10s'
def encode(x):return (json.dumps(x,default=str,separators=(',',':'))+'\n').encode()
def run():
 p=json.loads(PLAN.read_bytes())
 for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 cp=json.loads(CAPTURE_PLAN.read_bytes())
 for pin in cp['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 assert sha(OUT/'manifest.json')==p['manifest_sha256']
 meta=verify_metadata(OUT/'metadata',SELECTED,sha(CAPTURE_PLAN))['markets']
 RESULT.mkdir(exist_ok=False);audit=Archive(RESULT/'audit.jsonl.gz',81920)
 def sink(row):audit.add({'branch':LABEL,**row})
 cfg=Config('LIT',D(100),'adaptive',maker_latency_ns=100_000_000,cancel_latency_ns=400_000_000,maker_taker_latency_ns=400_000_000,hedge_ioc_latency_ns=400_000_000,quote_rest_ns=5*NS,hold_ns=10*NS,max_pair_skew_ns=250_000_000,max_book_age_ns=2*NS,reserve_bps=D(5),take_profit_usd=D('.06'),max_audit=32,max_episodes=256)
 b=FairValueBranch(cfg,meta,exit_policy='control10s',audit_sink=sink)
 manifest=json.loads((OUT/'manifest.json').read_bytes());b.capture_start_ns=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
 counts=Counter();end=None;error=None
 try:
  for event in iter_events(OUT,expected_manifest_sha256=p['manifest_sha256'],hedge_venue='rh_lighter',max_raw_bytes=3276800,max_decoded_bytes=128*1024*1024,max_records=100000,max_ids=100000):
   counts[event['type']]+=1
   if event['type']=='end':end=event
   b.process(event,{} if event['type']=='book' else None)
 except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
 finally:audit.close()
 s={'schema':'core-passive-fair-value-exploratory-v1','exploratory':True,'actual_pnl':None,'error':error,'completion_marker_received':end is not None,'manifest_sha256':p['manifest_sha256'],'plan_sha256':sha(PLAN),'audit_sha256':sha(RESULT/'audit.jsonl.gz'),'audit_records':audit.count,'audit_bytes':audit.bytes,'counts':dict(counts),'adapter_end':end,'branches':{LABEL:b.summary()},'scope':'Existing capture reused after its outcomes were seen; not prospective evidence. One independent100perleg400prefunded portfolio. Public-flow queue/ACK/IOC/parity assumptions inherited.'}
 packed=gzip.compress(encode(s),mtime=0);assert len(packed)<=32768;(RESULT/'summary.json.gz').write_bytes(packed)
 eps=s['branches'][LABEL]['episodes'];known=[e for e in eps if not e.get('execution_unknown') and not e['funding_unknown'] and D(e['maker_attributed'])>0]
 metrics={'error':error,'completion_marker_received':end is not None,'quotes':b.counts.get('quote_requested',0),'flow_closes':len(known),'paired_closes':sum(D(e.get('entry_hedge_qty','0'))==D(e['maker_attributed']) for e in known),'positive_cash':sum(D(e['fee_only_net'])>0 for e in known),'positive_stressed':sum(D(e['stressed_net'])>0 for e in known),'cash':str(sum((D(e['fee_only_net']) for e in known),D(0))),'stress':str(sum((D(e['stressed_net']) for e in known),D(0))),'unknown_reason':b.unknown_reason,'complete_net':s['branches'][LABEL]['complete_net'],'summary_sha256':sha(RESULT/'summary.json.gz')}
 (RESULT/'metrics.json').write_bytes(encode(metrics));print(json.dumps(metrics,indent=2))
if __name__=='__main__':run()
