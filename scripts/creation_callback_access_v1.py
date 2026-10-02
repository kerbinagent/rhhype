"""Five fixed RPC slots; creation and authenticated self-callback access only.

Default is offline dry. No compiler, Aave calls, tokens, gas costs or economics.
"""
import argparse
import hashlib
import os
from pathlib import Path
import resource
import struct
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/creation_callback_access_v1.py'
TEST='tests/test_creation_callback_access_v1.py'
DESIGN='reports/creation-callback-access-v1/design.txt'
DRAFT='reports/creation-callback-access-v1/draft-plan.json'
PLAN='reports/experiment-storage/creation-callback-access-v1.json'
OUT='reports/creation-callback-access-v1/run-v1'
HELPER=dict(path='scripts/aave_trace_access_v1.py',bytes=27936,
    sha256='48697649d725daacef637181efea89d7376ea967426e4b1b2db55397c9fde6de')
ALLOCATION=dict(path='reports/experiment-storage/creation-callback-access-preparation-v1.json',
    bytes=4866,sha256='6f7fdaee187af0a47294bc966a2983e4e3385ada9adf0b3fcbc333c0a8002843')
ENDPOINT='https://ethereum-rpc.publicnode.com'
CAPS=dict(requests=5,response_bytes=[4096,32768,4096,4096,32768],body_bytes=77829,
    raw_bytes=147456,controls_bytes=16384,request_seconds=20,work_seconds=115,
    total_seconds=120,cpu_seconds=15,ram_bytes=268435456,gas=500000)
CLAIMS=dict(simulation_only=True,aave_callback=False,protocol_execution=False,
    source_equivalence=False,economics=False,gas_cost_evidence=False,account_ownership=False)
MAGIC=b'CREATION-CALLBACK-V1\n'
CONSTANT='7f'+'11'*32+'60005260206000f3'
RUNTIME=('361561006a5736600414156100935733301415610093576000357f61626364'+'00'*28+
    '1415610093577f'+'22'*32+'60005260206000f35b6361626364600052602060006004601c6000305af115'+
    '610093573d602014156100935760206000f35b600080fd')
CHILD='6098600c60003960986000f3'+RUNTIME
CALLBACK=('6100a46100486000396100a460006000f0801561004357803b15610043576040526020600060006000'+
    '60006040515af115610043573d602014156100435760206000f35b600080fd'+CHILD)
EXPECTED=['0x'+'11'*32,'0x'+'22'*32]


class Refusal(Exception): pass


def sha(raw): return hashlib.sha256(raw).hexdigest()


def read(path,cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as f: raw=f.read(cap+1)
    if len(raw)>cap: raise Refusal('file_cap')
    return raw


_raw=read(ROOT/HELPER['path'],32768)
if len(_raw)!=HELPER['bytes'] or sha(_raw)!=HELPER['sha256']: raise Refusal('helper_identity')
h=types.ModuleType('creation_callback_immutable_helpers'); h.__file__=str(ROOT/HELPER['path'])
exec(compile(_raw,h.__file__,'exec'),h.__dict__)
del _raw
encode=h.encoded
decode=h.strict_json


def bytecode_spec():
    return dict(constant_initcode='0x'+CONSTANT,callback_initcode='0x'+CALLBACK,
        child_initcode='0x'+CHILD,child_runtime='0x'+RUNTIME,expected_results=EXPECTED,
        offsets=dict(constant_bytes=41,outer_bytes=236,outer_child_offset=72,
            outer_failure_jumpdest=67,child_init_bytes=164,child_runtime_offset=12,
            child_runtime_bytes=152,runtime_entry_jumpdest=106,runtime_failure_jumpdest=147,
            outer_jump_pushes=[19,26,49,58],runtime_jump_pushes=[2,11,19,61,129,138],
            outer_codecopy_pc=8,child_codecopy_pc=6,outer_create_pc=16,
            outer_call_pc=47,runtime_self_call_pc=127),
        callback_selector='0x61626364',callback_input_bytes=4,
        return_bytes=32,from_address='0x0000000000000000000000000000000000000001')


def build_manifest():
    def call(code):
        return dict(method='eth_call',params=[dict(**{'from':bytecode_spec()['from_address']},
            input='0x'+code,value='0x0',gasPrice='0x0',gas=hex(500000)),'$block.number'])
    return [dict(method='eth_chainId',params=[]),dict(method='eth_getBlockByNumber',params=['finalized',False]),
        call(CONSTANT),call(CALLBACK),dict(method='eth_getBlockByNumber',params=['$block.number',False])]


def pin(p):
    if (not isinstance(p,dict) or set(p)!={'path','bytes','sha256'} or type(p['bytes']) is not int
        or not 0<p['bytes']<=49152): raise Refusal('pin_schema')
    raw=read(ROOT/p['path'],49152)
    if len(raw)!=p['bytes'] or sha(raw)!=p['sha256']: raise Refusal('pin_identity')


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if not isinstance(digest,str) or len(digest)!=64 or sha(raw)!=digest: raise Refusal('exact_plan_sha_required')
    p=decode(raw)
    expected=dict(schema='creation-callback-access-v1',status='frozen_creation_callback_probe',
        endpoint=ENDPOINT,output_dir=OUT,chain_id=1,allocation=ALLOCATION,helper=HELPER,resource_limits=CAPS,
        bytecode_spec=bytecode_spec(),request_manifest=build_manifest(),claims=CLAIMS,runtime=h.runtime())
    if not isinstance(p,dict) or any(encode(p.get(k))!=encode(v) for k,v in expected.items()):
        raise Refusal('frozen_scope_runtime')
    required={SOURCE,TEST,DESIGN,DRAFT,HELPER['path'],ALLOCATION['path']}; pins=p.get('source_pins')
    if (not isinstance(pins,list) or len(pins)!=6 or any(not isinstance(x,dict) for x in pins)
        or {x.get('path') for x in pins}!=required): raise Refusal('exact_pins')
    for item in pins:
        pin(item)
        if item['path']==HELPER['path'] and item!=HELPER: raise Refusal('fixed_helper')
        if item['path']==ALLOCATION['path'] and item!=ALLOCATION: raise Refusal('fixed_allocation')
    if sum(x['bytes'] for x in pins if x['path'] in {SOURCE,TEST,DESIGN,DRAFT})+len(raw)>49152:
        raise Refusal('source_package_cap')
    for path in (ROOT/'reports',ROOT/'reports/creation-callback-access-v1',ROOT/OUT):
        if path.is_symlink(): raise Refusal('symlink_output')
    return p


def publish(out,name,value):
    raw=encode(value)+b'\n'
    if len(raw)>4096: raise Refusal('control_file_cap')
    used={}
    for path in out.iterdir():
        if path.is_file() and path.name!='responses.frames':
            st=path.stat(); used[st.st_dev,st.st_ino]=st.st_size
    reserve=4096 if name!='terminal.json' else 0
    if sum(used.values())+len(raw)+reserve>16384: raise Refusal('control_total_cap')
    pending=out/(name+'.pending')
    with pending.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    os.link(pending,out/name); pending.unlink()


class Frames:
    def __init__(self,out):
        self.f=(out/'responses.frames').open('xb'); self.used=len(MAGIC)
        self.f.write(MAGIC); self.f.flush(); os.fsync(self.f.fileno())
    def append(self,kind,raw):
        if kind not in (b'B',b'H',b'D',b'E') or len(raw)>(4096 if kind==b'D' else 2048):
            raise Refusal('frame_cap')
        body=kind+struct.pack('>I',len(raw))+raw
        if self.used+len(body)+(2053 if kind!=b'E' else 0)>147456: raise Refusal('raw_cap')
        self.f.write(body); self.f.flush(); os.fsync(self.f.fileno()); self.used+=len(body)
    def close(self): self.f.close()


class State:
    def __init__(self): self.block=None; self.outputs=[]; self.final=False
    def request(self,i):
        def resolve(v):
            if v=='$block.number': return (self.block or {}).get('number')
            if isinstance(v,list): return [resolve(x) for x in v]
            if isinstance(v,dict): return {k:resolve(x) for k,x in v.items()}
            return v
        return dict(jsonrpc='2.0',id=i+1,**resolve(build_manifest()[i]))
    def accept(self,i,v):
        if i==0:
            if h.quantity(v)!=1: raise Refusal('wrong_chain')
        elif i in (1,4):
            if not isinstance(v,dict): raise Refusal('block_schema')
            for k in ('hash','parentHash'): h.hexdata(v.get(k),32)
            for k in ('number','timestamp'): h.quantity(v.get(k))
            if not isinstance(v.get('transactions'),list): raise Refusal('block_transactions')
            for tx in v['transactions']: h.hexdata(tx,32)
            if i==1: self.block=v
            else:
                if encode(v)!=encode(self.block): raise Refusal('canonical_header_changed')
                self.final=True
        elif i in (2,3):
            h.hexdata(v,32)
            if v.lower()!=EXPECTED[i-2]: raise Refusal('creation_output_mismatch')
            self.outputs.append(v.lower())
    def projection(self,digest,raw_pin):
        if not self.final or self.outputs!=EXPECTED: raise Refusal('incomplete_five_slots')
        return dict(schema='creation-callback-access-v1-projection',status='creation_self_callback_outputs_available',
            plan_sha256=digest,raw=raw_pin,block_number=self.block['number'],block_hash=self.block['hash'],
            outputs=self.outputs,provider_asserted_canonicality=True,request_denominator=5,**CLAIMS)


def replay(path):
    raw=read(path,147456); offset=len(MAGIC); state=State(); active=None; count=total=0
    if raw[:offset]!=MAGIC: raise Refusal('raw_magic')
    while offset<len(raw):
        if offset+5>len(raw): raise Refusal('truncated_frame')
        kind=raw[offset:offset+1]; size=struct.unpack('>I',raw[offset+1:offset+5])[0]; offset+=5
        if size>(4096 if kind==b'D' else 2048) or offset+size>len(raw): raise Refusal('frame_length')
        body=raw[offset:offset+size]; offset+=size
        if kind==b'B':
            if active is not None or count>=5 or decode(body).get('request')!=state.request(count):
                raise Refusal('request_order_manifest')
            active=dict(body=bytearray(),headers=None)
        elif kind==b'H':
            if active is None or active['headers'] is not None: raise Refusal('headers_order')
            active['headers']=decode(body)
        elif kind==b'D':
            if active is None or active['headers'] is None: raise Refusal('body_before_headers')
            if len(active['body'])+size>CAPS['response_bytes'][count]+1: raise Refusal('body_cap')
            active['body'].extend(body); total+=size
            if total>77829: raise Refusal('cumulative_cap')
        elif kind==b'E':
            if active is None: raise Refusal('end_order')
            end=decode(body); response=bytes(active['body'])
            if (end.get('error') is not None or end.get('http_status')!=200 or end.get('dispatch_attempted') is not True
                or end.get('response_bytes')!=len(response) or end.get('response_sha256')!=sha(response)
                or len(response)>CAPS['response_bytes'][count] or not isinstance(active['headers'],dict)
                or active['headers'].get('status')!=200): raise Refusal('failed_request_not_admitted')
            state.accept(count,h.envelope(response,count+1)); active=None; count+=1
        else: raise Refusal('frame_kind')
    if active is not None or count!=5: raise Refusal('incomplete_five_slots')
    return state,dict(bytes=len(raw),sha256=sha(raw))


def reason(exc):
    return str(exc)[:160] if isinstance(exc,(Refusal,h.Refusal)) else ('deadline' if isinstance(exc,TimeoutError) else 'bounded_failure')


def run(digest):
    began=time.monotonic(); deadline=began+120; work=began+115
    frames=None; attempts=total=0; error=None; status='unavailable'; out=None; started_ns=time.time_ns()
    with h.alarm(120):
        p=verify(digest); out=ROOT/OUT; out.mkdir(parents=True,exist_ok=False)
        publish(out,'claim.json',dict(schema='creation-callback-access-v1-claim',plan_sha256=digest,
            started_ns=started_ns,source_pins=p['source_pins'],**CLAIMS))
        try:
            resource.setrlimit(resource.RLIMIT_CPU,(15,15)); resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
            with h.alarm(work-time.monotonic()):
                frames=Frames(out); state=State()
                for i in range(5):
                    verify(digest); request=state.request(i); cap=CAPS['response_bytes'][i]
                    frames.append(b'B',encode(dict(request=request,admitted_ns=time.time_ns(),dispatch_attempted=None)))
                    body=bytearray(); code=None; failure=None; dispatched=False
                    def dispatch():
                        nonlocal attempts,dispatched
                        attempts+=1; dispatched=True
                    def emit(part):
                        nonlocal total
                        if len(body)+len(part)>cap+1 or total+len(part)>77829: raise Refusal('body_retention_cap')
                        frames.append(b'D',part); body.extend(part); total+=len(part)
                    def headers(status_code,part):
                        nonlocal code
                        code=status_code; frames.append(b'H',part)
                    try:
                        remain=min(20,work-time.monotonic())
                        if remain<=0: raise TimeoutError('deadline')
                        code,n=h.fetch(request,cap,remain,emit,headers,dispatch)
                        if code!=200 or n!=len(body): raise Refusal('http_status_or_count')
                    except Exception as exc: failure=reason(exc)
                    frames.append(b'E',encode(dict(http_status=code,dispatch_attempted=dispatched,error=failure,
                        response_bytes=len(body),response_bytes_meaning='retained_prefix',response_sha256=sha(body),ended_ns=time.time_ns())))
                    if failure: raise Refusal(failure)
                    state.accept(i,h.envelope(bytes(body),i+1))
                frames.close(); frames=None
                decoded,pin_=replay(out/'responses.frames'); projection=decoded.projection(digest,pin_)
                if encode(projection)!=encode(state.projection(digest,pin_)): raise Refusal('raw_replay_mismatch')
                verify(digest); publish(out,'projection.json',projection); verify(digest)
                status='creation_self_callback_outputs_available'
        except BaseException as exc: status='unavailable'; error=reason(exc)
        finally:
            if frames is not None: frames.close()
            try:
                verify(digest)
            except TimeoutError: raise
            except Exception: status='unavailable'; error='post_run_pin_failure'
            publish(out,'terminal.json',dict(schema='creation-callback-access-v1-terminal',status=status,error=error,
                plan_sha256=digest,requests_attempted=attempts,response_bytes=total,request_denominator=5,
                attempts_meaning='request_method_invocations_not_wire_proof',started_ns=started_ns,
                ended_ns=time.time_ns(),elapsed_ns=int((time.monotonic()-began)*10**9),**CLAIMS))
        return status=='creation_self_callback_outputs_available' and error is None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run',action='store_true')
    parser.add_argument('--plan-sha256'); args=parser.parse_args(argv)
    if not args.run:
        print('dry: zero requests; zero outputs; fixed creation/self-callback access probe'); return 0
    try:
        ok=run(args.plan_sha256); print('creation_self_callback_outputs_available' if ok else 'unavailable')
        return 0 if ok else 1
    except Exception as exc: print('refused: '+reason(exc)); return 1


if __name__=='__main__': raise SystemExit(main())
