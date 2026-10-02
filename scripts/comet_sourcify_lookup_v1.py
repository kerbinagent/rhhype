"""One root-frozen Sourcify v2 lookup. Default dry has zero I/O."""
import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import ssl
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/comet_sourcify_lookup_v1.py'
TEST = 'tests/test_comet_sourcify_lookup_v1.py'
DESIGN = 'reports/comet-sourcify-lookup-v1/design.txt'
PLAN = 'reports/experiment-storage/comet-sourcify-lookup-v1.json'
OUT = 'reports/comet-sourcify-lookup-v1/run-v1'
ALLOCATION = {'path':'reports/experiment-storage/comet-sourcify-lookup-v1-allocation.json',
              'bytes':4571,'sha256':'6923a186a26521b4a75b0a370ca69d3677f6813c39cc0f3137b1a0e8c37496ee'}
URL = ('https://sourcify.dev/server/v2/contract/1/0x63e749153baf1838f63ca22c275370bd2b1ceb15'
       '?fields=metadata,compilation,runtimeBytecode.onchainBytecode,runtimeBytecode.recompiledBytecode,'
       'runtimeBytecode.transformations,runtimeBytecode.transformationValues,'
       'runtimeBytecode.immutableReferences,runtimeBytecode.linkReferences,runtimeBytecode.cborAuxdata')
HOST = 'sourcify.dev'
TARGET = URL.removeprefix('https://'+HOST)
CHAIN = '1'
ADDRESS = '0x63e749153baf1838f63ca22c275370bd2b1ceb15'
RUNTIME_BYTES = 18599
RUNTIME_SHA = 'b942614560ef7218a52173cc501ce9198f74a558348edf957cda62a218aa20fe'
ACCEPT = 131072
RECEIVED = ACCEPT + 1
PROJECTION = 8192

class Refusal(Exception): pass

def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def bounded(path,cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as handle: raw=handle.read(cap+1)
    if len(raw)>cap: raise Refusal('file_cap')
    return raw

def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def reject(_): raise ValueError('nonfinite_json')
    def finite(text):
        value=float(text)
        if not math.isfinite(value): reject(text)
        return value
    value=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,
                     parse_constant=reject,parse_float=finite)
    if not isinstance(value,dict): raise ValueError('nonobject_json')
    pending=[(value,0)]; nodes=0
    while pending:
        item,depth=pending.pop(); nodes+=1
        if depth>32 or nodes>16384: raise ValueError('json_complexity')
        if isinstance(item,dict): pending.extend((v,depth+1) for v in item.values())
        elif isinstance(item,list): pending.extend((v,depth+1) for v in item)
    return value

def pin(record,expected,cap):
    if (not isinstance(record,dict) or set(record)!={'path','bytes','sha256'}
        or record.get('path')!=expected or type(record.get('bytes')) is not int
        or not 0<record['bytes']<=cap or not isinstance(record.get('sha256'),str)
        or not re.fullmatch('[0-9a-f]{64}',record['sha256'])): raise Refusal('pin_schema')
    path=ROOT/expected
    if any(p.is_symlink() for p in (path,*path.parents)): raise Refusal('pin_symlink')
    raw=bounded(path,cap)
    if len(raw)!=record['bytes'] or sha(raw)!=record['sha256']: raise Refusal('pin_mismatch')
    return raw

def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise Refusal('plan_sha_required')
    raw=bounded(ROOT/PLAN,16384)
    if sha(raw)!=digest: raise Refusal('plan_sha_mismatch')
    plan=strict_json(raw)
    allocation=strict_json(pin(ALLOCATION,ALLOCATION['path'],8192))
    request=allocation['request_after_separate_freeze']
    expected=allocation['frozen_expected']
    if (plan.get('schema')!='comet-sourcify-lookup-v1' or plan.get('status')!='frozen_root_only'
        or plan.get('allocation')!=ALLOCATION or plan.get('request')!=request
        or plan.get('expected')!=expected or plan.get('output_dir')!=OUT
        or plan.get('claims')!={'source_equivalence':False,'eligibility':False,'economics':False}
        or request.get('url')!=URL or request.get('count')!=1 or request.get('method')!='GET'
        or request.get('body_accept_cap_bytes')!=ACCEPT
        or request.get('body_received_cap_including_failure_sentinel_bytes')!=RECEIVED
        or expected.get('chain_id')!=CHAIN or expected.get('implementation')!=ADDRESS
        or expected.get('runtime_bytes')!=RUNTIME_BYTES or expected.get('runtime_sha256')!=RUNTIME_SHA):
        raise Refusal('plan_scope')
    pins=plan.get('source_pins')
    if (not isinstance(pins,list) or len(pins)!=3
        or {p.get('path') for p in pins if isinstance(p,dict)}!={SOURCE,TEST,DESIGN}): raise Refusal('source_pins')
    for item in pins: pin(item,item['path'],20480)
    inputs=plan.get('input_pins')
    if inputs!=allocation['inputs']: raise Refusal('input_pin_scope')
    for item in inputs: pin(item,item['path'],20480)
    if (ROOT/OUT).is_symlink(): raise Refusal('output_symlink')
    return plan

@contextmanager
def alarm(seconds):
    def expired(*_): raise TimeoutError('deadline')
    previous_handler=signal.signal(signal.SIGALRM,expired)
    earlier=signal.getitimer(signal.ITIMER_REAL)[0]
    prior=signal.setitimer(signal.ITIMER_REAL,max(0.000001,min(seconds,earlier) if earlier else seconds))
    began=time.monotonic()
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,previous_handler)
        if prior[0]: signal.setitimer(signal.ITIMER_REAL,max(0.000001,prior[0]-(time.monotonic()-began)),prior[1])

def publish(out,name,value,cap):
    body=encoded(value)+b'\n'
    if len(body)>cap: raise Refusal('control_cap')
    pending=out/(name+'.pending')
    with pending.open('xb') as handle:
        handle.write(body); handle.flush(); os.fsync(handle.fileno())
    os.link(pending,out/name); pending.unlink()

def finalize_raw(out):
    pending=out/'response.raw.pending'; final=out/'response.raw'
    if pending.exists() and not final.exists(): os.link(pending,final); pending.unlink()

def fetch(emit,on_status,factory=http.client.HTTPSConnection):
    """One direct TLS GET. Each delivered read1 chunk is retained before parsing."""
    connection=None; total=0
    with alarm(60):
        try:
            connection=factory(HOST,timeout=60,context=ssl.create_default_context())
            connection.request('GET',TARGET,headers={'Accept-Encoding':'identity','Accept':'application/json'})
            response=connection.getresponse()
            if type(response.status) is not int: raise Refusal('http_status_schema')
            on_status(response.status)
            length=response.getheader('Content-Length')
            if response.getheader('Content-Encoding') not in (None,'identity'): raise Refusal('content_encoding')
            if length is not None and (not re.fullmatch('[0-9]+',length) or int(length)>ACCEPT):
                raise Refusal('content_length_cap')
            while total<=ACCEPT:
                limit=min(8192,RECEIVED-total)
                try: chunk=response.read1(limit)
                except http.client.IncompleteRead as exc:
                    part=exc.partial
                    if isinstance(part,bytes) and part:
                        emit(part[:limit])
                    raise Refusal('incomplete_body') from None
                if not isinstance(chunk,bytes) or len(chunk)>limit: raise Refusal('read_contract')
                if not chunk:
                    if length is not None and total!=int(length): raise Refusal('incomplete_body')
                    if response.status!=200: raise Refusal('http_status')
                    return total
                emit(chunk); total+=len(chunk)
                if total>ACCEPT: raise Refusal('body_oversize')
            raise Refusal('body_oversize')
        finally:
            if connection is not None: connection.close()

def exact_runtime(obj):
    value=obj.get('runtimeBytecode')
    if not isinstance(value,dict): raise Refusal('runtime_missing')
    wire=value.get('onchainBytecode')
    if isinstance(wire,dict): wire=wire.get('bytecode')
    if not isinstance(wire,str) or not re.fullmatch('0x(?:[0-9a-fA-F]{2})*',wire):
        raise Refusal('runtime_hex')
    code=bytes.fromhex(wire[2:])
    if len(code)!=RUNTIME_BYTES or sha(code)!=RUNTIME_SHA: raise Refusal('runtime_identity')
    return value

def projection(raw,digest):
    obj=strict_json(raw)
    chain=obj.get('chainId')
    if type(chain) is int: chain=str(chain)
    if chain!=CHAIN: raise Refusal('wrong_chain')
    address=obj.get('address')
    if not isinstance(address,str) or address.lower()!=ADDRESS: raise Refusal('wrong_address')
    runtime=exact_runtime(obj)
    fields={}
    for key in ('metadata','compilation'):
        value=obj.get(key)
        if value is not None:
            fields[key+'_returned_json_sha256']=sha(encoded(value))
            fields[key+'_type']=type(value).__name__
    for key in ('recompiledBytecode','transformations','transformationValues',
                'immutableReferences','linkReferences','cborAuxdata'):
        value=runtime.get(key)
        if value is not None:
            fields[key+'_claim_sha256']=sha(encoded(value))
    match=obj.get('match')
    if match is not None: fields['match_claim_sha256']=sha(encoded(match))
    result={'schema':'comet-sourcify-lookup-v1-projection','status':'runtime_fingerprint_matched',
            'plan_sha256':digest,'raw_sha256':sha(raw),'raw_bytes':len(raw),'chain_id':CHAIN,
            'implementation':ADDRESS,'runtime_bytes':RUNTIME_BYTES,'runtime_sha256':RUNTIME_SHA,
            'provider_claims':fields,'source_equivalence':False,'eligibility':False,'economics':False,
            'metadata_cid_verified':False,'source_urls_followed':False}
    if len(encoded(result))>PROJECTION: raise Refusal('projection_cap')
    return result

def worker(digest,out):
    status='unavailable'; reason=None; count=0; http_status=None; handle=None
    try:
        with alarm(60):
            verify(digest)
            handle=(out/'response.raw.pending').open('xb')
            def emit(chunk):
                nonlocal count
                if not isinstance(chunk,bytes) or count+len(chunk)>RECEIVED: raise Refusal('received_cap')
                handle.write(chunk); handle.flush(); os.fsync(handle.fileno()); count+=len(chunk)
            def observed(code):
                nonlocal http_status
                http_status=code
                publish(out,'http-status.json',{'http_status':code,'plan_sha256':digest},512)
            fetch(emit,observed)
            handle.close(); handle=None; finalize_raw(out)
            raw=bounded(out/'response.raw',ACCEPT)
            if len(raw)!=count: raise Refusal('raw_length')
            value=projection(raw,digest)
            verify(digest); publish(out,'projection.json',value,PROJECTION)
            verify(digest); status='runtime_fingerprint_matched'
    except BaseException as exc:
        reason=str(exc)[:160] if isinstance(exc,Refusal) else ('timeout' if isinstance(exc,TimeoutError) else 'worker_failure')
    finally:
        if handle is not None: handle.close()
        finalize_raw(out)
        try: verify(digest)
        except Exception: status='unavailable'; reason='post_run_pin_failure'
        path=out/'response.raw'; body=bounded(path,RECEIVED) if path.exists() else None
        publish(out,'terminal.json',{'schema':'comet-sourcify-lookup-v1-terminal','status':status,
            'reason':reason,'plan_sha256':digest,'http_status':http_status,'received_bytes':count,
            'raw':{'bytes':len(body),'sha256':sha(body)} if body is not None else None,
            'source_equivalence':False,'eligibility':False,'economics':False},4096)

def run(digest):
    began=time.monotonic(); hard_deadline=began+65; cleanup_start=hard_deadline-2
    with alarm(max(0.000001,hard_deadline-time.monotonic())):
        plan=verify(digest)
        out=ROOT/OUT
        if any(path.is_symlink() for path in (out,*out.parents)): raise Refusal('output_symlink')
        out.mkdir(parents=True,exist_ok=False)
        publish(out,'claim.json',{'schema':'comet-sourcify-lookup-v1-claim','plan_sha256':digest,
            'source_pins':plan['source_pins'],'input_pins':plan['input_pins'],
            'claimed_ns':time.time_ns(),'one_get':True},4096)
        child=multiprocessing.get_context('fork').Process(target=worker,args=(digest,out)); started=False; interrupted=False
        if time.monotonic() < cleanup_start:
            try:
                child.start(); started=True
                child.join(max(0,cleanup_start-time.monotonic()))
            except TimeoutError:
                if child.pid is not None:
                    try: os.kill(child.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                raise
            except Exception:
                interrupted=True
                if not started and child.pid is not None:
                    try: os.kill(child.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
            except BaseException:
                if child.pid is not None:
                    try: os.kill(child.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                raise
        else:
            interrupted=True
        try:
            if started and child.is_alive():
                child.kill()
                child.join(min(0.5,max(0,hard_deadline-time.monotonic())))
        except TimeoutError:
            if child.pid is not None:
                try: os.kill(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            raise
        finalize_raw(out)
        if not (out/'terminal.json').exists():
            observed_status=None
            for name in ('http-status.json','http-status.json.pending'):
                if (out/name).exists():
                    try: observed_status=strict_json(bounded(out/name,512)).get('http_status')
                    except TimeoutError: raise
                    except Exception: pass
                    if type(observed_status) is int: break
            publish(out,'terminal.json',{'schema':'comet-sourcify-lookup-v1-terminal','status':'unavailable',
                'reason':'worker_no_terminal','plan_sha256':digest,'http_status':observed_status,
                'received_bytes':None,'raw_partial_retained':(out/'response.raw').exists()},4096)
        terminal=strict_json(bounded(out/'terminal.json',4096))
        good=not interrupted and child.exitcode==0 and terminal['status']=='runtime_fingerprint_matched'
        try: verify(digest)
        except TimeoutError: raise
        except Exception: good=False
        publish(out,'supervisor.json',{'schema':'comet-sourcify-lookup-v1-supervisor',
            'status':'runtime_fingerprint_matched' if good else 'unavailable','plan_sha256':digest,
            'worker_exitcode':child.exitcode,'terminal_sha256':sha(bounded(out/'terminal.json',4096)),
            'http_status':terminal.get('http_status'),'source_equivalence':False,'eligibility':False,
            'economics':False},4096)
        return good

def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument('--run',action='store_true')
    parser.add_argument('--plan-sha256'); args=parser.parse_args(argv)
    if not args.run:
        print(encoded({'status':'dry','network_requests':0,'writes':0}).decode()); return 0
    try:
        good=run(args.plan_sha256)
        print(encoded({'status':'runtime_fingerprint_matched' if good else 'unavailable'}).decode())
        return 0 if good else 1
    except Exception:
        print(encoded({'status':'unavailable'}).decode()); return 1
if __name__=='__main__': sys.exit(main())
