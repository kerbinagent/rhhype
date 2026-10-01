"""Compressed metadata trust, separate venue provenance and nonce/flow controls."""
import gzip,hashlib,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from scripts import core_maker_lit_events as events
from scripts import core_maker_lit_capture as capture
from tests.test_passive_three_venue_events import BASE,row,book,flow,trade,market_row

def fixture(directory,rows):
 directory.mkdir();md=directory/'metadata';md.mkdir()
 raw=json.dumps({'selected':capture.SELECTED}).encode();(md/'market_plan.json').write_bytes(raw);plan_hash=hashlib.sha256(raw).hexdigest()
 bodies={'rh_markets':{'code':200,'order_book_details':[market_row('LIT',5)]},'core_markets':{'code':200,'order_book_details':[market_row('LIT',120)]},'rh_assets':{'code':200,'asset_details':[{'symbol':'USDG','margin_mode':'enabled'}]},'core_assets':{'code':200,'asset_details':[{'symbol':'USDC','margin_mode':'enabled'}]}}
 for name,(method,url,body) in capture.REQUESTS.items():
  raw=json.dumps(bodies[name]).encode();packed=gzip.compress(raw,mtime=0);(md/f'{name}.json.gz').write_bytes(packed)
  (md/f'{name}.request.json').write_text(json.dumps({'method':method,'url':url,'json_body':body,'status':200,'raw_file':f'{name}.json.gz','raw_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'compressed_sha256':hashlib.sha256(packed).hexdigest(),'request_started_utc_ns':BASE-2_000_000_000,'response_completed_utc_ns':BASE-1_000_000_000}))
 normalized=capture.verify_metadata(md,capture.SELECTED,plan_hash);(md/'normalized.json').write_text(json.dumps(normalized))
 frames=gzip.compress(b''.join(json.dumps(r).encode()+b'\n' for r in rows),mtime=0);(directory/'frames.jsonl.gz').write_bytes(frames)
 manifest={'schema':'core-maker-lit-offset-public-capture-v1','read_only':True,'started_utc':datetime.fromtimestamp(BASE/1e9,timezone.utc).isoformat(),'ended_utc':datetime.fromtimestamp(BASE/1e9+30,timezone.utc).isoformat(),'configured_seconds':30,'configured_total_bytes':capture.HARD_BYTES,'compressed_payload_bytes':len(frames),'metadata_bytes':sum(p.stat().st_size for p in md.iterdir()),'selected_markets':capture.SELECTED,'market_plan_sha256':plan_hash,'payload_records':len(rows),'frames_sha256':hashlib.sha256(frames).hexdigest(),'end_reason':'duration_limit','truncated':False,'errors':[]}
 (directory/'manifest.json').write_text(json.dumps(manifest));return events.sha256(directory/'manifest.json')
class CoreEventTests(unittest.TestCase):
 def test_compressed_metadata_real_venues_backlog_dedupe_and_eof(self):
  rows=[row('connection_open',0),row('connection_open',1,'lighter'),book(100,market='5'),book(110,'lighter','120'),flow(200,market='5',subscribed=True),flow(210,market='5',trades=[trade(3,190,5),trade(3,190,5)])]
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'capture';digest=fixture(p,rows);out=list(events.iter_events(p,expected_manifest_sha256=digest,hedge_venue='lighter'))
   books=[e for e in out if e['type']=='book'];self.assertEqual([e['venue'] for e in books],['rh_lighter','lighter']);self.assertEqual([e['role'] for e in books],['maker','hedge'])
   self.assertEqual(len([e for e in out if e['type']=='trade']),1);self.assertEqual(out[-1]['type'],'end');self.assertTrue(out[-1]['metadata_sha256'])
   f=p/'metadata/core_markets.json.gz';f.write_bytes(f.read_bytes()+b'x')
   with self.assertRaises((ValueError,AssertionError,EOFError,OSError)):list(events.iter_events(p,expected_manifest_sha256=digest))
 def test_nonce_gap_and_future_clock_never_publish_valid_books(self):
  rows=[row('connection_open',0),book(100,market='5'),book(200,market='5',nonce=3,begin=99),book(300,market='5',source_offset=500)]
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'capture';digest=fixture(p,rows);out=list(events.iter_events(p,expected_manifest_sha256=digest,hedge_venue='lighter'))
   self.assertEqual(len([e for e in out if e['type']=='book']),1);self.assertGreaterEqual(len([e for e in out if e['type']=='invalidate']),2)
if __name__=='__main__':unittest.main()
