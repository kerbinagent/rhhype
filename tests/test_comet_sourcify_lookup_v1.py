"""Offline transport and projection synthetics; no real HTTP or large disk bodies."""
import contextlib
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from scripts import comet_sourcify_lookup_v1 as s

class Reply:
    def __init__(self,body,status=200,length=None,encoding=None):
        self.body=io.BytesIO(body); self.status=status; self.length=length; self.encoding=encoding
    def getheader(self,key):
        return self.length if key=='Content-Length' else (self.encoding if key=='Content-Encoding' else None)
    def read1(self,limit): return self.body.read(limit)
class Connection:
    def __init__(self,reply): self.reply=reply; self.calls=[]; self.closed=False
    def request(self,*args,**kwargs): self.calls.append((args,kwargs))
    def getresponse(self): return self.reply
    def close(self): self.closed=True

def specimen(**changes):
    value={'chainId':'1','address':s.ADDRESS,
           'runtimeBytecode':{'onchainBytecode':'0x'+bytes(s.RUNTIME_BYTES).hex(),
                              'recompiledBytecode':'0x1234','transformations':[]},
           'metadata':{'compiler':{'version':'claim'}},'compilation':{'language':'Solidity'},
           'match':'exact_match_claim'}
    value.update(changes)
    return value

class Tests(unittest.TestCase):
    def test_fixed_one_get_caps_status_and_no_redirect(self):
        for count in (3,s.ACCEPT,s.RECEIVED):
            with self.subTest(count=count):
                connection=Connection(Reply(b'x'*count,status=302)); got=[]; codes=[]
                if count==s.RECEIVED:
                    with self.assertRaisesRegex(s.Refusal,'body_oversize'):
                        s.fetch(got.append,codes.append,lambda *a,**k:connection)
                else:
                    with self.assertRaisesRegex(s.Refusal,'http_status'):
                        s.fetch(got.append,codes.append,lambda *a,**k:connection)
                self.assertEqual(len(b''.join(got)),count)
                self.assertEqual(codes,[302]); self.assertTrue(connection.closed)
                self.assertEqual(len(connection.calls),1)
                self.assertEqual(connection.calls[0][0],('GET',s.TARGET))
                self.assertEqual(connection.calls[0][1]['headers']['Accept-Encoding'],'identity')
        reply=Reply(b'abc',length='4'); got=[]; codes=[]
        with self.assertRaisesRegex(s.Refusal,'incomplete_body'):
            s.fetch(got.append,codes.append,lambda *a,**k:Connection(reply))
        self.assertEqual(got,[b'abc'])
        reply=Reply(b'')
        with mock.patch.object(reply,'read1',side_effect=http.client.IncompleteRead(b'prefix',2)):
            got=[]
            with self.assertRaisesRegex(s.Refusal,'incomplete_body'):
                s.fetch(got.append,lambda _:None,lambda *a,**k:Connection(reply))
            self.assertEqual(got,[b'prefix'])
    def test_runtime_chain_address_and_claims(self):
        code=bytes(s.RUNTIME_BYTES)
        with mock.patch.object(s,'RUNTIME_SHA',hashlib.sha256(code).hexdigest()):
            obj=specimen(); raw=s.encoded(obj)
            result=s.projection(raw,'a'*64)
            self.assertEqual(result['runtime_bytes'],s.RUNTIME_BYTES)
            self.assertFalse(any(result[k] for k in ('source_equivalence','eligibility','economics','metadata_cid_verified')))
            self.assertIn('recompiledBytecode_claim_sha256',result['provider_claims'])
            for changed,label in (({'chainId':'2'},'wrong_chain'),({'address':'0x'+'11'*20},'wrong_address'),
                                  ({'runtimeBytecode':{'onchainBytecode':'0x00'}},'runtime_identity')):
                with self.subTest(label=label),self.assertRaisesRegex(s.Refusal,label):
                    s.projection(s.encoded(specimen(**changed)),'a'*64)
            bloated=specimen(); bloated['match']='x'*9000
            # Only a fixed digest of the provider claim enters the projection.
            self.assertLess(len(s.encoded(s.projection(s.encoded(bloated),'a'*64))),s.PROJECTION)
        with self.assertRaisesRegex(s.Refusal,'runtime_identity'):
            s.projection(s.encoded(specimen()),'a'*64)
    def test_json_and_narrow_projection(self):
        for raw in (b'[]',b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'\xff',b'['*40+b'0'+b']'*40):
            with self.subTest(raw=raw),self.assertRaises((ValueError,UnicodeError)):
                s.strict_json(raw)
        obj={'x':[[0]*4 for _ in range(17000)]}
        with self.assertRaisesRegex(ValueError,'json_complexity'): s.strict_json(s.encoded(obj))
    def test_frozen_pins_and_dry(self):
        allocation=(s.ROOT/s.ALLOCATION['path']).read_bytes()
        value=json.loads(allocation)
        bodies={s.ALLOCATION['path']:allocation,s.SOURCE:b's',s.TEST:b't',s.DESIGN:b'd'}
        for item in value['inputs']: bodies[item['path']]=(s.ROOT/item['path']).read_bytes()
        sourcepins=[{'path':p,'bytes':len(bodies[p]),'sha256':s.sha(bodies[p])} for p in (s.SOURCE,s.TEST,s.DESIGN)]
        plan={'schema':'comet-sourcify-lookup-v1','status':'frozen_root_only','allocation':s.ALLOCATION,
              'request':value['request_after_separate_freeze'],'expected':value['frozen_expected'],
              'output_dir':s.OUT,'claims':{'source_equivalence':False,'eligibility':False,'economics':False},
              'source_pins':sourcepins,'input_pins':value['inputs']}
        bodies[s.PLAN]=s.encoded(plan)
        def fake(path,_cap): return bodies[str(path.relative_to(s.ROOT))]
        with mock.patch.object(s,'bounded',side_effect=fake):
            self.assertEqual(s.verify(s.sha(bodies[s.PLAN])),plan)
            bodies[s.SOURCE]=b'changed'
            with self.assertRaisesRegex(s.Refusal,'pin_mismatch'): s.verify(s.sha(bodies[s.PLAN]))
            bodies[s.SOURCE]=b's'
            first=value['inputs'][0]['path']; bodies[first]=b'changed input'
            with self.assertRaisesRegex(s.Refusal,'pin_mismatch'): s.verify(s.sha(bodies[s.PLAN]))
        with contextlib.redirect_stdout(io.StringIO()) as output,mock.patch.object(s,'fetch',side_effect=AssertionError):
            self.assertEqual(s.main([]),0)
        self.assertEqual(json.loads(output.getvalue())['network_requests'],0)
    def test_small_failure_inode_and_existing_claim(self):
        with tempfile.TemporaryDirectory(dir=s.ROOT/'reports/comet-sourcify-lookup-v1') as directory:
            out=Path(directory)
            def partial(emit,status): status(503); emit(b'partial'); raise OSError('synthetic')
            with mock.patch.object(s,'verify',return_value={}):
                with mock.patch.object(s,'fetch',side_effect=partial): s.worker('a'*64,out)
            raw=out/'response.raw'
            self.assertEqual(raw.read_bytes(),b'partial')
            terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['http_status'],503)
            self.assertEqual(terminal['status'],'unavailable')
            self.assertFalse((out/'response.raw.pending').exists())
            with mock.patch.object(s,'verify',return_value={'source_pins':[],'input_pins':[]}):
                with mock.patch.object(s,'OUT',str(out.relative_to(s.ROOT))):
                    with self.assertRaises(FileExistsError): s.run('a'*64)
    def test_nested_timeout(self):
        begin=time.monotonic()
        with self.assertRaises(TimeoutError):
            with s.alarm(0.03):
                with s.alarm(1): time.sleep(0.15)
        self.assertLess(time.monotonic()-begin,0.12)
    def test_parent_absolute_join_and_hard_timeout(self):
        with tempfile.TemporaryDirectory(dir=s.ROOT/'reports/comet-sourcify-lookup-v1') as directory:
            context=mock.Mock(); child=context.Process.return_value
            child.is_alive.return_value=False; child.exitcode=None; child.pid=12345
            with mock.patch.object(s,'ROOT',s.ROOT),mock.patch.object(s,'OUT',str((Path(directory)/'one').relative_to(s.ROOT))),\
                 mock.patch.object(s,'verify',return_value={'source_pins':[],'input_pins':[]}),\
                 mock.patch.object(s,'alarm',return_value=contextlib.nullcontext()),\
                 mock.patch.object(s.multiprocessing,'get_context',return_value=context),\
                 mock.patch.object(s.time,'monotonic',side_effect=[100,101,102,103]):
                self.assertFalse(s.run('a'*64))
            child.join.assert_called_once_with(60)
            child.join.reset_mock(); child.join.side_effect=TimeoutError('synthetic hard deadline')
            with mock.patch.object(s,'OUT',str((Path(directory)/'two').relative_to(s.ROOT))),\
                 mock.patch.object(s,'verify',return_value={'source_pins':[],'input_pins':[]}),\
                 mock.patch.object(s,'alarm',return_value=contextlib.nullcontext()),\
                 mock.patch.object(s.multiprocessing,'get_context',return_value=context),\
                 mock.patch.object(s.os,'kill') as kill:
                with self.assertRaisesRegex(TimeoutError,'synthetic hard deadline'):
                    s.run('a'*64)
            kill.assert_called_once_with(12345,s.signal.SIGKILL)
            self.assertFalse((Path(directory)/'two'/'supervisor.json').exists())
    def test_parent_cleanup_does_not_swallow_hard_timeout(self):
        with tempfile.TemporaryDirectory(dir=s.ROOT/'reports/comet-sourcify-lookup-v1') as directory:
            root=Path(directory); context=mock.Mock(); child=context.Process.return_value
            child.is_alive.return_value=False; child.exitcode=None
            plan={'source_pins':[],'input_pins':[]}
            target=root/'status'
            child.start.side_effect=lambda: (target/'http-status.json.pending').write_bytes(b'{}')
            original=s.bounded
            def interrupted(path,cap):
                if path.name=='http-status.json.pending': raise TimeoutError('status deadline')
                return original(path,cap)
            with mock.patch.object(s,'OUT',str(target.relative_to(s.ROOT))),mock.patch.object(s,'verify',return_value=plan),\
                 mock.patch.object(s,'alarm',return_value=contextlib.nullcontext()),\
                 mock.patch.object(s.multiprocessing,'get_context',return_value=context),\
                 mock.patch.object(s,'bounded',side_effect=interrupted):
                with self.assertRaisesRegex(TimeoutError,'status deadline'): s.run('a'*64)
            self.assertFalse((target/'supervisor.json').exists())
            child.start.side_effect=None; target=root/'final'
            with mock.patch.object(s,'OUT',str(target.relative_to(s.ROOT))),\
                 mock.patch.object(s,'verify',side_effect=[plan,TimeoutError('final pin deadline')]),\
                 mock.patch.object(s,'alarm',return_value=contextlib.nullcontext()),\
                 mock.patch.object(s.multiprocessing,'get_context',return_value=context):
                with self.assertRaisesRegex(TimeoutError,'final pin deadline'): s.run('a'*64)
            self.assertFalse((target/'supervisor.json').exists())
if __name__=='__main__': unittest.main()
