"""Synthetic only; no network, live plan or retained fixtures."""
import contextlib,hashlib,http.client,io,json,os,tempfile,time,unittest
from pathlib import Path
from unittest import mock
from scripts import comet_source_metadata_v1 as c
class Reply:
    status=200
    def __init__(self,b): self.b=io.BytesIO(b)
    def getheader(self,k): return None
    def read(self,n): return self.b.read(n)
    def read1(self,n): return self.read(n)
class Conn:
    def __init__(self,r): self.r=r; self.calls=[]; self.closed=False
    def request(self,*a,**kw): self.calls.append((a,kw))
    def getresponse(self): return self.r
    def close(self): self.closed=True
class Tests(unittest.TestCase):
    def test_ipfs_and_json(self):
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        def b58(b):
            n=int.from_bytes(b,'big'); s=''
            while n: n,r=divmod(n,58); s=alphabet[r]+s
            return s
        self.assertEqual(b58(bytes.fromhex(c.cid(b''))),'QmbFMke1KXqnYyBBWxB74N4c5SBnJMVAiMNRcGu6x1AwQH')
        self.assertEqual(b58(bytes.fromhex(c.cid(b'x'))),'QmULKig5Fxrs2sC4qt9nNduucXfb92AFYQ6Hi3YRqDmrYC')
        self.assertEqual(b58(bytes.fromhex(c.cid(bytes(10250)))),'QmVJJBB3gKKBWYC9QTywpH8ZL1bDeTDJ17B63Af5kino9i')
        with self.assertRaisesRegex(c.Refusal,'cid_mismatch'): c.project(b'{}','a'*64)
        for b in (b'{"x":1,"x":2}',b'{"x":NaN}',b'[]',b'\xff',b'{"x":1e999}'):
            with self.assertRaises((ValueError,UnicodeError)): c.js(b)
    def test_stream(self):
        for size in (3,65536,65537):
            conn=Conn(Reply(b'x'*size)); got=[]
            if size>65536:
                with self.assertRaisesRegex(c.Refusal,'oversize'): c.fetch(got.append,lambda *a,**k:conn)
            else: self.assertEqual(c.fetch(got.append,lambda *a,**k:conn),size)
            self.assertEqual(len(b''.join(got)),size)
            self.assertEqual(len(conn.calls),1); self.assertTrue(conn.closed)
        r=Reply(b'')
        with mock.patch.object(r,'read1',side_effect=http.client.IncompleteRead(b'abc',2)):
            got=[]
            with self.assertRaisesRegex(c.Refusal,'incomplete_body'): c.fetch(got.append,lambda *a,**k:Conn(r))
            self.assertEqual(got,[b'abc'])
    def test_raw_claim_and_dry(self):
        with tempfile.TemporaryDirectory(dir=c.R/'reports') as d:
            out=Path(d); p=out/'body.raw.pending'
            with p.open('xb') as f: f.write(b'prefix'); f.flush(); os.fsync(f.fileno())
            inode=p.stat().st_ino; c.finish(out)
            self.assertEqual((out/'body.raw').stat().st_ino,inode)
            with mock.patch.object(c,'verify',return_value={'source_pins':[]}),mock.patch.object(c,'O',str(out.relative_to(c.R))):
                with self.assertRaises(FileExistsError): c.run('a'*64)
        with contextlib.redirect_stdout(io.StringIO()) as stdout,mock.patch.object(c,'fetch',side_effect=AssertionError):
            self.assertEqual(c.main([]),0)
        self.assertEqual(json.loads(stdout.getvalue())['network_requests'],0)
        for digest in (None,'bad'):
            with self.assertRaises(c.Refusal): c.verify(digest)
    def test_frozen_source_pins(self):
        bodies={c.S:b's',c.T:b't',c.D:b'd'}
        bodies[c.A['path']]=(c.R/c.A['path']).read_bytes()
        bodies[c.AM['path']]=(c.R/c.AM['path']).read_bytes()
        plan={'schema':'comet-source-metadata-v1','status':'frozen_root_only','url':c.U,
              'expected_multihash_hex':c.M,'output_dir':c.O,'allocation':c.A,
              'category_amendment':c.AM,'request':{'method':'GET','accept_encoding':'identity'},
              'claims':{'source_equivalence':False,'eligibility':False,'economics':False},
              'source_pins':[{'path':k,'bytes':len(v),'sha256':c.h(v)} for k,v in bodies.items() if k in (c.S,c.T,c.D)]}
        bodies[c.P]=c.enc(plan)
        def fake(path,_cap): return bodies[str(path.relative_to(c.R))]
        with mock.patch.object(c,'read',side_effect=fake):
            self.assertEqual(c.verify(c.h(bodies[c.P])),plan)
            bodies[c.S]=b'changed'
            with self.assertRaisesRegex(c.Refusal,'pin_mismatch'): c.verify(c.h(bodies[c.P]))
    def test_nested_deadline_does_not_extend_outer(self):
        start=time.monotonic()
        with self.assertRaises(TimeoutError):
            with c.alarm(0.03):
                with c.alarm(1): time.sleep(0.15)
        self.assertLess(time.monotonic()-start,0.12)
if __name__=='__main__': unittest.main()
