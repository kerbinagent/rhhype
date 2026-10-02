"""Fixed historical liquidation census and pre-block observability, read-only.

The default is dry. A single run requires a frozen plan and its exact SHA256.
No transaction submission, state overrides, credentials, or profit inference.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import struct
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/aave_liquidation_census_v1.py'
TEST = 'tests/test_aave_liquidation_census_v1.py'
DESIGN = 'reports/aave-liquidation-census-v1/design.txt'
PLAN = 'reports/aave-liquidation-census-v1/plan.json'
OUT = 'reports/aave-liquidation-census-v1/run-v1'
ALLOCATION = 'reports/experiment-storage/aave-liquidation-census-preparation-v1.json'
HELPER = 'scripts/aave_trace_access_v1.py'
HELPER_SHA = '48697649d725daacef637181efea89d7376ea967426e4b1b2db55397c9fde6de'
POOL = '0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2'
PROVIDER = '0x2f39d218133afab8f2b819b1066c7e434ad94e9e'
CAPS = dict(requests=62, response_bytes=65536, body_bytes=1048576,
            raw_bytes=1572864, projection_bytes=131072, controls_bytes=32768,
            request_seconds=12, wall_seconds=240, work_seconds=225,
            cpu_seconds=30, ram_bytes=536870912, events=512, pairs=128)
SPEC = dict(chain_id=1, pool=POOL, provider=PROVIDER, blocks=7200,
            pages=16, blocks_per_page=450, samples=8,
            selection='first8_events_by_block_transaction_log_index_no_replacement',
            endpoint='https://ethereum-rpc.publicnode.com', retries=0, fallbacks=0)
MAGIC = b'AAVE-LIQUIDATION-CENSUS-V1\n'


class Refusal(Exception):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, cap):
    if path.is_symlink() or not path.is_file():
        raise Refusal('nonregular_file')
    with path.open('rb') as f:
        raw = f.read(cap + 1)
    if len(raw) > cap:
        raise Refusal('file_cap')
    return raw


_raw = read(ROOT / HELPER, 32768)
if sha(_raw) != HELPER_SHA:
    raise Refusal('immutable_helper_mismatch')
h = types.ModuleType('aave_census_helpers')
h.__file__ = str(ROOT / HELPER)
exec(compile(_raw, h.__file__, 'exec'), h.__dict__)
del _raw
encode, decode = h.encoded, h.strict_json


def keccak_hex(s):
    from Crypto.Hash import keccak
    return '0x' + keccak.new(digest_bits=256, data=s.encode('ascii')).hexdigest()


TOPIC = keccak_hex('LiquidationCall(address,address,address,uint256,uint256,address,bool)')
HEALTH_SELECTOR = keccak_hex('getUserAccountData(address)')[:10]
PROVIDER_SELECTOR = keccak_hex('ADDRESSES_PROVIDER()')[:10]


def address_word(v):
    v = h.hexdata(v, 32)
    if v[2:26] != '0' * 24:
        raise Refusal('noncanonical_address_word')
    return '0x' + v[26:]


def header(v):
    if not isinstance(v, dict):
        raise Refusal('header_unavailable')
    return dict(number=h.quantity(v.get('number')), hash=h.hexdata(v.get('hash'), 32),
                parentHash=h.hexdata(v.get('parentHash'), 32),
                timestamp=h.quantity(v.get('timestamp')), stateRoot=h.hexdata(v.get('stateRoot'), 32))


def event(v, low, high):
    if not isinstance(v, dict) or v.get('removed') is not False:
        raise Refusal('removed_or_malformed_log')
    if h.hexdata(v.get('address'), 20) != POOL:
        raise Refusal('wrong_pool_log')
    topics = v.get('topics')
    if not isinstance(topics, list) or len(topics) != 4 or h.hexdata(topics[0], 32) != TOPIC:
        raise Refusal('wrong_event_topics')
    data = h.hexdata(v.get('data'), 128)[2:]
    words = ['0x' + data[i:i+64] for i in range(0, 256, 64)]
    received = int(words[3], 16)
    if received not in (0, 1):
        raise Refusal('noncanonical_bool')
    n = h.quantity(v.get('blockNumber'))
    if not low <= n <= high:
        raise Refusal('log_outside_page')
    return dict(block_number=n, block_hash=h.hexdata(v.get('blockHash'), 32),
                transaction_hash=h.hexdata(v.get('transactionHash'), 32),
                transaction_index=h.quantity(v.get('transactionIndex')),
                log_index=h.quantity(v.get('logIndex')),
                collateral=address_word(topics[1]), debt=address_word(topics[2]),
                borrower=address_word(topics[3]), debt_repaid_raw=str(int(words[0], 16)),
                collateral_received_raw=str(int(words[1], 16)),
                liquidator=address_word(words[2]), receive_atoken=bool(received))


def health(v):
    if isinstance(v, dict) and 'rpc_unavailable' in v:
        return dict(available=False, reason='rpc_error', code=v['rpc_unavailable'])
    try:
        raw = h.hexdata(v, 192)[2:]
        x = [int(raw[i:i+64], 16) for i in range(0, 384, 64)]
    except (h.Refusal, TypeError, ValueError):
        return dict(available=False, reason='null_or_malformed_six_word_result')
    return dict(available=True, total_collateral_base_raw=str(x[0]),
                total_debt_base_raw=str(x[1]), available_borrows_base_raw=str(x[2]),
                liquidation_threshold_raw=str(x[3]), ltv_raw=str(x[4]),
                health_factor_wad=str(x[5]),
                debt_positive_and_health_below_one=(x[1] > 0 and x[5] < 10**18))


def receipt(v, selected):
    if v is None or (isinstance(v, dict) and 'rpc_unavailable' in v):
        return dict(available=False, reason='receipt_unavailable')
    if not isinstance(v, dict):
        raise Refusal('receipt_schema')
    for key, expected in [('transactionHash', selected['transaction_hash']),
                          ('blockHash', selected['block_hash'])]:
        if h.hexdata(v.get(key), 32) != expected:
            raise Refusal('receipt_identity')
    if (h.quantity(v.get('blockNumber')) != selected['block_number'] or
            h.quantity(v.get('transactionIndex')) != selected['transaction_index'] or
            h.quantity(v.get('status')) != 1):
        raise Refusal('receipt_block_index_status')
    logs = v.get('logs')
    if not isinstance(logs, list) or len(logs) > 1024:
        raise Refusal('receipt_logs')
    matches = [x for x in logs if isinstance(x, dict) and
               h.quantity(x.get('logIndex')) == selected['log_index']]
    if len(matches) != 1:
        raise Refusal('receipt_event_missing_or_duplicate')
    if event(matches[0], selected['block_number'], selected['block_number']) != selected:
        raise Refusal('receipt_event_mismatch')
    used, price = h.quantity(v.get('gasUsed')), h.quantity(v.get('effectiveGasPrice'))
    return dict(available=True, whole_transaction_gas_used=str(used),
                effective_gas_price_wei=str(price), whole_transaction_fee_wei=str(used * price),
                allocation_to_liquidation='unknown_shared_transaction_cost')


def call_params(data, block_hash):
    return [dict(to=POOL, data=data, gas=hex(1000000)),
            dict(blockHash=block_hash, requireCanonical=True)]


def collect(rpc):
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('wrong_chain')
    anchor = header(rpc('anchor', 'eth_getBlockByNumber', ['finalized', False]))
    end = anchor['number']
    start = end - 7199
    if start < 1:
        raise Refusal('insufficient_chain_history')
    code = rpc('pool_code', 'eth_getCode', [POOL, dict(blockHash=anchor['hash'], requireCanonical=True)])
    h.hexdata(code)
    if len(code) <= 2:
        raise Refusal('empty_pool_code')
    p = rpc('pool_provider', 'eth_call', call_params(PROVIDER_SELECTOR, anchor['hash']))
    if address_word(p) != PROVIDER:
        raise Refusal('pool_provider_mismatch')
    events, seen = [], set()
    page_counts = []
    for page in range(16):
        low = start + 450 * page
        high = low + 449
        rows = rpc('logs_' + str(page), 'eth_getLogs', [dict(address=POOL,
                   fromBlock=hex(low), toBlock=hex(high), topics=[TOPIC])])
        if not isinstance(rows, list):
            raise Refusal('logs_not_list')
        if len(rows) + len(events) > CAPS['events']:
            raise Refusal('event_cap')
        for row in rows:
            e = event(row, low, high)
            key = (e['block_number'], e['log_index'])
            if key in seen:
                raise Refusal('duplicate_log_identity')
            seen.add(key)
            events.append(e)
        page_counts.append(len(rows))
    events.sort(key=lambda e: (e['block_number'], e['transaction_index'], e['log_index']))
    first = header(rpc('range_start', 'eth_getBlockByNumber', [hex(start), False]))
    if first['number'] != start or first['timestamp'] > anchor['timestamp']:
        raise Refusal('range_start_header')
    pairs = Counter((e['collateral'], e['debt']) for e in events)
    if len(pairs) > CAPS['pairs']:
        raise Refusal('pair_cap')
    samples = []
    # This slice is chosen from the complete census before any outcome is read.
    for i, e in enumerate(events[:8]):
        pre = 'sample_' + str(i) + '_'
        rec = receipt(rpc(pre + 'receipt', 'eth_getTransactionReceipt',
                          [e['transaction_hash']], allow_unavailable=True), e)
        block = header(rpc(pre + 'block', 'eth_getBlockByHash', [e['block_hash'], False]))
        before = header(rpc(pre + 'before_block', 'eth_getBlockByNumber',
                            [hex(e['block_number'] - 1), False]))
        if (block['number'] != e['block_number'] or block['hash'] != e['block_hash'] or
                before['number'] != e['block_number'] - 1 or block['parentHash'] != before['hash'] or
                before['timestamp'] > block['timestamp']):
            raise Refusal('sample_header_linkage')
        data = HEALTH_SELECTOR + e['borrower'][2:].rjust(64, '0')
        before_health = health(rpc(pre + 'health_before', 'eth_call',
                                   call_params(data, before['hash']), allow_unavailable=True))
        after_health = health(rpc(pre + 'health_after', 'eth_call',
                                  call_params(data, block['hash']), allow_unavailable=True))
        samples.append(dict(event=e, receipt=rec, block=block, before_block=before,
                            preceding_block_health=before_health, end_of_event_block_health=after_health))
    reread = header(rpc('anchor_reread', 'eth_getBlockByNumber', [hex(end), False]))
    if reread != anchor:
        raise Refusal('anchor_changed')
    return dict(schema='aave-liquidation-census-projection-v1', status='historical_census_complete',
                pool=POOL, pool_code_sha256=sha(bytes.fromhex(code[2:])),
                anchor=anchor, range_start=first, blocks=7200, page_counts=page_counts,
                event_count=len(events), transaction_count=len({e['transaction_hash'] for e in events}),
                borrower_count=len({e['borrower'] for e in events}),
                pair_counts=[dict(collateral=k[0], debt=k[1], events=n) for k, n in sorted(pairs.items())],
                selected_event_count=len(samples), selection=SPEC['selection'], samples=samples,
                historical_simulation_candidates=sum(s['preceding_block_health'].get(
                    'debt_positive_and_health_below_one') is True for s in samples),
                missing_preceding_health=sum(not s['preceding_block_health']['available'] for s in samples),
                provider_assertions_only=True, state_immediately_before_transaction=False,
                complete_market_liquidation_population=False, economics=False, closed_cash=False)


def rpc_result(raw, id_, allow_unavailable):
    obj = decode(raw)
    if not isinstance(obj, dict) or obj.get('jsonrpc') != '2.0' or type(obj.get('id')) is not int or obj['id'] != id_:
        raise Refusal('rpc_identity')
    if set(obj) == {'jsonrpc', 'id', 'error'}:
        e = obj['error']
        if (not isinstance(e, dict) or not {'code', 'message'} <= set(e) <= {'code', 'message', 'data'}
                or type(e['code']) is not int or not isinstance(e['message'], str)):
            raise Refusal('rpc_error_schema')
        if allow_unavailable:
            return dict(rpc_unavailable=e['code'])
        raise Refusal('rpc_error_no_retry')
    if set(obj) != {'jsonrpc', 'id', 'result'}:
        raise Refusal('rpc_result_schema')
    if obj['result'] is None and not allow_unavailable:
        raise Refusal('rpc_null_result')
    return obj['result']


def verify(digest):
    raw = read(ROOT / PLAN, 16384)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    if (p.get('status') != 'frozen' or p.get('spec') != SPEC or p.get('caps') != CAPS or
            p.get('runtime') != h.runtime() or p.get('output_dir') != OUT):
        raise Refusal('frozen_scope')
    pins = p.get('pins', [])
    required = {SOURCE, TEST, DESIGN, HELPER, ALLOCATION}
    if len(pins) != len(required) or {x.get('path') for x in pins} != required:
        raise Refusal('pins_schema')
    for x in pins:
        b = read(ROOT / x['path'], 65536)
        if len(b) != x['bytes'] or sha(b) != x['sha256']:
            raise Refusal('source_pin')
    for path in (ROOT / 'reports', ROOT / 'reports/aave-liquidation-census-v1', ROOT / OUT):
        if path.is_symlink():
            raise Refusal('output_symlink')
    return p


def publish(out, name, obj, cap=8192):
    raw = encode(obj) + b'\n'
    if len(raw) > cap:
        raise Refusal('publication_cap')
    with (out / name).open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


class Frames:
    def __init__(self, out):
        self.path = out / 'responses.frames'
        self.file = self.path.open('xb')
        self.file.write(MAGIC)
        self.used = len(MAGIC)

    def append(self, kind, raw):
        if kind not in (b'B', b'H', b'D', b'E') or len(raw) > (4096 if kind == b'D' else 2048):
            raise Refusal('frame_cap')
        packet = kind + struct.pack('>I', len(raw)) + raw
        if self.used + len(packet) + (2053 if kind != b'E' else 0) > CAPS['raw_bytes']:
            raise Refusal('raw_cap')
        self.file.write(packet)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.used += len(packet)

    def close(self):
        self.file.close()


def decode_frames(path):
    raw = read(path, CAPS['raw_bytes'])
    if not raw.startswith(MAGIC):
        raise Refusal('raw_magic')
    at, active, records, total = len(MAGIC), None, [], 0
    while at < len(raw):
        if at + 5 > len(raw):
            raise Refusal('partial_frame')
        kind, n = raw[at:at+1], struct.unpack('>I', raw[at+1:at+5])[0]
        at += 5
        if n > (4096 if kind == b'D' else 2048) or at + n > len(raw):
            raise Refusal('frame_size')
        part, at = raw[at:at+n], at+n
        if kind == b'B':
            if active is not None or len(records) >= 62:
                raise Refusal('begin_order')
            active = dict(begin=decode(part), header=None, body=bytearray())
        elif kind == b'H':
            if active is None or active['header'] is not None:
                raise Refusal('header_order')
            active['header'] = decode(part)
        elif kind == b'D':
            if active is None or active['header'] is None:
                raise Refusal('body_order')
            active['body'].extend(part)
            total += n
            if len(active['body']) > 65537 or total > CAPS['body_bytes']:
                raise Refusal('body_cap')
        elif kind == b'E':
            if active is None:
                raise Refusal('end_order')
            e = decode(part)
            if (e.get('error') is not None or e.get('dispatch_attempted') is not True or
                    e.get('http_status') != 200 or not isinstance(active['header'], dict) or
                    active['header'].get('status') != 200 or len(active['body']) > 65536 or
                    e.get('response_bytes') != len(active['body']) or e.get('response_sha256') != sha(active['body'])):
                raise Refusal('incomplete_rpc')
            records.append(active)
            active = None
        else:
            raise Refusal('frame_type')
    if active is not None:
        raise Refusal('unfinished_rpc')
    return records, dict(bytes=len(raw), sha256=sha(raw)), total


def replay(path):
    records, pin, total = decode_frames(path)
    index = 0

    def rpc(name, method, params, allow_unavailable=False):
        nonlocal index
        if index >= len(records):
            raise Refusal('missing_request')
        rec = records[index]
        index += 1
        expected = dict(jsonrpc='2.0', id=index, method=method, params=params)
        if rec['begin'].get('name') != name or rec['begin'].get('request') != expected:
            raise Refusal('request_manifest')
        return rpc_result(bytes(rec['body']), index, allow_unavailable)

    result = collect(rpc)
    if index != len(records):
        raise Refusal('extra_request')
    return result, pin, total


def reason(exc):
    return str(exc)[:160] if isinstance(exc, (Refusal, h.Refusal)) else type(exc).__name__


def run(digest):
    start = time.monotonic()
    frames = None
    attempts = total = 0
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        p = verify(digest)
        out = ROOT / OUT
        out.mkdir(exist_ok=False)
        publish(out, 'claim.json', dict(plan_sha256=digest, started_ns=time.time_ns(), pins=p['pins']))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            with h.alarm(CAPS['work_seconds'] - (time.monotonic() - start)):
                frames = Frames(out)

                def rpc(name, method, params, allow_unavailable=False):
                    nonlocal attempts, total
                    if attempts >= 62:
                        raise Refusal('request_cap')
                    if CAPS['body_bytes'] - total < 65537:
                        raise Refusal('body_reserve_before_dispatch')
                    request = dict(jsonrpc='2.0', id=attempts+1, method=method, params=params)
                    frames.append(b'B', encode(dict(name=name, request=request, dispatch_attempted=None,
                                                   admitted_ns=time.time_ns())))
                    body, code, dispatched, failure = bytearray(), None, False, None

                    def dispatch():
                        nonlocal attempts, dispatched
                        attempts += 1
                        dispatched = True

                    def emit(part):
                        nonlocal total
                        if total + len(part) > CAPS['body_bytes']:
                            raise Refusal('cumulative_body_cap')
                        frames.append(b'D', part)
                        body.extend(part)
                        total += len(part)

                    def headers(c, part):
                        nonlocal code
                        code = c
                        frames.append(b'H', part)

                    try:
                        seconds = min(12, CAPS['work_seconds'] - (time.monotonic() - start))
                        if seconds <= 0:
                            raise Refusal('work_deadline')
                        code, count = h.fetch(request, 65536, seconds, emit, headers, dispatch)
                        if code != 200 or count != len(body):
                            raise Refusal('http_status_or_size')
                    except Exception as exc:
                        failure = reason(exc)
                    frames.append(b'E', encode(dict(error=failure, http_status=code,
                        dispatch_attempted=dispatched, response_bytes=len(body),
                        response_sha256=sha(body), ended_ns=time.time_ns())))
                    if failure:
                        raise Refusal(failure)
                    return rpc_result(bytes(body), attempts, allow_unavailable)

                result = collect(rpc)
                frames.close()
                frames = None
                reproduced, raw_pin, replay_bytes = replay(out / 'responses.frames')
                if encode(result) != encode(reproduced) or replay_bytes != total:
                    raise Refusal('replay_mismatch')
                verify(digest)
                result.update(plan_sha256=digest, raw=raw_pin, requests_attempted=attempts)
                publish(out, 'projection.json', result, CAPS['projection_bytes'])
                status = 'historical_census_complete'
        except BaseException as exc:
            error = reason(exc)
        finally:
            if frames:
                frames.close()
            try:
                verify(digest)
            except Exception:
                status, error = 'unavailable', 'final_pin_mismatch'
            publish(out, 'terminal.json', dict(status=status, error=error, plan_sha256=digest,
                requests_attempted=attempts, request_cap=62, retained_body_bytes=total,
                elapsed_seconds=round(time.monotonic()-start, 6), ended_ns=time.time_ns(),
                economics=False, closed_cash=False))
    return status == 'historical_census_complete' and error is None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--plan-sha256')
    ap.add_argument('--replay', action='store_true')
    args = ap.parse_args()
    if args.replay:
        verify(args.plan_sha256)
        result, pin, size = replay(ROOT / OUT / 'responses.frames')
        print(encode(dict(status=result['status'], events=result['event_count'], raw=pin, body_bytes=size)).decode())
        return 0
    if not args.run:
        print('dry: zero requests; zero outputs;7200blocks;first8events;62RPC maximum')
        return 0
    return 0 if run(args.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
