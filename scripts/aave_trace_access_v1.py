"""Six fixed anonymous RPCs: trace-access evidence only; default is dry.

Provider responses are assertions, not proofs or transaction cash ledgers.
No Aave selection, token decoding, opportunity, source-equivalence or profit.
"""
import argparse
import contextlib
import hashlib
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import platform
import re
import resource
import signal
import ssl
import struct
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/aave_trace_access_v1.py'
TEST = 'tests/test_aave_trace_access_v1.py'
DESIGN = 'reports/aave-trace-access-v1/design.txt'
DRAFT = 'reports/aave-trace-access-v1/draft-plan.json'
PLAN = 'reports/experiment-storage/aave-trace-access-v1.json'
OUT = 'reports/aave-trace-access-v1/run-v1'
EXTERNAL = 'reports/aave-trace-access-v1/unavailable-v1.json'
ENDPOINT = 'https://ethereum-rpc.publicnode.com'
ALLOCATION = dict(path='reports/experiment-storage/aave-trace-access-preparation-v1.json',
    bytes=4665, sha256='d3f0e9a76ccc9f514eccda588e53176778da11d527c03447f5ed03a8899c09d7')
CAPS = dict(requests=6, response_bytes=[4096,32768,32768,98304,98304,32768],
    body_bytes=299014, raw_bytes=360448, runtime_controls_bytes=20480,
    run_controls_bytes=16384, external_receipt_bytes=4096,
    request_seconds=20, worker_seconds=145, supervisor_seconds=150,
    cpu_seconds=15, ram_bytes=268435456, json_depth=32, json_nodes=60000)
CLAIMS = dict(source_equivalence=False, eligibility=False, economics=False,
    complete_cash_ledger=False, attainable_opportunity=False)
MAGIC = b'AAVE-TRACE-ACCESS-V1\n'


class Refusal(Exception):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        answer = {}
        for k,v in items:
            if k in answer:
                raise Refusal('duplicate_json_key')
            answer[k] = v
        return answer
    def integer(s):
        if len(s)>80:
            raise Refusal('json_integer_cap')
        return int(s)
    def reject(s):
        raise Refusal('nonfinite_or_float_json')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_int=integer, parse_float=reject, parse_constant=reject)
        todo = [(value,0)]; count = 0
        while todo:
            item,depth = todo.pop(); count += 1
            if depth>CAPS['json_depth'] or count>CAPS['json_nodes']:
                raise Refusal('json_structure_cap')
            if isinstance(item,str):
                item.encode('utf-8')  # Reject unpaired escaped surrogates.
            elif isinstance(item,dict):
                todo.extend((x,depth+1) for pair in item.items() for x in pair)
            elif isinstance(item,list):
                todo.extend((x,depth+1) for x in item)
        return value
    except Refusal:
        raise
    except (ValueError,UnicodeError,RecursionError):
        raise Refusal('invalid_json') from None


def bounded(path,cap):
    if path.is_symlink() or not path.is_file():
        raise Refusal('nonregular_input')
    with path.open('rb') as f:
        raw = f.read(cap+1)
    if len(raw)>cap:
        raise Refusal('file_cap')
    return raw


def runtime():
    return dict(python=sys.version, executable=sys.executable,
                implementation=platform.python_implementation(), openssl=ssl.OPENSSL_VERSION)


def build_manifest():
    return [dict(method='eth_chainId',params=[]),
        dict(method='eth_getBlockByNumber',params=['finalized',False]),
        dict(method='eth_getTransactionReceipt',params=['$transaction']),
        dict(method='debug_traceTransaction',params=['$transaction',dict(
            tracer='callTracer',timeout='10s',tracerConfig=dict(onlyTopCall=False,withLog=False))]),
        dict(method='debug_traceTransaction',params=['$transaction',dict(
            tracer='prestateTracer',timeout='10s',tracerConfig=dict(diffMode=True))]),
        dict(method='eth_getBlockByNumber',params=['$block.number',False])]


def check_pin(pin):
    path = pin.get('path') if isinstance(pin,dict) else None
    allowed = {SOURCE,TEST,DESIGN,DRAFT,ALLOCATION['path']}
    if (path not in allowed or set(pin)!={'path','bytes','sha256'}
        or type(pin['bytes']) is not int or not 0<pin['bytes']<=98304
        or not isinstance(pin['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256'])):
        raise Refusal('pin_schema')
    raw = bounded(ROOT/path,98304)
    if len(raw)!=pin['bytes'] or sha(raw)!=pin['sha256']:
        raise Refusal('pin_identity')


def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
        raise Refusal('exact_plan_sha_required')
    raw = bounded(ROOT/PLAN,8192)
    if sha(raw)!=digest:
        raise Refusal('plan_identity')
    p = strict_json(raw)
    expected = dict(schema='aave-trace-access-v1',status='frozen_trace_access_probe',
        endpoint=ENDPOINT,output_dir=OUT,external_receipt=EXTERNAL,chain_id=1,allocation=ALLOCATION,
        resource_limits=CAPS,request_manifest=build_manifest(),claims=CLAIMS,runtime=runtime())
    if not isinstance(p,dict) or any(encoded(p.get(k))!=encoded(v) for k,v in expected.items()):
        raise Refusal('frozen_scope_runtime')
    pins = p.get('source_pins')
    required = {SOURCE,TEST,DESIGN,DRAFT,ALLOCATION['path']}
    if (not isinstance(pins,list) or len(pins)!=5 or any(not isinstance(x,dict) for x in pins)
        or {x.get('path') for x in pins}!=required):
        raise Refusal('exact_direct_pins')
    for pin in pins:
        check_pin(pin)
        if pin['path']==ALLOCATION['path'] and pin!=ALLOCATION:
            raise Refusal('allocation_identity')
    if sum(x['bytes'] for x in pins if x['path']!=ALLOCATION['path'])+len(raw)>98304:
        raise Refusal('source_package_cap')
    for path in (ROOT/'reports', ROOT/'reports/aave-trace-access-v1', ROOT/OUT):
        if path.is_symlink():
            raise Refusal('symlink_output')
    return p


@contextlib.contextmanager
def alarm(seconds):
    def expired(signum,frame):
        raise TimeoutError('absolute_deadline')
    old_handler = signal.signal(signal.SIGALRM,expired)
    began = time.monotonic()
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    remaining = min(seconds,old_timer[0]) if old_timer[0]>0 else seconds
    signal.setitimer(signal.ITIMER_REAL,max(0.000001,remaining))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,old_handler)
        if old_timer[0]>0:
            signal.setitimer(signal.ITIMER_REAL,max(0.000001,
                old_timer[0]-(time.monotonic()-began)),old_timer[1])


def publish(out,name,value):
    raw = encoded(value)+b'\n'
    if len(raw)>4096:
        raise Refusal('control_file_cap')
    used = {}
    for path in out.iterdir():
        if path.is_file() and path.name!='responses.frames':
            st=path.stat(); used[st.st_dev,st.st_ino]=st.st_size
    reserve = 8192 if name not in ('terminal.json','supervisor.json') else (4096 if name=='terminal.json' else 0)
    if sum(used.values())+len(raw)+reserve>CAPS['run_controls_bytes']:
        raise Refusal('control_total_cap')
    pending = out/(name+'.pending')
    with pending.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    os.link(pending,out/name); pending.unlink()


class Frames:
    """One uncompressed inode; B request, H parsed headers, D body, E receipt."""
    def __init__(self,out):
        self.f=(out/'responses.frames').open('xb')
        self.f.write(MAGIC); self.f.flush(); os.fsync(self.f.fileno())
        self.used=len(MAGIC)
    def append(self,kind,raw):
        cap=4096 if kind==b'D' else 2048
        if kind not in (b'B',b'H',b'D',b'E') or len(raw)>cap:
            raise Refusal('frame_cap')
        body=kind+struct.pack('>I',len(raw))+raw
        # Keep a final E receipt available despite a preceding retention failure.
        reserve=2053 if kind!=b'E' else 0
        if self.used+len(body)+reserve>CAPS['raw_bytes']:
            raise Refusal('raw_total_cap')
        self.f.write(body); self.f.flush(); os.fsync(self.f.fileno()); self.used+=len(body)
    def close(self):
        self.f.close()


def fetch(request,cap,seconds,emit,observe,dispatch,factory=http.client.HTTPSConnection):
    """No redirect/proxy/retry; count one sentinel and retain every read fragment."""
    connection=None
    with alarm(seconds):
        try:
            connection=factory('ethereum-rpc.publicnode.com',timeout=seconds,
                               context=ssl.create_default_context())
            dispatch()
            connection.request('POST','/',body=encoded(request),headers={
                'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity'})
            response=connection.getresponse()
            headers=encoded(dict(status=response.status,headers=response.getheaders()))
            observe(response.status,headers[:2048])
            if len(headers)>2048:
                raise Refusal('parsed_headers_cap_prefix_retained')
            if response.getheader('Content-Encoding') not in (None,'identity'):
                raise Refusal('unsupported_content_encoding')
            count=0
            while count<=cap:
                limit=min(4096,cap+1-count)
                try:
                    raw=response.read1(limit)
                except http.client.IncompleteRead as exc:
                    raw=exc.partial
                    if isinstance(raw,bytes):
                        emit(raw[:limit])
                    raise Refusal('incomplete_body_prefix_retained') from None
                if not isinstance(raw,bytes) or len(raw)>limit:
                    raise Refusal('transport_read_contract')
                if not raw:
                    length=response.getheader('Content-Length')
                    if length is not None and (not re.fullmatch('[0-9]+',length) or int(length)!=count):
                        raise Refusal('content_length_mismatch')
                    return response.status,count
                emit(raw); count+=len(raw)
                if count>cap:
                    raise Refusal('response_cap_sentinel_retained')
        finally:
            if connection is not None:
                connection.close()


def hexdata(v,bytes_=None):
    if not isinstance(v,str) or not re.fullmatch('0x(?:[0-9a-fA-F]{2})*',v):
        raise Refusal('hex_data')
    if bytes_ is not None and len(v)!=2+2*bytes_:
        raise Refusal('hex_data_width')
    return v.lower()


def quantity(v):
    if not isinstance(v,str) or not re.fullmatch('0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,63})',v):
        raise Refusal('hex_quantity')
    return int(v,16)


def envelope(raw,id_):
    v=strict_json(raw)
    if not isinstance(v,dict) or v.get('jsonrpc')!='2.0' or type(v.get('id')) is not int or v['id']!=id_:
        raise Refusal('rpc_envelope_identity')
    if set(v)=={'jsonrpc','id','error'}:
        e=v['error']
        if (not isinstance(e,dict) or not {'code','message'}<=set(e)<={'code','message','data'}
            or type(e['code']) is not int or not isinstance(e['message'],str)):
            raise Refusal('rpc_error_schema')
        raise Refusal('rpc_error_no_retry')
    if set(v)!={'jsonrpc','id','result'} or v['result'] is None:
        raise Refusal('rpc_result_schema_or_null')
    return v['result']


class State:
    def __init__(self):
        self.block=None; self.tx=None; self.receipt_status=None
        self.call_available=self.diff_available=self.final=False
        self.call_frames=self.modified_storage_slots=0
    def request(self,index):
        item=build_manifest()[index]
        def resolve(v):
            if isinstance(v,str):
                return {'$transaction':self.tx,'$block.number':(self.block or {}).get('number')}.get(v,v)
            if isinstance(v,list): return [resolve(x) for x in v]
            if isinstance(v,dict): return {k:resolve(x) for k,x in v.items()}
            return v
        return dict(jsonrpc='2.0',id=index+1,**resolve(item))
    def accept(self,index,v):
        if index==0:
            if quantity(v)!=1: raise Refusal('wrong_chain')
        elif index in (1,5):
            if not isinstance(v,dict): raise Refusal('block_schema')
            for k in ('hash','parentHash'): hexdata(v.get(k),32)
            for k in ('number','timestamp'): quantity(v.get(k))
            txs=v.get('transactions')
            if not isinstance(txs,list) or not txs: raise Refusal('empty_or_invalid_block_no_replacement')
            for tx in txs: hexdata(tx,32)
            if len(set(txs))!=len(txs): raise Refusal('duplicate_transaction')
            if index==1:
                self.block=v; self.tx=txs[0]
            else:
                if encoded(v)!=encoded(self.block): raise Refusal('canonical_block_changed')
                self.final=True
        elif index==2:
            if (not isinstance(v,dict) or v.get('transactionHash')!=self.tx
                or v.get('blockHash')!=self.block['hash'] or v.get('blockNumber')!=self.block['number']
                or quantity(v.get('transactionIndex'))!=0):
                raise Refusal('receipt_block_transaction_mismatch')
            self.receipt_status=quantity(v.get('status'))
            if self.receipt_status not in (0,1): raise Refusal('receipt_status')
            quantity(v.get('gasUsed')); quantity(v.get('effectiveGasPrice'))
        elif index==3:
            todo=[v]
            while todo:
                call=todo.pop()
                if not isinstance(call,dict) or call.get('type') not in (
                    'CALL','STATICCALL','DELEGATECALL','CALLCODE','CREATE','CREATE2','SELFDESTRUCT'):
                    raise Refusal('call_tree_schema')
                hexdata(call.get('from'),20)
                if call.get('to') is not None: hexdata(call['to'],20)
                for k in ('gas','gasUsed'): quantity(call.get(k))
                if 'value' in call: quantity(call['value'])
                hexdata(call.get('input'))
                if 'output' in call: hexdata(call['output'])
                for k in ('error','revertReason'):
                    if k in call and not isinstance(call[k],str): raise Refusal('call_error_schema')
                calls=call.get('calls',[])
                if not isinstance(calls,list): raise Refusal('call_children_schema')
                todo.extend(calls)
                self.call_frames+=1
            self.call_available=True
        elif index==4:
            if not isinstance(v,dict) or set(v)!={'pre','post'}:
                raise Refusal('prestate_diff_schema')
            for accounts in v.values():
                if not isinstance(accounts,dict): raise Refusal('prestate_accounts_schema')
                for address,account in accounts.items():
                    hexdata(address,20)
                    if not isinstance(account,dict) or not set(account)<={'balance','nonce','code','storage'}:
                        raise Refusal('prestate_account_fields')
                    if 'balance' in account: quantity(account['balance'])
                    if 'nonce' in account and (type(account['nonce']) is not int or not 0<=account['nonce']<2**64):
                        raise Refusal('prestate_nonce_uint64')
                    if 'code' in account: hexdata(account['code'])
                    if 'storage' in account:
                        if not isinstance(account['storage'],dict): raise Refusal('prestate_storage_schema')
                        for key,value in account['storage'].items(): hexdata(key,32); hexdata(value,32)
                        if accounts is v['post']: self.modified_storage_slots+=len(account['storage'])
            self.diff_available=True
    def projection(self,digest,raw_pin):
        if not (self.call_available and self.diff_available and self.final):
            raise Refusal('incomplete_trace_access')
        return dict(schema='aave-trace-access-v1-projection',status='structurally_usable_provider_traces',
            plan_sha256=digest,raw=raw_pin,selected_block_hash=self.block['hash'],
            selected_block_number=self.block['number'],transaction_hash=self.tx,
            receipt_status=self.receipt_status,call_tree_available=True,pre_post_diff_available=True,
            call_frame_count=self.call_frames,post_diff_storage_slot_count=self.modified_storage_slots,
            provider_asserted_canonicality=True,independent_consensus_verified=False,**CLAIMS)


def replay(path):
    raw=bounded(path,CAPS['raw_bytes']); offset=len(MAGIC)
    if raw[:offset]!=MAGIC: raise Refusal('frame_magic')
    state=State(); active=None; completed=0; total=0
    while offset<len(raw):
        if offset+5>len(raw): raise Refusal('truncated_frame')
        kind=raw[offset:offset+1]; length=struct.unpack('>I',raw[offset+1:offset+5])[0]; offset+=5
        if length>(4096 if kind==b'D' else 2048) or offset+length>len(raw): raise Refusal('frame_length')
        part=raw[offset:offset+length]; offset+=length
        if kind==b'B':
            meta=strict_json(part)
            if active is not None or completed>=6 or meta.get('request')!=state.request(completed):
                raise Refusal('request_manifest_order')
            active=dict(body=bytearray(),headers=None)
        elif kind==b'H':
            if active is None or active['headers'] is not None: raise Refusal('headers_order')
            active['headers']=strict_json(part)
        elif kind==b'D':
            if active is None or len(active['body'])+length>CAPS['response_bytes'][completed]+1:
                raise Refusal('replay_body_cap')
            active['body'].extend(part); total+=length
            if total>CAPS['body_bytes']: raise Refusal('replay_cumulative_cap')
        elif kind==b'E':
            if active is None: raise Refusal('end_order')
            end=strict_json(part); body=bytes(active['body'])
            if (end.get('error') is not None or end.get('http_status')!=200 or end.get('dispatch_attempted') is not True
                or end.get('response_bytes')!=len(body) or end.get('response_sha256')!=sha(body)
                or len(body)>CAPS['response_bytes'][completed]
                or not isinstance(active['headers'],dict) or active['headers'].get('status')!=200
                or not isinstance(active['headers'].get('headers'),list)):
                raise Refusal('failed_request_not_admitted')
            state.accept(completed,envelope(body,completed+1)); active=None; completed+=1
        else: raise Refusal('unknown_frame_kind')
    if active is not None or completed!=6: raise Refusal('incomplete_six_request_trace')
    return state,dict(bytes=len(raw),sha256=sha(raw))


def reason(exc):
    return str(exc)[:160] if isinstance(exc,Refusal) else ('deadline' if isinstance(exc,TimeoutError) else 'bounded_failure')


def worker(digest,out,deadline):
    frames=None; attempts=total=0; status='unavailable'; error=None; began=time.time_ns()
    try:
        resource.setrlimit(resource.RLIMIT_CPU,(15,15))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        with alarm(deadline-time.monotonic()):
            verify(digest); frames=Frames(out); state=State()
            for index in range(6):
                verify(digest); request=state.request(index); cap=CAPS['response_bytes'][index]
                frames.append(b'B',encoded(dict(request=request,admitted_ns=time.time_ns(),dispatch_attempted=None)))
                body=bytearray(); code=None; dispatched=False; failure=None
                def emit(part):
                    nonlocal total
                    if len(body)+len(part)>cap+1 or total+len(part)>CAPS['body_bytes']:
                        raise Refusal('body_retention_cap')
                    frames.append(b'D',part); body.extend(part); total+=len(part)
                def headers(status_code,part):
                    nonlocal code
                    # Status stays available even if parsed header serialization is capped.
                    code=status_code
                    frames.append(b'H',part)
                def dispatch():
                    nonlocal dispatched,attempts
                    dispatched=True; attempts+=1
                try:
                    remaining=min(20,deadline-time.monotonic())
                    if remaining<=0: raise TimeoutError('deadline')
                    code,count=fetch(request,cap,remaining,emit,headers,dispatch)
                    if code!=200 or count!=len(body): raise Refusal('http_status_or_count')
                except Exception as exc:
                    failure=reason(exc)
                frames.append(b'E',encoded(dict(http_status=code,dispatch_attempted=dispatched,
                    response_bytes=len(body),response_bytes_meaning='retained_body_prefix',
                    response_sha256=sha(body),error=failure,finished_ns=time.time_ns())))
                if failure: raise Refusal(failure)
                state.accept(index,envelope(bytes(body),index+1))
            frames.close(); frames=None
            decoded,pin=replay(out/'responses.frames')
            projection=decoded.projection(digest,pin)
            if encoded(projection)!=encoded(state.projection(digest,pin)):
                raise Refusal('replay_disagreement')
            verify(digest); publish(out,'projection.json',projection); verify(digest)
            status='structurally_usable_provider_traces'
    except BaseException as exc:
        error=reason(exc)
    finally:
        if frames is not None: frames.close()
        try:
            with alarm(deadline-time.monotonic()):
                verify(digest)
                publish(out,'terminal.json',dict(schema='aave-trace-access-v1-terminal',status=status,
                    error=error,plan_sha256=digest,started_ns=began,ended_ns=time.time_ns(),
                    requests_attempted=attempts,attempts_meaning='request_method_invocations_not_proven_wire_delivery',
                    response_bytes=total,request_denominator=6,**CLAIMS))
        except BaseException:
            pass  # Supervisor retains unavailable closeout; never salvages projection.


def admitted(terminal,digest,exitcode):
    return (terminal.get('schema')=='aave-trace-access-v1-terminal'
        and terminal.get('status')=='structurally_usable_provider_traces'
        and terminal.get('plan_sha256')==digest and terminal.get('error') is None
        and terminal.get('requests_attempted')==6 and exitcode==0)


def external_receipt(digest,failure,deadline):
    """Exclusive bounded unavailable record; never inspects the worker directory.

    No safe time left means no receipt. Absence is unknown, never success.
    """
    remaining=deadline-time.monotonic()
    if remaining<=0:
        return False
    raw=encoded(dict(schema='aave-trace-access-v1-external-unavailable',status='unavailable',
        error=failure,plan_sha256=digest,request_denominator=6,requests_attempted=None,
        response_bytes=None,run_directory='untouched_after_unconfirmed_exit_or_deadline',
        post_run_pins_verified=False,ended_ns=time.time_ns(),**CLAIMS))+b'\n'
    if len(raw)>CAPS['external_receipt_bytes']:
        return False
    try:
        with alarm(min(remaining,0.5)):
            with (ROOT/EXTERNAL).open('xb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
        return True
    except BaseException:
        return False  # Prefix/absence is unavailable; never replace or retry it.


def stop_worker(process,deadline):
    if process is None or process.pid is None:
        return True
    try:
        if process.is_alive():
            process.kill()
            process.join(timeout=min(0.5,max(0,deadline-time.monotonic())))
        return not process.is_alive() and process.exitcode is not None
    except BaseException:
        return False


def run(digest):
    began=time.monotonic(); deadline=began+150; started_ns=time.time_ns(); process=None
    claimed=False; exit_confirmed=False
    try:
        with alarm(150):
            plan=verify(digest); out=ROOT/OUT
            if (ROOT/EXTERNAL).exists() or (ROOT/EXTERNAL).is_symlink():
                raise Refusal('existing_external_receipt')
            out.mkdir(parents=True,exist_ok=False); claimed=True
            publish(out,'claim.json',dict(schema='aave-trace-access-v1-claim',plan_sha256=digest,
                source_pins=plan['source_pins'],started_ns=started_ns,**CLAIMS))
            process=multiprocessing.get_context('fork').Process(target=worker,args=(digest,out,began+145))
            failure=None
            try:
                process.start()
                process.join(max(0,deadline-3-time.monotonic()))
                if process.pid is not None and process.is_alive(): failure='worker_deadline_or_exit'
            except TimeoutError:
                raise
            except BaseException as exc:
                failure=reason(exc)
            finally:
                exit_confirmed=stop_worker(process,deadline)
            if not exit_confirmed:
                external_receipt(digest,'worker_exit_unconfirmed',deadline)
                return False  # No run-dir inspection, reading, publication or pin salvage.
            if not (out/'terminal.json').exists():
                publish(out,'terminal.json',dict(schema='aave-trace-access-v1-terminal',status='unavailable',
                    error=failure or 'unrecovered_worker',plan_sha256=digest,requests_attempted=None,
                    response_bytes=None,request_denominator=6,dispatch_and_values='unavailable',
                    raw_prefix_retained=(out/'responses.frames').exists(),**CLAIMS))
            terminal=strict_json(bounded(out/'terminal.json',4096)); pins_ok=True
            try: verify(digest)
            except TimeoutError: raise
            except Exception: pins_ok=False
            ok=pins_ok and failure is None and admitted(terminal,digest,process.exitcode)
            publish(out,'supervisor.json',dict(schema='aave-trace-access-v1-supervisor',
                status='structurally_usable_provider_traces' if ok else 'unavailable',error=failure,
                plan_sha256=digest,worker_exitcode=process.exitcode,pins_verified=pins_ok,
                terminal_sha256=sha(bounded(out/'terminal.json',4096)),started_ns=started_ns,
                ended_ns=time.time_ns(),elapsed_ns=int((time.monotonic()-began)*10**9),**CLAIMS))
            return ok
    except TimeoutError:
        if claimed:
            if not exit_confirmed: stop_worker(process,deadline)
            external_receipt(digest,'outer_deadline_closeout_unknown',deadline)
        return False


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true'); parser.add_argument('--plan-sha256')
    args=parser.parse_args(argv)
    if not args.run:
        print('dry: zero requests; zero outputs; fixed six-request trace-access probe')
        return 0
    try:
        ok=run(args.plan_sha256)
        print('structurally_usable_provider_traces' if ok else 'unavailable')
        return 0 if ok else 1
    except Exception as exc:
        print('refused: '+reason(exc)); return 1


if __name__=='__main__':
    exit_code=main()
    try:
        sys.stdout.flush(); sys.stderr.flush()
    finally:
        # multiprocessing atexit otherwise joins active children without a bound.
        # All admitted records are already fsynced; imported run() remains unchanged.
        os._exit(exit_code)
