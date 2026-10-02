"""Paired historical health/price views around one original prefix transaction."""
import argparse
import copy
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/aave_state_transition_v1.py'
TEST = 'tests/test_aave_state_transition_v1.py'
BASE = 'reports/aave-state-transition-v1/'
PLAN, DESIGN, OUT, TRANSPORT = (BASE+n for n in ('plan.json', 'design.txt', 'run-v1', 'capture.py'))
ALLOCATION = 'reports/experiment-storage/aave-state-transition-allocation-v1.json'
HELPER = 'scripts/aave_ordered_control_v1.py'
HELPER_SHA = 'cfbe348b44f8401adc8f877f3fb8cb2eb8a1475a7cebf855d48b98b524e9a5eb'
CONTROL_PLAN_SHA = '78856bf87932c7665756c46227df934b621908821d3afd6d54ea00e3b189ab09'
CAPS = dict(requests=13, body_bytes=196608, raw_bytes=262144, request_bytes=8192,
            projection_bytes=16384, request_seconds=20, wall_seconds=180, work_seconds=165,
            cpu_seconds=20, ram_bytes=536870912, total_supplied_gas=6000000)
SLOTS = [('chain', 4096), ('parent', 32768), ('provider_oracle', 4096),
         ('oracle_unit', 4096), ('collateral_source', 4096), ('source_description', 8192),
         ('source_decimals', 4096), ('source_aggregator', 4096), ('source_round', 8192),
         ('without_prefix_views', 32768), ('with_prefix_views', 32768),
         ('parent_recheck', 32768), ('event_recheck', 32768)]
OPTIONAL = {'source_description', 'source_decimals', 'source_aggregator', 'source_round'}


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


def module(path, name, digest=None):
    raw = read(ROOT/path, 32768)
    if digest is not None and sha(raw) != digest:
        raise Refusal('immutable_helper')
    value = types.ModuleType(name)
    value.__file__ = str(ROOT/path)
    exec(compile(raw, value.__file__, 'exec'), value.__dict__)
    return value


c = module(HELPER, 'state_transition_control', HELPER_SHA)
o, h, encode, decode = c.o, c.h, c.encode, c.decode
t = module(TRANSPORT, 'state_transition_capture', 'a93fe1a0db2de4cd02b670ac4c4dd3f62c1af282ad1d362218fd62e3f96bd817')


def selector(signature):
    return o.c.keccak_hex(signature)[:10]


def word_address(address):
    return h.hexdata(address, 20)[2:].rjust(64, '0')


def uint_word(raw):
    return str(int(h.hexdata(raw, 32), 16))


def decimal_word(raw):
    value = uint_word(raw)
    if int(value) >= 256:
        raise Refusal('decimals_uint8_width')
    return value


def string_word(raw):
    b = bytes.fromhex(h.hexdata(raw)[2:])
    if len(b) < 64 or int.from_bytes(b[:32], 'big') != 32:
        raise Refusal('string_offset')
    size = int.from_bytes(b[32:64], 'big')
    if size > 256 or len(b) != 64 + ((size+31)//32)*32 or any(b[64+size:]):
        raise Refusal('string_length_or_padding')
    return b[64:64+size].decode('utf-8', errors='strict')


def round_words(raw):
    data = h.hexdata(raw, 160)[2:]
    values = [int(data[i:i+64], 16) for i in range(0, 320, 64)]
    answer = values[1] - 2**256 if values[1] >= 2**255 else values[1]
    if values[0] >= 2**80 or values[4] >= 2**80:
        raise Refusal('round_word_width')
    return dict(round_id=str(values[0]), answer_signed=str(answer),
                started_at=str(values[2]), updated_at=str(values[3]), answered_in_round=str(values[4]))


def optional(value, parser):
    if isinstance(value, dict) and 'rpc_unavailable' in value:
        return dict(available=False, reason='rpc_error', code=value['rpc_unavailable'])
    try:
        parsed = parser(value)
    except (Refusal, o.c.Refusal, h.Refusal, TypeError, ValueError, UnicodeError):
        return dict(available=False, reason='null_or_noncanonical_result')
    return dict(available=True, value=parsed)


def inputs():
    c.verify(CONTROL_PLAN_SHA)
    terminal = decode(read(ROOT/c.OUT/'terminal.json', 4096))
    result = decode(read(ROOT/c.OUT/'projection.json', 8192))
    if terminal['status'] != 'control_complete' or terminal['error'] is not None or result['outcome'] != 'reverted_without_prefix':
        raise Refusal('prior_control_not_admitted')
    setup = c.inputs()
    records, _, _ = o.decode_frames(ROOT/c.POSITIVE_RAW)
    setup['prefix_receipt'] = next(decode(r['body'])['result'] for r in records if r['begin']['name'] == 'prefix_receipt')
    answer_topic = o.c.keccak_hex('AnswerUpdated(int256,uint256,uint256)')
    rows = [r for r in setup['prefix_receipt']['logs'] if r['topics'][0] == answer_topic]
    if len(rows) != 1 or len(rows[0]['topics']) != 3:
        raise Refusal('baseline_answer_event')
    setup['answer_emitter'] = h.hexdata(rows[0]['address'], 20)
    answer = int(h.hexdata(rows[0]['topics'][1], 32), 16)
    setup['answer_raw'] = str(answer-2**256 if answer >= 2**255 else answer)
    return setup


def probe_params(setup, oracle, with_prefix):
    params = copy.deepcopy(setup['original_params'])
    prefix = params[0]['blockStateCalls'][0]['calls'][0]
    nonce = h.quantity(prefix['nonce']) + int(with_prefix)
    probes = []
    for index, (to, data, gas) in enumerate([
        (o.c.POOL, o.c.HEALTH_SELECTOR+word_address(setup['event']['borrower']), 1000000),
        (oracle, selector('getAssetPrice(address)')+word_address(setup['event']['collateral']), 300000),
    ]):
        call = copy.deepcopy(prefix)
        call.update(to=to, input=data, gas=hex(gas), nonce=hex(nonce+index), value='0x0', accessList=[])
        probes.append(call)
    calls = ([prefix] if with_prefix else []) + probes
    params[0]['blockStateCalls'][0]['calls'] = calls
    return params


def branch_result(value, setup, with_prefix):
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
    if not isinstance(calls, list) or len(calls) != 2+int(with_prefix):
        raise Refusal('simulation_call_count')
    for i, call in enumerate(calls):
        if (not isinstance(call, dict) or h.quantity(call.get('status')) != 1 or
                call.get('error') is not None or not isinstance(call.get('logs'), list)):
            raise Refusal('probe_or_prefix_failed')
        gas = h.quantity(call.get('gasUsed'))
        limit = (h.quantity(setup['original_params'][0]['blockStateCalls'][0]['calls'][0]['gas'])
                 if with_prefix and i == 0 else 1000000 if i == int(with_prefix) else 300000)
        if not 21000 <= gas <= limit:
            raise Refusal('probe_gas_bound')
        h.hexdata(call.get('returnData'))
        if with_prefix and i == 0:
            rec = setup['prefix_receipt']
            if gas != h.quantity(rec['gasUsed']) or [o.log_content(x) for x in call['logs']] != [o.log_content(x) for x in rec['logs']]:
                raise Refusal('prefix_receipt_diverged')
        elif call['logs']:
            raise Refusal('view_probe_emitted_logs')
    probes = calls[int(with_prefix):]
    health = o.c.health(probes[0]['returnData'])
    if not health['available']:
        raise Refusal('health_return_schema')
    return dict(health=health, collateral_price_raw=uint_word(probes[1]['returnData']),
                probe_gas_used=[str(h.quantity(x['gasUsed'])) for x in probes],
                original_prefix_receipt_matched=with_prefix)


def collect(rpc, setup):
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('wrong_chain')
    parent, block = setup['parent'], setup['block']
    o.same_header(rpc('parent', 'eth_getBlockByNumber', [parent['number'], False]), parent)

    def view(name, to, data):
        sender = setup['original_params'][0]['blockStateCalls'][0]['calls'][0]['from']
        return rpc(name, 'eth_call', [dict(to=to, data=data, gas=hex(300000), **{'from': sender}),
                   dict(blockHash=parent['hash'], requireCanonical=True)], allow_unavailable=name in OPTIONAL)

    oracle = o.c.address_word(view('provider_oracle', o.c.PROVIDER, selector('getPriceOracle()')))
    unit = uint_word(view('oracle_unit', oracle, selector('BASE_CURRENCY_UNIT()')))
    source = o.c.address_word(view('collateral_source', oracle,
                                  selector('getSourceOfAsset(address)')+word_address(setup['event']['collateral'])))
    if oracle == '0x'+'00'*20 or source == '0x'+'00'*20 or int(unit) == 0:
        raise Refusal('empty_oracle_source_or_unit')
    metadata = {}
    for name, signature, parser in [
        ('source_description', 'description()', string_word),
        ('source_decimals', 'decimals()', decimal_word),
        ('source_aggregator', 'aggregator()', o.c.address_word),
        ('source_round', 'latestRoundData()', round_words),
    ]:
        metadata[name] = optional(view(name, source, selector(signature)), parser)
    params = [probe_params(setup, oracle, flag) for flag in (False, True)]
    gas_total = 7*300000 + sum(h.quantity(x['gas']) for p in params for x in p[0]['blockStateCalls'][0]['calls'])
    if gas_total > CAPS['total_supplied_gas']:
        raise Refusal('total_supplied_gas')
    before = branch_result(rpc('without_prefix_views', 'eth_simulateV1', params[0]), setup, False)
    after = branch_result(rpc('with_prefix_views', 'eth_simulateV1', params[1]), setup, True)
    o.same_header(rpc('parent_recheck', 'eth_getBlockByNumber', [parent['number'], False]), parent)
    event = rpc('event_recheck', 'eth_getBlockByNumber', [block['number'], False])
    o.same_header(event, block)
    if event.get('transactions', [])[:2] != block['transactions'][:2]:
        raise Refusal('event_prefix_changed')
    before_h, after_h = before['health'], after['health']
    aggregator = metadata['source_aggregator']
    return dict(schema='aave-state-transition-projection-v1', status='paired_views_complete',
        event=setup['event'], parent=o.c.header(parent), target_context=o.context(block),
        parent_oracle=oracle, parent_base_currency_unit_raw=unit, parent_source=source, parent_source_metadata=metadata,
        observed_prefix_answer_emitter=setup['answer_emitter'], observed_prefix_answer_raw=setup['answer_raw'],
        parent_direct_source_matches_emitter=source == setup['answer_emitter'],
        parent_source_aggregator_matches_emitter=(aggregator['value'] == setup['answer_emitter'] if aggregator['available'] else None),
        without_prefix=before, with_prefix=after,
        necessary_eligibility_crossed=(not before_h['debt_positive_and_health_below_one'] and after_h['debt_positive_and_health_below_one']),
        debt_and_threshold_unchanged=all(before_h[k] == after_h[k] for k in ('total_debt_base_raw', 'liquidation_threshold_raw')),
        price_changed=before['collateral_price_raw'] != after['collateral_price_raw'],
        supplied_gas_upper_bound=gas_total, provider_assertions_only=True,
        probe_sender_is_historical_prefix_sender=True, probe_sender_control_claimed=False,
        state_balance_overrides=False, specific_executor_error_attributed=False,
        post_prefix_oracle_wiring_verified=False, selected_price_caused_health_crossing=False,
        economics=False, closed_cash=False)


def verify(digest):
    raw = read(ROOT/PLAN, 16384)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    plan = decode(raw)
    required = {SOURCE, TEST, DESIGN, TRANSPORT, ALLOCATION, HELPER, c.PLAN,
                c.POSITIVE_RAW, c.OUT+'/projection.json', c.OUT+'/terminal.json'}
    if (plan.get('status') != 'frozen' or plan.get('caps') != CAPS or
            plan.get('slots') != [list(x) for x in SLOTS] or
            plan.get('runtime') != h.runtime() or plan.get('output_dir') != OUT or
            plan.get('control_plan_sha256') != CONTROL_PLAN_SHA):
        raise Refusal('frozen_scope')
    pins = plan.get('pins', [])
    if len(pins) != len(required) or {p.get('path') for p in pins} != required:
        raise Refusal('pins_schema')
    for pin in pins:
        data = read(ROOT/pin['path'], 131072)
        if len(data) != pin['bytes'] or sha(data) != pin['sha256']:
            raise Refusal('source_or_input_pin')
    if sum(p['bytes'] for p in pins if p['path'] in (SOURCE, TEST, DESIGN, TRANSPORT))+len(raw) > 65536:
        raise Refusal('source_package_cap')
    for path in (ROOT/'reports', ROOT/BASE, ROOT/OUT):
        if path.is_symlink():
            raise Refusal('output_symlink')
    return plan


def reason(exc):
    if isinstance(exc, (Refusal, t.Refusal, c.Refusal, o.Refusal, o.c.Refusal, h.Refusal)):
        return str(exc)[:160]
    return type(exc).__name__


def replay(path, setup):
    reader = t.Reader(path, SLOTS, CAPS, o.c)
    result = collect(reader.rpc, setup)
    reader.finish()
    return result, reader.body_bytes, reader.raw_bytes


def run(digest):
    started, capture = time.monotonic(), None
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        plan, setup = verify(digest), inputs()
        out = ROOT/OUT
        out.mkdir(exist_ok=False)
        o.publish(out, 'claim.json', dict(plan_sha256=digest, started_ns=time.time_ns(), pins=plan['pins']))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture = t.Capture(out/'raw', SLOTS, CAPS, o.c, started, reason)
                result = collect(capture.rpc, setup)
                reproduced, body, raw = replay(out/'raw', setup)
                if encode(result) != encode(reproduced) or body != capture.body_bytes or raw != capture.raw_bytes:
                    raise Refusal('raw_replay_mismatch')
                verify(digest)
                result.update(plan_sha256=digest, requests_attempted=capture.attempts)
                o.publish(out, 'projection.json', result, CAPS['projection_bytes'])
                status = 'paired_views_complete'
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
    return status == 'paired_views_complete' and error is None


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
        print(encode(dict(status=result['status'], necessary_eligibility_crossed=result['necessary_eligibility_crossed'],
                          body_bytes=body, raw_bytes=raw)).decode())
        return 0
    if not args.run:
        print('dry: zero requests;zero outputs;paired historical health/price views;13RPC maximum')
        return 0
    return 0 if run(args.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
