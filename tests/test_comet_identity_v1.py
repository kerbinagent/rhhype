"""Focused offline Comet identity and retention synthetics; no HTTP."""
import contextlib
import io
import http.client
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from scripts import comet_identity_v1 as c


def response(index,value):
    return c.encoded(dict(jsonrpc='2.0',id=index+1,result=value))


def values():
    header = dict(number='0x100',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,
        timestamp='0x65000000',stateRoot='0x'+'ef'*32,transactions=[],extraData='0x1234')
    return ['0x1',header,'0x6000','0x'+'00'*12+'11'*20,'0x60016000',dict(header)]


class WireResponse:
    def __init__(self,chunks,status=200,length=None):
        self.chunks = list(chunks)
        self.status,self.length = status,length
        self.read_limits = []

    def getheader(self,key):
        return self.length if key=='Content-Length' else None

    def read1(self,limit):
        self.read_limits.append(limit)
        chunk = self.chunks.pop(0) if self.chunks else b''
        if len(chunk)>limit:
            self.chunks.insert(0,chunk[limit:]); chunk=chunk[:limit]
        return chunk


class WireConnection:
    def __init__(self,response):
        self.response,self.requests,self.closed = response,[],False

    def request(self,*args,**kwargs):
        self.requests.append((args,kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed=True


class CometIdentityTests(unittest.TestCase):
    def fixture(self):
        # Every fixture is removed; each is comfortably below the 65KiB allowance.
        return tempfile.TemporaryDirectory(prefix='comet-synthetic-',dir=c.ROOT/'reports/comet-identity-v1')

    def write_trace(self,out,items=None):
        state = c.Identity(); trace = c.Trace(out)
        bodies = []
        for index,value in enumerate(values() if items is None else items):
            request = dict(jsonrpc='2.0',id=index+1,
                **c.resolve(c.build_manifest()[index],state.parent or {},state.implementation))
            body = response(index,value)
            trace.frame(ord('B'),c.encoded(dict(request=request,cap=c.CAPS['response_bytes'][index])))
            trace.frame(ord('D'),body[:7]); trace.frame(ord('D'),body[7:])
            trace.frame(ord('E'),c.encoded(dict(response_bytes=len(body),response_sha256=c.sha(body),
                outcome='received',http_status=200)))
            state.accept(index,value); bodies.append(body)
        trace.finish()
        return bodies,state

    def test_exact_manifest_identity_and_raw_reproduction(self):
        manifest = c.build_manifest()
        self.assertEqual(len(manifest),6)
        self.assertEqual([x['method'] for x in manifest],['eth_chainId','eth_getBlockByNumber',
            'eth_getCode','eth_getStorageAt','eth_getCode','eth_getBlockByNumber'])
        self.assertEqual(manifest[3]['params'][1],c.SLOT)
        for i in (2,3,4):
            self.assertEqual(manifest[i]['params'][-1],dict(blockHash='$parent.hash',requireCanonical=True))
        with self.fixture() as directory:
            out=Path(directory); bodies,state=self.write_trace(out)
            replayed,recovered,digest=c.replay(out/'responses.frames')
            self.assertEqual(recovered,bodies)
            self.assertEqual(digest,c.sha((out/'responses.frames').read_bytes()))
            self.assertEqual(replayed.projection('a'*64,digest),state.projection('a'*64,digest))
            self.assertEqual(state.proxy_fingerprint['runtime_sha256'],c.sha(bytes.fromhex('6000')))
            self.assertFalse(state.projection('a'*64,digest)['source_equivalence'])
            self.assertLess((out/'responses.frames').stat().st_size,c.CAPS['raw_bytes'])

    def test_wrong_chain_id_slot_code_and_full_header_reorg(self):
        with self.assertRaises(c.Refusal): c.Identity().accept(0,'0x2')
        for slot in ('0x'+'00'*32,'0x'+'01'+'00'*31,'0x11','0x'+'gg'*32):
            with self.subTest(slot=slot),self.assertRaises(Exception): c.Identity().accept(3,slot)
        for code in ('0x','0x0','garbage'):
            with self.subTest(code=code),self.assertRaises(Exception): c.Identity().accept(2,code)
        state=c.Identity(); state.accept(1,values()[1])
        for field in ('hash','extraData','transactions'):
            altered=dict(values()[1]); altered[field]=[] if field=='extraData' else '0x01'
            with self.subTest(field=field),self.assertRaises(Exception): state.accept(5,altered)

    def test_response_id_schema_depth_nonfinite_and_unsupported_no_retry(self):
        for obj in (dict(jsonrpc='2.0',id=True,result='0x1'),dict(jsonrpc='2.0',id=2,result='0x1'),
                    dict(jsonrpc='2.0',id=1,result='0x1',extra=True),
                    dict(jsonrpc='2.0',id=1,error=dict(code=-32602,message='unsupported blockHash'))):
            with self.subTest(obj=obj),self.assertRaises(c.Refusal): c.envelope(c.encoded(obj),1)
        for raw in (b'{"id":1,"id":1}',b'{"x":NaN}',b'['*40+b'0'+b']'*40,b'{"x":1e999}'):
            with self.subTest(raw=raw),self.assertRaises(Exception): c.helper.decode_json(raw)
        with self.fixture() as directory:
            out=Path(directory); calls=[]
            def unsupported(request,cap,timeout,emit):
                calls.append(request)
                if len(calls)<3:
                    raw=response(len(calls)-1,values()[len(calls)-1])
                else:
                    raw=c.encoded(dict(jsonrpc='2.0',id=3,error=dict(code=-32602,message='unsupported blockHash')))
                emit(raw)
                return 200,len(raw)
            with mock.patch.object(c,'verify',return_value={}),mock.patch.object(c,'transport',side_effect=unsupported):
                c.worker('a'*64,out,time.monotonic()+2)
            terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(len(calls),3)
            self.assertEqual(terminal['status'],'unavailable')
            self.assertEqual(terminal['reason'],'rpc_error_no_fallback')
            self.assertFalse((out/'projection.json').exists())
            self.assertIn(b'unsupported',(out/'responses.frames').read_bytes())

    def test_transport_cumulative_boundary_no_overread_and_redirect(self):
        received=[]; wire=WireResponse([b'abc',b'def',b'g'],length=None)
        connection=WireConnection(wire)
        with self.assertRaisesRegex(c.Refusal,'response_cap_eof_unproven'):
            c.transport({'id':1},6,1,received.append,lambda *a,**k:connection)
        self.assertEqual(b''.join(received),b'abcdef')
        self.assertEqual(wire.read_limits,[6,3])
        self.assertEqual(wire.chunks,[b'g'])
        self.assertTrue(connection.closed)
        wire=WireResponse([b'blocked'],status=302); connection=WireConnection(wire); received=[]
        status,count=c.transport({'id':1},100,1,received.append,lambda *a,**k:connection)
        self.assertEqual((status,count),(302,7))
        self.assertEqual(len(connection.requests),1)
        self.assertEqual(connection.requests[0][0],('POST','/'))

    def test_timeout_and_errorprefix_fsynced_terminal_retention(self):
        with self.assertRaises(TimeoutError):
            with c.hard_timeout(0.02): time.sleep(0.1)
        with self.fixture() as directory:
            out=Path(directory)
            def drip(request,cap,timeout,emit):
                emit(b'partial exact prefix\x00\xff'); raise TimeoutError('synthetic')
            with mock.patch.object(c,'verify',return_value={}),mock.patch.object(c,'transport',side_effect=drip):
                c.worker('a'*64,out,time.monotonic()+1)
            raw=(out/'responses.frames').read_bytes()
            self.assertIn(b'partial exact prefix\x00\xff',raw)
            self.assertFalse((out/'responses.frames.pending').exists())
            terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['reason'],'timeout')
            self.assertEqual(terminal['total_response_bytes'],len(b'partial exact prefix\x00\xff'))
            self.assertEqual(terminal['raw']['sha256'],c.sha(raw))
            self.assertFalse((out/'projection.json').exists())
            with self.assertRaises(c.Refusal): c.replay(out/'responses.frames')

    def test_partial_http_read_and_six_request_success(self):
        wire=WireResponse([]); connection=WireConnection(wire); retained=[]
        with mock.patch.object(wire,'read1',side_effect=http.client.IncompleteRead(b'exact prefix',5)):
            with self.assertRaisesRegex(c.Refusal,'incomplete_response_prefix_retained'):
                c.transport({'id':1},100,1,retained.append,lambda *a,**k:connection)
        self.assertEqual(retained,[b'exact prefix'])
        self.assertTrue(connection.closed)
        with self.fixture() as directory:
            out=Path(directory); calls=[]
            def synthetic(request,cap,timeout,emit):
                calls.append(request)
                body=response(len(calls)-1,values()[len(calls)-1])
                emit(body); return 200,len(body)
            with mock.patch.object(c,'verify',return_value={}),mock.patch.object(c,'transport',side_effect=synthetic):
                c.worker('a'*64,out,time.monotonic()+2)
            terminal=json.loads((out/'terminal.json').read_bytes())
            projection=json.loads((out/'projection.json').read_bytes())
            self.assertEqual(len(calls),6)
            self.assertEqual(terminal['status'],'identity_fingerprints_available')
            self.assertEqual(calls[-1]['params'],['0x100',False])
            self.assertEqual(calls[4]['params'][0],'0x'+'11'*20)
            self.assertEqual(projection['raw_sha256'],terminal['raw']['sha256'])
            self.assertTrue(all(projection[key] is False for key in ('economics','eligibility','source_equivalence')))
            self.assertFalse((out/'responses.frames.pending').exists())

    def test_trace_raw_cap_corruption_and_partial_finalization(self):
        with self.fixture() as directory:
            out=Path(directory); trace=c.Trace(out)
            trace.frame(ord('B'),b'{}'); trace.frame(ord('D'),b'prefix')
            trace.handle.close(); inode=(out/'responses.frames.pending').stat().st_ino
            c.finalize_partial(out)
            self.assertEqual((out/'responses.frames').stat().st_ino,inode)
            with self.assertRaises(c.Refusal): c.replay(out/'responses.frames')
        with self.fixture() as directory:
            out=Path(directory); self.write_trace(out)
            raw=(out/'responses.frames').read_bytes().replace(b'0x6000',b'0x6001',1)
            (out/'responses.frames').write_bytes(raw)
            with self.assertRaisesRegex(c.Refusal,'raw_body_identity'): c.replay(out/'responses.frames')
        with self.fixture() as directory:
            trace=c.Trace(Path(directory)); trace.bytes=c.CAPS['raw_bytes']-5
            with self.assertRaisesRegex(c.Refusal,'raw_total_cap'): trace.frame(ord('D'),b'x')
            trace.handle.close()

    def test_dry_zero_network_existing_output_and_pins(self):
        with mock.patch.object(c.sys,'argv',['collector']),mock.patch.object(c,'transport',side_effect=AssertionError),\
             mock.patch.object(c,'run',side_effect=AssertionError),mock.patch('sys.stdout',new_callable=io.StringIO) as output:
            c.main()
            self.assertEqual(json.loads(output.getvalue())['network_requests'],0)
        with self.fixture() as directory:
            original_root=c.ROOT; root=Path(directory)
            pin=dict(path='file',bytes=3,sha256=c.sha(b'abc')); (root/'file').write_bytes(b'bad')
            with mock.patch.object(c,'ROOT',root):
                with self.assertRaisesRegex(c.Refusal,'pin_identity'): c.check_pin(pin,10)
                for digest in (None,'bad'):
                    with self.assertRaises(c.Refusal): c.verify(digest)
                out=root/c.OUT; out.mkdir(parents=True)
                with mock.patch.object(c,'verify',return_value={}),mock.patch.object(c,'worker',side_effect=AssertionError):
                    with self.assertRaises(FileExistsError): c._run('a'*64,time.monotonic())
            with mock.patch.object(c,'ROOT',root),mock.patch.object(c,'verify',return_value={'source_pins':[]}):
                # A distinct synthetic output location models a failed OS spawn.
                with mock.patch.object(c,'OUT','fresh'),mock.patch.object(c.multiprocessing,'get_context') as context:
                    process=context.return_value.Process.return_value
                    process.start.side_effect=OSError('synthetic spawn failure')
                    process.exitcode=None
                    self.assertFalse(c._run('a'*64,time.monotonic()))
                    terminal=json.loads((root/'fresh/terminal.json').read_bytes())
                    supervisor=json.loads((root/'fresh/supervisor.json').read_bytes())
                    self.assertIsNone(terminal['requests_attempted'])
                    self.assertEqual(supervisor['status'],'unavailable')
                    self.assertEqual(supervisor['reason'],'spawn_or_supervisor_wait_failure')

    def test_frozen_exact_source_scope_and_pins(self):
        # In-memory bounded reads only; no real plan is edited or run.
        source=b'source'; test=b'test'; helper_raw=(c.ROOT/c.HELPER['path']).read_bytes()
        pins=[dict(path=c.SOURCE,bytes=len(source),sha256=c.sha(source)),
              dict(path=c.TEST,bytes=len(test),sha256=c.sha(test)),
              dict(path=c.HELPER['path'],bytes=len(helper_raw),sha256=c.sha(helper_raw))]
        plan=dict(schema='comet-identity-v1',status='frozen_comet_identity',endpoint=c.ENDPOINT,
            output_dir=c.OUT,chain_id=1,proxy=c.PROXY,implementation_slot=c.SLOT,
            resource_limits=c.CAPS,request_manifest=c.build_manifest(),runtime=c.runtime_identity(),
            allocation=c.ALLOCATION,claims=dict(source_equivalence=False,eligibility=False,economics=False),source_pins=pins)
        allocation=(c.ROOT/c.ALLOCATION['path']).read_bytes()
        def verify_fixture(p):
            raw=c.encoded(p)
            mapping={c.PLAN:raw,c.SOURCE:source,c.TEST:test,c.HELPER['path']:helper_raw,c.ALLOCATION['path']:allocation}
            def fake_bounded(path,cap):
                body=mapping[str(path.relative_to(c.ROOT))]
                if len(body)>cap: raise c.Refusal('file_byte_cap')
                return body
            with mock.patch.object(c,'bounded',side_effect=fake_bounded): return c.verify(c.sha(raw))
        self.assertEqual(verify_fixture(plan),plan)
        for key,value in [('status','draft_not_runnable'),('endpoint','https://other.invalid'),('chain_id',2),
                          ('source_pins',pins[:2]),('request_manifest',c.build_manifest()[:-1])]:
            changed=dict(plan); changed[key]=value
            with self.subTest(key=key),self.assertRaises(c.Refusal): verify_fixture(changed)
        changed=dict(plan); changed['source_pins']=[dict(p) for p in pins]; changed['source_pins'][0]['sha256']='0'*64
        with self.assertRaises(c.Refusal): verify_fixture(changed)


if __name__=='__main__': unittest.main()
