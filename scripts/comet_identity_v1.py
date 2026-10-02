"""One prospective six-request Comet identity pass; default is offline dry.

EIP-1898 blockHash/requireCanonical queries and ERC-1967 implementation slot.
SHA256 runtime fingerprints are not EVM codehashes or source-equivalence proofs.
Exact received body prefixes remain in one append-only, fsynced framed inode.
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
import signal
import ssl
import struct
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/comet_identity_v1.py'
TEST = 'tests/test_comet_identity_v1.py'
PLAN = 'reports/experiment-storage/comet-identity-v1.json'
OUT = 'reports/comet-identity-v1/run-v1'
ENDPOINT = 'https://ethereum-rpc.publicnode.com'
ALLOCATION = dict(path='reports/experiment-storage/comet-identity-v1-allocation.json', bytes=2945,
    sha256='fa3a78f729ced1c332dc281e7fa8d7ec00672f954c2d7b4e5e377551b0c4f62c')
HELPER = dict(path='scripts/peer_comet_eligibility_v1.py',
    sha256='879f58149d222bdfaa627d28b4335c2b01c72aba51a3771655f61764f473a908')
PROXY = '0xc3d688b66703497daa19211eedff47f25384cdc3'
SLOT = '0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc'
CAPS = dict(requests=6, response_bytes=[4096,65536,65536,4096,65536,65536],
    cumulative_body_bytes=270336, raw_bytes=327680, projection_bytes=16384,
    controls_bytes=12288, request_seconds=10, process_seconds=75,
    frame_payload_bytes=8192, json_depth=32, json_nodes=4096)
MAGIC = b'COMET-ID-V1\n'


class Refusal(Exception):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def bounded(path, cap):
    if path.is_symlink() or not path.is_file():
        raise Refusal('nonregular_file')
    with path.open('rb') as handle:
        raw = handle.read(cap+1)
    if len(raw) > cap:
        raise Refusal('file_byte_cap')
    return raw


def check_pin(pin, cap):
    if (not isinstance(pin, dict) or set(pin) != {'path','bytes','sha256'}
        or type(pin['bytes']) is not int or not 0 < pin['bytes'] <= cap
        or not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256'])):
        raise Refusal('pin_schema')
    raw = bounded(ROOT / pin['path'], cap)
    if len(raw) != pin['bytes'] or sha(raw) != pin['sha256']:
        raise Refusal('pin_identity')
    return raw


helper = types.ModuleType('comet_identity_pure_helpers')
helper.__file__ = str(ROOT / HELPER['path'])
_helper_raw = bounded(ROOT / HELPER['path'], 65536)
if sha(_helper_raw) != HELPER['sha256']:
    raise Refusal('helper_identity')
exec(compile(_helper_raw, helper.__file__, 'exec'), helper.__dict__)
del _helper_raw


def build_manifest():
    selector = dict(blockHash='$parent.hash', requireCanonical=True)
    return [dict(method='eth_chainId', params=[]),
        dict(method='eth_getBlockByNumber', params=['latest',False]),
        dict(method='eth_getCode', params=[PROXY,selector]),
        dict(method='eth_getStorageAt', params=[PROXY,SLOT,selector]),
        dict(method='eth_getCode', params=['$implementation',selector]),
        dict(method='eth_getBlockByNumber', params=['$parent.number',False])]


def resolve(value, parent, implementation):
    if isinstance(value,str):
        return {'$parent.hash':parent.get('hash'), '$parent.number':parent.get('number'),
                '$implementation':implementation}.get(value,value)
    if isinstance(value,list):
        return [resolve(x,parent,implementation) for x in value]
    if isinstance(value,dict):
        return {k:resolve(v,parent,implementation) for k,v in value.items()}
    return value


def runtime_identity():
    return dict(python=sys.version, executable=sys.executable, implementation=platform.python_implementation(),
                openssl=ssl.OPENSSL_VERSION)


def verify(plan_sha):
    if not isinstance(plan_sha,str) or not re.fullmatch('[0-9a-f]{64}',plan_sha):
        raise Refusal('exact_plan_sha_required')
    raw = bounded(ROOT / PLAN,16384)
    if sha(raw) != plan_sha:
        raise Refusal('plan_sha_mismatch')
    plan = helper.decode_json(raw)
    if (plan.get('schema') != 'comet-identity-v1' or plan.get('status') != 'frozen_comet_identity'
        or plan.get('endpoint') != ENDPOINT or plan.get('output_dir') != OUT
        or type(plan.get('chain_id')) is not int or plan.get('chain_id') != 1 or plan.get('proxy') != PROXY or plan.get('implementation_slot') != SLOT
        or encoded(plan.get('resource_limits')) != encoded(CAPS)
        or encoded(plan.get('request_manifest')) != encoded(build_manifest())
        or plan.get('runtime') != runtime_identity() or plan.get('allocation') != ALLOCATION
        or encoded(plan.get('claims')) != encoded(dict(source_equivalence=False,eligibility=False,economics=False))):
        raise Refusal('frozen_scope_or_runtime')
    pins = plan.get('source_pins')
    required = {SOURCE:65536,TEST:65536,HELPER['path']:65536}
    if (not isinstance(pins,list) or len(pins) != 3
        or any(not isinstance(p,dict) for p in pins)
        or {p.get('path') for p in pins} != set(required)):
        raise Refusal('exact_source_test_helper_pins')
    for pin in pins:
        check_pin(pin,required[pin['path']])
        if pin['path'] == HELPER['path'] and pin['sha256'] != HELPER['sha256']:
            raise Refusal('fixed_helper_pin')
    check_pin(ALLOCATION,16384)
    if (ROOT / OUT).is_symlink():
        raise Refusal('symlink_output')
    return plan


@contextlib.contextmanager
def hard_timeout(seconds):
    def expired(signum,frame):
        raise TimeoutError('hard_deadline')
    previous = signal.signal(signal.SIGALRM,expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL,max(0.000001,seconds))
    began = time.monotonic()
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,max(0.000001,old_timer[0]-(time.monotonic()-began)),old_timer[1])


def publish(out,name,value,cap):
    body = encoded(value)+b'\n'
    if len(body) > cap:
        raise Refusal('publication_byte_cap')
    used = {}
    for path in out.iterdir():
        if path.is_file() and (path.name.endswith('.json') or path.name.endswith('.json.pending')):
            st = path.stat()
            used[st.st_dev,st.st_ino] = st.st_size
    controls = sum(size for key,size in used.items())
    # Projection has its own allowance; controls reserve terminal space up front.
    if name != 'projection.json':
        projection = out / 'projection.json'
        if projection.exists():
            controls -= projection.stat().st_size
        if controls+len(body) > CAPS['controls_bytes']:
            raise Refusal('control_total_cap')
    pending = out / (name+'.pending')
    with pending.open('xb') as handle:
        handle.write(body); handle.flush(); os.fsync(handle.fileno())
    try:
        os.link(pending,out / name)
    finally:
        pending.unlink()


class Trace:
    """B/D/E frames: begin JSON, exact body chunk, end JSON. One inode only."""
    def __init__(self,out):
        self.out = out
        self.path = out / 'responses.frames.pending'
        self.handle = self.path.open('xb')
        self.handle.write(MAGIC); self.handle.flush(); os.fsync(self.handle.fileno())
        self.bytes = len(MAGIC)

    def frame(self,kind,payload):
        if kind not in b'BDE' or len(payload) > CAPS['frame_payload_bytes']:
            raise Refusal('frame_payload_cap')
        raw = bytes([kind])+struct.pack('>I',len(payload))+payload
        if self.bytes+len(raw) > CAPS['raw_bytes']:
            raise Refusal('raw_total_cap')
        self.handle.write(raw); self.handle.flush(); os.fsync(self.handle.fileno())
        self.bytes += len(raw)

    def finish(self):
        self.handle.close()
        os.link(self.path,self.out / 'responses.frames')
        self.path.unlink()


def finalize_partial(out):
    pending = out / 'responses.frames.pending'
    if pending.exists() and not (out / 'responses.frames').exists():
        os.link(pending,out / 'responses.frames')
        pending.unlink()


def envelope(raw,rpc_id):
    value = helper.decode_json(raw)
    if (not isinstance(value,dict) or value.get('jsonrpc') != '2.0'
        or type(value.get('id')) is not int or value['id'] != rpc_id):
        raise Refusal('rpc_envelope_identity')
    if set(value) == {'jsonrpc','id','error'}:
        error = value['error']
        if (not isinstance(error,dict) or not {'code','message'} <= set(error) <= {'code','message','data'}
            or type(error['code']) is not int or not isinstance(error['message'],str)):
            raise Refusal('rpc_error_schema')
        raise Refusal('rpc_error_no_fallback')
    if set(value) != {'jsonrpc','id','result'}:
        raise Refusal('rpc_result_schema')
    return value['result']


class Identity:
    def __init__(self):
        self.parent = self.implementation = None
        self.proxy_fingerprint = self.implementation_fingerprint = None
        self.final_parent_verified = False

    def accept(self,index,value):
        if index == 0:
            if value != '0x1':
                raise Refusal('wrong_chain')
        elif index == 1:
            helper.header(value)
            self.parent = value
        elif index in (2,4):
            code = helper.hex_bytes(value)
            if not code:
                raise Refusal('empty_runtime_code')
            result = dict(runtime_bytes=len(code),runtime_sha256=sha(code))
            if index == 2:
                self.proxy_fingerprint = result
            else:
                self.implementation_fingerprint = result
        elif index == 3:
            self.implementation = helper.address(value)
        elif index == 5:
            helper.header(value)
            if encoded(value) != encoded(self.parent):
                raise Refusal('original_header_changed')
            self.final_parent_verified = True

    def projection(self,plan_sha,trace_sha):
        if not self.final_parent_verified:
            raise Refusal('incomplete_identity')
        return dict(schema='comet-identity-v1-projection',status='identity_fingerprints_available',
            plan_sha256=plan_sha,raw_sha256=trace_sha,chain_id=1,proxy=PROXY,
            parent_identity=helper.header(self.parent),complete_header_sha256=sha(encoded(self.parent)),
            implementation_slot=SLOT,implementation=self.implementation,
            proxy_runtime=self.proxy_fingerprint,implementation_runtime=self.implementation_fingerprint,
            source_equivalence=False,eligibility=False,economics=False,
            limitations=['provider_asserted_canonicality_not_independent_consensus',
                'no_header_hash_recomputation_or_source_deployed_equivalence',
                'identity_at_selected_parent_not_future_upgrade_proof'])


def transport(request,cap,timeout,emit,connection_factory=http.client.HTTPSConnection):
    """Direct TLS only; SIGALRM covers DNS, headers and a drip-fed body."""
    connection = None
    total = 0
    buffered = bytearray()
    def retain(body):
        buffered.extend(body)
        while len(buffered)>=4096:
            chunk=bytes(buffered[:4096]); del buffered[:4096]
            emit(chunk)
    def flush():
        if buffered:
            chunk=bytes(buffered); buffered.clear(); emit(chunk)
    with hard_timeout(timeout):
        try:
            connection = connection_factory('ethereum-rpc.publicnode.com',timeout=timeout,
                                            context=ssl.create_default_context())
            connection.request('POST','/',body=encoded(request),headers={
                'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity'})
            response = connection.getresponse()
            length = response.getheader('Content-Length')
            if response.getheader('Content-Encoding') not in (None,'identity'):
                raise Refusal('unsupported_content_encoding')
            if length is not None and (not re.fullmatch('[0-9]+',length) or int(length)>cap):
                raise Refusal('response_content_length_cap')
            status = response.status
            while total < cap:
                try:
                    body = response.read1(min(4096,cap-total))
                except http.client.IncompleteRead as exc:
                    prefix = exc.partial
                    if isinstance(prefix,bytes) and prefix:
                        retain(prefix[:cap-total])
                    raise Refusal('incomplete_response_prefix_retained') from None
                if not isinstance(body,bytes) or len(body)>min(4096,cap-total):
                    raise Refusal('transport_read_contract')
                if not body:
                    if length is not None and total != int(length):
                        raise Refusal('response_length_mismatch')
                    flush()
                    return status,total
                retain(body)
                total += len(body)
            # Never overread merely to prove EOF; exact-cap bodies are unavailable.
            raise Refusal('response_cap_eof_unproven')
        finally:
            flush()
            if connection is not None:
                connection.close()


def replay(path,require_complete=True):
    """Reconstruct exact raw bodies, enforce requests, then recompute identity."""
    if path.is_symlink() or path.stat().st_size > CAPS['raw_bytes']:
        raise Refusal('raw_replay_cap')
    state = Identity()
    bodies = []
    active = None
    manifest = build_manifest()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        magic = handle.read(len(MAGIC)); digest.update(magic)
        if magic != MAGIC:
            raise Refusal('raw_magic')
        while True:
            head = handle.read(5); digest.update(head)
            if not head:
                break
            if len(head)!=5:
                if not require_complete:
                    break
                raise Refusal('truncated_frame_header')
            kind,length = head[0],struct.unpack('>I',head[1:])[0]
            if length > CAPS['frame_payload_bytes']:
                raise Refusal('replay_frame_cap')
            payload = handle.read(length); digest.update(payload)
            if len(payload)!=length:
                if not require_complete:
                    break
                raise Refusal('truncated_frame_payload')
            if kind == ord('B'):
                if active is not None or len(bodies)>=6:
                    raise Refusal('raw_request_order')
                meta = helper.decode_json(payload)
                index = len(bodies)
                expected = dict(jsonrpc='2.0',id=index+1,
                    **resolve(manifest[index],state.parent or {},state.implementation))
                if meta.get('request') != expected or meta.get('cap') != CAPS['response_bytes'][index]:
                    raise Refusal('raw_request_manifest')
                active = dict(meta=meta,body=bytearray())
            elif kind == ord('D'):
                if active is None or len(active['body'])+length > active['meta']['cap']:
                    raise Refusal('raw_body_cap')
                active['body'].extend(payload)
            elif kind == ord('E'):
                if active is None:
                    raise Refusal('raw_end_without_begin')
                end = helper.decode_json(payload)
                body = bytes(active['body'])
                if end.get('response_bytes') != len(body) or end.get('response_sha256') != sha(body):
                    raise Refusal('raw_body_identity')
                if end.get('outcome') != 'received' or end.get('http_status') != 200:
                    if require_complete:
                        raise Refusal('raw_failed_request')
                    return state,bodies,digest.hexdigest()
                state.accept(len(bodies),envelope(body,len(bodies)+1))
                bodies.append(body); active = None
            else:
                raise Refusal('unknown_frame_kind')
    if require_complete and (active is not None or len(bodies)!=6 or not state.final_parent_verified):
        raise Refusal('raw_incomplete')
    return state,bodies,digest.hexdigest()


def worker(plan_sha,out,deadline):
    trace = None
    attempts = total = 0
    status,reason = 'unavailable',None
    try:
        verify(plan_sha)
        trace = Trace(out)
        state = Identity()
        for index,item in enumerate(build_manifest()):
            verify(plan_sha)
            remain = deadline-time.monotonic()
            if remain<=0:
                raise Refusal('run_deadline')
            request = dict(jsonrpc='2.0',id=index+1,
                **resolve(item,state.parent or {},state.implementation))
            cap = CAPS['response_bytes'][index]
            trace.frame(ord('B'),encoded(dict(request=request,cap=cap,
                admitted_ns=time.time_ns(),dispatch_attempted=None)))
            attempts += 1
            body = bytearray()
            start = time.monotonic()
            def emit(chunk):
                nonlocal total
                if not isinstance(chunk,bytes) or len(body)+len(chunk)>cap:
                    raise Refusal('per_response_body_cap')
                if total+len(chunk)>CAPS['cumulative_body_bytes']:
                    raise Refusal('cumulative_body_cap')
                trace.frame(ord('D'),chunk)
                body.extend(chunk); total += len(chunk)
            code = None
            outcome = 'received'
            try:
                code,count = transport(request,cap,min(10,remain),emit)
                if count!=len(body) or code!=200:
                    raise Refusal('http_status_or_count')
                if time.monotonic()-start>min(10,remain):
                    raise Refusal('request_deadline')
            except Exception as exc:
                outcome = 'timeout' if isinstance(exc,TimeoutError) else (
                    str(exc) if isinstance(exc,Refusal) else 'transport_failure')
            trace.frame(ord('E'),encoded(dict(http_status=code,response_bytes=len(body),
                response_sha256=sha(body),outcome=outcome,receipt_ns=time.time_ns())))
            if outcome!='received':
                raise Refusal(outcome)
            state.accept(index,envelope(bytes(body),index+1))
        trace.finish(); trace = None
        decoded,bodies,trace_sha = replay(out / 'responses.frames')
        if encoded(decoded.projection(plan_sha,trace_sha)) != encoded(state.projection(plan_sha,trace_sha)):
            raise Refusal('raw_reproduction_mismatch')
        verify(plan_sha)
        publish(out,'projection.json',decoded.projection(plan_sha,trace_sha),CAPS['projection_bytes'])
        verify(plan_sha)
        status = 'identity_fingerprints_available'
    except BaseException as exc:
        reason = str(exc) if isinstance(exc,Refusal) else ('timeout' if isinstance(exc,TimeoutError) else 'bounded_worker_failure')
    finally:
        if trace is not None:
            trace.handle.close()
        finalize_partial(out)
        try:
            verify(plan_sha)
        except Exception:
            status,reason = 'unavailable','post_run_pin_failure'
        raw = out / 'responses.frames'
        raw_identity = None
        if raw.exists():
            content = bounded(raw,CAPS['raw_bytes'])
            raw_identity = dict(bytes=len(content),sha256=sha(content))
        publish(out,'terminal.json',dict(schema='comet-identity-v1-terminal',status=status,
            reason=reason,plan_sha256=plan_sha,requests_attempted=attempts,
            request_attempts_meaning='transport_helper_invocations_not_proven_wire_dispatches',
            total_response_bytes=total,raw=raw_identity,source_equivalence=False,eligibility=False,economics=False),4096)


def _run(plan_sha,began):
    plan = verify(plan_sha)
    out = ROOT / OUT
    out.mkdir(parents=True,exist_ok=False)
    publish(out,'claim.json',dict(schema='comet-identity-v1-claim',plan_sha256=plan_sha,
        source_pins=plan['source_pins'],claimed_ns=time.time_ns(),manifest_sha256=sha(encoded(build_manifest())),
        source_equivalence=False,eligibility=False,economics=False),4096)
    process = multiprocessing.get_context('fork').Process(target=worker,args=(plan_sha,out,began+72))
    started = False
    supervisor_failure = None
    try:
        process.start(); started = True
        process.join(max(0,began+73-time.monotonic()))
    except TimeoutError:
        # Do not swallow the supervisor's absolute hard deadline.
        raise
    except BaseException:
        # A failed spawn or interrupted wait must still retain a terminal receipt.
        supervisor_failure = 'spawn_or_supervisor_wait_failure'
    finally:
        if started and process.is_alive():
            process.kill(); process.join(timeout=0.5)
    finalize_partial(out)
    if not (out / 'terminal.json').exists():
        publish(out,'terminal.json',dict(schema='comet-identity-v1-terminal',status='unavailable',
            reason='worker_deadline_or_exit_without_terminal',plan_sha256=plan_sha,
            worker_exitcode=process.exitcode,requests_attempted=None,total_response_bytes=None,
            raw_partial_retained=(out / 'responses.frames').exists(),
            source_equivalence=False,eligibility=False,economics=False),4096)
    terminal = helper.decode_json(bounded(out / 'terminal.json',4096))
    pins_valid = True
    try:
        verify(plan_sha)
    except Exception:
        pins_valid = False
    ok = pins_valid and supervisor_failure is None and terminal['status']=='identity_fingerprints_available' and process.exitcode==0
    publish(out,'supervisor.json',dict(schema='comet-identity-v1-supervisor',plan_sha256=plan_sha,
        worker_exitcode=process.exitcode,terminal_sha256=sha(bounded(out / 'terminal.json',4096)),
        elapsed_seconds=time.monotonic()-began,status='identity_fingerprints_available' if ok else 'unavailable',
        source_pins_verified=pins_valid,reason=supervisor_failure if pins_valid else 'post_supervisor_pin_failure',
        source_equivalence=False,eligibility=False,economics=False),2048)
    return ok


def run(plan_sha):
    began = time.monotonic()
    with hard_timeout(75):
        return _run(plan_sha,began)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    if not args.run:
        print(encoded(dict(status='dry',network_requests=0,requests_scheduled=6,
            writes=0,source_equivalence=False,eligibility=False,economics=False)).decode())
        return
    try:
        ok = run(args.plan_sha256)
        print(encoded(dict(status='identity_fingerprints_available' if ok else 'unavailable',
            source_equivalence=False,eligibility=False,economics=False)).decode())
        if not ok:
            raise SystemExit(1)
    except (Exception,KeyboardInterrupt):
        print('{"status":"unavailable","source_equivalence":false,"eligibility":false,"economics":false}')
        raise SystemExit(1) from None


if __name__=='__main__':
    main()
