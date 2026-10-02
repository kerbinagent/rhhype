"""Small offline fixtures only: never downloads or executes a compiler."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec=importlib.util.spec_from_file_location('reproduction',Path(__file__).resolve().parents[1]/'scripts/comet_reproduction_v1.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def fixture():
    units={f'u{i}.sol':{'content':'x'} for i in range(11)}
    meta={'compiler':{'version':m.VERSION},'language':'Solidity',
          'sources':{k:{'keccak256':m.keccak(b'x')} for k in units},
          'settings':{'compilationTarget':{'u0.sol':'Comet'},'libraries':{},'remappings':[],
                      'optimizer':{'enabled':True,'runs':1},'evmVersion':'london'}}
    standard,target=m.standard_input(meta,{'sources':units})
    literal=m.enc(meta); compiled=bytes(32)+b'\xab'*8+b'\x00\x00'
    runtime=b'\x11'*32+compiled[32:]
    sources={k:{'id':i,'ast':{'absolutePath':k,'nodeType':'SourceUnit','nodes':[]}} for i,k in enumerate(units)}
    sources['u0.sol']['ast']['nodes']=[{'nodeType':'VariableDeclaration','id':99,'mutability':'immutable',
        'src':'0:1:0','name':'baseToken','typeDescriptions':{'typeString':'address'}}]
    output={'sources':sources,'contracts':{'u0.sol':{'Comet':{'metadata':literal.decode(),
        'evm':{'deployedBytecode':{'object':compiled.hex(),'linkReferences':{},
                                'immutableReferences':{'99':[{'start':0,'length':32}]}}}}}}}
    return meta,standard,target,literal,runtime,output

class Response:
    status=200
    def __init__(self,parts,status=200,headers=None): self.parts=list(parts); self.status=status; self.headers=headers or {}; self.limits=[]
    def getheader(self,k): return self.headers.get(k)
    def read1(self,n):
        self.limits.append(n)
        if not self.parts: return b''
        value=self.parts.pop(0)
        if isinstance(value,Exception): raise value
        if len(value)>n: self.parts.insert(0,value[n:]); return value[:n]
        return value

class Connection:
    def __init__(self,response): self.response=response; self.requests=0; self.closed=False
    def request(self,*a,**kw): self.requests+=1
    def getresponse(self): return self.response
    def close(self): self.closed=True

class Tests(unittest.TestCase):
    def test_keccak_vectors_and_manifest_hashes(self):
        m.crypto_check()
        self.assertEqual(m.keccak(b''),'0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
        build={'path':m.BINARY,'version':'0.8.15','longVersion':m.VERSION,'build':'commit.e14f2714',
               'sha256':'0x'+m.sha(b'binary'),'keccak256':m.keccak(b'binary')}
        manifest={'builds':[build],'releases':{'0.8.15':m.BINARY}}
        self.assertEqual(m.compiler_build(manifest),build)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'binary'; path.write_bytes(b'binary')
            self.assertEqual(m.check_binary(path,build)['bytes'],6)
            path.write_bytes(b'bad')
            with self.assertRaises(m.Refusal): m.check_binary(path,build)
        manifest['builds'].append(build)
        with self.assertRaises(m.Refusal): m.compiler_build(manifest)

    def test_content_only_exact_sources_settings_and_target(self):
        meta,standard,*_=fixture()
        self.assertNotIn('compilationTarget',standard['settings'])
        self.assertEqual(standard['settings']['optimizer'],meta['settings']['optimizer'])
        self.assertEqual(set(standard['sources']),set(meta['sources']))
        units=copy.deepcopy(standard['sources']); units['u0.sol']['content']='changed'
        with self.assertRaisesRegex(m.Refusal,'source_keccak'): m.standard_input(meta,{'sources':units})
        units.pop('u0.sol')
        with self.assertRaisesRegex(m.Refusal,'source_names'): m.standard_input(meta,{'sources':units})
        meta['settings']['libraries']={'u0.sol':{'X':'0x'+'11'*20}}
        with self.assertRaisesRegex(m.Refusal,'libraries'): m.standard_input(meta,{'sources':standard['sources']})

    def test_full_reproduction_not_provider_claim_and_compiler_errors(self):
        _,standard,target,literal,runtime,out=fixture()
        result=m.compare_output(out,standard,target,literal,runtime)
        self.assertEqual(result['status'],'exact_historical_implementation_reproduced')
        self.assertFalse(result['economics']); self.assertFalse(result['external_dependencies_equivalent'])
        out['errors']=[{'severity':'error','message':'bad'}]
        with self.assertRaisesRegex(m.Refusal,'compiler_error'): m.compare_output(out,standard,target,literal,runtime)
        del out['errors']; out['contracts']['u0.sol']['Comet']['metadata']+=' '
        with self.assertRaisesRegex(m.Refusal,'metadata_literal'): m.compare_output(out,standard,target,literal,runtime)

    def test_immutable_ast_ranges_repeats_and_unpatched_difference(self):
        _,standard,target,literal,runtime,out=fixture()
        out['sources']['u0.sol']['ast']['nodes'][0]['src']='0:1:10'
        with self.assertRaisesRegex(m.Refusal,'immutable_span'): m.compare_output(out,standard,target,literal,runtime)
        out['sources']['u0.sol']['ast']['nodes'][0]['src']='0:1:0'
        dep=out['contracts']['u0.sol']['Comet']['evm']['deployedBytecode']
        dep['immutableReferences']['99'][0]['length']=31
        with self.assertRaisesRegex(m.Refusal,'immutable_range'): m.compare_output(out,standard,target,literal,runtime)
        dep['immutableReferences']['99'][0]['length']=32
        with self.assertRaisesRegex(m.Refusal,'full_runtime_mismatch'): m.compare_output(out,standard,target,literal,runtime[:32]+b'\xcd'+runtime[33:])
        dep['object']='01'+dep['object'][2:]
        with self.assertRaisesRegex(m.Refusal,'nonzero_placeholder'): m.compare_output(out,standard,target,literal,runtime)

    def test_exact_repeats_and_overlap_rejected(self):
        _,standard,target,literal,runtime,out=fixture()
        dep=out['contracts']['u0.sol']['Comet']['evm']['deployedBytecode']
        dep['object']=(bytes(64)+b'\x00\x00').hex()
        dep['immutableReferences']['99']=[{'start':0,'length':32},{'start':32,'length':32}]
        runtime=b'\x11'*64+b'\x00\x00'
        self.assertEqual(len(m.compare_output(out,standard,target,literal,runtime)['immutables']),1)
        with self.assertRaisesRegex(m.Refusal,'repeat_disagreement'): m.compare_output(out,standard,target,literal,b'\x11'*32+b'\x22'*32+b'\x00\x00')
        dep['immutableReferences']['99'][1]['start']=16
        with self.assertRaises(m.Refusal): m.compare_output(out,standard,target,literal,runtime)

    def test_transport_sentinel_http_error_partial_and_no_retry(self):
        request={'host':'fixed.invalid','path':'/fixed','cap':4,'seconds':1}
        for response,expected,reason in [
            (Response([b'ab',b'cd']),b'abcd',None),
            (Response([b'abcdef']),b'abcde','body_cap'),
            (Response([b'bad'],302),b'bad','http_status'),
            (Response([b'a',m.http.client.IncompleteRead(b'bc')]),b'abc','incomplete_body')]:
            connection=Connection(response); parts=[]; statuses=[]
            if reason:
                with self.assertRaisesRegex(m.Refusal,reason): m.get(request,parts.append,statuses.append,lambda *a,**kw:connection)
            else: self.assertEqual(m.get(request,parts.append,statuses.append,lambda *a,**kw:connection),4)
            self.assertEqual(b''.join(parts),expected); self.assertEqual(connection.requests,1); self.assertTrue(connection.closed)
            self.assertEqual(statuses,[response.status])
        self.assertEqual(response.limits,[5,4])

    def test_partial_raw_same_inode_and_dry_no_output_or_requests(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); pending=out/'sources.pending'; pending.write_bytes(b'partial')
            inode=pending.stat().st_ino; m.finalize(out,'sources')
            self.assertEqual((out/'sources.raw').stat().st_ino,inode)
            self.assertEqual((out/'sources.raw').read_bytes(),b'partial')
            with patch.object(m,'pin') as pin,patch.object(m,'stage',side_effect=AssertionError('stage')),patch.object(m,'get',side_effect=AssertionError('HTTP')),patch('sys.stdout',io.StringIO()):
                self.assertEqual(m.main([]),0); self.assertEqual(pin.call_count,4)

    def test_deadline_preserves_received_prefix_and_nested_timer(self):
        request={'host':'fixed.invalid','path':'/fixed','cap':4,'seconds':1}
        connection=Connection(Response([b'ab',TimeoutError('drip')]))
        parts=[]
        with self.assertRaises(TimeoutError): m.get(request,parts.append,lambda s:None,lambda *a,**kw:connection)
        self.assertEqual(b''.join(parts),b'ab'); self.assertEqual(connection.requests,1); self.assertTrue(connection.closed)
        started=m.time.monotonic()
        with self.assertRaises(TimeoutError):
            with m.alarm(0.02):
                with m.alarm(1): m.time.sleep(0.1)
        self.assertLess(m.time.monotonic()-started,0.1)

    def test_plan_pins_scope_and_existing_output_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/Path(m.PLAN).parent).mkdir(parents=True)
            plan={'schema':'comet-reproduction-v1','status':'frozen_root_only','allocation':m.ALLOCATION,'input_pins':m.INPUTS,
                  'requests':m.REQUESTS,'limits':m.LIMITS,'output_dir':m.OUT,'compiler':m.VERSION,'claims':m.CLAIMS,
                  'sandbox_ack':m.SANDBOX_ACK,'crypto':m.CRYPTO,'runtime':{'python':'3.13.9','executable':'.venv/bin/python'},
                  'source_pins':[{'path':p} for p in (m.SOURCE,m.TEST,m.DESIGN)]}
            raw=m.enc(plan); (root/m.PLAN).write_bytes(raw)
            with patch.object(m,'ROOT',root),patch.object(m,'pin'),patch.object(m,'crypto_check'),patch.object(m.sys,'executable',str(root/'.venv/bin/python')):
                m.verify(m.sha(raw))
                with self.assertRaises(m.Refusal): m.verify('0'*64)
                plan['requests']=[]; raw=m.enc(plan); (root/m.PLAN).write_bytes(raw)
                with self.assertRaisesRegex(m.Refusal,'plan_scope'): m.verify(m.sha(raw))
            out=root/m.OUT; out.mkdir(parents=True)
            with patch.object(m,'ROOT',root),patch.object(m,'verify'),patch.object(m,'acquire_worker',side_effect=AssertionError('worker')):
                with self.assertRaises(FileExistsError): m.stage('acquire','0'*64)

    def test_failure_supervisor_and_unchanged_input_before_after(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/Path(m.OUT).parent).mkdir(parents=True)
            def worker(digest,out,pid):
                (out/'sources.pending').write_bytes(b'prefix')
                m.publish(out,'download-terminal.json',{'status':'unavailable','requests_attempted':2})
            with patch.object(m,'ROOT',root),patch.object(m,'verify'),patch.object(m,'acquire_worker',worker):
                self.assertFalse(m.stage('acquire','0'*64))
            out=root/m.OUT
            self.assertEqual((out/'sources.raw').read_bytes(),b'prefix')
            self.assertEqual(m.js((out/'acquire-supervisor.json').read_bytes())['requests_attempted'],2)
            with self.assertRaises(m.Refusal): m.verify_artifacts(out,'0'*64)

    def test_compile_cannot_salvage_failed_download_supervisor(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); digest='0'*64
            build={'path':m.BINARY,'version':'0.8.15','longVersion':m.VERSION,'build':'commit.e14f2714',
                   'sha256':'0x'+m.sha(b'binary'),'keccak256':m.keccak(b'binary')}
            bodies={'manifest':m.enc({'builds':[build],'releases':{'0.8.15':m.BINARY}}),'compiler':b'binary','sources':b'{}'}
            for name,body in bodies.items(): (out/(name+'.raw')).write_bytes(body)
            terminal={'status':'artifacts_authenticated','plan_sha256':digest,'requests_attempted':3,'error':None,
                      'http_statuses':[{'request':r['name'],'status':200} for r in m.REQUESTS],
                      'manifest_build':build,'raw_pins':[{'name':k,'bytes':len(v),'sha256':m.sha(v)} for k,v in bodies.items()]}
            (out/'download-terminal.json').write_bytes(m.enc(terminal))
            for status,error,exitcode in [('unavailable',None,0),('artifacts_authenticated','postcheck',0),('artifacts_authenticated',None,1)]:
                (out/'acquire-supervisor.json').write_bytes(m.enc({'status':status,'error':error,'exitcode':exitcode,'plan_sha256':digest}))
                with self.assertRaisesRegex(m.Refusal,'supervisor_unavailable'): m.verify_artifacts(out,digest)
            (out/'acquire-supervisor.json').write_bytes(m.enc({'status':'artifacts_authenticated','error':None,'exitcode':0,'plan_sha256':digest}))
            m.verify_artifacts(out,digest)
            terminal['http_statuses'].reverse(); (out/'download-terminal.json').write_bytes(m.enc(terminal))
            with self.assertRaisesRegex(m.Refusal,'http_identity'): m.verify_artifacts(out,digest)

    def test_compiler_prefix_cap_kills_mock_and_retains_no_large_buffers(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); inp=out/'input'; inp.write_bytes(b'{}'); cwd=out/'empty'; cwd.mkdir()
            child=Mock(pid=123,stdout=Mock(),stderr=Mock()); child.stdout.fileno.return_value=3; child.stderr.fileno.return_value=4
            child.poll.return_value=None; child.wait.return_value=0
            selector=Mock(); selector.get_map.return_value={1:1}
            key=Mock(fileobj=child.stdout,data=('stdout',None))
            def selected(_):
                key.data=('stdout',holder['file']); return [(key,1)]
            holder={}
            original=Path.open
            def opened(path,*a,**kw):
                f=original(path,*a,**kw)
                if path.name=='stdout.pending': holder['file']=f
                return f
            limits={**m.LIMITS,'stdout_bytes':4}
            with patch.object(m,'LIMITS',limits),patch.object(m.selectors,'DefaultSelector',return_value=selector),patch.object(selector,'select',side_effect=selected),patch.object(m.os,'set_blocking'),patch.object(m.os,'read',return_value=b'12345'),patch.object(m.os,'killpg') as kill,patch.object(Path,'open',opened):
                calls=[]
                def launch(argv,**kw): calls.append((argv,kw)); return child
                with self.assertRaisesRegex(m.Refusal,'stdout_cap'): m.compile_process(out/'fake',inp,out,cwd,launcher=launch)
            self.assertEqual(calls[0][0],[str(out/'fake'),'--standard-json','--base-path',str(cwd),'--allow-paths',str(cwd)])
            self.assertEqual(calls[0][1]['env'],{'LANG':'C','LC_ALL':'C'}); self.assertEqual(list(cwd.iterdir()),[])
            (cwd/'unexpected.sol').write_text('x')
            with self.assertRaisesRegex(m.Refusal,'not_empty'): m.compile_process(out/'fake',inp,out,cwd,launcher=launch)
            self.assertEqual((out/'stdout.raw').read_bytes(),b'1234'); kill.assert_called_once()

    def test_preexec_parent_death_guard_closes_unpublished_pid_race(self):
        libc=Mock(); libc.prctl.return_value=0
        with patch.object(m.os,'getppid',return_value=10),patch.object(m.os,'getpid',return_value=20),patch.object(m.os,'kill') as kill:
            m.parent_death_guard(10,libc); kill.assert_not_called()
            m.parent_death_guard(9,libc); kill.assert_called_once_with(20,m.signal.SIGKILL)
        libc.prctl.assert_called_with(1,m.signal.SIGKILL,0,0,0)
        libc.prctl.return_value=-1
        with self.assertRaises(OSError): m.parent_death_guard(10,libc)

    def test_final_download_pin_failure_never_publishes_success(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            def get(request,emit,status): status(200); emit(b'{}')
            with patch.object(m,'verify'),patch.object(m,'get',get),patch.object(m,'compiler_build',return_value={}),patch.object(m,'check_binary',return_value={}),patch.object(m,'authenticated_inputs',return_value=({},b'',b'')),patch.object(m,'standard_input'),patch.object(m,'fingerprint',side_effect=m.Refusal('final_pin')):
                m.acquire_worker('0'*64,out)
            terminal=m.js((out/'download-terminal.json').read_bytes())
            self.assertEqual(terminal['status'],'unavailable'); self.assertIn('final_pin',terminal['error'])
            self.assertEqual(terminal['requests_attempted'],3)
            for name in ('manifest','compiler','sources'): self.assertEqual((out/(name+'.raw')).read_bytes(),b'{}')

    def test_stage_admission_exact_status_plan_and_error_for_both_stages(self):
        digest='0'*64
        for stage_name,expected,wrong in [('acquire','artifacts_authenticated','exact_historical_implementation_reproduced'),('compile','exact_historical_implementation_reproduced','artifacts_authenticated')]:
            for status,error,plan,admitted in [(expected,None,digest,True),(wrong,None,digest,False),(expected,'late_failure',digest,False),(expected,None,'1'*64,False)]:
                with tempfile.TemporaryDirectory() as d:
                    root=Path(d); out=root/m.OUT
                    if stage_name=='compile': out.mkdir(parents=True)
                    else: out.parent.mkdir(parents=True)
                    def worker(got,out,pid):
                        filename='download-terminal.json' if stage_name=='acquire' else 'compile-terminal.json'
                        m.publish(out,filename,{'status':status,'error':error,'plan_sha256':plan,'requests_attempted':3})
                    with patch.object(m,'ROOT',root),patch.object(m,'verify'),patch.object(m,'verify_artifacts'),patch.object(m,'acquire_worker',worker),patch.object(m,'compile_worker',worker):
                        self.assertEqual(m.stage(stage_name,digest,m.SANDBOX_ACK),admitted)
                    supervisor=m.js((out/(stage_name+'-supervisor.json')).read_bytes())
                    self.assertEqual(supervisor['status'],expected if admitted else 'unavailable')

if __name__=='__main__': unittest.main()
