"""One fixed public historical-hint lookup for the selected Aave oracle prefix."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import resource
import sys
import time
import types
from Crypto.Hash import keccak

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE, TEST = 'scripts/aave_hint_access_v1.py', 'tests/test_aave_hint_access_v1.py'
BASE = 'reports/aave-hint-access-v1/'
PLAN, DESIGN, OUT = (BASE+x for x in ('plan.json', 'design.txt', 'run-v1'))
ALLOCATION = 'reports/experiment-storage/aave-hint-access-allocation-v1.json'
HELPER = 'scripts/aave_state_transition_v1.py'
HELPER_SHA = '9bb451c71b62a6ee67447cf991c795877e3431b6659dc1a8344345455c9cedd1'
PARENT_PLAN_SHA = '45af227ecef9bc5bc1f409bff17f8dc632340ad0f55b3f68d6208e01f0d3407e'
PREFIX_REQUEST = 'reports/aave-state-transition-v1/run-v1/raw/11.request.json'
HOST = 'mev-share.flashbots.net'
LOW, HIGH, LIMIT = 26103136, 26103141, 100
PREFIX_HASH = '0xf04ac291f6537bd58059aa48decd78e82291bc7d53a34a8185fe3e7d051387d2'
SLOTS = [('info', '/api/v1/history/info', 4096),
         ('history', '/api/v1/history?blockStart=26103136&blockEnd=26103141&limit=100&offset=0', 262144)]
CAPS = dict(requests=2, request_seconds=20, work_seconds=80, wall_seconds=90,
            body_bytes=266242, raw_bytes=360448, projection_bytes=16384,
            cpu_seconds=20, ram_bytes=536870912)


class Refusal(Exception):
    pass


def read(path, cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as f: raw = f.read(cap+1)
    if len(raw) > cap: raise Refusal('file_cap')
    return raw


def sha(raw): return hashlib.sha256(raw).hexdigest()


helper_raw = read(ROOT/HELPER, 32768)
if sha(helper_raw) != HELPER_SHA: raise Refusal('immutable_helper')
s = types.ModuleType('hint_state_helpers'); s.__file__ = str(ROOT/HELPER)
exec(compile(helper_raw, s.__file__, 'exec'), s.__dict__)
h, encode, decode = s.h, s.encode, s.decode


def reason(exc):
    return str(exc)[:160] if isinstance(exc, Refusal) else s.reason(exc)


def nonnegative(value):
    if type(value) is not int or value < 0: raise Refusal('nonnegative_integer_required')
    return value


def inputs():
    s.verify(PARENT_PLAN_SHA)
    terminal = decode(read(ROOT/s.OUT/'terminal.json', 4096))
    projection = decode(read(ROOT/s.OUT/'projection.json', 16384))
    if terminal['status'] != 'paired_views_complete' or terminal['error'] is not None:
        raise Refusal('parent_not_admitted')
    request = decode(read(ROOT/PREFIX_REQUEST, 8192))
    prefix = request['request']['params'][0]['blockStateCalls'][0]['calls'][0]
    double_hash = '0x'+keccak.new(digest_bits=256, data=bytes.fromhex(PREFIX_HASH[2:])).hexdigest()
    return dict(prefix=prefix, hash=PREFIX_HASH, double_hash=double_hash,
                block_timestamp=int(projection['target_context']['time'],16))


def info_result(value):
    required = ('count','minBlock','maxBlock','minTimestamp','maxTimestamp','maxLimit')
    if not isinstance(value, dict) or not set(required) <= set(value): raise Refusal('info_schema')
    result = {key:nonnegative(value[key]) for key in required}
    if not result['minBlock'] <= LOW <= HIGH <= result['maxBlock']:
        raise Refusal('fixed_range_outside_reported_history')
    if result['maxLimit'] < LIMIT or result['minTimestamp'] > result['maxTimestamp']:
        raise Refusal('info_limit_or_time')
    return result


def optional_hex(value, size=None):
    return None if value is None else h.hexdata(value, size)


def history_result(value, setup):
    if not isinstance(value,list) or len(value) > LIMIT: raise Refusal('history_array_cap')
    matches = []
    for i, row in enumerate(value):
        if not isinstance(row,dict) or not {'block','timestamp','hint'} <= set(row): raise Refusal('history_row_schema')
        block, timestamp = nonnegative(row['block']), nonnegative(row['timestamp'])
        if not LOW <= block <= HIGH: raise Refusal('history_outside_fixed_range')
        hint = row['hint']
        if not isinstance(hint,dict): raise Refusal('hint_schema')
        root_hash = h.hexdata(hint.get('hash'),32)
        txs = hint.get('txs')
        if txs is None: txs = []
        if not isinstance(txs,list) or len(txs) > 128: raise Refusal('hint_transactions_schema')
        kinds = ['root_double_hash'] if root_hash == setup['double_hash'] else []
        tx_matches = []
        for j, tx in enumerate(txs):
            if not isinstance(tx,dict): raise Refusal('hint_transaction_schema')
            tx_hash, to, data = (optional_hex(tx.get('hash'),32), optional_hex(tx.get('to'),20),
                                 optional_hex(tx.get('callData')))
            identity = tx_hash == setup['hash']
            content = to == setup['prefix']['to'] and data == setup['prefix']['input']
            if identity or content:
                if identity and 'transaction_hash' not in kinds: kinds.append('transaction_hash')
                if content and 'to_and_full_calldata' not in kinds: kinds.append('to_and_full_calldata')
                tx_matches.append(dict(index=j,identity_match=identity,content_match=content,
                    shared_fields=sorted(tx), calldata_bytes=len(data[2:])//2 if data is not None else None))
        if kinds:
            matches.append(dict(row_index=i,root_hash=root_hash,kind=kinds,block=block,timestamp=timestamp,
                target_timestamp_minus_hint_seconds=setup['block_timestamp']-timestamp,
                metadata_block_precedes_target=block < HIGH, matched_transactions=tx_matches))
    return dict(returned_rows=len(value),limit_reached=len(value)==LIMIT,matches=matches,
        identity_match_rows=sum(any(k in x['kind'] for k in ('root_double_hash','transaction_hash')) for x in matches),
        content_match_rows=sum('to_and_full_calldata' in x['kind'] for x in matches),
        broader_absence_established=False,live_delivery_latency_measured=False,
        actual_auction_path_identified=False,obtainable_inclusion_established=False,economics=False)


def collect(get, setup):
    info = info_result(get(*SLOTS[0]))
    result = history_result(get(*SLOTS[1]),setup)
    return dict(schema='aave-hint-access-projection-v1',status='bounded_history_complete',
                history_info=info,block_range=[LOW,HIGH],limit=LIMIT,offset=0,
                prefix_transaction_hash=setup['hash'],expected_double_hash=setup['double_hash'],**result)


def body_length(headers):
    lengths=[value.strip() for key,value in headers if key.lower()=='content-length']
    encodings=[value.strip().lower() for key,value in headers if key.lower()=='transfer-encoding']
    if encodings:
        if lengths or encodings!=['chunked']: raise Refusal('ambiguous_response_framing')
        return None
    if len(lengths)!=1 or not lengths[0] or len(lengths[0])>12 or any(c not in '0123456789' for c in lengths[0]):
        raise Refusal('missing_or_invalid_content_length')
    return int(lengths[0])


class Archive:
    def __init__(self,path,started,replay=False):
        self.path,self.started,self.replay = path,started,replay
        self.attempts=self.body_bytes=self.raw_bytes=0
        if replay:
            expected={str(i)+'.'+kind for i in (1,2) for kind in ('request.json','headers.json','body','receipt.json')}
            if {p.name for p in path.iterdir()} != expected: raise Refusal('raw_manifest')
        else: path.mkdir(exist_ok=False)

    def save(self,name,raw,cap):
        if len(raw)>cap or self.raw_bytes+len(raw)>CAPS['raw_bytes']: raise Refusal('raw_cap')
        with (self.path/name).open('xb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        self.raw_bytes+=len(raw)

    def get(self,name,path,cap):
        i=self.attempts
        if i>=2 or (name,path,cap)!=SLOTS[i]: raise Refusal('request_slot')
        stem=str(i+1)
        request=dict(name=name,method='GET',host=HOST,path=path,headers={'Accept':'application/json','Accept-Encoding':'identity'},body=None)
        if self.replay:
            raw=[read(self.path/(stem+'.'+kind),limit) for kind,limit in
                 [('request.json',2048),('headers.json',2048),('body',cap),('receipt.json',2048)]]
            self.raw_bytes+=sum(map(len,raw));self.body_bytes+=len(raw[2]);self.attempts+=1
            rec=decode(raw[3]);headers=decode(raw[1])
            if decode(raw[0])!=request: raise Refusal('request_identity')
            if (headers.get('status')!=200 or rec.get('http_status')!=200 or rec.get('error') is not None or
                    rec.get('dispatch_attempted') is not True or rec.get('response_bytes')!=len(raw[2]) or
                    rec.get('response_sha256')!=sha(raw[2])): raise Refusal('raw_integrity')
            expected=body_length(headers['headers'])
            if expected is not None and expected!=len(raw[2]): raise Refusal('incomplete_content_length')
            if self.raw_bytes>CAPS['raw_bytes'] or self.body_bytes>CAPS['body_bytes']: raise Refusal('replay_cap')
            return decode(raw[2])
        payload=encode(request)
        if self.raw_bytes+len(payload)+cap+1+4096>CAPS['raw_bytes'] or self.body_bytes+cap+1>CAPS['body_bytes']:
            raise Refusal('reserve_before_dispatch')
        self.save(stem+'.request.json',payload,2048)
        body,code,error,conn=bytearray(),None,None,None
        dispatched=False
        with (self.path/(stem+'.body')).open('xb') as f:
            try:
                seconds=min(CAPS['request_seconds'],CAPS['work_seconds']-(time.monotonic()-self.started))
                if seconds<=0: raise Refusal('work_deadline')
                with h.alarm(seconds):
                    conn=http.client.HTTPSConnection(HOST,timeout=seconds)
                    dispatched=True;self.attempts+=1
                    conn.request('GET',path,headers=request['headers'])
                    response=conn.getresponse();code=response.status
                    pairs=response.getheaders()
                    header=encode(dict(status=code,headers=pairs))
                    self.save(stem+'.headers.json',header[:2048],2048)
                    if len(header)>2048: raise Refusal('header_cap_prefix_retained')
                    if response.getheader('Content-Encoding','identity').lower() not in ('identity',''):
                        raise Refusal('encoded_body_refused')
                    expected=body_length(pairs)
                    while True:
                        part=response.read1(min(8192,cap+1-len(body)))
                        if not part: break
                        f.write(part);f.flush();os.fsync(f.fileno());body.extend(part)
                        self.body_bytes+=len(part);self.raw_bytes+=len(part)
                        if len(body)>cap: raise Refusal('body_cap_sentinel_retained')
                    if expected is not None and len(body)!=expected: raise Refusal('incomplete_content_length')
                    if code!=200: raise Refusal('http_status')
            except Exception as exc: error=reason(exc)
            finally:
                if conn is not None: conn.close()
        self.save(stem+'.receipt.json',encode(dict(error=error,http_status=code,dispatch_attempted=dispatched,
            response_bytes=len(body),response_sha256=sha(body),ended_ns=time.time_ns())),2048)
        if error: raise Refusal(error)
        return decode(bytes(body))


def verify(digest):
    raw=read(ROOT/PLAN,16384)
    if sha(raw)!=digest: raise Refusal('plan_sha_required')
    plan=decode(raw)
    required={SOURCE,TEST,DESIGN,ALLOCATION,HELPER,s.PLAN,PREFIX_REQUEST,s.OUT+'/projection.json',s.OUT+'/terminal.json'}
    if (plan.get('status')!='frozen' or plan.get('caps')!=CAPS or plan.get('slots')!=[list(x) for x in SLOTS] or
            plan.get('host')!=HOST or plan.get('runtime')!=h.runtime() or plan.get('output_dir')!=OUT): raise Refusal('frozen_scope')
    pins=plan.get('pins',[])
    if len(pins)!=len(required) or {p.get('path') for p in pins}!=required: raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],65536)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']: raise Refusal('source_or_input_pin')
    if sum(p['bytes'] for p in pins if p['path'] in (SOURCE,TEST,DESIGN))+len(raw)>65536: raise Refusal('source_package_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)): raise Refusal('output_symlink')
    return plan


def replay(path,setup):
    archive=Archive(path,time.monotonic(),True)
    result=collect(archive.get,setup)
    if archive.attempts!=2: raise Refusal('unused_raw')
    return result,archive.body_bytes,archive.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None
    status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        plan,setup=verify(digest),inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=plan['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=Archive(out/'raw',started)
                result=collect(capture.get,setup)
                check,body,raw=replay(out/'raw',setup)
                if result!=check or body!=capture.body_bytes or raw!=capture.raw_bytes: raise Refusal('exact_replay')
                verify(digest)
                result['plan_sha256']=digest
                s.o.publish(out,'projection.json',result,CAPS['projection_bytes']);status='bounded_history_complete'
        except BaseException as exc: error=reason(exc)
        finally:
            try: verify(digest)
            except Exception: status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='bounded_history_complete' and error is None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group();group.add_argument('--run',action='store_true');group.add_argument('--replay',action='store_true')
    parser.add_argument('--plan-sha256');args=parser.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw',inputs())
        print(encode(dict(status=result['status'],identity_match_rows=result['identity_match_rows'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run: print('dry: zero requests;zero outputs;two fixed anonymous historical GETs');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__': raise SystemExit(main())
