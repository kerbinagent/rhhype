"""Small synthetic streams only. No RPC, old raw replay or compiler invocation."""
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); obj=importlib.util.module_from_spec(spec); spec.loader.exec_module(obj); return obj

ROOT=Path(__file__).resolve().parents[1]
m=load('eligibility_live',ROOT/'scripts/comet_eligibility_live_v1.py')
fixture=load('eligibility_fixture',ROOT/'tests/test_peer_comet_eligibility_v1.py')
KNOWN={'address':fixture.IMPL,'runtime_bytes':len(fixture.CODE['implementation'][1]),
       'runtime_sha256':m.sha(fixture.CODE['implementation'][1])}

class Response:
    def __init__(self,body,headers=None,status=200,parts=None):
        self.body=io.BytesIO(body); self.headers=headers if headers is not None else [('Content-Length',str(len(body))),('X-Duplicate','a'),('X-Duplicate','b')]
        self.status=status; self.parts=None if parts is None else list(parts); self.read_sizes=[]
    def getheaders(self): return self.headers
    def getheader(self,key):
        vals=[v for k,v in self.headers if k.lower()==key.lower()]
        return ', '.join(vals) if vals else None
    def read1(self,n):
        self.read_sizes.append(n)
        if self.parts is None: return self.body.read(n)
        if not self.parts: return b''
        value=self.parts.pop(0)
        if isinstance(value,Exception): raise value
        if len(value)>n: self.parts.insert(0,value[n:]); value=value[:n]
        return value

class Factory:
    def __init__(self,server=None,response=None): self.server=server; self.response=response; self.connections=[]
    def __call__(self,host,**kw):
        outer=self
        class Connection:
            closed=False
            def request(self,method,path,body,headers):
                self.request_obj=m.decode(body); self.method=method; self.path=path
                if outer.server is not None: outer.server.requests.append(copy.deepcopy(self.request_obj))
            def getresponse(self):
                if outer.response is not None: return outer.response
                result=outer.server.result(self.request_obj)
                return Response(m.enc({'jsonrpc':'2.0','id':self.request_obj['id'],'result':result}))
            def close(self): self.closed=True
        connection=Connection(); self.connections.append((host,kw,connection)); return connection

def collect(out,eligible=False,replies=None):
    server=fixture.SyntheticTransport(child_values=fixture.view_words(reserves=-1 if eligible else 0),replies=replies)
    frames=m.Frames(out); clock=m.Clock(); factory=Factory(server=server)
    collector=m.Collector(None,clock=clock); collector.transport=m.Transport(frames,lambda:collector.current_name,factory)
    result=collector.execute(fixture.DECISION_MS); frames.finish()
    return result,collector,clock,factory,frames

class Tests(unittest.TestCase):
    def test_complete23_and31_denominators_metadata_not_binding(self):
        for eligible,count,skipped in [(False,23,8),(True,31,0)]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                out=Path(d); result,collector,clock,factory,frames=collect(out,eligible)
                self.assertEqual(result['status'],'source_binding_unavailable'); self.assertEqual(result['requests'],count)
                self.assertIsNone(result['economics']); self.assertFalse(result['cash_closed']); self.assertEqual(result['source_binding'],'unavailable')
                self.assertEqual(result['requests']+len(result['unexecuted_steps']),31)
                self.assertEqual(len(result['runtime_roles_checked']),8 if eligible else 6)
                self.assertEqual(result['certificate_roles_matched'],[]); self.assertEqual(len(result['certificate_roles_unverified']),8)
                replayed,trace,raw_sha,total=m.replay(out/'responses.frames',clock.samples,fixture.DECISION_MS)
                self.assertEqual(m.enc(result),m.enc(replayed)); self.assertEqual(m.enc(collector.trace),m.enc(trace))
                projected=m.projection(result,'0'*64,raw_sha,total)
                self.assertTrue(projected['metadata_collection_complete']); self.assertEqual(projected['conditionally_skipped_steps'],skipped)
                self.assertEqual(projected['expected_historical_implementation'],KNOWN); self.assertTrue(projected['observed_implementation_matched'])
                self.assertEqual(projected['adapter_transport_model'],'direct_fixed_anonymous_https_jsonrpc')
                self.assertEqual(projected['engine_result']['evidence_kind'],'offline_transport'); self.assertEqual(projected['engine_result']['network_requests_permitted'],0)
                records,_,_=m.parse_frames(out/'responses.frames')
                self.assertEqual(records[0]['http']['headers'][-2:],[['X-Duplicate','a'],['X-Duplicate','b']])
                self.assertTrue(all(c[0]=='ethereum-rpc.publicnode.com' and c[2].method=='POST' and c[2].path=='/' and c[2].closed for c in factory.connections))

    def test_impl_address_and_runtime_gate_before_further_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            # Actual frozen historical address differs from synthetic slot: stop at4.
            result,collector,_,_,_=collect(Path(d))
            self.assertEqual(result['status'],'known_implementation_mismatch'); self.assertEqual(result['requests'],4)
            self.assertEqual(result['runtime_roles_checked'],['proxy'])
            self.assertNotIn('parent_eligibility_claim',result['metadata'])
            self.assertFalse(m.projection(result,'0'*64,'1'*64,result['body_bytes'])['observed_implementation_matched'])
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            result,_,_,_,_=collect(Path(d),replies={'implementation_code':'0x6002'})
            self.assertEqual(result['status'],'known_implementation_mismatch'); self.assertEqual(result['requests'],5)
            self.assertEqual(result['requests']+len(result['unexecuted_steps']),31)
            self.assertFalse(m.projection(result,'0'*64,'1'*64,result['body_bytes'])['observed_implementation_matched'])

    def test_partial_roles_and_parent_child_final_failures_remain_unknown(self):
        for replies,status,count in [({'baseScale()':fixture.word(1)},'identity_unavailable',10),
                                      ({'final_implementation':fixture.addr(fixture.USDC_IMPL)},'canonicality_unavailable',23),
                                      ({'final_parent':{**fixture.PARENT,'stateRoot':'0x'+'aa'*32}},'canonicality_unavailable',23)]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                result,_,_,_,_=collect(Path(d),replies=replies)
                self.assertEqual(result['status'],status); self.assertEqual(result['requests'],count)
                projected=m.projection(result,'0'*64,'1'*64,result['body_bytes'])
                self.assertFalse(projected['metadata_collection_complete']); self.assertEqual(projected['source_binding'],'unavailable')
                self.assertTrue(projected['observed_implementation_matched'])  # these later failures follow the successful implementation gate
                self.assertEqual(result['requests']+len(result['unexecuted_steps']),31)
                self.assertFalse(result['runtime_dependency_closure_complete'])

    def test_timeout_and_incomplete_prefix_fsynced_and_no_retry(self):
        for exception in [TimeoutError('drip'),m.http.client.IncompleteRead(b'cd')]:
            with tempfile.TemporaryDirectory() as d:
                out=Path(d); frames=m.Frames(out); response=Response(b'',headers=[],parts=[b'ab',exception])
                factory=Factory(response=response); collector=m.Collector(None); collector.transport=m.Transport(frames,lambda:collector.current_name,factory)
                result=collector.execute(0); frames.finish()
                records,_,total=m.parse_frames(out/'responses.frames',complete=False)
                expected=b'abcd' if isinstance(exception,m.http.client.IncompleteRead) else b'ab'
                self.assertEqual(records[0]['body'],expected); self.assertEqual(total,len(expected))
                self.assertEqual(len(factory.connections),1); self.assertTrue(factory.connections[0][2].closed)
                self.assertEqual(result['requests'],1); self.assertFalse(records[0]['end']['eof'])
                self.assertEqual(records[0]['end']['outcome'],'unavailable')
                with self.assertRaises(m.Refusal): m.parse_frames(out/'responses.frames')

    def test_cumulative_boundary_no_overread_http_redirect_no_retry(self):
        with tempfile.TemporaryDirectory() as d:
            frames=m.Frames(Path(d)); frames.body_bytes=m.CAPS['cumulative_body_bytes']-3
            response=Response(b'',headers=[],parts=[b'abcdef']); factory=Factory(response=response)
            transport=m.Transport(frames,lambda:'chain',factory)
            _,stream=transport({'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]},1)
            with self.assertRaisesRegex(m.Refusal,'remaining_cap'):
                with stream:
                    self.assertEqual(stream.read(8192),b'abc'); stream.read(8192)
            self.assertEqual(response.read_sizes,[3]); frames.finish()
        with tempfile.TemporaryDirectory() as d:
            frames=m.Frames(Path(d)); response=Response(b'error',headers=[('Location','https://other.invalid')],status=302)
            factory=Factory(response=response); collector=m.Collector(None); collector.transport=m.Transport(frames,lambda:collector.current_name,factory)
            result=collector.execute(0); frames.finish()
            self.assertEqual(result['requests'],1); self.assertEqual(len(factory.connections),1)
            rows,_,_=m.parse_frames(Path(d)/'responses.frames',complete=False)
            self.assertEqual(rows[0]['http']['http_status'],302); self.assertEqual(rows[0]['body'],b'error')

    def test_frames_caps_same_inode_corruption_and_truncated_failure(self):
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            out=Path(d); result,_,clock,_,_=collect(out)
            records,_,_=m.parse_frames(out/'responses.frames'); self.assertEqual(len(records),23)
            raw=(out/'responses.frames').read_bytes(); (out/'responses.frames').write_bytes(raw[:-1])
            with self.assertRaises(m.Refusal): m.parse_frames(out/'responses.frames')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); frames=m.Frames(out); inode=frames.path.stat().st_ino
            frames.bytes=m.CAPS['raw_bytes']-6
            with self.assertRaises(m.Refusal): frames.frame(ord('D'),b'ab')
            frames.finish(); self.assertEqual((out/'responses.frames').stat().st_ino,inode)
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            out=Path(d); result,_,clock,_,_=collect(out)
            clock.samples[0]=clock.samples[0]+1
            with self.assertRaises(m.Refusal): m.replay(out/'responses.frames',clock.samples,fixture.DECISION_MS)

    def test_worker_reproduces_saved_success_and_retains_failure_projection(self):
        for replies,expected in [(None,'metadata_collection_complete'),({'baseScale()':fixture.word(1)},'unavailable')]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                out=Path(d); server=fixture.SyntheticTransport(child_values=fixture.view_words(reserves=0),replies=replies)
                factory=Factory(server=server); original=m.Transport
                with patch.object(m,'verify'),patch.object(m,'Transport',side_effect=lambda frames,name:original(frames,name,factory)):
                    m.worker('0'*64,out,m.time.monotonic()+5)
                terminal=m.decode((out/'terminal.json').read_bytes()); projected=m.decode((out/'projection.json').read_bytes())
                self.assertEqual(terminal['status'],expected); self.assertEqual(projected['engine_result']['requests']+len(projected['engine_result']['unexecuted_steps']),31)
                self.assertEqual(projected['engine_result']['source_binding'],'unavailable')
                self.assertLess(sum(p.stat().st_size for p in out.iterdir()),150000)

    def test_default_dry_no_network_outputs_and_existing_output_refusal(self):
        with patch.object(m,'fixed_pins'),patch.object(m,'run',side_effect=AssertionError('run')),patch.object(m,'Transport',side_effect=AssertionError('network')),patch('sys.stdout',io.StringIO()):
            self.assertEqual(m.main([]),0)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/m.OUT).mkdir(parents=True)
            with patch.object(m,'ROOT',root),patch.object(m,'verify'),patch.object(m,'worker',side_effect=AssertionError('worker')):
                with self.assertRaises(FileExistsError): m.run('0'*64)

    def test_deadline_nested_earlier_timer_and_exact_terminal_admission(self):
        with self.assertRaises(TimeoutError):
            with m.alarm(0.02):
                with m.alarm(1): m.time.sleep(0.1)
        for status,error,plan in [('source_binding_unavailable',None,'0'*64),('metadata_collection_complete','failure','0'*64),('metadata_collection_complete',None,'1'*64)]:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d); (root/Path(m.OUT).parent).mkdir(parents=True)
                def worker(digest,out,deadline): m.publish(out,'terminal.json',{'status':status,'error':error,'plan_sha256':plan,'requests_attempted':0},8192)
                with patch.object(m,'ROOT',root),patch.object(m,'verify',return_value={'source_pins':[]}),patch.object(m,'worker',worker):
                    self.assertFalse(m.run('0'*64))
                supervisor=m.decode((root/m.OUT/'supervisor.json').read_bytes()); self.assertEqual(supervisor['status'],'unavailable')

    def test_whole_worker_deadline_retains_pending_prefix_without_success(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            def interrupted(digest,out,deadline):
                frames=m.Frames(out); frames.frame(ord('B'),m.enc({'request':{'id':1}}))
                frames.handle.close(); m.time.sleep(0.2)
            started=m.time.monotonic()
            with patch.object(m,'_worker',interrupted): m.worker('0'*64,out,started+0.03)
            self.assertLess(m.time.monotonic()-started,0.15)
            self.assertFalse((out/'terminal.json').exists()); self.assertTrue((out/'responses.frames.pending').exists())
            m.identity.finalize_partial(out)
            self.assertTrue((out/'responses.frames').read_bytes().startswith(m.MAGIC))

    def test_controls_reserve_and_source_plan_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); out=root/'out'; out.mkdir()
            (out/'earlier.json').write_bytes(b'x'*32760)
            with self.assertRaisesRegex(m.Refusal,'controls_cap'): m.publish(out,'new.json',{'x':'long'},8192)
            path=root/m.PLAN; path.parent.mkdir(parents=True); path.write_bytes(b'{}')
            with patch.object(m,'ROOT',root):
                with self.assertRaisesRegex(m.Refusal,'plan_sha'): m.verify('0'*64)

if __name__=='__main__': unittest.main()
