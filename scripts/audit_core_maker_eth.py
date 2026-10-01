"""Independent raw-book walks and Decimal wallet/inventory/capital reconciliation."""
import collections,gzip,hashlib,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.core_maker_events import iter_events
from scripts.core_maker_capture import OUT,PLAN,sha
R=ROOT/'reports/core-maker-eth/result';NS=10**9

def run():
 s=json.loads(gzip.decompress((R/'summary.json.gz').read_bytes()));assert s['error'] is None and s['completion_marker_received']
 a=[json.loads(x) for x in gzip.decompress((R/'audit.jsonl.gz').read_bytes()).splitlines()]
 assert len(a)==s['audit_records'] and sha(R/'audit.jsonl.gz')==s['audit_sha256']
 fills=[r for r in a if r['event']=='fill'];times={(f['source_venue'],f['ns']) for f in fills if not f['maker']}
 books={};trades={};clock=collections.defaultdict(list);end=None
 for e in iter_events(OUT,expected_manifest_sha256=s['manifest_sha256'],hedge_venue='lighter',max_raw_bytes=1507328):
  if e['type']=='book':
   clock[e['venue']].append((e['received_ns'],e['source_ns'],e['generation']))
   if (e['venue'],e['received_ns']) in times:books[(e['venue'],e['received_ns'])]=e
  elif e['type']=='trade':trades[(e['received_ns'],str(e['trade_id']))]=e
  elif e['type']=='end':end=e
 assert end and len(books)==len(times)
 consumed={};walks=0;flows=0;results={}
 for label,b in s['branches'].items():
  rows=[r for r in a if r['branch']==label];ff=[r for r in rows if r['event']=='fill']
  cash=collections.defaultdict(lambda:D(0));pos=collections.defaultdict(lambda:D(0));lots={'maker':[],'hedge':[]};capital=D(0);base=D(0);previous=None
  for f in ff:
   qty,value=D(f['qty']),D(f['value']);role=f['venue'];source={'maker':'rh_lighter','hedge':'lighter'}[role]
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
   rules=end['metadata']['markets'][source]['ETH'];step=D(rules['qty_step']);assert qty%step==0
   if f['maker']:
    name='maker_increment' if f['side']=='buy' else 'passive_maker_sell_increment'
    candidates=[r for r in rows if r['event']==name and r['ns']==f['ns'] and D(r['qty'])==qty]
    assert candidates
    t=trades[(f['ns'],str(candidates[0]['trade_id']))]
    assert t['venue']=='rh_lighter' and 0<=t['received_ns']-t['source_ns']<=2*NS and D(str(t['qty']))>=qty
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
    # Entry and passive-cover intents explicitly log their deadlines.
    schedule='hedge_scheduled' if f['side']=='sell' and role=='hedge' else 'passive_hedge_buy_scheduled' if role=='hedge' else None
    if schedule:
     candidates=[r for r in rows if r['event']==schedule and r['due_ns']<=f['ns'] and r['ns']<f['ns']]
     # A taker fallback cover need not have a passive-buy intent.
     matched=[r for r in candidates if f['ns']-r['ns']<=3*NS and D(r['qty'])>=qty]
     if matched:
      intent=matched[-1];assert intent['due_ns']-intent['ns']==400_000_000 and book['source_ns']>=intent['due_ns']
      earlier=[z for z in clock[source] if intent['due_ns']<=z[0]<f['ns'] and z[1]>=intent['due_ns'] and 0<=z[0]-z[1]<=2*NS]
      assert not earlier,(label,'not_first_eligible',earlier[0])
    walks+=1
  if previous is not None:capital+=base*D(end['stopped_ns']-previous)*D('.05')/D(365*86400*NS)
  assert cash['maker']==D(b['cash_maker_usdg']) and cash['hedge']==D(b['cash_hedge_usdc'])
  assert pos['maker']==D(b['maker_position']) and pos['hedge']==D(b['hedge_position'])
  assert D(b['fees_maker'])==D(b['fees_hedge'])==0
  assert abs(capital-D(b['capital_cost']))<D('0.00000001')
  for episode in b['episodes']:
   scoped=[f for f in ff if episode['decided_ns']<=f['ns']<=episode['flat_ns']]
   c=sum((D(f['value'])*(1 if f['side']=='sell' else -1) for f in scoped),D(0));assert c==D(episode['cash_known'])
   assert not scoped or len({f['ns']//(3600*NS) for f in scoped})==1
   reserve=max(D(episode['entry_maker_notional']),D(episode['entry_hedge_notional']))*D('.0005');assert reserve==D(episode['reserve_cost'])
   if not episode.get('execution_unknown') and not episode['funding_unknown']:
    assert D(episode['fee_only_net'])==c and D(episode['stressed_net'])==c-reserve-D(episode['capital_cost'])
  results[label]={'fills':len(ff),'cash_maker':str(cash['maker']),'cash_hedge':str(cash['hedge']),'maker_position':str(pos['maker']),'hedge_position':str(pos['hedge']),'capital_recomputed':str(capital)}
 out={'audit':'passed','raw_taker_walks':walks,'maker_flow_matches':flows,'branches':results,'summary_sha256':sha(R/'summary.json.gz'),'audit_trace_sha256':sha(R/'audit.jsonl.gz'),'limitations':'Public trade flow and queue assumptions are conditional maker evidence. Checks retain branch unknowns and do not authenticate ACKs/fills. Taker deadline check independently covers logged entry/passive-cover intents; fallback timing follows frozen engine and synthetic tests.'}
 with (R/'independent-audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':run()
