"""Independent raw-book walks and Decimal wallet/inventory/capital reconciliation."""
import collections,gzip,hashlib,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_passive_lit_events import iter_events
from scripts.core_passive_lit_capture import OUT,PLAN,sha
R=ROOT/'reports/core-passive-lit/result';NS=10**9

def run():
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert s['error'] is None and s['completion_marker_received']
 a=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 assert len(a)==s['audit_records'] and sha(R/'audit.jsonl.gz')==s['audit_sha256']
 fills=[r for r in a if r['event']=='fill'];times={(f['source_venue'],f['ns']) for f in fills if not f['maker']}
 books={};trades={};clock=collections.defaultdict(list);end=None
 for e in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],hedge_venue='rh_lighter',max_raw_bytes=3276800):
  if e['type']=='book':
   clock[e['venue']].append((e['received_ns'],e['source_ns'],e['generation']))
   if (e['venue'],e['received_ns']) in times:books[(e['venue'],e['received_ns'])]=e
  elif e['type']=='trade':trades[(e['received_ns'],str(e['trade_id']))]=e
  elif e['type']=='end':end=e
 assert end and len(books)==len(times)
 consumed={};walks=0;flows=0;results={}
 for label,b in s['branches'].items():
  rows=[r for r in a if r['branch']==label];ff=[r for r in rows if r['event']=='fill']
  cash=collections.defaultdict(lambda:D(0));pos=collections.defaultdict(lambda:D(0));lots={'maker':[],'hedge':[]};capital=D(0);base=D(0);previous=None;used_intents=set()
  for f in ff:
   qty,value=D(f['qty']),D(f['value']);role=f['venue'];source={'maker':'lighter','hedge':'rh_lighter'}[role]
   assert f['source_venue']==source and qty>0 and value>0
   if previous is not None:capital+=base*D(f['ns']-previous)*D('.05')/D(365*86400*NS)
   previous=f['ns'];signed=qty if f['side']=='buy' else -qty
   old=pos[role];remaining=qty
   if old and (old>0)!=(signed>0):
    while remaining and lots[role]:
     take=min(remaining,lots[role][0][0]);remaining-=take;lots[role][0][0]-=take
     if not lots[role][0][0]:lots[role].pop(0)
   if remaining:lots[role].append([remaining,value/qty])
   pos[role]+=signed;cash[role]+=value if signed<0 else -value
   base=sum((q*p for ll in lots.values() for q,p in ll),D(0))
   rules=end['metadata']['markets'][source]['LIT'];step=D(rules['qty_step']);assert qty%step==0
   if f['maker']:
    name='maker_increment' if f['side']=='buy' else 'passive_maker_sell_increment'
    candidates=[r for r in rows if r['event']==name and r['ns']==f['ns'] and D(r['qty'])==qty]
    assert candidates
    t=trades[(f['ns'],str(candidates[0]['trade_id']))]
    assert t['venue']=='lighter' and 0<=t['received_ns']-t['source_ns']<=2*NS and D(str(t['qty']))>=qty
    price=value/qty;assert (t['side']=='sell' and D(str(t['price']))<=price) if f['side']=='buy' else (t['side']=='buy' and D(str(t['price']))>=price)
    flows+=1
   else:
    book=books[(source,f['ns'])];assert 0<=book['received_ns']-book['source_ns']<=2*NS
    key=(label,source,f['ns']);available=consumed.setdefault(key,{side:[[D(str(p)),D(str(q))] for p,q in book[side]] for side in ('bids','asks')})
    need=qty;cost=D(0);side='asks' if f['side']=='buy' else 'bids'
    for level in available[side]:
     take=min(need,level[1]);cost+=take*level[0];need-=take;level[1]-=take
     if not need:break
    assert not need and abs(cost-value)<D('0.00000001'),(label,cost,value)
    if role=='hedge' and f['side']=='sell':
     # Match each entry fill to its immediate hedge_result and consume one exact
     # scheduled intent. A later larger intent can share receipt time; >=qty is ambiguous.
     at=next(i for i,r in enumerate(rows) if r is f)
     result=next(r for r in rows[at+1:] if r['event']=='hedge_result')
     assert result['ns']==f['ns'] and D(result['filled'])==qty
     candidates=[(i,r) for i,r in enumerate(rows[:at]) if r['event']=='hedge_scheduled' and i not in used_intents and D(r['qty'])==D(result['requested']) and r['due_ns']<=book['source_ns']]
     assert candidates;idx,intent=candidates[0];used_intents.add(idx)
     assert intent['due_ns']-intent['ns']==400_000_000 and book['source_ns']>=intent['due_ns']
     earlier=[z for z in clock[source] if intent['due_ns']<=z[0]<f['ns'] and z[1]>=intent['due_ns'] and 0<=z[0]-z[1]<=2*NS]
     assert not earlier,(label,'not_first_eligible',earlier[0])
    elif not f['maker']:
     candidates=[r for r in rows if r['event']=='exit_requested' and r['ns']+400_000_000<=f['ns']]
     assert candidates;intent=candidates[-1];due=intent['ns']+400_000_000
     assert book['source_ns']>=due
     earlier=[z for z in clock[source] if due<=z[0]<f['ns'] and z[1]>=due and 0<=z[0]-z[1]<=2*NS]
     assert not earlier,(label,'exit_not_first_eligible',earlier[0])
    walks+=1
  if previous is not None:capital+=base*D(end['stopped_ns']-previous)*D('.05')/D(365*86400*NS)
  assert cash['maker']==D(b['cash_maker_usdc']) and cash['hedge']==D(b['cash_hedge_usdg'])
  assert pos['maker']==D(b['maker_position']) and pos['hedge']==D(b['hedge_position'])
  assert D(b['fees_maker'])==D(b['fees_hedge'])==0
  assert abs(capital-D(b['capital_cost']))<D('0.00000001')
  for episode in b['episodes']:
   starts=[i for i,r in enumerate(rows) if r['event']=='quote_requested']
   start=starts[episode['number']-1]
   stop=next(i for i in range(start+1,len(rows)) if rows[i]['event']=='episode_flat')
   assert rows[start]['ns']==episode['decided_ns'] and rows[stop]['ns']==episode['flat_ns']
   assert not any(r['event']=='quote_requested' for r in rows[start+1:stop])
   scoped=[r for r in rows[start+1:stop] if r['event']=='fill']
   c=sum((D(f['value'])*(1 if f['side']=='sell' else -1) for f in scoped),D(0));assert c==D(episode['cash_known'])
   assert not scoped or len({f['ns']//(3600*NS) for f in scoped})==1
   reserve=max(D(episode['entry_maker_notional']),D(episode['entry_hedge_notional']))*D('.0005');assert reserve==D(episode['reserve_cost'])
   if not episode.get('execution_unknown') and not episode['funding_unknown']:
    assert D(episode['fee_only_net'])==c and D(episode['stressed_net'])==c-reserve-D(episode['capital_cost'])
  results[label]={'fills':len(ff),'cash_maker':str(cash['maker']),'cash_hedge':str(cash['hedge']),'maker_position':str(pos['maker']),'hedge_position':str(pos['hedge']),'capital_recomputed':str(capital)}
 out={'audit':'passed','raw_taker_walks':walks,'maker_flow_matches':flows,'branches':results,'summary_sha256':sha(R/'summary.json.gz'),'audit_trace_sha256':sha(R/'audit.jsonl.gz'),'limitations':'Public trade flow and queue assumptions are conditional maker evidence. Checks retain branch unknowns and do not authenticate ACKs/fills. Entry intent matching consumes exact scheduled quantities in stream order; entry and control-exit first eligible timestamps checked against retained full books.'}
 with (R/'independent-audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':run()
