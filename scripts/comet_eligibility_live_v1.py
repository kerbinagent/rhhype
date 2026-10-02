"""One prospective metadata pass around the unchanged Comet offline engine.

Default dry: fixed local pin checks, no request/output. Binding is always None.
The known historical implementation gate is not a transitive certificate.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import io
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import ssl
import struct
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/comet_eligibility_live_v1.py'
TEST='tests/test_comet_eligibility_live_v1.py'
DESIGN='reports/comet-eligibility-live-v1/design.txt'
PLAN='reports/experiment-storage/comet-eligibility-live-v1.json'
OUT='reports/comet-eligibility-live-v1/run-v1'
ENDPOINT='https://ethereum-rpc.publicnode.com'
ALLOCATION={'path':'reports/experiment-storage/comet-reproduction-closeout-eligibility-preparation-v1.json',
            'bytes':10063,'sha256':'0e54f38043e39fb0290bf784202854f33d028a44442a6738a3ec1ff1db0b4a7a'}
ENGINE={'path':'scripts/peer_comet_eligibility_v1.py','bytes':30601,'sha256':'879f58149d222bdfaa627d28b4335c2b01c72aba51a3771655f61764f473a908'}
IDENTITY={'path':'scripts/comet_identity_v1.py','bytes':23578,'sha256':'ba41a82ed270803d8cef7488c2dfdd5345db9ea49d906e6301a51b28006bebf9'}
OLD_PLAN={'path':'research/peer-comet-eligibility-v1.json','bytes':14403,'sha256':'25ae206579b13cf6b4f4329e2615a1bdf4ee6301f8cc5e8d480f543de2cc8dde'}
REPRODUCTION={'path':'reports/comet-reproduction-v1/root-reconciliation.json','bytes':3539,
              'sha256':'b7b9c7b26ee0efbd8088f1899e88484620a1b7a15509b7a4361045fa2113edfd'}
KNOWN={'address':'0x63e749153baf1838f63ca22c275370bd2b1ceb15','runtime_bytes':18599,
       'runtime_sha256':'b942614560ef7218a52173cc501ce9198f74a558348edf957cda62a218aa20fe'}
CAPS={'requests':31,'response_bytes':65536,'cumulative_body_bytes':524288,'raw_bytes':655360,
      'derived_trace_bytes':524288,'projection_bytes':32768,'controls_bytes':65536,
      'run_controls_bytes':32768,'frame_payload_bytes':8192,'header_bytes':8192,
      'request_seconds':10,'worker_seconds':120,'supervisor_seconds':125,'clock_samples':512}
CLAIMS={'source_equivalence_proven_by_wrapper':False,'transitive_source_binding_available':False,
        'future_inclusion_proven':False,'economic_cash_evaluated':False,'cash_closed':False}
MAGIC=b'COMET-ELIGIBILITY-LIVE-V1\n'

class Refusal(Exception): pass

def sha(b): return hashlib.sha256(b).hexdigest()

def bounded(path,cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as f: raw=f.read(cap+1)
    if len(raw)>cap: raise Refusal('file_cap')
    return raw

def pin(record,cap=262144):
    if (not isinstance(record,dict) or set(record)!={'path','bytes','sha256'} or type(record['bytes']) is not int
        or not 0<record['bytes']<=cap or not isinstance(record['sha256'],str)
        or not re.fullmatch('[0-9a-f]{64}',record['sha256'])): raise Refusal('pin_schema')
    path=ROOT/record['path']
    if not path.resolve().is_relative_to(ROOT) or any(p.is_symlink() for p in (path,*path.parents)): raise Refusal('pin_path')
    raw=bounded(path,cap)
    if len(raw)!=record['bytes'] or sha(raw)!=record['sha256']: raise Refusal('pin_identity')
    return raw

# Reuse the frozen identity package's pure functions; never call its run/verify.
_raw=pin(IDENTITY,65536)
identity=types.ModuleType('comet_eligibility_identity_helpers'); identity.__file__=str(ROOT/IDENTITY['path'])
exec(compile(_raw,identity.__file__,'exec'),identity.__dict__)
del _raw
engine=identity.helper
enc=identity.encoded
decode=engine.decode_json

def utc(): return datetime.now(timezone.utc).isoformat()
def context(): return {'pid':os.getpid(),'ppid':os.getppid(),'cwd':os.getcwd(),
                       'runtime':identity.runtime_identity(),'network_namespace':os.readlink('/proc/self/ns/net')}

def fixed_pins():
    pin(ALLOCATION,16384); pin(IDENTITY,65536); pin(ENGINE,65536); pin(REPRODUCTION,8192)
    old=decode(pin(OLD_PLAN,32768)); engine.validate_plan(old)
    if old.get('runtime_binding') is not None: raise Refusal('old_binding_must_be_none')
    engine.verify_file_pins(old)
    return old

def build_manifest(): return engine.manifest()

def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise Refusal('exact_plan_sha_required')
    raw=bounded(ROOT/PLAN,32768)
    if sha(raw)!=digest: raise Refusal('plan_sha')
    p=decode(raw); fixed_pins()
    if (p.get('schema')!='comet-eligibility-live-v1' or p.get('status')!='frozen_comet_eligibility_live'
        or p.get('allocation')!=ALLOCATION or p.get('fixed_dependency_pins')!=[IDENTITY,ENGINE,OLD_PLAN,REPRODUCTION]
        or p.get('known_implementation')!=KNOWN or p.get('endpoint')!=ENDPOINT or p.get('output_dir')!=OUT
        or p.get('resource_limits')!=CAPS or p.get('claims')!=CLAIMS or p.get('runtime')!=identity.runtime_identity()
        or p.get('manifest_sha256')!=sha(enc(build_manifest())) or p.get('binding') is not None): raise Refusal('frozen_scope')
    pins=p.get('source_pins')
    if not isinstance(pins,list) or len(pins)!=3 or {x.get('path') for x in pins if isinstance(x,dict)}!={SOURCE,TEST,DESIGN}: raise Refusal('exact_source_pins')
    for item in pins: pin(item,131072)
    if Path(sys.executable).absolute()!=ROOT/'.venv/bin/python' or sys.version_info[:3]!=(3,13,9): raise Refusal('python_runtime')
    path=ROOT/OUT
    if any(x.is_symlink() for x in (path,*path.parents)): raise Refusal('output_symlink')
    return p

@contextmanager
def alarm(seconds):
    def expire(*_): raise TimeoutError('absolute_deadline')
    old=signal.signal(signal.SIGALRM,expire); prior=signal.getitimer(signal.ITIMER_REAL); began=time.monotonic()
    signal.setitimer(signal.ITIMER_REAL,max(0.000001,min(seconds,prior[0]) if prior[0]>0 else seconds))
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,old)
        if prior[0]>0: signal.setitimer(signal.ITIMER_REAL,max(0.000001,prior[0]-(time.monotonic()-began)),prior[1])

def publish(out,name,value,cap,kind='control'):
    body=enc(value)+b'\n'
    if len(body)>cap: raise Refusal('publication_cap')
    if kind=='control':
        used={}
        for p in out.iterdir():
            if p.is_file() and p.name not in ('projection.json','trace.json') and (p.name.endswith('.json') or p.name.endswith('.json.pending')):
                st=p.stat(); used[(st.st_dev,st.st_ino)]=st.st_size
        if sum(used.values())+len(body)>CAPS['run_controls_bytes']: raise Refusal('run_controls_cap')
    pending=out/(name+'.pending')
    with pending.open('xb') as f: f.write(body); f.flush(); os.fsync(f.fileno())
    try: os.link(pending,out/name)
    finally: pending.unlink()

class Collector(engine.Collector):
    """Only the known implementation preflight is added; no binding mutation."""
    def __init__(self,transport,*,clock=time.monotonic):
        self.current_name=None
        super().__init__(transport,binding=None,clock=clock)
    def rpc(self,name,method,params):
        self.current_name=name
        value=super().rpc(name,method,params)
        if name=='implementation_slot' and engine.address(value)!=KNOWN['address']:
            engine.fail('known_implementation_mismatch','current implementation address differs from historical reproduced implementation')
        if name=='implementation_code':
            code=engine.hex_bytes(value)
            if len(code)!=KNOWN['runtime_bytes'] or sha(code)!=KNOWN['runtime_sha256']:
                engine.fail('known_implementation_mismatch','current implementation runtime differs from historical reproduced implementation')
        return value

class Clock:
    def __init__(self,samples=None):
        if samples is not None and (not isinstance(samples,list) or not 0<len(samples)<=CAPS['clock_samples']
            or any(type(x) not in (float,int) or not math.isfinite(x) or x<0 for x in samples)
            or any(a>b for a,b in zip(samples,samples[1:]))): raise Refusal('clock_samples_invalid')
        self.samples=[] if samples is None else list(samples); self.index=0; self.replay=samples is not None
    def __call__(self):
        if self.replay:
            if self.index>=len(self.samples): raise Refusal('clock_replay_exhausted')
            value=self.samples[self.index]; self.index+=1; return value
        if len(self.samples)>=CAPS['clock_samples']: raise Refusal('clock_samples_cap')
        value=time.monotonic(); self.samples.append(value); return value

class Frames:
    def __init__(self,out):
        self.out=out; self.path=out/'responses.frames.pending'; self.handle=self.path.open('xb')
        self.handle.write(MAGIC); self.handle.flush(); os.fsync(self.handle.fileno()); self.bytes=len(MAGIC)
        self.body_bytes=0; self.attempts=0
    def frame(self,kind,payload,reserve=0):
        if kind not in b'BHDE' or len(payload)>CAPS['frame_payload_bytes']: raise Refusal('frame_payload_cap')
        raw=bytes([kind])+struct.pack('>I',len(payload))+payload
        if self.bytes+len(raw)+reserve>CAPS['raw_bytes']: raise Refusal('raw_frame_cap')
        self.handle.write(raw); self.handle.flush(); os.fsync(self.handle.fileno()); self.bytes+=len(raw)
    def body(self,b):
        if self.body_bytes+len(b)>CAPS['cumulative_body_bytes']: raise Refusal('cumulative_body_cap')
        self.frame(ord('D'),b,reserve=4096); self.body_bytes+=len(b)
    def finish(self): self.handle.close(); identity.finalize_partial(self.out)

class Stream:
    """Timer spans initialization through every body read and stream close."""
    def __init__(self,transport,request,timeout):
        self.transport=transport; self.request=request; self.timeout=timeout
        self.connection=None; self.response=None; self.status=None; self.total=0; self.digest=hashlib.sha256()
        self.eof=False; self.closed=False; self.error=None; self.deferred=None; self.length=None
        self.timer=alarm(timeout); self.timer.__enter__(); self.started=time.monotonic()
        frames=transport.frames; frames.attempts+=1
        try:
            frames.frame(ord('B'),enc({'name':transport.name(),'request':request,'timeout_seconds':timeout,
                         'begin_utc':utc(),'begin_monotonic':self.started}),reserve=16384)
            self.connection=transport.factory('ethereum-rpc.publicnode.com',timeout=timeout,context=ssl.create_default_context())
            self.connection.request('POST','/',body=enc(request),headers={'Content-Type':'application/json',
                'Accept':'application/json','Accept-Encoding':'identity','Connection':'close'})
            self.response=self.connection.getresponse(); self.status=self.response.status
            headers=self.response.getheaders()
            raw=enc({'http_status':self.status,'headers':headers})
            if len(raw)>CAPS['header_bytes']:
                frames.frame(ord('H'),raw[:CAPS['header_bytes']],reserve=4096)
                raise Refusal('http_headers_cap_prefix_retained')
            frames.frame(ord('H'),raw,reserve=4096)
            if self.response.getheader('Content-Encoding') not in (None,'identity'): raise Refusal('content_encoding')
            declared=self.response.getheader('Content-Length')
            if declared is not None:
                if not isinstance(declared,str) or len(declared)>12 or not re.fullmatch('[0-9]+',declared): raise Refusal('content_length')
                self.length=int(declared)
        except BaseException as exc:
            self.error=type(exc).__name__+':'+str(exc)[:120]
            self.close(); raise
    def __enter__(self): return self
    def __exit__(self,typ,value,tb):
        if value is not None: self.error=type(value).__name__+':'+str(value)[:120]
        self.close(); return False
    def retain(self,b):
        self.transport.frames.body(b); self.total+=len(b); self.digest.update(b)
    def read(self,n):
        if self.deferred is not None: raise self.deferred
        if self.closed or type(n) is not int or not 0<n<=8192: raise Refusal('bounded_read_contract')
        frames=self.transport.frames
        allowed=min(n,CAPS['response_bytes']+1-self.total,CAPS['cumulative_body_bytes']-frames.body_bytes,
                    CAPS['raw_bytes']-frames.bytes-4101)
        if allowed<=0: raise Refusal('body_or_raw_remaining_cap')
        try: b=self.response.read1(allowed)
        except http.client.IncompleteRead as exc:
            b=exc.partial
            if not isinstance(b,bytes): raise Refusal('partial_body_type')
            b=b[:allowed]; self.deferred=Refusal('incomplete_body_prefix_retained')
            if not b: raise self.deferred
        if not isinstance(b,bytes) or len(b)>allowed: raise Refusal('read1_contract')
        if b: self.retain(b)
        else:
            self.eof=True
            if self.length is not None and self.total!=self.length: raise Refusal('content_length_mismatch')
        return b
    def close(self):
        if self.closed: return
        self.closed=True
        try:
            if self.connection is not None: self.connection.close()
            outcome='received' if self.eof and self.error is None and self.deferred is None else 'unavailable'
            self.transport.frames.frame(ord('E'),enc({'http_status':self.status,'body_bytes':self.total,
                'body_sha256':self.digest.hexdigest(),'eof':self.eof,'outcome':outcome,'error':self.error,
                'end_utc':utc(),'end_monotonic':time.monotonic()}))
        finally: self.timer.__exit__(None,None,None)

class Transport:
    def __init__(self,frames,name,factory=http.client.HTTPSConnection): self.frames=frames; self.name=name; self.factory=factory
    def __call__(self,request,timeout):
        if self.frames.attempts>=CAPS['requests'] or not 0<timeout<=10: raise Refusal('transport_admission_cap')
        stream=Stream(self,request,timeout); return stream.status,stream

def parse_frames(path,complete=True):
    raw=bounded(path,CAPS['raw_bytes'])
    if not raw.startswith(MAGIC): raise Refusal('raw_magic')
    offset=len(MAGIC); records=[]; active=None; total=0
    while offset<len(raw):
        if len(raw)-offset<5:
            if not complete: break
            raise Refusal('truncated_frame')
        kind=raw[offset]; length=struct.unpack('>I',raw[offset+1:offset+5])[0]; offset+=5
        if length>CAPS['frame_payload_bytes']: raise Refusal('frame_cap')
        payload=raw[offset:offset+length]; offset+=length
        if len(payload)!=length:
            if not complete: break
            raise Refusal('truncated_payload')
        if kind==ord('B'):
            if active is not None or len(records)>=31: raise Refusal('frame_request_order')
            begin=decode(payload)
            active={'begin':begin,'body':bytearray(),'http':None}
        elif kind==ord('H'):
            if active is None or active['http'] is not None: raise Refusal('frame_header_order')
            active['http']=decode(payload)
        elif kind==ord('D'):
            if active is None or active['http'] is None: raise Refusal('frame_body_order')
            active['body'].extend(payload); total+=len(payload)
            if len(active['body'])>65537 or total>524288: raise Refusal('raw_body_cap')
        elif kind==ord('E'):
            if active is None: raise Refusal('frame_end_order')
            end=decode(payload); body=bytes(active['body'])
            if end.get('body_bytes')!=len(body) or end.get('body_sha256')!=sha(body): raise Refusal('raw_body_identity')
            if complete and (end.get('outcome')!='received' or end.get('error') is not None or end.get('eof') is not True
                or active['http'] is None or active['http'].get('http_status')!=200 or end.get('http_status')!=200): raise Refusal('raw_request_unavailable')
            records.append({**active,'body':body,'end':end}); active=None
        else: raise Refusal('frame_kind')
    if complete and active is not None: raise Refusal('raw_incomplete')
    return records,sha(raw),total

def replay(path,samples,decision_ms):
    records,raw_sha,total=parse_frames(path); clock=Clock(samples); index=0
    def transport(request,timeout):
        nonlocal index
        if index>=len(records): raise Refusal('raw_replay_exhausted')
        row=records[index]; index+=1
        if enc(request)!=enc(row['begin'].get('request')) or row['begin'].get('name')!=collector.current_name or timeout!=row['begin'].get('timeout_seconds'):
            raise Refusal('raw_request_reproduction')
        return row['http']['http_status'],io.BytesIO(row['body'])
    collector=Collector(transport,clock=clock); result=collector.execute(decision_ms)
    if index!=len(records) or clock.index!=len(samples): raise Refusal('raw_or_clock_replay_unused')
    return result,collector.trace,raw_sha,total

def projection(result,digest,raw_sha,total):
    complete=result.get('status')=='source_binding_unavailable' and result.get('canonical_parent_rechecked') is True and 'error' not in result
    count=result.get('requests'); omitted=result.get('unexecuted_steps')
    if type(count) is not int or not isinstance(omitted,list) or count+len(omitted)!=31: raise Refusal('all31_denominator')
    observed=(result.get('metadata',{}).get('code_fingerprints',{}).get('implementation')==
              {'address':KNOWN['address'],'runtime_sha256':KNOWN['runtime_sha256']}
              and 'implementation' in result.get('runtime_roles_checked',[]))
    return {'schema':'comet-eligibility-live-v1-projection','status':'metadata_collection_complete' if complete else 'metadata_collection_unavailable',
            'metadata_collection_complete':complete,'plan_sha256':digest,'raw_sha256':raw_sha,'retained_body_bytes':total,
            'expected_historical_implementation':KNOWN,'observed_implementation_matched':observed,
            'adapter_transport_model':'direct_fixed_anonymous_https_jsonrpc','source_binding':'unavailable','engine_result':result,
            'engine_context_fields_preserved':'offline-engine labels are unchanged; this wrapper records the actual transport',
            'maximum_steps':31,'conditionally_skipped_steps':sum(x.get('reason')=='condition_not_met' for x in omitted),
            'not_reached_steps':sum(x.get('reason')=='not_reached_after_failure' for x in omitted),
            'canonicality':'provider asserted; five-field final parent comparison; no header hash or consensus verification',
            'child_model':'conditional numeric-parent simulation; UTC decision+400ms floor on12s grid; no inclusion guarantee',**CLAIMS}

def _worker(digest,out,deadline):
    frames=None; result=None; status='unavailable'; error=None; start_utc=utc(); started=time.monotonic()
    attempts=body_bytes=None; clock=Clock(); decision=None
    try:
        with alarm(max(0.000001,deadline-2-time.monotonic())):
            verify(digest); frames=Frames(out)
            collector=Collector(None,clock=clock); collector.transport=Transport(frames,lambda:collector.current_name)
            decision=time.time_ns()//1000000; result=collector.execute(decision)
            attempts=frames.attempts; body_bytes=frames.body_bytes
            frames.finish(); frames=None
            publish(out,'clock-samples.json',{'decision_utc_ms':decision,'samples':clock.samples},16384)
            publish(out,'trace.json',collector.trace,CAPS['derived_trace_bytes'],kind='trace')
            raw_sha=sha(bounded(out/'responses.frames',CAPS['raw_bytes'])); total=body_bytes
            projected=projection(result,digest,raw_sha,total)
            if projected['metadata_collection_complete']:
                reproduced,reproduced_trace,reproduced_sha,reproduced_total=replay(out/'responses.frames',clock.samples,decision)
                if enc(reproduced)!=enc(result) or enc(reproduced_trace)!=enc(collector.trace) or reproduced_sha!=raw_sha or reproduced_total!=total:
                    raise Refusal('raw_result_reproduction')
            verify(digest)
            publish(out,'projection.json',projected,CAPS['projection_bytes'],kind='projection')
            verify(digest)
            if projected['metadata_collection_complete']: status='metadata_collection_complete'
            else: error='engine_'+result.get('status','unavailable')
    except Exception as exc: status='unavailable'; error=type(exc).__name__+':'+str(exc)[:160]
    finally:
        if frames is not None:
            attempts=frames.attempts; body_bytes=frames.body_bytes; frames.finish()
        identity.finalize_partial(out)
        publish(out,'terminal.json',{'schema':'comet-eligibility-live-v1-terminal','status':status,'error':error,'plan_sha256':digest,
                'requests_attempted':attempts,'attempt_meaning':'transport helper invocations; not authenticated wire dispatch',
                'retained_body_bytes':body_bytes,'engine_status':result.get('status') if result else None,
                'worker_start_utc':start_utc,'worker_end_utc':utc(),'worker_start_monotonic':started,'worker_end_monotonic':time.monotonic(),
                'decision_utc_ms':decision,'raw_partial_retained':(out/'responses.frames').exists(),**CLAIMS},8192)

def worker(digest,out,deadline):
    # Outer bound includes terminal/fsync cleanup; parent can recover an absent terminal.
    try:
        with alarm(max(0.000001,deadline-time.monotonic())): _worker(digest,out,deadline)
    except BaseException:
        return  # no child traceback/log; missing terminal is unavailable, even exit0

def run(digest):
    began=time.monotonic(); start_utc=utc(); process=None; out=None; failure=None
    with alarm(125):
        plan=verify(digest); out=ROOT/OUT; out.mkdir(parents=True,exist_ok=False)
        publish(out,'claim.json',{'schema':'comet-eligibility-live-v1-claim','plan_sha256':digest,'source_pins':plan['source_pins'],
                'claimed_utc':start_utc,'launch_context':context(),'manifest_sha256':sha(enc(build_manifest())),**CLAIMS},8192)
        process=multiprocessing.get_context('fork').Process(target=worker,args=(digest,out,began+120))
        good=False; terminal={'status':'unavailable','requests_attempted':None}
        try:
            with alarm(max(0.000001,began+123-time.monotonic())):
                process.start(); process.join(max(0,began+122-time.monotonic()))
                if process.is_alive(): raise TimeoutError('worker_deadline')
                if (out/'terminal.json').exists(): terminal=decode(bounded(out/'terminal.json',8192))
                verify(digest)
                good=(process.exitcode==0 and terminal.get('status')=='metadata_collection_complete'
                      and terminal.get('plan_sha256')==digest and terminal.get('error','missing') is None)
                if good:
                    projected=decode(bounded(out/'projection.json',32768)); clocks=decode(bounded(out/'clock-samples.json',16384))
                    reproduced,reproduced_trace,raw_sha,total=replay(out/'responses.frames',clocks['samples'],clocks['decision_utc_ms'])
                    if enc(projected)!=enc(projection(reproduced,digest,raw_sha,total)) or enc(reproduced_trace)!=enc(decode(bounded(out/'trace.json',524288))):
                        raise Refusal('supervisor_saved_reproduction')
                verify(digest)
        except Exception as exc: good=False; failure=type(exc).__name__+':'+str(exc)[:120]
        finally:
            if process.pid is not None and process.is_alive(): process.kill(); process.join(timeout=0.25)
            identity.finalize_partial(out)
            if not (out/'terminal.json').exists(): publish(out,'terminal.json',{'schema':'comet-eligibility-live-v1-terminal',
                    'status':'unavailable','error':failure or 'worker_exit_without_terminal','plan_sha256':digest,'requests_attempted':None,
                    'retained_body_bytes':None,'raw_partial_retained':(out/'responses.frames').exists(),**CLAIMS},8192)
            publish(out,'supervisor.json',{'schema':'comet-eligibility-live-v1-supervisor','status':'metadata_collection_complete' if good else 'unavailable',
                    'error':failure,'plan_sha256':digest,'exitcode':process.exitcode,'requests_attempted':terminal.get('requests_attempted'),
                    'terminal_sha256':sha(bounded(out/'terminal.json',8192)),'start_utc':start_utc,'end_utc':utc(),
                    'start_monotonic':began,'end_monotonic':time.monotonic(),'launch_context':context(),**CLAIMS},8192)
        return good

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--run',action='store_true'); p.add_argument('--plan-sha256'); a=p.parse_args(argv)
    if not a.run:
        fixed_pins(); print(enc({'status':'dry','requests':0,'outputs':0,'prospective_max_requests':31,**CLAIMS}).decode()); return 0
    try:
        good=run(a.plan_sha256); print(enc({'status':'metadata_collection_complete' if good else 'unavailable',**CLAIMS}).decode()); return 0 if good else 1
    except Exception as exc:
        print(enc({'status':'refused_or_unavailable','error':type(exc).__name__+':'+str(exc)[:120],**CLAIMS}).decode()); return 1

if __name__=='__main__': raise SystemExit(main())
