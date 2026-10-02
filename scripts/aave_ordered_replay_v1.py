"""One frozen read-only replay of two historical transactions; dry by default."""
import argparse
from collections import defaultdict
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
SOURCE = 'scripts/aave_ordered_replay_v1.py'
TEST = 'tests/test_aave_ordered_replay_v1.py'
DESIGN = 'reports/aave-ordered-replay-v1/design.txt'
PLAN = 'reports/aave-ordered-replay-v1/plan.json'
OUT = 'reports/aave-ordered-replay-v1/run-v1'
ALLOCATION = 'reports/experiment-storage/aave-ordered-replay-preparation-v1.json'
CENSUS = 'scripts/aave_liquidation_census_v1.py'
CENSUS_SHA = '33827d6535377fe6edbd73569486c8ff26af7b772391dd65263c35f324a095fb'
BASE = 'reports/aave-liquidation-census-v1/run-v1/'
INPUT_PINS = {
    BASE + 'responses.frames': 'e671de3c4cee8177a98f2db9a3174e97e8b18656e1e75f2db9d273ec63b5f6d9',
    BASE + 'projection.json': 'e147c5928370fc5fe43c797087a9584fda4f34ac157be1c911295afb7c845622',
    BASE + 'terminal.json': '786b42bb260542569a065b511c947f65cc043a01c7bad625c9e29a38f8e3578e',
}
CAPS = dict(requests=8, body_bytes=327680, raw_bytes=393216,
            request_bytes=32768, projection_bytes=32768, request_seconds=20,
            wall_seconds=120, work_seconds=110, cpu_seconds=20,
            ram_bytes=536870912, total_call_gas=6000000)
SLOTS = [('chain', 4096), ('parent', 32768), ('prefix_tx', 32768),
         ('target_tx', 32768), ('prefix_receipt', 65536), ('simulate', 131072),
         ('parent_recheck', 32768), ('event_recheck', 32768)]
SPEC = dict(chain_id=1, endpoint='https://ethereum-rpc.publicnode.com',
            selection='first_chronological_census_event_and_its_one_preceding_transaction',
            target='0xb71c422001da07370bb52ac46be01551c20b2bfa6c0f4cddf6b7765e9c94644f',
            prefix='0xf04ac291f6537bd58059aa48decd78e82291bc7d53a34a8185fe3e7d051387d2',
            validation=True, traceTransfers=True, retries=0, fallbacks=0,
            state_overrides=False, transaction_submission=False)
MAGIC = b'AAVE-ORDERED-REPLAY-V1\n'
ETH = '0x' + 'ee' * 20


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


_raw = read(ROOT / CENSUS, 32768)
if sha(_raw) != CENSUS_SHA:
    raise Refusal('immutable_census_helper')
c = types.ModuleType('ordered_replay_census')
c.__file__ = str(ROOT / CENSUS)
exec(compile(_raw, c.__file__, 'exec'), c.__dict__)
del _raw
h = c.h
encode, decode = c.encode, c.decode
TRANSFER = c.keccak_hex('Transfer(address,address,uint256)')


def load_baseline():
    for path, digest in INPUT_PINS.items():
        if sha(read(ROOT / path, 393216)) != digest:
            raise Refusal('baseline_pin')
    # The hash-pinned prior terminal uses a floating elapsed_seconds control.
    terminal = json.loads(read(ROOT / (BASE + 'terminal.json'), 4096))
    if terminal['status'] != 'historical_census_complete' or terminal['error'] is not None:
        raise Refusal('census_incomplete')
    projection = decode(read(ROOT / (BASE + 'projection.json'), 16384))
    selected = projection['samples'][0]['event']
    records, _, _ = c.decode_frames(ROOT / (BASE + 'responses.frames'))
    values = {r['begin']['name']: c.rpc_result(bytes(r['body']), r['begin']['request']['id'], True)
              for r in records}
    block, parent, receipt = (values['sample_0_' + k] for k in ('block', 'before_block', 'receipt'))
    if (selected['transaction_hash'] != SPEC['target'] or selected['transaction_index'] != 1 or
            block['transactions'][:2] != [SPEC['prefix'], SPEC['target']] or
            block['parentHash'] != parent['hash'] or
            h.quantity(block['number']) != h.quantity(parent['number']) + 1):
        raise Refusal('baseline_selection')
    c.receipt(receipt, selected)
    return dict(event=selected, block=block, parent=parent, target_receipt=receipt)


def context(v):
    """Fields that the supported RPC can set; this is not the entire block."""
    if not isinstance(v, dict):
        raise Refusal('block_schema')
    return dict(number=hex(h.quantity(v.get('number'))), time=hex(h.quantity(v.get('timestamp'))),
                gasLimit=hex(h.quantity(v.get('gasLimit'))),
                feeRecipient=h.hexdata(v.get('miner'), 20), prevRandao=h.hexdata(v.get('mixHash'), 32),
                baseFeePerGas=hex(h.quantity(v.get('baseFeePerGas'))))


def same_header(actual, expected):
    if c.header(actual) != c.header(expected) or context(actual) != context(expected):
        raise Refusal('canonical_header_changed')


def call_args(v, block, index):
    if not isinstance(v, dict):
        raise Refusal('transaction_unavailable')
    if (h.hexdata(v.get('hash'), 32) != block['transactions'][index] or
            h.hexdata(v.get('blockHash'), 32) != block['hash'] or
            h.quantity(v.get('blockNumber')) != h.quantity(block['number']) or
            h.quantity(v.get('transactionIndex')) != index):
        raise Refusal('transaction_identity')
    typ = h.quantity(v.get('type'))
    if typ not in (0, 1, 2):
        raise Refusal('unsupported_transaction_type')
    if any(v.get(k) not in (None, []) for k in ('authorizationList', 'blobVersionedHashes')):
        raise Refusal('unsupported_transaction_fields')
    if h.quantity(v.get('chainId', '0x1')) != 1:
        raise Refusal('transaction_chain')
    if typ and 'chainId' not in v:
        raise Refusal('typed_transaction_missing_chain')
    data = h.hexdata(v.get('input'))
    if len(data) > 2 + 2 * 16384:
        raise Refusal('calldata_cap')
    result = dict(to=h.hexdata(v.get('to'), 20), input=data,
                  **{'from': h.hexdata(v.get('from'), 20)})
    for key in ('gas', 'nonce', 'value'):
        result[key] = hex(h.quantity(v.get(key)))
    if not 21000 <= h.quantity(result['gas']) <= CAPS['total_call_gas']:
        raise Refusal('transaction_gas_cap')
    if h.quantity(result['nonce']) >= 2**64:
        raise Refusal('transaction_nonce_cap')
    # Fee fields and accessList determine types 0/1/2 in Geth TransactionArgs.
    if typ == 2:
        for key in ('maxFeePerGas', 'maxPriorityFeePerGas'):
            result[key] = hex(h.quantity(v.get(key)))
        if h.quantity(result['maxPriorityFeePerGas']) > h.quantity(result['maxFeePerGas']):
            raise Refusal('fee_cap_below_tip')
    else:
        result['gasPrice'] = hex(h.quantity(v.get('gasPrice')))
    if typ:
        result['chainId'] = '0x1'
        access = v.get('accessList')
        if not isinstance(access, list) or len(access) > 128:
            raise Refusal('access_list')
        result['accessList'] = []
        keys = 0
        for row in access:
            if not isinstance(row, dict) or set(row) != {'address', 'storageKeys'}:
                raise Refusal('access_list_entry')
            if not isinstance(row['storageKeys'], list):
                raise Refusal('access_list_keys')
            keys += len(row['storageKeys'])
            if keys > 256:
                raise Refusal('access_list_key_cap')
            result['accessList'].append(dict(address=h.hexdata(row['address'], 20),
                storageKeys=[h.hexdata(x, 32) for x in row['storageKeys']]))
    return result


def log_content(row):
    if not isinstance(row, dict) or row.get('removed', False) is not False:
        raise Refusal('log_schema')
    topics = row.get('topics')
    if not isinstance(topics, list) or len(topics) > 4:
        raise Refusal('log_topics')
    return dict(address=h.hexdata(row.get('address'), 20),
                topics=[h.hexdata(t, 32) for t in topics], data=h.hexdata(row.get('data')))


def receipt_check(rec, tx, block, index):
    if not isinstance(rec, dict):
        raise Refusal('receipt_unavailable')
    for key, expected in [('transactionHash', block['transactions'][index]), ('blockHash', block['hash'])]:
        if h.hexdata(rec.get(key), 32) != expected:
            raise Refusal('receipt_identity')
    if (h.quantity(rec.get('transactionIndex')) != index or
            h.quantity(rec.get('blockNumber')) != h.quantity(block['number']) or
            h.quantity(rec.get('status')) != 1):
        raise Refusal('receipt_status_or_index')
    if h.hexdata(rec.get('from'), 20) != tx['from'] or h.hexdata(rec.get('to'), 20) != tx['to']:
        raise Refusal('receipt_parties')
    gas = h.quantity(rec.get('gasUsed'))
    price = h.quantity(rec.get('effectiveGasPrice'))
    base = h.quantity(block['baseFeePerGas'])
    expected_price = (h.quantity(tx['gasPrice']) if 'gasPrice' in tx else
                      min(h.quantity(tx['maxFeePerGas']), base + h.quantity(tx['maxPriorityFeePerGas'])))
    if not 21000 <= gas <= h.quantity(tx['gas']) or price != expected_price or price < base:
        raise Refusal('receipt_gas_or_fee')
    logs = rec.get('logs')
    if not isinstance(logs, list) or len(logs) > 512:
        raise Refusal('receipt_logs')
    last = -1
    for row in logs:
        log_content(row)
        if (h.hexdata(row.get('transactionHash'), 32) != rec['transactionHash'] or
                h.hexdata(row.get('blockHash'), 32) != block['hash'] or
                h.quantity(row.get('transactionIndex')) != index or
                h.quantity(row.get('blockNumber')) != h.quantity(block['number']) or
                h.quantity(row.get('logIndex')) <= last):
            raise Refusal('receipt_log_identity_order')
        if row['address'].lower() == ETH:
            raise Refusal('synthetic_address_in_real_receipt')
        last = h.quantity(row['logIndex'])
    cumulative = h.quantity(rec.get('cumulativeGasUsed'))
    if cumulative < gas or (index == 0 and cumulative != gas):
        raise Refusal('receipt_cumulative_gas')
    return dict(gas_used=gas, cumulative_gas=cumulative,
                gas_fee_wei=gas * price, regular_logs=[log_content(x) for x in logs])


def transfer(row):
    if len(row['topics']) != 3 or row['topics'][0] != TRANSFER:
        raise Refusal('transfer_shape')
    return dict(asset=row['address'], sender=c.address_word(row['topics'][1]),
                recipient=c.address_word(row['topics'][2]),
                amount_raw=str(int(h.hexdata(row['data'], 32), 16)))


def flow_accounting(rows, tx, fee):
    """Observed event vectors, with explicit conditional account grouping."""
    transfers, nonstandard = [], 0
    for row in rows:
        if row['address'] == ETH:
            transfers.append(transfer(row))
        elif row['topics'] and row['topics'][0] == TRANSFER:
            if len(row['topics']) == 3 and len(row['data']) == 66:
                transfers.append(transfer(row))
            else:
                nonstandard += 1
    parties = sorted({tx['from'], tx['to']})
    net = defaultdict(lambda: defaultdict(int))
    for row in transfers:
        n = int(row['amount_raw'])
        net[row['sender']][row['asset']] -= n
        net[row['recipient']][row['asset']] += n
    grouped = defaultdict(int)
    for addr in parties:
        for asset, amount in net[addr].items():
            grouped[asset] += amount
    return dict(transfers=transfers, nonstandard_transfer_topic_logs=nonstandard,
        selected_addresses=parties,
        address_event_net_raw={a: {k: str(v) for k, v in sorted(net[a].items())} for a in parties},
        conditional_group_event_net_raw={k: str(v) for k, v in sorted(grouped.items())},
        conditional_group_native_after_target_gas_wei=str(grouped[ETH] - fee),
        target_transaction_gas_fee_wei=str(fee),
        gas_treatment='synthetic_ETH_events_exclude_gas_subtract_target_receipt_fee_once',
        grouping_assumption='transaction_sender_and_top_level_recipient_under_same_economic_control_unproved',
        token_balances_verified=False, private_costs_known=False, prospective_profit=False,
        realized_profit=False, closed_cash=False)


def match_simulation(result, block, calls, receipts):
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise Refusal('simulation_block_count')
    value = result[0]
    expected = context(block)
    for field, original in expected.items():
        aliases = {'time': ('timestamp', 'time'), 'feeRecipient': ('miner', 'feeRecipient'),
                   'prevRandao': ('mixHash', 'prevRandao')}.get(field, (field,))
        present = [k for k in aliases if k in value]
        if not present:
            raise Refusal('simulation_context_missing_' + field)
        for k in present:
            normalized = (h.hexdata(value[k], 20 if field == 'feeRecipient' else 32)
                          if field in ('feeRecipient', 'prevRandao') else hex(h.quantity(value[k])))
            if normalized != original:
                raise Refusal('simulation_context_mismatch_' + field)
    simulated = value.get('calls')
    if not isinstance(simulated, list) or len(simulated) != 2:
        raise Refusal('simulation_call_count')
    comparisons, contents = [], []
    for i, (value, rec) in enumerate(zip(simulated, receipts)):
        if (not isinstance(value, dict) or h.quantity(value.get('status')) != 1 or
                value.get('error') is not None or h.quantity(value.get('gasUsed')) != rec['gas_used']):
            raise Refusal('simulation_status_or_gas_' + str(i))
        h.hexdata(value.get('returnData'))
        logs = value.get('logs')
        if not isinstance(logs, list) or len(logs) > 512:
            raise Refusal('simulation_logs')
        content = [log_content(x) for x in logs]
        regular = [x for x in content if x['address'] != ETH]
        if regular != rec['regular_logs']:
            raise Refusal('simulation_regular_logs_' + str(i))
        for row in content:
            if row['address'] == ETH:
                transfer(row)
        comparisons.append(dict(index=i, gas_used=str(rec['gas_used']),
                                regular_logs_matched=len(regular),
                                native_transfer_events=len(content)-len(regular)))
        contents.append(content)
    if not any(x['address'] == ETH for x in contents[1]):
        # This selected receipt contains a WETH withdrawal. A provider silently
        # ignoring traceTransfers must not create an invented zero-ETH result.
        raise Refusal('native_transfer_trace_unavailable')
    return comparisons, flow_accounting(contents[1], calls[1], receipts[1]['gas_fee_wei'])


def collect(rpc, baseline=None):
    b = load_baseline() if baseline is None else baseline
    block, parent = b['block'], b['parent']
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('wrong_chain')
    same_header(rpc('parent', 'eth_getBlockByNumber', [parent['number'], False]), parent)
    calls = [call_args(rpc(name, 'eth_getTransactionByHash', [block['transactions'][i]]), block, i)
             for i, name in enumerate(('prefix_tx', 'target_tx'))]
    if sum(h.quantity(x['gas']) for x in calls) > CAPS['total_call_gas']:
        raise Refusal('total_call_gas_cap')
    prefix = rpc('prefix_receipt', 'eth_getTransactionReceipt', [block['transactions'][0]])
    receipts = [receipt_check(rec, tx, block, i)
                for i, (rec, tx) in enumerate(zip((prefix, b['target_receipt']), calls))]
    if receipts[1]['cumulative_gas'] != sum(r['gas_used'] for r in receipts):
        raise Refusal('receipt_prefix_cumulative_gas')
    params = [dict(blockStateCalls=[dict(blockOverrides=context(block), calls=calls)],
                   validation=True, traceTransfers=True, returnFullTransactions=False), parent['number']]
    simulated = rpc('simulate', 'eth_simulateV1', params)
    comparisons, accounting = match_simulation(simulated, block, calls, receipts)
    same_header(rpc('parent_recheck', 'eth_getBlockByNumber', [parent['number'], False]), parent)
    event = rpc('event_recheck', 'eth_getBlockByNumber', [block['number'], False])
    same_header(event, block)
    if event.get('transactions', [])[:2] != block['transactions'][:2]:
        raise Refusal('event_transaction_prefix_changed')
    return dict(schema='aave-ordered-replay-projection-v1', status='ordered_receipts_matched',
        event=b['event'], parent=c.header(parent), event_block=c.header(block),
        prefix_transaction=block['transactions'][0], calls=[dict(sender=x['from'], to=x['to'],
            selector=x['input'][:10], gas_limit=str(h.quantity(x['gas']))) for x in calls],
        comparisons=comparisons, target_flows=accounting, provider_assertions_only=True,
        whole_block_state_root_reproduced=False, causal_trigger_identified=False,
        economics=False, closed_cash=False)


def verify(digest):
    raw = read(ROOT / PLAN, 16384)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    if (p.get('status') != 'frozen' or p.get('spec') != SPEC or p.get('caps') != CAPS or
            p.get('slots') != [list(x) for x in SLOTS] or p.get('runtime') != h.runtime() or
            p.get('output_dir') != OUT):
        raise Refusal('frozen_scope')
    required = {SOURCE, TEST, DESIGN, ALLOCATION, CENSUS, c.HELPER, *INPUT_PINS}
    pins = p.get('pins', [])
    if len(pins) != len(required) or {x.get('path') for x in pins} != required:
        raise Refusal('pin_schema')
    for pin in pins:
        data = read(ROOT / pin['path'], 393216)
        if len(data) != pin['bytes'] or sha(data) != pin['sha256']:
            raise Refusal('source_or_input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE, TEST, DESIGN)) + len(raw) > 131072:
        raise Refusal('source_package_cap')
    for path in (ROOT / 'reports', ROOT / 'reports/aave-ordered-replay-v1', ROOT / OUT):
        if path.is_symlink():
            raise Refusal('output_symlink')
    return p


def publish(out, name, value, cap=8192):
    data = encode(value) + b'\n'
    if len(data) > cap:
        raise Refusal('publication_cap')
    with (out / name).open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def frame_cap(kind):
    caps = {b'B': CAPS['request_bytes'], b'H': 2048, b'D': 4096, b'E': 2048}
    if kind not in caps:
        raise Refusal('frame_kind')
    return caps[kind]


class Frames:
    def __init__(self, out):
        self.path = out / 'responses.frames'
        self.file = self.path.open('xb')
        self.file.write(MAGIC)
        self.used = len(MAGIC)

    def append(self, kind, raw):
        if len(raw) > frame_cap(kind):
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
        kind, size = raw[at:at+1], struct.unpack('>I', raw[at+1:at+5])[0]
        at += 5
        if size > frame_cap(kind) or at + size > len(raw):
            raise Refusal('frame_size')
        part, at = raw[at:at+size], at+size
        if kind == b'B':
            if active is not None or len(records) >= 8:
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
            total += size
            if len(active['body']) > SLOTS[len(records)][1] + 1 or total > CAPS['body_bytes']:
                raise Refusal('body_cap')
        elif kind == b'E':
            if active is None:
                raise Refusal('end_order')
            end = decode(part)
            if (end.get('error') is not None or end.get('http_status') != 200 or
                    end.get('dispatch_attempted') is not True or not isinstance(active['header'], dict) or
                    active['header'].get('status') != 200 or
                    len(active['body']) > SLOTS[len(records)][1] or
                    end.get('response_bytes') != len(active['body']) or
                    end.get('response_sha256') != sha(active['body'])):
                raise Refusal('incomplete_rpc')
            records.append(active)
            active = None
    if active is not None:
        raise Refusal('unfinished_rpc')
    return records, dict(bytes=len(raw), sha256=sha(raw)), total


def replay(path, baseline=None):
    records, pin, total = decode_frames(path)
    index = 0

    def rpc(name, method, params):
        nonlocal index
        if index >= len(records):
            raise Refusal('missing_request')
        rec = records[index]
        index += 1
        expected = dict(jsonrpc='2.0', id=index, method=method, params=params)
        if rec['begin'].get('name') != name or rec['begin'].get('request') != expected:
            raise Refusal('request_manifest')
        return c.rpc_result(bytes(rec['body']), index, False)

    result = collect(rpc, baseline)
    if index != len(records):
        raise Refusal('extra_request')
    return result, pin, total


def reason(exc):
    return str(exc)[:160] if isinstance(exc, (Refusal, c.Refusal, h.Refusal)) else type(exc).__name__


def run(digest):
    start, frames = time.monotonic(), None
    attempts = total = 0
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        plan = verify(digest)
        baseline = load_baseline()
        out = ROOT / OUT
        out.mkdir(exist_ok=False)
        publish(out, 'claim.json', dict(plan_sha256=digest, started_ns=time.time_ns(), pins=plan['pins']))
        resource.setrlimit(resource.RLIMIT_CPU, (CAPS['cpu_seconds'], CAPS['cpu_seconds']))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            with h.alarm(CAPS['work_seconds'] - (time.monotonic() - start)):
                frames = Frames(out)

                def rpc(name, method, params):
                    nonlocal attempts, total
                    if attempts >= 8 or name != SLOTS[attempts][0]:
                        raise Refusal('request_slot')
                    cap = SLOTS[attempts][1]
                    if CAPS['body_bytes'] - total < cap + 1:
                        raise Refusal('body_reserve_before_dispatch')
                    request = dict(jsonrpc='2.0', id=attempts+1, method=method, params=params)
                    begin = encode(dict(name=name, request=request, admitted_ns=time.time_ns()))
                    reserve = cap + 1 + 5 * ((cap + 4096) // 4096) + 2 * 2053
                    if frames.used + 5 + len(begin) + reserve > CAPS['raw_bytes']:
                        raise Refusal('raw_reserve_before_dispatch')
                    frames.append(b'B', begin)
                    body, pending, code, dispatched, failure = bytearray(), bytearray(), None, False, None

                    def dispatch():
                        nonlocal attempts, dispatched
                        attempts += 1
                        dispatched = True

                    def emit(part):
                        nonlocal total
                        if total + len(part) > CAPS['body_bytes'] or len(body) + len(part) > cap + 1:
                            raise Refusal('cumulative_body_cap')
                        body.extend(part)
                        pending.extend(part)
                        total += len(part)
                        while len(pending) >= 4096:
                            frames.append(b'D', bytes(pending[:4096]))
                            del pending[:4096]

                    def observe(http_status, headers):
                        nonlocal code
                        code = http_status
                        frames.append(b'H', headers)

                    try:
                        seconds = min(CAPS['request_seconds'], CAPS['work_seconds'] - (time.monotonic()-start))
                        if seconds <= 0:
                            raise Refusal('work_deadline')
                        code, count = h.fetch(request, cap, seconds, emit, observe, dispatch)
                        if code != 200 or count != len(body):
                            raise Refusal('http_status_or_size')
                    except Exception as exc:
                        failure = reason(exc)
                    if pending:
                        frames.append(b'D', bytes(pending))
                    frames.append(b'E', encode(dict(error=failure, http_status=code,
                        dispatch_attempted=dispatched, response_bytes=len(body),
                        response_sha256=sha(body), ended_ns=time.time_ns())))
                    if failure:
                        raise Refusal(failure)
                    return c.rpc_result(bytes(body), attempts, False)

                result = collect(rpc, baseline)
                frames.close()
                frames = None
                reproduced, raw_pin, replay_bytes = replay(out / 'responses.frames', baseline)
                if encode(result) != encode(reproduced) or replay_bytes != total:
                    raise Refusal('replay_mismatch')
                verify(digest)
                result.update(plan_sha256=digest, raw=raw_pin, requests_attempted=attempts)
                publish(out, 'projection.json', result, CAPS['projection_bytes'])
                status = result['status']
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
                requests_attempted=attempts, retained_body_bytes=total,
                elapsed_milliseconds=int((time.monotonic()-start)*1000), ended_ns=time.time_ns(),
                economics=False, closed_cash=False))
    return status == 'ordered_receipts_matched' and error is None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--replay', action='store_true')
    ap.add_argument('--plan-sha256')
    args = ap.parse_args()
    if args.replay:
        verify(args.plan_sha256)
        result, pin, size = replay(ROOT / OUT / 'responses.frames')
        print(encode(dict(status=result['status'], raw=pin, body_bytes=size)).decode())
        return 0
    if not args.run:
        print('dry: zero requests;zero outputs;two historical calls;8RPC maximum')
        return 0
    return 0 if run(args.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
