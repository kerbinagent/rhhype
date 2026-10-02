"""One historical liquidation control omitting the preceding transaction."""
import argparse
import copy
import hashlib
import os
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/aave_ordered_control_v1.py'
TEST = 'tests/test_aave_ordered_control_v1.py'
BASE = 'reports/aave-ordered-control-v1/'
PLAN, DESIGN, OUT = BASE+'plan.json', BASE+'design.txt', BASE+'run-v1'
ALLOCATION = 'reports/experiment-storage/aave-ordered-control-allocation-v1.json'
HELPER = 'scripts/aave_ordered_replay_v1.py'
HELPER_SHA = 'bf520660bf886bbdf71ed92b9b8d42b9ad078fc6472304a4a532a610333478ce'
POSITIVE_PLAN_SHA = 'a07214cb94cacb76a340e01f4025206b2d1af70a28da89aeb72921974ede843c'
POSITIVE_RAW = 'reports/aave-ordered-replay-v1/run-v1/responses.frames'
POSITIVE_RAW_SHA = 'e71b33fb3d824b73688312cf949ff57812a626200f722046d2186712fddbc93e'
CAPS = dict(requests=5, body_bytes=163840, raw_bytes=196608, request_bytes=8192,
            request_seconds=20, wall_seconds=120, work_seconds=110, cpu_seconds=20,
            ram_bytes=536870912, total_call_gas=1200000)
SLOTS = [('chain', 4096), ('parent', 32768), ('without_prefix', 65536),
         ('parent_recheck', 32768), ('event_recheck', 32768)]


class Refusal(Exception):
    pass


def read(path, cap):
    if path.is_symlink() or not path.is_file():
        raise Refusal('nonregular_file')
    with path.open('rb') as f:
        raw = f.read(cap+1)
    if len(raw) > cap:
        raise Refusal('file_cap')
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


_raw = read(ROOT/HELPER, 32768)
if sha(_raw) != HELPER_SHA:
    raise Refusal('immutable_helper')
o = types.ModuleType('aave_control_helpers')
o.__file__ = str(ROOT/HELPER)
exec(compile(_raw, o.__file__, 'exec'), o.__dict__)
del _raw
h, encode, decode = o.h, o.encode, o.decode


def inputs():
    o.verify(POSITIVE_PLAN_SHA)
    terminal = decode(read(ROOT/o.OUT/'terminal.json', 4096))
    if terminal['status'] != 'ordered_receipts_matched' or terminal['error'] is not None:
        raise Refusal('positive_run_not_admitted')
    records, pin, _ = o.decode_frames(ROOT/POSITIVE_RAW)
    if pin['sha256'] != POSITIVE_RAW_SHA:
        raise Refusal('positive_raw_pin')
    setup = o.load_baseline()
    original = next(r['begin']['request']['params'] for r in records if r['begin']['name'] == 'simulate')
    params = copy.deepcopy(original)
    calls = params[0]['blockStateCalls'][0]['calls']
    if len(calls) != 2:
        raise Refusal('positive_call_count')
    params[0]['blockStateCalls'][0]['calls'] = [calls[1]]
    if h.quantity(calls[1]['gas']) > CAPS['total_call_gas']:
        raise Refusal('control_gas_cap')
    setup['original_params'], setup['params'] = original, params
    setup['manifest'] = [
        ('chain', 'eth_chainId', []),
        ('parent', 'eth_getBlockByNumber', [setup['parent']['number'], False]),
        ('without_prefix', 'eth_simulateV1', params),
        ('parent_recheck', 'eth_getBlockByNumber', [setup['parent']['number'], False]),
        ('event_recheck', 'eth_getBlockByNumber', [setup['block']['number'], False]),
    ]
    return setup


def error_string(data):
    raw = bytes.fromhex(h.hexdata(data)[2:])
    if not raw.startswith(bytes.fromhex('08c379a0')):
        return None
    if len(raw) < 68 or int.from_bytes(raw[4:36], 'big') != 32:
        raise Refusal('revert_string_offset')
    size = int.from_bytes(raw[36:68], 'big')
    padded = (size+31)//32*32
    if size > 256 or len(raw) != 68+padded or any(raw[68+size:]):
        raise Refusal('revert_string_size_or_padding')
    return raw[68:68+size].decode('utf-8', errors='strict')


def result_projection(value, setup):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise Refusal('simulation_blocks')
    block = value[0]
    for field, expected in o.context(setup['block']).items():
        aliases = {'time': ('timestamp', 'time'), 'feeRecipient': ('miner', 'feeRecipient'),
                   'prevRandao': ('mixHash', 'prevRandao')}.get(field, (field,))
        present = [k for k in aliases if k in block]
        if not present:
            raise Refusal('simulation_context_missing')
        for key in present:
            actual = (h.hexdata(block[key], 20 if field == 'feeRecipient' else 32)
                      if field in ('feeRecipient', 'prevRandao') else hex(h.quantity(block[key])))
            if actual != expected:
                raise Refusal('simulation_context_changed')
    calls = block.get('calls')
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise Refusal('simulation_calls')
    call = calls[0]
    status, gas = h.quantity(call.get('status')), h.quantity(call.get('gasUsed'))
    original_call = setup['params'][0]['blockStateCalls'][0]['calls'][0]
    if status not in (0, 1) or not 21000 <= gas <= h.quantity(original_call['gas']):
        raise Refusal('simulation_status_or_gas')
    data = h.hexdata(call.get('returnData'))
    if len(data) > 4098:
        raise Refusal('return_data_cap')
    # The API's failed-call schema can omit logs; successful calls require it.
    logs = call.get('logs', [] if status == 0 else None)
    if not isinstance(logs, list) or len(logs) > 512 or (status == 0 and logs):
        raise Refusal('simulation_logs')
    if status == 1 and call.get('error') is not None:
        raise Refusal('successful_call_with_error')
    error = call.get('error')
    if status == 0 and (not isinstance(error, dict) or not error or
            ('message' in error and not isinstance(error['message'], str)) or
            ('code' in error and type(error['code']) is not int)):
        raise Refusal('failed_call_error_schema')
    contents = [o.log_content(x) for x in logs]
    for row in contents:
        if row['address'] == o.ETH:
            o.transfer(row)
    regular = [x for x in contents if x['address'] != o.ETH]
    target = setup['target_receipt']
    matched = status == 1 and gas == h.quantity(target['gasUsed']) and regular == [o.log_content(x) for x in target['logs']]
    outcome = ('reverted_without_prefix' if status == 0 else
               'same_receipt_reproduced_without_prefix' if matched else 'succeeded_with_different_effects')
    return dict(schema='aave-ordered-control-projection-v1', status='control_complete',
        outcome=outcome, target=o.SPEC['target'], omitted_transaction=o.SPEC['prefix'],
        parent=o.c.header(setup['parent']), target_block=o.c.header(setup['block']),
        simulation_call_status=status, simulated_gas_used=str(gas),
        return_data=data, abi_error_string=error_string(data) if status == 0 else None,
        regular_log_count=len(regular), same_receipt_matched=matched,
        single_mutation='remove_original_prefix_call_only', positive_raw_sha256=POSITIVE_RAW_SHA,
        hypothetical_gas_not_spent=True, provider_assertions_only=True,
        oracle_causality_established=False, economics=False, closed_cash=False)


def collect(rpc, setup):
    results = {}
    for name, method, params in setup['manifest']:
        value = rpc(name, method, params)
        if name == 'chain' and h.quantity(value) != 1:
            raise Refusal('wrong_chain')
        if name in ('parent', 'parent_recheck'):
            o.same_header(value, setup['parent'])
        if name == 'event_recheck':
            o.same_header(value, setup['block'])
            if value.get('transactions', [])[:2] != setup['block']['transactions'][:2]:
                raise Refusal('event_prefix_changed')
        if name == 'without_prefix':
            results = result_projection(value, setup)
    return results


def verify(digest):
    raw = read(ROOT/PLAN, 16384)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    required = {SOURCE, TEST, DESIGN, ALLOCATION, HELPER, o.PLAN, POSITIVE_RAW,
                'reports/aave-ordered-replay-v1/run-v1/terminal.json'}
    if (p.get('status') != 'frozen' or p.get('caps') != CAPS or p.get('output_dir') != OUT or
            p.get('slots') != [list(x) for x in SLOTS] or p.get('runtime') != h.runtime() or
            p.get('positive_plan_sha256') != POSITIVE_PLAN_SHA):
        raise Refusal('frozen_scope')
    pins = p.get('pins', [])
    if len(pins) != len(required) or {x.get('path') for x in pins} != required:
        raise Refusal('pins_schema')
    for pin in pins:
        data = read(ROOT/pin['path'], 131072)
        if len(data) != pin['bytes'] or sha(data) != pin['sha256']:
            raise Refusal('source_or_input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE, TEST, DESIGN)) + len(raw) > 65536:
        raise Refusal('source_package_cap')
    for path in (ROOT/'reports', ROOT/BASE, ROOT/OUT):
        if path.is_symlink():
            raise Refusal('output_symlink')
    return p


def reason(exc):
    if isinstance(exc, (Refusal, o.Refusal, o.c.Refusal, h.Refusal)):
        return str(exc)[:160]
    return type(exc).__name__


class Capture:
    def __init__(self, path, started):
        path.mkdir(exist_ok=False)
        self.path, self.started = path, started
        self.attempts = self.body_bytes = self.raw_bytes = 0

    def save(self, stem, kind, raw, cap):
        if len(raw) > cap or self.raw_bytes + len(raw) > CAPS['raw_bytes']:
            raise Refusal('raw_file_cap')
        with (self.path/(stem+'.'+kind)).open('xb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        self.raw_bytes += len(raw)

    def rpc(self, name, method, params):
        i = self.attempts
        if i >= 5 or SLOTS[i][0] != name:
            raise Refusal('request_slot')
        cap, stem = SLOTS[i][1], '%02d' % (i+1)
        request = dict(jsonrpc='2.0', id=i+1, method=method, params=params)
        payload = encode(dict(name=name, request=request))
        if (self.body_bytes+cap+1 > CAPS['body_bytes'] or
                self.raw_bytes+len(payload)+cap+1+4096 > CAPS['raw_bytes']):
            raise Refusal('reserve_before_dispatch')
        self.save(stem, 'request.json', payload, CAPS['request_bytes'])
        body, code, dispatched, failure = bytearray(), None, False, None
        with (self.path/(stem+'.body')).open('xb') as f:
            def emit(part):
                if len(body)+len(part) > cap+1 or self.body_bytes+len(part) > CAPS['body_bytes']:
                    raise Refusal('body_cap')
                f.write(part)
                f.flush()
                os.fsync(f.fileno())
                body.extend(part)
                self.body_bytes += len(part)
                self.raw_bytes += len(part)

            def headers(status, data):
                nonlocal code
                code = status
                self.save(stem, 'headers.json', data, 2048)

            def dispatch():
                nonlocal dispatched
                self.attempts += 1
                dispatched = True

            try:
                seconds = min(CAPS['request_seconds'], CAPS['work_seconds']-(time.monotonic()-self.started))
                if seconds <= 0:
                    raise Refusal('work_deadline')
                code, count = h.fetch(request, cap, seconds, emit, headers, dispatch)
                if code != 200 or count != len(body):
                    raise Refusal('http_status_or_size')
            except Exception as exc:
                failure = reason(exc)
        self.save(stem, 'receipt.json', encode(dict(error=failure, http_status=code,
            dispatch_attempted=dispatched, response_bytes=len(body), response_sha256=sha(body),
            ended_ns=time.time_ns())), 2048)
        if failure:
            raise Refusal(failure)
        return o.c.rpc_result(bytes(body), i+1, False)


def replay(path, setup):
    index = total = raw_total = 0
    files = {p.name for p in path.iterdir()}
    expected_files = {('%02d.' % i)+kind for i in range(1, 6)
                      for kind in ('request.json', 'headers.json', 'body', 'receipt.json')}
    if files != expected_files:
        raise Refusal('raw_file_manifest')

    def rpc(name, method, params):
        nonlocal index, total, raw_total
        index += 1
        cap, stem = SLOTS[index-1][1], '%02d' % index
        request_raw = read(path/(stem+'.request.json'), CAPS['request_bytes'])
        header_raw = read(path/(stem+'.headers.json'), 2048)
        body = read(path/(stem+'.body'), cap)
        receipt_raw = read(path/(stem+'.receipt.json'), 2048)
        request, headers, receipt = decode(request_raw), decode(header_raw), decode(receipt_raw)
        raw_total += sum(map(len, (request_raw, header_raw, body, receipt_raw)))
        total += len(body)
        if raw_total > CAPS['raw_bytes'] or total > CAPS['body_bytes']:
            raise Refusal('raw_or_body_cap')
        if request != dict(name=name, request=dict(jsonrpc='2.0', id=index, method=method, params=params)):
            raise Refusal('request_manifest')
        if (headers.get('status') != 200 or receipt.get('error') is not None or
                receipt.get('http_status') != 200 or receipt.get('dispatch_attempted') is not True or
                receipt.get('response_bytes') != len(body) or receipt.get('response_sha256') != sha(body)):
            raise Refusal('incomplete_rpc')
        return o.c.rpc_result(body, index, False)

    result = collect(rpc, setup)
    return result, total, raw_total


def run(digest):
    started, capture = time.monotonic(), None
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        p, setup = verify(digest), inputs()
        out = ROOT/OUT
        out.mkdir(exist_ok=False)
        o.publish(out, 'claim.json', dict(plan_sha256=digest, started_ns=time.time_ns(), pins=p['pins']))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture = Capture(out/'raw', started)
                result = collect(capture.rpc, setup)
                reproduced, body, raw = replay(out/'raw', setup)
                if encode(result) != encode(reproduced) or body != capture.body_bytes or raw != capture.raw_bytes:
                    raise Refusal('raw_replay_mismatch')
                verify(digest)
                result.update(plan_sha256=digest, requests_attempted=capture.attempts)
                o.publish(out, 'projection.json', result)
                status = 'control_complete'
        except BaseException as exc:
            error = reason(exc)
        finally:
            try:
                verify(digest)
            except Exception:
                status, error = 'unavailable', 'final_pin_mismatch'
            o.publish(out, 'terminal.json', dict(status=status, error=error, plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,
                retained_body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,
                elapsed_milliseconds=int((time.monotonic()-started)*1000), ended_ns=time.time_ns(),
                economics=False, closed_cash=False))
    return status == 'control_complete' and error is None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--replay', action='store_true')
    ap.add_argument('--plan-sha256')
    args = ap.parse_args()
    if args.replay:
        verify(args.plan_sha256)
        result, body, raw = replay(ROOT/OUT/'raw', inputs())
        print(encode(dict(outcome=result['outcome'], body_bytes=body, raw_bytes=raw)).decode())
        return 0
    if not args.run:
        print('dry: zero requests;zero outputs;one historical call without its prefix;5RPC maximum')
        return 0
    return 0 if run(args.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
