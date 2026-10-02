"""Offline synthetic boundaries; never queries a provider or real transaction."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import aave_trace_access_v1 as m


H='0x'+'11'*32
TX='0x'+'22'*32
A='0x'+'33'*20
B='0x'+'44'*20


def responses():
    block=dict(hash=H,parentHash='0x'+'55'*32,number='0x100',timestamp='0x200',transactions=[TX])
    receipt=dict(transactionHash=TX,transactionIndex='0x0',blockHash=H,blockNumber='0x100',
                 status='0x1',gasUsed='0x5208',effectiveGasPrice='0x1')
    call=dict(type='CALL',**{'from':A,'to':B},gas='0x5208',gasUsed='0x0',input='0x',value='0x1')
    diff=dict(pre={A:dict(balance='0x20',nonce=0)},post={A:dict(balance='0x10',nonce=1),B:dict(balance='0x1')})
    return ['0x1',block,receipt,call,diff,dict(block)]


def frozen_plan():
    return dict(schema='aave-trace-access-v1',status='frozen_trace_access_probe',endpoint=m.ENDPOINT,
        output_dir=m.OUT,external_receipt=m.EXTERNAL,chain_id=1,allocation=m.ALLOCATION,resource_limits=m.CAPS,
        request_manifest=m.build_manifest(),claims=m.CLAIMS,runtime=m.runtime())


class Response:
    def __init__(self,raw,status=200,headers=None,failure=None):
        self.raw=raw; self.status=status; self.offset=0; self.limits=[]
        self.headers=headers or []; self.failure=failure
    def getheaders(self): return self.headers
    def getheader(self,key): return dict(self.headers).get(key)
    def read1(self,limit):
        self.limits.append(limit)
        if self.failure is not None:
            failure=self.failure; self.failure=None; raise failure
        part=self.raw[self.offset:self.offset+limit]; self.offset+=len(part); return part


class Connection:
    def __init__(self,response): self.response=response; self.calls=[]; self.closed=False
    def request(self,*args,**kwargs): self.calls.append((args,kwargs))
    def getresponse(self): return self.response
    def close(self): self.closed=True


class Tests(unittest.TestCase):
    def test_default_dry_and_mandatory_pin_no_network_no_output(self):
        with patch.object(m,'run') as run, patch.object(m,'fetch') as fetch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main([]),0); run.assert_not_called(); fetch.assert_not_called()
        with patch.object(m,'fetch') as fetch:
            with self.assertRaises(m.Refusal): m.run(None)
            fetch.assert_not_called()

    def test_cli_flushes_output_and_bypasses_atexit_hooks(self):
        code=("import atexit,runpy; "
              "atexit.register(lambda: print('UNBOUNDED_EXIT_HOOK')); "
              "runpy.run_path('scripts/aave_trace_access_v1.py',run_name='__main__')")
        result=subprocess.run([m.sys.executable,'-B','-c',code],cwd=m.ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3,check=False)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,b'dry: zero requests; zero outputs; fixed six-request trace-access probe\n')
        self.assertEqual(result.stderr,b'')

    def test_fixed_manifest_and_strict_schema_canonical_binding(self):
        manifest=m.build_manifest()
        self.assertEqual(len(manifest),6)
        self.assertEqual(manifest[1]['params'],['finalized',False])
        self.assertFalse(manifest[3]['params'][1]['tracerConfig']['onlyTopCall'])
        self.assertTrue(manifest[4]['params'][1]['tracerConfig']['diffMode'])
        state=m.State()
        for i,v in enumerate(responses()): state.accept(i,v)
        projection=state.projection('a'*64,dict(bytes=1,sha256='b'*64))
        self.assertEqual(projection['call_frame_count'],1)
        self.assertEqual(projection['post_diff_storage_slot_count'],0)
        for index,value,reason in [(0,'0x2','wrong_chain'),(1,dict(responses()[1],transactions=[]),'empty'),
            (2,dict(responses()[2],transactionIndex='0x1'),'mismatch'),
            (5,dict(responses()[5],hash='0x'+'66'*32),'changed')]:
            state=m.State()
            for i,v in enumerate(responses()[:index]): state.accept(i,v)
            with self.assertRaisesRegex(m.Refusal,reason): state.accept(index,value)
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'{"a":"\\ud800"}',b'['*40+b'0'+b']'*40):
            with self.assertRaises(m.Refusal): m.strict_json(raw)
        with self.assertRaises(m.Refusal): m.envelope(b'{"jsonrpc":"2.0","id":true,"result":"0x1"}',1)
        state=m.State()
        with self.assertRaises(m.Refusal): state.accept(4,dict(pre={A:dict(nonce=True)},post={}))
        # Creation/deletion asymmetry and omitted unchanged fields are valid.
        state.accept(4,dict(pre={A:dict(nonce=1)},post={B:dict(storage={H:TX})}))
        self.assertEqual(state.modified_storage_slots,1)

    def test_transport_exact_cap_sentinel_no_redirect_retry_and_prefix(self):
        for raw,cap,passes in [(b'abcd',4,True),(b'abcdeMORE',4,False)]:
            r=Response(raw); c=Connection(r); retained=[]; observed=[]; dispatch=[]
            call=lambda: m.fetch(dict(id=1),cap,1,retained.append,
                lambda code,part: observed.append((code,part)),lambda: dispatch.append(True),
                factory=lambda *a,**k:c)
            if passes: self.assertEqual(call(),(200,4))
            else:
                with self.assertRaisesRegex(m.Refusal,'sentinel'): call()
            self.assertEqual(b''.join(retained),raw[:cap+1]); self.assertEqual(len(c.calls),1)
            self.assertEqual(len(dispatch),1); self.assertTrue(c.closed)
            self.assertEqual(r.offset,min(len(raw),cap+1))
        r=Response(b'failure',status=302); c=Connection(r); retained=[]
        self.assertEqual(m.fetch({},100,1,retained.append,lambda *x:None,lambda:None,
                                 factory=lambda *a,**k:c),(302,7))
        self.assertEqual(len(c.calls),1); self.assertEqual(b''.join(retained),b'failure')
        r=Response(b'',failure=m.http.client.IncompleteRead(b'prefix',100)); c=Connection(r); retained=[]
        with self.assertRaisesRegex(m.Refusal,'prefix_retained'):
            m.fetch({},20,1,retained.append,lambda *x:None,lambda:None,factory=lambda *a,**k:c)
        self.assertEqual(b''.join(retained),b'prefix')

    def test_timeout_and_oversized_parsed_headers_preserve_numeric_status(self):
        class Drip(Response):
            def read1(self,limit):
                if self.offset: raise TimeoutError('synthetic drip timeout')
                self.offset=1; return b'partial'
        r=Drip(b''); c=Connection(r); retained=[]; observed=[]
        with self.assertRaises(TimeoutError):
            m.fetch({},100,1,retained.append,lambda *x:observed.append(x),lambda:None,
                    factory=lambda *a,**k:c)
        self.assertEqual(b''.join(retained),b'partial'); self.assertEqual(observed[0][0],200)
        r=Response(b'',status=503,headers=[('X','x'*3000)]); c=Connection(r); observed=[]
        with self.assertRaisesRegex(m.Refusal,'headers_cap'):
            m.fetch({},10,1,lambda x:None,lambda *x:observed.append(x),lambda:None,
                    factory=lambda *a,**k:c)
        self.assertEqual(observed[0][0],503); self.assertEqual(len(observed[0][1]),2048)

    def test_frozen_scope_pins_existing_output_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=frozen_plan(); pins=[]
            for path in (m.SOURCE,m.TEST,m.DESIGN,m.DRAFT):
                raw=b'synthetic owned source'; target=root/path
                target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
                pins.append(dict(path=path,bytes=len(raw),sha256=m.sha(raw)))
            raw=(m.ROOT/m.ALLOCATION['path']).read_bytes(); target=root/m.ALLOCATION['path']
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw); pins.append(m.ALLOCATION)
            p['source_pins']=pins; target=root/m.PLAN; raw=m.encoded(p); target.write_bytes(raw)
            with patch.object(m,'ROOT',root), patch.object(m,'fetch') as fetch:
                m.verify(m.sha(raw))
                (root/m.OUT).mkdir()
                with self.assertRaises(FileExistsError): m.run(m.sha(raw))
                fetch.assert_not_called()
                (root/m.SOURCE).write_bytes(b'changed')
                with self.assertRaisesRegex(m.Refusal,'pin_identity'): m.verify(m.sha(raw))
                p['source_pins']=pins[:-1]; target.write_bytes(m.encoded(p))
                with self.assertRaisesRegex(m.Refusal,'direct_pins'): m.verify(m.sha(m.encoded(p)))

    def worker_fixture(self,out,values,postcheck_failure=False):
        calls=[]; checks=[]
        def verify(digest):
            checks.append(digest)
            if postcheck_failure and len(checks)==9: raise m.Refusal('synthetic_postcheck_failure')
            return {}
        def fetch(request,cap,seconds,emit,observe,dispatch):
            index=len(calls); calls.append(request); dispatch()
            observe(200,m.encoded(dict(status=200,headers=[])))
            raw=m.encoded(dict(jsonrpc='2.0',id=index+1,result=values[index]))
            for j in range(0,len(raw),7): emit(raw[j:j+7])
            return 200,len(raw)
        with patch.object(m,'verify',side_effect=verify), patch.object(m,'fetch',side_effect=fetch), \
             patch.object(m.resource,'setrlimit'):
            m.worker('a'*64,out,m.time.monotonic()+10)
        return calls

    def test_worker_raw_reproduction_counts_and_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); calls=self.worker_fixture(out,responses())
            self.assertEqual(len(calls),6)
            state,pin=m.replay(out/'responses.frames')
            self.assertEqual(pin['bytes'],(out/'responses.frames').stat().st_size)
            projection=m.strict_json((out/'projection.json').read_bytes())
            self.assertEqual(projection,state.projection('a'*64,pin))
            terminal=m.strict_json((out/'terminal.json').read_bytes())
            self.assertTrue(m.admitted(terminal,'a'*64,0))
            for changes in [dict(error='failure'),dict(status='other_stage'),dict(plan_sha256='b'*64),
                            dict(requests_attempted=5),dict(schema='wrong')]:
                self.assertFalse(m.admitted(dict(terminal,**changes),'a'*64,0))
            self.assertFalse(m.admitted(terminal,'a'*64,1))
            raw=(out/'responses.frames').read_bytes(); (out/'responses.frames').write_bytes(raw[:-1])
            with self.assertRaises(m.Refusal): m.replay(out/'responses.frames')

    def test_failures_stop_keep_denominator_and_postcheck_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); values=responses(); values[0]='0x2'
            calls=self.worker_fixture(out,values)
            self.assertEqual(len(calls),1)
            terminal=m.strict_json((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['request_denominator'],6)
            self.assertEqual(terminal['requests_attempted'],1); self.assertEqual(terminal['status'],'unavailable')
            self.assertTrue((out/'responses.frames').exists()); self.assertFalse((out/'projection.json').exists())
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); self.worker_fixture(out,responses(),True)
            terminal=m.strict_json((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['status'],'unavailable')
            self.assertFalse(m.admitted(terminal,'a'*64,0))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); calls=[]
            def unsupported(request,cap,seconds,emit,observe,dispatch):
                calls.append(request); dispatch(); observe(200,m.encoded(dict(status=200,headers=[])))
                raw=m.encoded(dict(jsonrpc='2.0',id=1,error=dict(code=-32601,message='method unavailable')))
                emit(raw); return 200,len(raw)
            with patch.object(m,'verify',return_value={}), patch.object(m,'fetch',side_effect=unsupported), \
                 patch.object(m.resource,'setrlimit'):
                m.worker('a'*64,out,m.time.monotonic()+5)
            self.assertEqual(len(calls),1)
            terminal=m.strict_json((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['error'],'rpc_error_no_retry')
            self.assertEqual(terminal['request_denominator'],6)
            self.assertFalse((out/'projection.json').exists())

    def test_unrecovered_worker_terminal_dispatch_unknown(self):
        class FailedProcess:
            pid=None; exitcode=1
            def start(self): raise RuntimeError('synthetic failed spawn')
        class Context:
            def Process(self,*a,**k): return FailedProcess()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(m,'ROOT',root), patch.object(m,'verify',return_value=dict(source_pins=[])), \
                 patch.object(m.multiprocessing,'get_context',return_value=Context()):
                self.assertFalse(m.run('a'*64))
            terminal=m.strict_json((root/m.OUT/'terminal.json').read_bytes())
            self.assertIsNone(terminal['requests_attempted']); self.assertIsNone(terminal['response_bytes'])
            self.assertEqual(terminal['request_denominator'],6)
            supervisor=m.strict_json((root/m.OUT/'supervisor.json').read_bytes())
            self.assertEqual(supervisor['status'],'unavailable')

    def test_lingering_worker_never_touches_run_directory_after_kill(self):
        class Lingering:
            pid=123; exitcode=None; killed=False
            def start(self): pass
            def join(self,*a,**k): pass
            def is_alive(self): return True
            def kill(self): self.killed=True
        process=Lingering()
        class Context:
            def Process(self,*a,**k): return process
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); out=root/m.OUT
            methods={name:getattr(Path,name) for name in ('exists','open','stat','iterdir')}
            def guard(name):
                def invoke(path,*args,**kwargs):
                    if process.killed and (path==out or out in path.parents):
                        self.fail('run directory touched after unconfirmed kill: '+name)
                    return methods[name](path,*args,**kwargs)
                return invoke
            with patch.object(m,'ROOT',root), patch.object(m,'verify',return_value=dict(source_pins=[])), \
                 patch.object(m.multiprocessing,'get_context',return_value=Context()), \
                 patch.object(Path,'exists',guard('exists')), patch.object(Path,'open',guard('open')), \
                 patch.object(Path,'stat',guard('stat')), patch.object(Path,'iterdir',guard('iterdir')):
                self.assertFalse(m.run('a'*64))
            receipt=m.strict_json((root/m.EXTERNAL).read_bytes())
            self.assertEqual(receipt['error'],'worker_exit_unconfirmed')
            self.assertIsNone(receipt['requests_attempted'])
            self.assertEqual(list(out.iterdir()),[out/'claim.json'])
            with self.assertRaises(m.Refusal), patch.object(m,'ROOT',root), \
                 patch.object(m,'verify',return_value=dict(source_pins=[])):
                m.run('a'*64)

    def test_outer_deadline_is_unavailable_external_only_if_safe_time(self):
        class ExpiredWait:
            pid=123; exitcode=None; live=True
            def start(self): pass
            def join(self,*a,**k):
                if self.live: raise TimeoutError('synthetic outer deadline')
            def is_alive(self): return self.live
            def kill(self): self.live=False; self.exitcode=-9
        process=ExpiredWait()
        class Context:
            def Process(self,*a,**k): return process
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(m,'ROOT',root), patch.object(m,'verify',return_value=dict(source_pins=[])), \
                 patch.object(m.multiprocessing,'get_context',return_value=Context()):
                self.assertFalse(m.run('a'*64))
            receipt=m.strict_json((root/m.EXTERNAL).read_bytes())
            self.assertEqual(receipt['error'],'outer_deadline_closeout_unknown')
            self.assertFalse((root/m.OUT/'terminal.json').exists())
            # An actually exhausted deadline does not promise or attempt a write.
            with patch.object(m,'ROOT',root), patch.object(Path,'open') as opened:
                self.assertFalse(m.external_receipt('a'*64,'deadline',m.time.monotonic()-1))
                opened.assert_not_called()

    def test_raw_and_control_cap_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); f=m.Frames(out)
            with patch.dict(m.CAPS,raw_bytes=f.used+2053+6):
                f.append(b'D',b'x')
                with self.assertRaisesRegex(m.Refusal,'raw_total'): f.append(b'D',b'y')
                f.append(b'E',b'{}')
            f.close()
            self.assertEqual(f.used,(out/'responses.frames').stat().st_size)
            with patch.dict(m.CAPS,run_controls_bytes=8200):
                with self.assertRaisesRegex(m.Refusal,'control_total'):
                    m.publish(out,'claim.json',dict(x='large enough'))
            self.assertFalse((out/'claim.json').exists())


if __name__=='__main__': unittest.main()
