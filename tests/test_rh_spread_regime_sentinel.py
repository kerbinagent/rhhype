import asyncio
import gzip
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fractions import Fraction
import scripts.rh_spread_regime_sentinel as m

def markets():return [{'asset':r['asset'],'eligible':True,'reason':None,'reference':r,'market':dict(r)} for r in m.reference()]
def ticker(source=10_000_000,kind='update/ticker',channel='ticker:5',price='3.7783',ask='3.7813'):
 return json.dumps({'type':kind,'channel':channel,'ticker':{'s':'LIT','last_updated_at':source,'b':{'price':price,'size':'100'},'a':{'price':ask,'size':'100'}}})
def feed():return m.Feed(markets(),m.Clock(10*m.NS,20*m.NS))

class SentinelTests(unittest.TestCase):
 def test_future_and_receipt_mapping_cannot_poison_watermark(self):
  f=feed();f.accept(ticker(),10*m.NS,20*m.NS);self.assertEqual(f.watermarks['5'],10*m.NS)
  f.accept(ticker(source=20_000_000),10*m.NS,20*m.NS);self.assertNotIn('5',f.latest);self.assertEqual(f.watermarks['5'],10*m.NS)
  f.accept(ticker(source=15_000_000),16*m.NS,21*m.NS);self.assertNotIn('5',f.latest);self.assertEqual(f.watermarks['5'],10*m.NS)
  f.accept(ticker(source=11_000_000),11*m.NS,21*m.NS);self.assertIn('5',f.latest);self.assertEqual(f.watermarks['5'],11*m.NS)
 def test_malformed_regression_and_recovery_without_old_fallback(self):
  f=feed();f.accept(ticker(),10*m.NS,20*m.NS)
  f.accept('{bad',10*m.NS,20*m.NS);self.assertNotIn('5',f.latest)
  f.accept(ticker(source=9_000_000),10*m.NS,20*m.NS);self.assertNotIn('5',f.latest)
  f.accept(ticker(),10*m.NS,20*m.NS);self.assertIn('5',f.latest)
  f.accept(ticker(price='3.77835'),10*m.NS,20*m.NS);self.assertNotIn('5',f.latest)
 def test_errors_missing_channel_and_repeated_subscription(self):
  for raw,terminal in ((json.dumps({'type':'error','message':'bad'}),True),(ticker(channel=''),False)):
   f=feed();f.accept(ticker(),10*m.NS,20*m.NS);f.accept(raw,10*m.NS,20*m.NS)
   self.assertFalse(f.latest);self.assertEqual(f.stop_reason is not None,terminal)
  f=feed();f.accept(ticker(kind='subscribed/ticker'),10*m.NS,20*m.NS)
  f.accept(ticker(kind='subscribed/ticker'),10*m.NS,20*m.NS)
  self.assertEqual(f.stop_reason,'unexpected_subscription_generation');self.assertFalse(f.latest)
 def test_sample_age_dispatch_and_mapping_boundaries(self):
  f=feed();f.accept(ticker(),10*m.NS,20*m.NS)
  row=next(r for r in f.snapshot(0,22*m.NS,12*m.NS,22*m.NS) if r['asset']=='LIT');self.assertIsNone(row['reason'])
  row=next(r for r in f.snapshot(1,22*m.NS,12*m.NS+1,22*m.NS+1) if r['asset']=='LIT');self.assertEqual(row['reason'],'stale_source_or_receipt')
  f.accept(ticker(source=12_000_000),12*m.NS,22*m.NS)
  self.assertTrue(all(r['reason']=='dispatch_late' for r in f.snapshot(0,22*m.NS,12*m.NS+m.LATENESS+1,22*m.NS+m.LATENESS+1)))
  f.snapshot(0,22*m.NS,13*m.NS,22*m.NS);self.assertFalse(f.latest);self.assertEqual(f.watermarks['5'],12*m.NS)
 def test_exact_original_quantity_and_optimistic_budget(self):
  f=feed();f.accept(ticker(),10*m.NS,20*m.NS)
  sample=next(r for r in f.snapshot(0,20*m.NS,10*m.NS,20*m.NS) if r['asset']=='LIT')
  market=next(r for r in markets() if r['asset']=='LIT');r=m.score(sample,market,1000)
  self.assertTrue(r['valid']);self.assertEqual(r['quantity'],'264');self.assertEqual(r['optimistic_budget'],'0.1932644');self.assertEqual(r['paired_hedge_status'],'unknown')
  early=m.score(sample,market,1000,economic=False);self.assertFalse(early['valid']);self.assertNotIn('optimistic_budget',early)
  self.assertEqual(m.median([Fraction('-0.1'),Fraction('0.3')]),Fraction('.1'))
 def test_all1680keys_strict_gate_and_no_smaller_alternate(self):
  samples=m.missing_slots([],m.Clock(10*m.NS,20*m.NS),30*m.NS,'collector_stopped')
  self.assertEqual(len(samples),420);self.assertEqual(samples[-1]['k'],19)
  rows=[{'k':s['k'],'asset':s['asset'],'budget':b,'valid':False,'reason':'missing','paired_hedge_status':'unknown'} for s in samples for b in m.BUDGETS]
  for r in rows:
   if r['asset']=='LIT' and r['budget']==1000 and r['k']%5<4:r.update(valid=True,optimistic_budget='0.1' if r['k']<15 else '-0.01',positive=r['k']<15);r.pop('reason')
   if r['asset']=='BTC' and r['budget']==500:r.update(valid=True,optimistic_budget='99',positive=True);r.pop('reason')
  summary=m.summarize(rows,True);self.assertEqual(summary['later_cost_screen_candidates'],['LIT'])
  self.assertEqual(summary['unknown_paired_hedge_rows'],1680)
  next(r for r in rows if r['asset']=='LIT' and r['budget']==1000 and r['k']==0).update(valid=False,reason='missing')
  self.assertEqual(m.summarize(rows,True)['later_cost_screen_candidates'],[])
  self.assertEqual(m.summarize(rows,False)['later_cost_screen_candidates'],[])
 def test_beforewrite_caps_and_gzip_trailers(self):
  with TemporaryDirectory() as t:
   store=m.Store(t);store.write('meta.bin',b'x'*m.LIMITS['metadata'],'metadata');before=store.bytes()
   with self.assertRaises(m.CapReached):store.write('overflow.bin',b'x','metadata')
   self.assertEqual(before,store.bytes());self.assertFalse((Path(t)/'overflow.bin').exists())
   payload=gzip.compress(bytes(range(256))*100,mtime=0);store.write('samples.jsonl.gz',payload,'samples')
   self.assertEqual((Path(t)/'samples.jsonl.gz').stat().st_size,len(payload));self.assertEqual(gzip.decompress(payload),bytes(range(256))*100)
   store.verify();self.assertLessEqual(store.bytes(),500000)
 def test_numeric_exponents_and_decoded_finalization_reserve(self):
  for value in ('1e99999999','1e-99999999','9'*81):
   with self.assertRaises(ValueError):m.f(value)
  samples=m.missing_slots([],m.Clock(10*m.NS,20*m.NS),20*m.NS,'collector_stopped')
  # A highly compressible payload can exhaust decoded bytes independently.
  for s in samples[:30]:s['ticker']={'raw':'x'*50000}
  prefix=samples[:30];raw=m.compressed_samples(prefix,normal=True)
  self.assertLess(len(raw),75000)
  self.assertLessEqual(len(gzip.decompress(m.compressed_samples(samples))),2000000)
  for s in samples[30:35]:s['ticker']={'raw':'x'*50000}
  with self.assertRaises(m.CapReached):m.compressed_samples(samples[:35],normal=True)
  for s in samples[30:35]:s['ticker']=None
  self.assertEqual(len(gzip.decompress(m.compressed_samples(samples)).splitlines()),420)
 def test_metadata_age_and_no_retry_preparation_error_provenance(self):
  req={str(i):{'completed_ns':10*m.NS,'completed_mono_ns':20*m.NS} for i in range(3)}
  self.assertTrue(m.metadata_fresh(req,130*m.NS,140*m.NS));self.assertFalse(m.metadata_fresh(req,130*m.NS+1,140*m.NS))
  self.assertFalse(m.metadata_fresh(req,11*m.NS,141*m.NS))
  calls=[]
  class Fake:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def request(self,method,url,**kwargs):calls.append((method,url,kwargs));raise TimeoutError('synthetic')
  with TemporaryDirectory() as t,patch.object(m,'stage_path',return_value=Path(t)),patch.object(m,'client_session',return_value=Fake()),patch('sys.stdout',new_callable=io.StringIO):
   with self.assertRaises(TimeoutError):asyncio.run(m.prepare(Path(t)))
   self.assertEqual(len(calls),1);self.assertFalse(calls[0][2]['allow_redirects'])
   report=json.loads((Path(t)/'requests.json').read_bytes());r=next(iter(report.values()));self.assertIn('url',r);self.assertIn('started_ns',r);self.assertIn('status',r);self.assertIn('TimeoutError',r['error'])
   data=gzip.decompress((Path(t)/'observations.csv.gz').read_bytes());self.assertEqual(data.count(b'\n'),1681);m.Store(t).verify()
 def test_existing_metadata_fixture_full_stage_fits_all_final_caps(self):
  fixture=m.ROOT/'reports/passive-universe-screen/20260930T0310Z'
  replies=[(fixture/(name+'.json')).read_bytes() for name in m.REQUESTS];attempts=[]
  class Content:
   def __init__(self,raw):self.raw=raw
   async def iter_chunked(self,n):
    for k in range(0,len(self.raw),n):yield self.raw[k:k+n]
  class Response:
   status=200
   def __init__(self,raw):self.content=Content(raw)
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
  class Session:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def request(self,*a,**kw):attempts.append((a,kw));return Response(replies[len(attempts)-1])
  with TemporaryDirectory() as t,patch.object(m,'stage_path',return_value=Path(t)),patch.object(m,'client_session',return_value=Session()),patch('sys.stdout',new_callable=io.StringIO):
   asyncio.run(m.prepare(Path(t)));self.assertEqual(len(attempts),3)
   m.freeze(Path(t));store,p,req,prepared_markets=m.prepared(Path(t))
   self.assertTrue((Path(t)/'root-freeze.json').exists());self.assertEqual(len(prepared_markets),21)
   now,mono=m.utc(),m.time.monotonic_ns();clock=m.Clock(now,mono)
   store.write('schedule.json',{'t0_utc_ns':now,'t0_mono_ns':mono,'endpoint_utc_ns':now+m.DURATION,'endpoint_mono_ns':mono+m.DURATION,'slot_count':20},'control')
   samples=m.missing_slots([],clock,mono,'synthetic_missing');store.write('samples.jsonl.gz',m.compressed_samples(samples),'samples')
   rows=[m.score(s,next(x for x in prepared_markets if x['asset']==s['asset']),b,economic=False) for s in samples for b in m.BUDGETS]
   m.write_rows(store,rows);summary=m.summarize(rows,False)
   store.write('summary.json.gz',gzip.compress(m.encoded(summary),mtime=0),'derived');store.write('readout.md',m.readout(summary,'incomplete').encode(),'logs')
   store.write('manifest.json',{'status':'incomplete','completed_utc_ns':now,'economic_endpoint_reached':False,'metadata_attempts':3,'websocket_attempts':1,'input_hashes_unchanged':True,'input_hashes':p['inputs'],
     'output_hashes':{n:v['sha256'] for n,v in store.entries.items()},'cap_bytes':m.CAP,'no_automatic_followup':True,'failure_denominator_rows':1680,'source_study':'new_sampled_public_network_evidence'},'control',final=True)
   store.verify();self.assertLessEqual(store.bytes(),500000)
   control=sum(v['bytes'] for v in store.entries.values() if v['category']=='control')+store.index.stat().st_size
   self.assertLessEqual(control,90000);self.stage_fit={'aggregate_bytes':store.bytes(),'control_bytes_including_final_manifest_and_index':control};self.assertEqual(gzip.decompress((Path(t)/'observations.csv.gz').read_bytes()).count(b'\n'),1681)
 def test_freeze_expiry_preserves_all_rows_without_network(self):
  with TemporaryDirectory() as t:
   store=m.Store(t)
   with patch.object(m,'stage_path',return_value=Path(t)),patch.object(m,'prepared',return_value=(store,{}, {'x':{'completed_ns':0}},[])):
    m.freeze(Path(t))
   self.assertEqual(gzip.decompress((Path(t)/'observations.csv.gz').read_bytes()).count(b'\n'),1681)
   self.assertFalse((Path(t)/'root-freeze.json').exists());m.Store(t).verify()
 def test_schedule_cap_failure_publishes1680_before_any_websocket(self):
  with TemporaryDirectory() as t:
   path=Path(t);store=m.Store(path);inputs=m.input_hashes();p={'inputs':inputs}
   store.write('prepared.json',p,'control')
   store.write('root-freeze.json',{'inputs':inputs,'prepared_sha256':m.sha(path/'prepared.json'),'stage_hashes':{}},'control')
   requests={str(i):{'completed_ns':m.utc(),'completed_mono_ns':m.time.monotonic_ns()} for i in range(3)}
   write=store.write
   def capped(name,*a,**kw):
    if name=='schedule.json':raise m.CapReached('synthetic_schedule_cap')
    return write(name,*a,**kw)
   with patch.object(m,'stage_path',return_value=path),patch.object(m,'prepared',return_value=(store,p,requests,markets())),patch.object(store,'write',side_effect=capped),patch.object(m,'receive',side_effect=AssertionError('network_forbidden')):
    asyncio.run(m.run(path))
   self.assertEqual(gzip.decompress((path/'observations.csv.gz').read_bytes()).count(b'\n'),1681)
   self.assertFalse((path/'schedule.json').exists());m.Store(path).verify()
 def test_technical_stop_and_user_stop_endpoint_boundaries(self):
  f=feed();f.stop('socket_closed');samples=[]
  for k in range(20):samples.extend(f.snapshot(k,20*m.NS+k*60*m.NS,10*m.NS+k*60*m.NS,20*m.NS+k*60*m.NS))
  self.assertEqual(len(samples),420);self.assertTrue(all(s['reason']=='socket_closed' for s in samples))
  stop=asyncio.Event();stop.set();self.assertFalse(asyncio.run(m.wait_deadline(10**30,stop)))
  samples=m.missing_slots([],m.Clock(10*m.NS,20*m.NS),20*m.NS,'user_stop')
  rows=[m.score(s,next(x for x in markets() if x['asset']==s['asset']),b,economic=False) for s in samples for b in m.BUDGETS]
  self.assertEqual(len(rows),1680);self.assertFalse(any('optimistic_budget' in r for r in rows))

if __name__=='__main__':unittest.main()
