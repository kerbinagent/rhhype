"""Post-hoc price-drift decomposition; no new strategy, fills, or live data."""
import collections,csv,datetime,gzip,io,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_lit_capture import OUT,sha
from scripts.core_passive_lit_events import iter_events
PLAN=ROOT/'reports/experiment-storage/core-maker-hedge-drift-v1.json'
RESULT=ROOT/'reports/core-maker-hedge-drift'
NS=10**9

def walk(levels,qty):
 left=qty;value=D(0)
 for p,q in levels:
  take=min(left,D(str(q)));value+=take*D(str(p));left-=take
  if not left:break
 return qty-left,value

def run():
 plan=json.loads(PLAN.read_bytes())
 for pin in plan['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
 state={};traces={};timed=collections.defaultdict(list);results=[];snapshots={}
 for run in plan['inputs']:
  source=ROOT/run['summary'];s=json.loads(gzip.decompress(source.read_bytes()));assert s['completion_marker_received'] and not s['error']
  assert sha(source)==run['summary_sha256'];rows=[json.loads(x) for x in gzip.decompress((source.parent/'audit.jsonl.gz').read_bytes()).splitlines()]
  assert sha(source.parent/'audit.jsonl.gz')==s['audit_sha256']
  for label in s['branches']:
   key=source.parent.name+':'+label;traces[key]=[r for r in rows if r['branch']==label];state[key]={}
   for index,row in enumerate(traces[key]):timed[row['ns']].append((key,index,row))
 for event in iter_events(OUT,expected_manifest_sha256=plan['manifest_sha256'],hedge_venue='rh_lighter',max_raw_bytes=3276800):
  now=event.get('received_ns');venue=event.get('venue')
  for key,books in state.items():
   if event['type']=='book':books[venue]=dict(event)
   if event['type']=='invalidate':books.pop(venue,None)
  for key,index,row in timed.pop(now,[]):
   books=state[key]
   if row['event']=='fill' and row['maker'] and row['side']=='buy':
    qty=D(row['qty']);book=books.get('rh_lighter');assert book
    found,value=walk(book['bids'],qty)
    snapshots[(key,index)]={'qty':qty,'value':value,'found':found,'book_ns':book['received_ns'],'source_ns':book['source_ns'],'fill_ns':now,'maker_value':D(row['value'])}
   if row['event']=='hedge_result':
    trace=traces[key];prior=[(j,r) for j,r in enumerate(trace[:index]) if r['event']=='hedge_scheduled']
    assert prior;intent_i,intent=prior[-1]
    maker_i=next(j for j in range(intent_i-1,-1,-1) if trace[j]['event']=='fill' and trace[j]['maker'] and trace[j]['side']=='buy')
    snap=snapshots[(key,maker_i)];qty=D(row['requested']);assert qty==snap['qty']
    # Taker fills precede hedge_result in the trace. Rebuild first eligible
    # book's pre-fill proceeds from current remaining depth plus actual fill.
    actual=D(row['filled']);actual_value=sum((D(r['value']) for r in trace[intent_i+1:index] if r['event']=='fill' and r['side']=='sell' and r['venue']=='hedge' and r['ns']==now),D(0))
    book=books['rh_lighter'];left=qty-actual;found,value=walk(book['bids'],left);value+=actual_value;found+=actual
    instant_ok=snap['found']==qty and 0<=snap['fill_ns']-snap['book_ns']<=2*NS and 0<=snap['fill_ns']-snap['source_ns']<=2*NS
    out={'branch':key,'maker_fill_ns':snap['fill_ns'],'hedge_result_ns':now,'delay_ms':str(D(now-snap['fill_ns'])/1000000),'qty':str(qty),'maker_price':str(snap['maker_value']/qty),'instant_reference_valid':instant_ok,'instant_book_age_ms':str(D(snap['fill_ns']-snap['source_ns'])/1000000),'instant_sell_value':str(snap['value']),'hedge_filled_qty':str(actual),'hedge_actual_proceeds':str(actual_value),'hedge_limit':row['limit'],'delayed_full_depth':found==qty,'delayed_unlimited_sell_value':str(value),'proceeds_deterioration_usd':str(snap['value']-value) if instant_ok and found==qty else None,'proceeds_deterioration_bps':str((snap['value']-value)/snap['value']*10000) if instant_ok and found==qty else None,'instant_entry_spread_usd':str(snap['value']-snap['maker_value']) if instant_ok else None,'delayed_unlimited_entry_spread_usd':str(value-snap['maker_value']) if found==qty else None}
    assert book['source_ns']>=intent['due_ns'] and intent['due_ns']-intent['ns']==400_000_000
    results.append(out)
   if row['event']=='fill' and not row['maker']:
    b=books[row['source_venue']];side='asks' if row['side']=='buy' else 'bids';left=D(row['qty']);levels=[]
    for p,q in b[side]:
     p,q=D(str(p)),D(str(q));take=min(q,left);q-=take;left-=take
     if q:levels.append([p,q])
    assert left==0;b[side]=levels
 assert len(results)==5
 RESULT.mkdir(exist_ok=False)
 summary={'schema':'core-maker-hedge-drift-v1','exploratory_post_hoc':True,'actual_pnl':None,'plan_sha256':sha(PLAN),'rows':results,'scope':'Existing100ms/400msfixed-offset arms and fair-value arm overlap; rows are not independent and must not be summed as a portfolio. Instant/delayed unlimited depths are hypothetical executable quotes, not authenticated fills. No hypothetical round-trip profit calculated. Late flow and public trade reporting delays remain unobserved latency components.'}
 packed=gzip.compress((json.dumps(summary,default=str)+'\n').encode(),mtime=0);assert len(packed)<=8192
 (RESULT/'summary.json.gz').write_bytes(packed)
 print(json.dumps(results,indent=2))
if __name__=='__main__':run()
