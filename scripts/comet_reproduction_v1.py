"""Offline preparation; acquisition and sandbox compilation require a separate freeze.

No RPC, source URLs, installer, or compiler is invoked by default or acquisition.
Compilation's network isolation is an external launch precondition, not a Python claim.
"""
import argparse
import ctypes
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import ssl
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/comet_reproduction_v1.py'
TEST = 'tests/test_comet_reproduction_v1.py'
DESIGN = 'reports/comet-reproduction-v1/design.txt'
PLAN = 'reports/experiment-storage/comet-reproduction-v1.json'
OUT = 'reports/comet-reproduction-v1/run-v1'
ALLOCATION = {'path':'reports/experiment-storage/comet-reproduction-hip4-live-preparation-allocation-v1.json',
              'bytes':5982,'sha256':'1d2a63ddd166129959108c936fbeaf1bf0311e5c5ad54da0599169b0677b0bd4'}
INPUTS = [
 {'path':'reports/comet-sourcify-lookup-v1/run-v1/response.raw','bytes':124569,'sha256':'5c314b54024ea40dca7463793ca74cccfc7ee6b9a28275b0c5b3d5ac952cab68'},
 {'path':'reports/comet-sourcify-lookup-v1/literal-metadata-root-review.json','bytes':2017,'sha256':'61fba9a302d6e601dda0496e3ce97795f21ff870a3a0f22f7326b83f0984af6c'},
 {'path':'reports/comet-identity-v1/run-v1/projection.json','bytes':1375,'sha256':'a6025a1fde7811d92a050da087f34083c875de86c32e45825b1f664d9f590a07'}]
VERSION = '0.8.15+commit.e14f2714'
BINARY = 'solc-linux-amd64-v'+VERSION
REQUESTS = [
 {'name':'manifest','host':'binaries.soliditylang.org','path':'/linux-amd64/list.json','cap':131072,'seconds':30},
 {'name':'compiler','host':'binaries.soliditylang.org','path':'/linux-amd64/'+BINARY,'cap':20971520,'seconds':90},
 {'name':'sources','host':'sourcify.dev','path':'/server/v2/contract/1/0x63e749153baf1838f63ca22c275370bd2b1ceb15?fields=sources','cap':1048576,'seconds':30}]
LIMITS = {'download_seconds':150,'download_supervisor_seconds':155,'compile_seconds':240,
          'compile_supervisor_seconds':245,'cpu_seconds':180,'address_space_bytes':1073741824,
          'stdout_bytes':8388608,'stderr_bytes':65536,'input_bytes':1048576,'projection_bytes':65536}
RUNTIME_SHA = 'b942614560ef7218a52173cc501ce9198f74a558348edf957cda62a218aa20fe'
META_SHA = '386c4a9822d4475b90c59addf8153cb0b10f83a237af2a60b75aa3eeb2f03b6a'
SANDBOX_ACK = 'empty-workdir-network-isolated-external-sandbox'
CLAIMS = {'external_dependencies_equivalent':False,'proxy_equivalent':False,
          'future_upgrades_equivalent':False,'eligibility':False,'economics':False}

class Refusal(Exception): pass

def utc(): return datetime.now(timezone.utc).isoformat()
def context():
    return {'pid':os.getpid(),'ppid':os.getppid(),'cwd':os.getcwd(),'python_executable':sys.executable,
            'network_namespace':os.readlink('/proc/self/ns/net'),'sandbox_is_external_precondition':True}
def sha(b): return hashlib.sha256(b).hexdigest()
def enc(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def js(raw, nodes=1000000, depth=256):
    def pairs(items):
        obj={}
        for k,v in items:
            if k in obj: raise Refusal('duplicate_json_key')
            obj[k]=v
        return obj
    def reject(_): raise Refusal('nonfinite_json')
    def number(s):
        v=float(s)
        if not math.isfinite(v): reject(s)
        return v
    obj=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=reject,parse_float=number)
    pending=[(obj,0)]; count=0
    while pending:
        v,d=pending.pop(); count+=1
        if count>nodes or d>depth: raise Refusal('json_complexity')
        if isinstance(v,dict): pending.extend((x,d+1) for x in v.values())
        elif isinstance(v,list): pending.extend((x,d+1) for x in v)
    if not isinstance(obj,dict): raise Refusal('json_object_required')
    return obj

def read(path, cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as f: b=f.read(cap+1)
    if len(b)>cap: raise Refusal('file_cap')
    return b

def fingerprint(path, cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    n=0; digest=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            b=f.read(min(65536,cap+1-n))
            if not b: break
            n+=len(b); digest.update(b)
            if n>cap: raise Refusal('file_cap')
    return n,digest.hexdigest()

def pin(p, cap):
    if (not isinstance(p,dict) or set(p)!={'path','bytes','sha256'} or type(p['bytes']) is not int
        or not 0<p['bytes']<=cap or not re.fullmatch('[0-9a-f]{64}',p['sha256'])): raise Refusal('pin_schema')
    path=ROOT/p['path']
    if any(x.is_symlink() for x in (path,*path.parents)) or not path.resolve().is_relative_to(ROOT): raise Refusal('pin_path')
    if fingerprint(path,cap)!=(p['bytes'],p['sha256']): raise Refusal('pin_mismatch')

def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise Refusal('plan_sha_required')
    raw=read(ROOT/PLAN,16384)
    if sha(raw)!=digest: raise Refusal('plan_sha')
    p=js(raw,5000,32)
    if (p.get('schema')!='comet-reproduction-v1' or p.get('status')!='frozen_root_only'
        or p.get('allocation')!=ALLOCATION or p.get('input_pins')!=INPUTS or p.get('requests')!=REQUESTS
        or p.get('limits')!=LIMITS or p.get('output_dir')!=OUT or p.get('compiler')!=VERSION
        or p.get('claims')!=CLAIMS or p.get('sandbox_ack')!=SANDBOX_ACK or p.get('crypto')!=CRYPTO or p.get('runtime')!={'python':'3.13.9','executable':'.venv/bin/python'}): raise Refusal('plan_scope')
    pins=p.get('source_pins')
    if not isinstance(pins,list) or len(pins)!=3 or {x.get('path') for x in pins if isinstance(x,dict)}!={SOURCE,TEST,DESIGN}: raise Refusal('source_pins')
    for x in [ALLOCATION,*INPUTS,*pins]: pin(x,196608)
    if sys.version_info[:3]!=(3,13,9) or Path(sys.executable).absolute()!=ROOT/'.venv/bin/python': raise Refusal('python_runtime')
    crypto_check()
    if (ROOT/OUT).is_symlink(): raise Refusal('output_symlink')
    return p

CRYPTO = {'version':'3.23.0',
          'python_sha256':'f798f27e64aa5bd3ebd9dbea293cba4930de3c26d6579a0e805b8c2abac6a244',
          'native_bytes':41632,'native_sha256':'78e30b92f3c32ab063ccf462b3d1079fc8291a692242b502c33ff878287e522e'}

def crypto_check():
    import importlib.metadata
    import Crypto.Hash.keccak as module
    path=Path(module.__file__)
    native=path.with_name('_keccak.abi3.so')
    if (importlib.metadata.version('pycryptodome')!=CRYPTO['version']
        or path.resolve()!=ROOT/'.venv/lib/python3.13/site-packages/Crypto/Hash/keccak.py'
        or fingerprint(path,16384)[1]!=CRYPTO['python_sha256']
        or fingerprint(native,65536)!=(CRYPTO['native_bytes'],CRYPTO['native_sha256'])): raise Refusal('keccak_runtime_pin')
    return module

def new_keccak():
    from Crypto.Hash import keccak
    return keccak.new(digest_bits=256)

def keccak(b):
    k=new_keccak(); k.update(b); return '0x'+k.hexdigest()

def compiler_build(manifest):
    builds=manifest.get('builds'); releases=manifest.get('releases')
    if not isinstance(builds,list) or not isinstance(releases,dict) or releases.get('0.8.15')!=BINARY: raise Refusal('compiler_release')
    found=[x for x in builds if isinstance(x,dict) and (x.get('path')==BINARY or x.get('longVersion')==VERSION)]
    if len(found)!=1: raise Refusal('compiler_build_unique')
    x=found[0]
    if x.get('path')!=BINARY or x.get('version')!='0.8.15' or x.get('longVersion')!=VERSION or x.get('build')!='commit.e14f2714': raise Refusal('compiler_version')
    for field in ('sha256','keccak256'):
        if not isinstance(x.get(field),str) or not re.fullmatch('0x[0-9a-f]{64}',x[field]): raise Refusal('compiler_hash_schema')
    return {k:x[k] for k in ('path','version','longVersion','build','sha256','keccak256')}

def check_binary(path, build):
    n,d=fingerprint(path,20971520)
    if not n or '0x'+d!=build['sha256']: raise Refusal('compiler_sha256')
    k=new_keccak()
    with path.open('rb') as f:
        while b:=f.read(65536): k.update(b)
    if '0x'+k.hexdigest()!=build['keccak256']: raise Refusal('compiler_keccak')
    return {'bytes':n,'sha256':d,'keccak256':'0x'+k.hexdigest()}

def authenticated_inputs():
    raw=read(ROOT/INPUTS[0]['path'],124569); meta=raw[12:40242]
    if sha(meta)!=META_SHA or len(meta)!=40230: raise Refusal('literal_metadata_slice')
    obj=js(raw); metadata=js(meta)
    if obj.get('metadata')!=metadata: raise Refusal('literal_metadata_wrapper')
    value=obj.get('runtimeBytecode',{}).get('onchainBytecode')
    if not isinstance(value,str) or not re.fullmatch('0x[0-9a-fA-F]+',value): raise Refusal('retained_runtime_hex')
    runtime=bytes.fromhex(value[2:])
    if len(runtime)!=18599 or sha(runtime)!=RUNTIME_SHA: raise Refusal('retained_runtime_identity')
    if metadata.get('compiler',{}).get('version')!=VERSION: raise Refusal('metadata_compiler')
    sources=metadata.get('sources'); settings=metadata.get('settings')
    if not isinstance(sources,dict) or len(sources)!=11 or not isinstance(settings,dict): raise Refusal('metadata_source_count')
    return metadata,meta,runtime

def standard_input(metadata, sources_response):
    units=sources_response.get('sources')
    expected=metadata['sources']
    if not isinstance(units,dict) or set(units)!=set(expected) or len(units)!=11: raise Refusal('source_names')
    content={}
    for name,spec in expected.items():
        if not isinstance(name,str) or not name or '\x00' in name or not isinstance(spec,dict): raise Refusal('source_name')
        entry=units[name]
        if not isinstance(entry,dict) or not isinstance(entry.get('content'),str): raise Refusal('source_content')
        text=entry['content']; raw=text.encode('utf-8','strict')
        if keccak(raw)!=spec.get('keccak256'): raise Refusal('source_keccak')
        content[name]={'content':text}
    settings=json.loads(json.dumps(metadata['settings']))
    targets=settings.pop('compilationTarget',None)
    if not isinstance(targets,dict) or len(targets)!=1: raise Refusal('compilation_target')
    path,name=next(iter(targets.items()))
    if path not in content or not isinstance(name,str) or not name: raise Refusal('compilation_target')
    if settings.get('libraries') not in ({},None) or settings.get('remappings') not in ([],None): raise Refusal('libraries_or_remappings')
    settings['outputSelection']={'*':{'':['ast']},path:{name:['metadata','evm.deployedBytecode.object','evm.deployedBytecode.immutableReferences','evm.deployedBytecode.linkReferences'],'':['ast']}}
    result={'language':metadata.get('language'),'sources':content,'settings':settings}
    if result['language']!='Solidity': raise Refusal('language')
    if len(enc(result))>LIMITS['input_bytes']: raise Refusal('standard_input_cap')
    return result,(path,name)

def compare_output(result, standard, target, literal, runtime):
    errors=result.get('errors',[])
    if not isinstance(errors,list) or any(not isinstance(x,dict) or x.get('severity') not in ('warning','info','error') for x in errors): raise Refusal('compiler_errors_schema')
    if any(x['severity']=='error' for x in errors): raise Refusal('compiler_error')
    output_units=result.get('sources')
    if not isinstance(output_units,dict) or set(output_units)!=set(standard['sources']): raise Refusal('ast_source_names')
    ids={}; declarations={}
    for path,unit in output_units.items():
        if not isinstance(unit,dict) or type(unit.get('id')) is not int or unit['id']<0 or unit['id'] in ids or not isinstance(unit.get('ast'),dict): raise Refusal('ast_source_id')
        ids[unit['id']]=path
    for path,unit in output_units.items():
        stack=[unit['ast']]
        if unit['ast'].get('absolutePath')!=path or unit['ast'].get('nodeType')!='SourceUnit': raise Refusal('ast_path')
        while stack:
            node=stack.pop()
            if isinstance(node,dict):
                if node.get('nodeType')=='VariableDeclaration' and node.get('mutability')=='immutable':
                    ident=node.get('id'); span=node.get('src')
                    if type(ident) is not int or ident<0 or ident in declarations or not isinstance(span,str) or not re.fullmatch('[0-9]+:[0-9]+:[0-9]+',span): raise Refusal('immutable_ast')
                    start,length,fileid=map(int,span.split(':'))
                    if ids.get(fileid)!=path or start+length>len(standard['sources'][path]['content'].encode()): raise Refusal('immutable_span')
                    declarations[ident]={'path':path,'src':span,'name':node.get('name'),'type':node.get('typeDescriptions',{}).get('typeString')}
                stack.extend(node.values())
            elif isinstance(node,list): stack.extend(node)
    path,name=target
    contracts=result.get('contracts')
    if not isinstance(contracts,dict) or set(contracts)!={path} or not isinstance(contracts[path],dict) or set(contracts[path])!={name}: raise Refusal('target_outputs')
    artifact=contracts[path][name]
    if not isinstance(artifact,dict) or not isinstance(artifact.get('metadata'),str) or artifact['metadata'].encode()!=literal: raise Refusal('compiled_metadata_literal')
    deployed=artifact.get('evm',{}).get('deployedBytecode',{})
    if deployed.get('linkReferences')!={}: raise Refusal('link_references')
    value=deployed.get('object'); refs=deployed.get('immutableReferences')
    if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]+',value) or not isinstance(refs,dict) or not refs: raise Refusal('compiled_runtime_schema')
    code=bytearray.fromhex(value)
    if len(code)!=len(runtime): raise Refusal('compiled_runtime_length')
    trailer_size=int.from_bytes(runtime[-2:],'big')+2
    if trailer_size>len(runtime): raise Refusal('runtime_trailer')
    intervals=[]; projected=[]
    for key,ranges in refs.items():
        if not isinstance(key,str) or not re.fullmatch('0|[1-9][0-9]*',key) or int(key) not in declarations or not isinstance(ranges,list) or not ranges: raise Refusal('immutable_reference_ast')
        vals=[]
        for item in ranges:
            if not isinstance(item,dict) or set(item)!={'start','length'} or type(item['start']) is not int or type(item['length']) is not int or item['length']!=32 or not 0<=item['start']<=len(code)-trailer_size-32: raise Refusal('immutable_range')
            start=item['start']; intervals.append((start,start+32))
            if code[start:start+32]!=bytes(32): raise Refusal('immutable_nonzero_placeholder')
            vals.append(runtime[start:start+32])
        if len(set(vals))!=1: raise Refusal('immutable_repeat_disagreement')
        projected.append({'ast_id':int(key),**declarations[int(key)],'value_hex':'0x'+vals[0].hex(),'ranges':ranges})
        for item in ranges: code[item['start']:item['start']+32]=vals[0]
    intervals.sort()
    if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])): raise Refusal('immutable_overlap')
    if bytes(code)!=runtime: raise Refusal('full_runtime_mismatch')
    # Literal metadata equality plus full bytecode equality authenticates the unchanged trailer.
    trailer_size=int.from_bytes(runtime[-2:],'big')+2
    if trailer_size>len(runtime) or value[-2*trailer_size:].lower()!=runtime[-trailer_size:].hex(): raise Refusal('runtime_trailer_mismatch')
    return {'status':'exact_historical_implementation_reproduced','runtime_bytes':len(runtime),'runtime_sha256':sha(runtime),
            'compiled_metadata_sha256':sha(literal),'immutables':sorted(projected,key=lambda x:x['ast_id']),
            'immutable_values_inferred_from_retained_runtime':True,'warnings':sum(x['severity']=='warning' for x in errors),
            'source_equivalence_scope':'retained historical implementation only',**CLAIMS}

@contextmanager
def alarm(seconds):
    def expire(*_): raise TimeoutError('deadline')
    old=signal.signal(signal.SIGALRM,expire); prior=signal.getitimer(signal.ITIMER_REAL); began=time.monotonic()
    signal.setitimer(signal.ITIMER_REAL,min(seconds,prior[0]) if prior[0]>0 else seconds)
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,old)
        if prior[0]>0: signal.setitimer(signal.ITIMER_REAL,max(0.000001,prior[0]-(time.monotonic()-began)),prior[1])

def publish(out,name,value,cap=8192):
    raw=enc(value)
    if len(raw)>cap: raise Refusal('publication_cap')
    with (out/name).open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())

def finalize(out,name):
    pending=out/(name+'.pending'); final=out/(name+'.raw')
    if pending.exists(): os.link(pending,final); pending.unlink()

def get(request,emit,status,factory=http.client.HTTPSConnection):
    connection=None; total=0
    with alarm(request['seconds']):
        try:
            connection=factory(request['host'],timeout=request['seconds'],context=ssl.create_default_context())
            connection.request('GET',request['path'],headers={'Accept-Encoding':'identity','Connection':'close','User-Agent':'comet-reproduction-v1'})
            response=connection.getresponse(); status(response.status)
            if response.getheader('Content-Encoding') not in (None,'identity'): raise Refusal('content_encoding')
            declared=response.getheader('Content-Length')
            if declared is not None and (not re.fullmatch('[0-9]+',declared) or len(declared)>12): raise Refusal('content_length')
            while True:
                try: b=response.read1(min(65536,request['cap']+1-total))
                except http.client.IncompleteRead as exc:
                    b=exc.partial
                    if b: emit(b[:request['cap']+1-total]); total+=min(len(b),request['cap']+1-total)
                    raise Refusal('incomplete_body') from exc
                if not b: break
                emit(b); total+=len(b)
                if total>request['cap']: raise Refusal('body_cap')
            if response.status!=200: raise Refusal('http_status')
            if declared is not None and total!=int(declared): raise Refusal('content_length_mismatch')
            return total
        finally:
            if connection is not None: connection.close()

def acquire_worker(digest,out,compiler_pid=None):
    result={'status':'unavailable','plan_sha256':digest,'requests_attempted':0,'http_statuses':[],
            'worker_start_utc':utc(),'worker_start_monotonic':time.monotonic(),'worker_pid':os.getpid()}; error=None
    try:
        with alarm(LIMITS['download_seconds']):
            verify(digest)
            for request in REQUESTS:
                result['requests_attempted']+=1; observed=[]
                with (out/(request['name']+'.pending')).open('xb') as f:
                    def emit(b): f.write(b); f.flush(); os.fsync(f.fileno())
                    try: get(request,emit,observed.append)
                    finally:
                        if observed: result['http_statuses'].append({'request':request['name'],'status':observed[0]})
                finalize(out,request['name'])
                if request['name']=='manifest': build=compiler_build(js(read(out/'manifest.raw',131072),10000,32))
                elif request['name']=='compiler': result['compiler']=check_binary(out/'compiler.raw',build)
                else:
                    metadata,_,_=authenticated_inputs(); standard_input(metadata,js(read(out/'sources.raw',1048576)))
            verify(digest)
            result['manifest_build']=build
            result['raw_pins']=[{'name':r['name'],'bytes':fingerprint(out/(r['name']+'.raw'),r['cap'])[0],
                                'sha256':fingerprint(out/(r['name']+'.raw'),r['cap'])[1]} for r in REQUESTS]
            result['status']='artifacts_authenticated'
    except Exception as exc:
        result['status']='unavailable'; error=type(exc).__name__+':'+str(exc)[:160]
    finally:
        for r in REQUESTS: finalize(out,r['name'])
        result.update(error=error,worker_end_utc=utc(),worker_end_monotonic=time.monotonic())
        publish(out,'download-terminal.json',result)

def parent_death_guard(expected_parent,libc=None):
    lib=libc if libc is not None else ctypes.CDLL(None,use_errno=True)
    lib.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    lib.prctl.restype=ctypes.c_int
    if lib.prctl(1,signal.SIGKILL,0,0,0)!=0: raise OSError(ctypes.get_errno(),'PR_SET_PDEATHSIG')
    if os.getppid()!=expected_parent: os.kill(os.getpid(),signal.SIGKILL)


def compile_process(binary,stdin_path,out,cwd,launcher=subprocess.Popen,on_start=lambda pid:None):
    expected_parent=os.getpid()
    def restricted():
        parent_death_guard(expected_parent)
        os.setsid(); os.nice(19)
        resource.setrlimit(resource.RLIMIT_CPU,(180,180)); resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824)); resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    if cwd.is_symlink() or not cwd.is_dir() or list(cwd.iterdir()): raise Refusal('compile_workdir_not_empty')
    began=time.monotonic(); child=None; selector=selectors.DefaultSelector(); sizes={'stdout':0,'stderr':0}
    try:
        with stdin_path.open('rb') as inp, (out/'stdout.pending').open('xb') as stdout, (out/'stderr.pending').open('xb') as stderr:
            child=launcher([str(binary),'--standard-json','--base-path',str(cwd.resolve()),'--allow-paths',str(cwd.resolve())],stdin=inp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           cwd=cwd,env={'LANG':'C','LC_ALL':'C'},preexec_fn=restricted,close_fds=True)
            on_start(child.pid)
            for name,stream,f in [('stdout',child.stdout,stdout),('stderr',child.stderr,stderr)]:
                os.set_blocking(stream.fileno(),False); selector.register(stream,selectors.EVENT_READ,(name,f))
            while selector.get_map():
                if time.monotonic()-began>=240: raise TimeoutError('compiler_wall')
                for key,_ in selector.select(min(0.1,max(0,240-(time.monotonic()-began)))):
                    name,f=key.data; cap=LIMITS[name+'_bytes']; b=os.read(key.fileobj.fileno(),min(65536,cap+1-sizes[name]))
                    if not b: selector.unregister(key.fileobj); key.fileobj.close(); continue
                    retained=b[:cap-sizes[name]]
                    if retained: f.write(retained); f.flush(); os.fsync(f.fileno())
                    sizes[name]+=len(b)
                    if sizes[name]>cap: raise Refusal('compiler_'+name+'_cap')
            remaining=240-(time.monotonic()-began)
            if remaining<=0: raise TimeoutError('compiler_wall')
            code=child.wait(timeout=remaining)
            if code!=0: raise Refusal('compiler_exit')
            return sizes
    finally:
        if child is not None and child.poll() is None:
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=1)
        selector.close()
        finalize(out,'stdout'); finalize(out,'stderr')

def verify_artifacts(out,digest):
    terminal=js(read(out/'download-terminal.json',8192))
    supervisor=js(read(out/'acquire-supervisor.json',8192))
    if (supervisor.get('status')!='artifacts_authenticated' or supervisor.get('plan_sha256')!=digest
        or supervisor.get('exitcode')!=0 or supervisor.get('error') is not None): raise Refusal('download_supervisor_unavailable')
    if terminal.get('status')!='artifacts_authenticated' or terminal.get('plan_sha256')!=digest or terminal.get('requests_attempted')!=3: raise Refusal('download_not_authenticated')
    if terminal.get('error') is not None or terminal.get('http_statuses')!=[{'request':r['name'],'status':200} for r in REQUESTS]: raise Refusal('download_http_identity')
    pins=terminal.get('raw_pins')
    if not isinstance(pins,list) or len(pins)!=3 or {x.get('name') for x in pins}!={r['name'] for r in REQUESTS}: raise Refusal('artifact_pins')
    for r in REQUESTS:
        p=next(x for x in pins if x['name']==r['name'])
        if fingerprint(out/(r['name']+'.raw'),r['cap'])!=(p.get('bytes'),p.get('sha256')): raise Refusal('artifact_mutated')
    build=compiler_build(js(read(out/'manifest.raw',131072),10000,32))
    if build!=terminal.get('manifest_build'): raise Refusal('build_mutated')
    check_binary(out/'compiler.raw',build)
    return pins

def compile_worker(digest,out,compiler_pid=None):
    status='unavailable'; error=None; start_utc=utc(); start_mono=time.monotonic()
    try:
        with alarm(243):
            verify(digest); pins=verify_artifacts(out,digest)
            metadata,literal,runtime=authenticated_inputs()
            standard,target=standard_input(metadata,js(read(out/'sources.raw',1048576)))
            raw=enc(standard)
            with (out/'standard-input.json').open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
            work=out/'compile-work'; work.mkdir()
            binary=out/'compiler.raw'; binary.chmod(0o500)
            sizes=compile_process(binary.resolve(),out/'standard-input.json',out,work,
                                  on_start=lambda pid:setattr(compiler_pid,'value',pid))
            if list(work.iterdir()): raise Refusal('compiler_created_files')
            projection=compare_output(js(read(out/'stdout.raw',8388608)),standard,target,literal,runtime)
            if read(out/'standard-input.json',1048576)!=raw: raise Refusal('standard_input_mutated')
            verify(digest)
            if verify_artifacts(out,digest)!=pins: raise Refusal('artifact_mutated')
            projection.update(plan_sha256=digest,standard_input_sha256=sha(raw),compiler_stdout_sha256=fingerprint(out/'stdout.raw',8388608)[1],
                              compiler_stderr_sha256=fingerprint(out/'stderr.raw',65536)[1],compiler_output_sizes=sizes,
                              sandbox_is_external_precondition=True)
            publish(out,'projection.json',projection,65536); status=projection['status']
    except Exception as exc: status='unavailable'; error=type(exc).__name__+':'+str(exc)[:160]
    finally: publish(out,'compile-terminal.json',{'status':status,'error':error,'plan_sha256':digest,
                        'worker_start_utc':start_utc,'worker_end_utc':utc(),'worker_start_monotonic':start_mono,
                        'worker_end_monotonic':time.monotonic(),'worker_pid':os.getpid(),**CLAIMS})

def kill_compiler(pid,out):
    if not pid: return
    # A shared PID is never trusted after reuse: require our exact executable argv and group.
    try:
        command=Path('/proc')/str(pid)/'cmdline'
        argv=command.read_bytes().split(b'\0')
        if argv[:2]==[str((out/'compiler.raw').resolve()).encode(),b'--standard-json'] and os.getpgid(pid)==pid:
            os.killpg(pid,signal.SIGKILL)
    except (FileNotFoundError,ProcessLookupError): pass


def stage(stage_name,digest,ack=None):
    seconds=155 if stage_name=='acquire' else 245; began=time.monotonic(); start_utc=utc(); child=None
    ctx=multiprocessing.get_context('fork'); compiler_pid=ctx.Value('i',0)
    with alarm(seconds):
        verify(digest); out=ROOT/OUT
        if stage_name=='acquire': out.mkdir(exist_ok=False)
        else:
            if ack!=SANDBOX_ACK: raise Refusal('sandbox_ack_required')
            if not out.is_dir() or out.is_symlink(): raise Refusal('download_required')
            verify_artifacts(out,digest)
        publish(out,stage_name+'-claim.json',{'plan_sha256':digest,'stage':stage_name,'began_monotonic':began,'start_utc':start_utc,
                    'launch_context':context(),'sandbox_ack':ack})
        filename='download-terminal.json' if stage_name=='acquire' else 'compile-terminal.json'
        good=False; terminal={'status':'unavailable','requests_attempted':None}; failure=None
        child=ctx.Process(target=acquire_worker if stage_name=='acquire' else compile_worker,args=(digest,out,compiler_pid))
        try:
            with alarm(max(0.001,began+seconds-2-time.monotonic())):
                child.start(); child.join(max(0,began+seconds-3-time.monotonic()))
                if child.is_alive(): raise TimeoutError('stage_deadline')
                if (out/filename).exists(): terminal=js(read(out/filename,8192))
                verify(digest)
                expected='artifacts_authenticated' if stage_name=='acquire' else 'exact_historical_implementation_reproduced'
                good=(child.exitcode==0 and terminal.get('status')==expected
                      and terminal.get('plan_sha256')==digest and terminal.get('error','missing') is None)
        except Exception as exc:
            failure=type(exc).__name__+':'+str(exc)[:100]
        finally:
            kill_compiler(compiler_pid.value,out)
            if child.pid is not None and child.is_alive(): child.kill(); child.join(timeout=0.25)
            for name in ('manifest','compiler','sources','stdout','stderr'): finalize(out,name)
            if not (out/filename).exists():
                publish(out,filename,{'status':'unavailable','plan_sha256':digest,'error':failure,
                                    'requests_attempted':None,**CLAIMS})
            publish(out,stage_name+'-supervisor.json',{'status':terminal['status'] if good else 'unavailable','exitcode':child.exitcode,
                    'error':failure,'plan_sha256':digest,'requests_attempted':terminal.get('requests_attempted'),
                    'start_utc':start_utc,'end_utc':utc(),'start_monotonic':began,'end_monotonic':time.monotonic(),
                    'launch_context':context(),'sandbox_ack':ack,**CLAIMS})
        return good

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=('dry','acquire','compile'),nargs='?',default='dry')
    p.add_argument('--run',action='store_true'); p.add_argument('--plan-sha256'); p.add_argument('--sandbox-ack')
    a=p.parse_args(argv)
    if not a.run:
        # Only fixed local identity hashes; no parsing source/artifacts, HTTP or output.
        for record in [ALLOCATION,*INPUTS]: pin(record,196608)
        print(enc({'status':'dry','http_requests':0,'compiler_invocations':0,'outputs':0}).decode()); return 0
    if a.stage=='dry': p.error('--run requires acquire or compile')
    try:
        good=stage(a.stage,a.plan_sha256,a.sandbox_ack)
        print(enc({'status':'completed' if good else 'unavailable','stage':a.stage}).decode()); return 0 if good else 1
    except Exception as exc:
        print(enc({'status':'refused_or_unavailable','error':type(exc).__name__+':'+str(exc)[:120]}).decode()); return 1

if __name__=='__main__': raise SystemExit(main())
