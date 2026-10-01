"""Supplemental independent cash take-profit checks from saved public books."""
import gzip,json,hashlib,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def dec(x):return D(str(x))
def main(name):
 assert name in ('core-spot-perp-limits','core-spot-perp-limits-retry')
 out=ROOT/'reports'/name;rows=[json.loads(l) for l in gzip.decompress((out/'events.jsonl.gz').read_bytes()).splitlines()]
 positions={(r['branch'],r['data']['id']):r['data'] for r in rows if r['kind']=='terminal_position'}
 checked=[]
 for r in rows:
  if r['kind']!='exit_request' or r['data']['reason']!='take_profit':continue
  d=r['data'];p=positions[(r['branch'],d['position_id'])];now=dec(d['requested_at']);mark=D(0);cap=D(0)
  assert len(d['books'])==2
  assert abs(dec(d['books'][0]['received'])-dec(d['books'][1]['received']))<=D('.25')
  for leg,b in zip(p['legs'],d['books']):
   assert b['valid'] and b['venue']==leg['venue'] and b['market']==leg['market']
   assert 0<=now-dec(b['received'])<=2 and 0<=now-dec(b['engine_time'])<=2
   assert dec(b['engine_time'])<=dec(b['received'])
   assert int(dec(leg['entry_time'])//3600)==int(now//3600)
   assert all(dec(f['timestamp'])>now for f in leg['exit_fills'])
   assert dec(leg['fees_usd'])==0
   q=dec(leg['quantity']);left=q;value=D(0)
   for price,size in b['bids' if leg['side']=='long' else 'asks']:
    take=min(left,dec(size));left-=take;value+=take*dec(price)
    if left==0:break
   assert left==0
   mark+=(value-dec(leg['entry_value']))*(1 if leg['side']=='long' else -1)
   cap+=(now-dec(leg['entry_time']))*dec(leg['entry_value'])*D('.05')/D(365*86400)
  net=mark-cap;assert abs(net-dec(d['estimated_net_pnl_usd']))<D('1e-8') and net>=D('.01')
  checked.append({'branch':r['branch'],'position_id':p['id'],'request_time':str(now),'cash_mark':str(mark),'capital_mark':str(cap),'net_mark':str(net),'eventual_cash':str(dec(p['price_pnl'])-dec(p['fees_usd'])),'exit_request_to_final_fill_seconds':str(dec(p['closed_at'])-now)})
 result={'status':'passed','take_profit_marks_checked':len(checked),'cases':checked,'raw_sha256':hashlib.sha256((out/'events.jsonl.gz').read_bytes()).hexdigest(),'checks':'Every recorded take-profit reconstructed independently from saved quote depth and actual entry costs; receipt/source freshness, receive skew, time-before-exit, same funding hour, zero fees and capital.1cent decision threshold.','limitations':'Does not assert a take-profit trigger was available earlier than the recorded request; private execution remains unverified.'}
 body=(json.dumps(result,indent=2)+'\n').encode();assert len(body)<8192
 with (out/'exit-mark-audit.json').open('xb') as f:f.write(body)
 print(body.decode())
if __name__=='__main__':main(sys.argv[1])
