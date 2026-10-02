#!/usr/bin/env python3
"""Fixed public-contract metadata RPC preflight. Default is offline.

No prices, wallets, balances, transaction simulation or source-equivalence claim.
The exact manifest is pinned independently of the execution-plan hash.
Post-observation metadata correction: fixed pUSD implementation only.
V1 remains inconclusive and is not modified.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import re
import ssl
import sys
import time

from Crypto.Hash import keccak

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import polymarket_no_basket_metadata as metadata

Refusal = metadata.Refusal
PLAN = ROOT / 'reports/experiment-storage/polymarket-no-basket-chain-metadata-v2.json'
SOURCE = 'scripts/polymarket_no_basket_chain_metadata_v2.py'
TEST = 'tests/test_polymarket_no_basket_chain_metadata_v2.py'
OUT = 'reports/polymarket-no-basket/chain-metadata-v2'
HOST = 'polygon-bor-rpc.publicnode.com'
ENDPOINT = 'https://' + HOST
MANIFEST_SHA = '8946c4bed375754e7f7a2c0cb09f1acfa09c32de768c236ecb614b80f56421f5'
PROJECTION = {
    'path': 'reports/polymarket-no-basket/calendar-review-v1.json', 'bytes': 20256,
    'sha256': '60fd720f615d2531e4e12b1e8c8e75b4f154290ebfa7335c596ac98870ddfabe',
}
PARENT = 'reports/experiment-storage/polymarket-no-basket-calendar-v1.json'
PARENT_SHA = 'f79cd021e936c8471afdd28af8eb03a9af0ee1b4256abf286b2d4d10c64d8372'
ORIGINAL_SHA = '118815a62a774caab5251518cb6e674503585a8027bcc960c0bfbc60d9a7b90f'
EVENT = '606422'
MARKET = '0x09ac0b2770dbcad3f2e4f5356a68af57cb8ca7502b02645a07b0290d46026a00'
CONTRACTS = {
    'wrapper': '0xadA2005600Dec949baf300f4C6120000bDB6eAab',
    'legacy_adapter': '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296',
    'ctf': '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045',
    'pusd_proxy': '0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB',
    'pusd_implementation': '0xce84e053301a82937f90ee2c2c1889cab1db25de',
}
LIMITS = {
    'rpc_requests': 55, 'request_seconds': 12, 'request_work_seconds': 170,
    'process_seconds': 180, 'minimum_start_spacing_seconds': 1,
    'response_bytes': 131072, 'total_response_bytes': 1048576,
    'retained_trace_plaintext_bytes': 524288, 'retained_trace_gzip_bytes': 524288,
    'derived_receipts_bytes': 65536,
}
SIGNATURES = frozenset((
    'NEG_RISK_ADAPTER()', 'CONDITIONAL_TOKENS()', 'COLLATERAL_TOKEN()', 'USDCE()',
    'WRAPPED_COLLATERAL()', 'ctf()', 'col()', 'wcol()', 'decimals()', 'paused(address)',
    'rolesOf(address)', 'isApprovedForAll(address,address)', 'getOracle(bytes32)',
    'getQuestionCount(bytes32)', 'getFeeBips(bytes32)', 'getDetermined(bytes32)',
    'getConditionId(bytes32)', 'getPositionId(bytes32,bool)',
    'getOutcomeSlotCount(bytes32)', 'payoutDenominator(bytes32)',
))
HEADER_FIELDS = ('number', 'hash', 'parentHash', 'timestamp', 'stateRoot')


def canonical(obj):
    return json.dumps(obj, separators=(',', ':'), sort_keys=True, allow_nan=False).encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_identity(path, pin, cap):
    raw = metadata.bounded_read(path, cap)
    if len(raw) != pin.get('bytes') or sha(raw) != pin.get('sha256'):
        raise Refusal('input_or_source_identity_mismatch')
    return raw


def verify(plan_sha256):
    if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
        raise Refusal('expected_plan_sha_required')
    raw = metadata.bounded_read(PLAN, 32768)
    if sha(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = metadata.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != 'polymarket-no-basket-chain-metadata-v2':
        raise Refusal('plan_schema')
    if p.get('status') != 'frozen_chain_metadata_probe':
        raise Refusal('plan_not_frozen')
    for key, expected in {
        'endpoint': ENDPOINT, 'output_dir': OUT, 'contracts': CONTRACTS, 'limits': LIMITS,
        'input_projection': PROJECTION, 'previous': PARENT, 'previous_sha256': PARENT_SHA,
        'original_metadata_plan_sha256': ORIGINAL_SHA, 'event_id': EVENT,
        'neg_risk_market_id': MARKET, 'reserved_bytes': 0,
    }.items():
        if canonical(p.get(key)) != canonical(expected):
            raise Refusal('fixed_plan_scope_changed')
    manifest = p.get('manifest')
    if not isinstance(manifest, list) or sha(canonical(manifest)) != MANIFEST_SHA:
        raise Refusal('fixed_manifest_changed')
    if len(manifest) != 55 or [r['id'] for r in manifest] != list(range(1, 56)):
        raise Refusal('manifest_request_count')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 2:
        raise Refusal('own_source_test_pins_required')
    if sorted(pin.get('path', '') for pin in pins if isinstance(pin, dict)) != sorted((SOURCE, TEST)):
        raise Refusal('own_source_test_pins_required')
    for pin in pins:
        path = ROOT / pin['path']
        if path.resolve() != ROOT.resolve() / pin['path']:
            raise Refusal('source_symlink')
        file_identity(path, pin, 65536)
    if sha(metadata.bounded_read(ROOT / PARENT, 32768)) != PARENT_SHA:
        raise Refusal('parent_plan_sha_mismatch')
    parent = metadata.strict_json(metadata.bounded_read(ROOT / PARENT, 32768))
    parent_source = parent['source_pin']
    if parent_source.get('path') != 'scripts/polymarket_no_basket_calendar_review.py':
        raise Refusal('parent_source_scope')
    file_identity(ROOT / parent_source['path'], parent_source, 65536)
    metadata.verify(ORIGINAL_SHA)  # Original source/test and its predecessor pins.
    projection = metadata.strict_json(file_identity(ROOT / PROJECTION['path'], PROJECTION, 131072))
    event = projection['candidate']['values']
    if event['id'] != EVENT or event['negRiskMarketID'] != MARKET or event['negRiskAugmented'] is not False:
        raise Refusal('projection_event_mismatch')
    expected_markets = []
    for index, row in enumerate(projection['candidate']['markets']):
        value = row['values']
        outcomes = metadata.strict_json(value['outcomes'].encode('utf-8'))
        tokens = metadata.strict_json(value['clobTokenIds'].encode('utf-8'))
        if outcomes != ['Yes', 'No'] or len(tokens) != 2:
            raise Refusal('projection_outcome_mapping')
        expected_markets.append({
            'index': index, 'market_id': value['id'], 'question_id': value['questionID'],
            'condition_id': value['conditionId'], 'yes_token_id': tokens[0], 'no_token_id': tokens[1],
        })
    if len(expected_markets) != 5 or p.get('markets') != expected_markets:
        raise Refusal('projection_market_mapping_mismatch')
    if (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_symlink')
    return p


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value):
        raise Refusal('invalid_rpc_quantity')
    return int(value[2:], 16)


def hex_data(value, byte_count=None):
    if not isinstance(value, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', value):
        raise Refusal('invalid_rpc_hex_data')
    raw = bytes.fromhex(value[2:])
    if byte_count is not None and len(raw) != byte_count:
        raise Refusal('abi_word_length')
    return raw


def address_word(value):
    raw = hex_data(value, 32)
    if raw[:12] != bytes(12) or not any(raw[12:]):
        raise Refusal('noncanonical_or_zero_address')
    return '0x' + raw[12:].hex()


def header_projection(value):
    if not isinstance(value, dict):
        raise Refusal('invalid_block_header')
    result = {key: value.get(key) for key in HEADER_FIELDS}
    for key in ('number', 'timestamp'):
        quantity(result[key])
        result[key] = hex(quantity(result[key]))
    for key in ('hash', 'parentHash', 'stateRoot'):
        result[key] = '0x' + hex_data(result[key], 32).hex()
    return result


def calldata(signature, args, addresses):
    if signature not in SIGNATURES:
        raise Refusal('unapproved_abi_signature')
    types = signature.split('(', 1)[1][:-1].split(',') if not signature.endswith('()') else []
    if len(types) != len(args):
        raise Refusal('abi_argument_count')
    words = []
    for kind, value in zip(types, args):
        if isinstance(value, str) and value.startswith('$'):
            name = value[1:]
            if name not in addresses:
                raise Refusal('missing_scoped_address_dependency')
            value = addresses[name]
        if kind == 'address':
            raw = hex_data(value, 20)
            if not any(raw):
                raise Refusal('zero_address_argument')
            words.append(raw.rjust(32, b'\0'))
        elif kind == 'bytes32':
            words.append(hex_data(value, 32))
        elif kind == 'bool' and type(value) is bool:
            words.append(int(value).to_bytes(32, 'big'))
        else:
            raise Refusal('unsupported_abi_argument')
    selector = keccak.new(digest_bits=256, data=signature.encode('ascii')).digest()[:4]
    return '0x' + (selector + b''.join(words)).hex()


def request_for(row, addresses, header):
    method = row['method']
    if method == 'eth_chainId':
        params = []
    elif method == 'eth_getBlockByNumber':
        params = [header['number'] if row['id'] == 55 else 'latest', False]
    else:
        if header is None:
            raise Refusal('missing_frozen_header')
        target = row['target']
        if target not in addresses:
            raise Refusal('missing_scoped_address_dependency')
        at = {'blockHash': header['hash'], 'requireCanonical': True}
        if method == 'eth_getCode':
            params = [addresses[target], at]
        elif method == 'eth_getStorageAt':
            params = [addresses[target], row['slot'], at]
        elif method == 'eth_call':
            params = [{'to': addresses[target], 'data': calldata(row['signature'], row['args'], addresses)}, at]
        else:
            raise Refusal('unapproved_rpc_method')
    return {'jsonrpc': '2.0', 'id': row['id'], 'method': method, 'params': params}


def accept(row, envelope, addresses, header):
    if not isinstance(envelope, dict) or envelope.get('jsonrpc') != '2.0' or type(envelope.get('id')) is not int or envelope['id'] != row['id']:
        raise Refusal('rpc_envelope_or_id_mismatch')
    if 'error' in envelope or 'result' not in envelope:
        raise Refusal('rpc_error_or_missing_result')
    result = envelope['result']
    method = row['method']
    if method == 'eth_chainId':
        if quantity(result) != 137:
            raise Refusal('chain_id_mismatch')
        return {'chain_id': 137}
    if method == 'eth_getBlockByNumber':
        projected = header_projection(result)
        if row['id'] == 55 and projected != header:
            raise Refusal('final_header_mismatch')
        return projected
    if method == 'eth_getCode':
        code = hex_data(result)
        if not code:
            raise Refusal('empty_contract_code')
        return {'code_bytes': len(code), 'code_sha256': sha(code),
                'compiled_source_equivalence': 'unverified'}
    raw = hex_data(result, 32)
    number = int.from_bytes(raw, 'big')
    expect = row['expect']
    key, wanted = next(iter(expect.items()))
    if key in ('address_equals', 'capture_nonzero_address', 'nonzero_address'):
        value = address_word(result)
        if key == 'address_equals' and value != addresses[wanted].lower():
            raise Refusal('address_binding_mismatch')
        if key == 'capture_nonzero_address':
            if wanted not in ('usdce', 'wrapped_collateral') or wanted in addresses:
                raise Refusal('discovered_address_scope')
            addresses[wanted] = value
        return {'address': value}
    if key == 'bytes32_equals':
        if result.lower() != wanted.lower():
            raise Refusal('condition_mapping_mismatch')
        return {'bytes32': result.lower()}
    if key == 'bool_equals':
        if number not in (0, 1):
            raise Refusal('noncanonical_abi_bool')
        if bool(number) is not wanted:
            raise Refusal('bool_state_mismatch')
        return {'bool': bool(number)}
    if key == 'uint_equals':
        if number != int(wanted):
            raise Refusal('uint_count_or_token_mismatch')
    elif key == 'uint_range':
        if not wanted[0] <= number <= wanted[1]:
            raise Refusal('uint_range_mismatch')
    elif key == 'uint_has_bits':
        if number & wanted != wanted:
            raise Refusal('required_role_missing')
    else:
        raise Refusal('unsupported_frozen_expectation')
    return {'uint': str(number)}


class Trace:
    """One gzip checkpoint; plaintext exists only in bounded memory."""
    def __init__(self, out):
        self.out = out
        self.plaintext = bytearray()

    def append(self, record):
        line = metadata.encoded(record)
        if len(self.plaintext) + len(line) > LIMITS['retained_trace_plaintext_bytes']:
            raise Refusal('trace_plaintext_cap')
        data = bytes(self.plaintext) + line
        packed = gzip.compress(data, mtime=0)
        if len(packed) > LIMITS['retained_trace_gzip_bytes']:
            raise Refusal('trace_gzip_cap')
        target = self.out / 'trace.jsonl.gz'
        pending = self.out / 'trace.pending.gz'
        with pending.open('xb') as stream:
            stream.write(packed)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, target)
        self.plaintext.extend(line)


def publish(out, name, value):
    body = metadata.encoded(value)
    used = sum(path.stat().st_size for path in out.glob('*.json'))
    if used + len(body) * 2 > LIMITS['derived_receipts_bytes']:
        raise Refusal('derived_receipts_total_cap')
    metadata.publish(out / name, value, 24576)


def transport(payload, record, budget, deadline):
    remaining = LIMITS['total_response_bytes'] - budget['bytes']
    cap = min(LIMITS['response_bytes'], remaining)
    if cap <= 0:
        raise Refusal('cumulative_response_cap_before_request')
    seconds = min(LIMITS['request_seconds'], deadline - time.monotonic())
    if seconds <= 0:
        raise Refusal('request_work_deadline')
    connection = None
    body = bytearray()
    try:
        with metadata.hard_deadline(seconds, 'request_deadline'):
            connection = http.client.HTTPSConnection(HOST, timeout=seconds, context=ssl.create_default_context())
            record['request_attempted'] = True
            record['started_utc'] = metadata.utc()
            budget['requests'] += 1
            connection.request('POST', '/', body=canonical(payload), headers={
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'Accept-Encoding': 'identity', 'Connection': 'close',
                'User-Agent': 'rhhype-public-chain-metadata/1.0',
            })
            response = connection.getresponse()
            record['http_status'] = response.status
            length = response.getheader('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]{1,12}', length) or int(length) > cap):
                raise Refusal('declared_response_exceeds_remaining_cap')
            expected = int(length) if length is not None else None
            complete = False
            while len(body) < cap:
                read_limit = min(16384, cap - len(body))
                try:
                    chunk = response.read1(read_limit)
                except http.client.IncompleteRead as exc:
                    partial = exc.partial
                    if not isinstance(partial, bytes) or len(partial) > read_limit:
                        raise Refusal('transport_read_contract_violation') from None
                    body.extend(partial)
                    budget['bytes'] += len(partial)
                    raise Refusal('incomplete_response_body') from None
                if not isinstance(chunk, bytes) or len(chunk) > read_limit:
                    raise Refusal('transport_read_contract_violation')
                if not chunk:
                    complete = True
                    break
                body.extend(chunk)
                budget['bytes'] += len(chunk)
            if expected is not None and len(body) == expected:
                complete = True
            record['body_complete'] = complete
            if not complete:
                raise Refusal('response_cap_without_proven_eof')
            if expected is not None and len(body) != expected:
                raise Refusal('incomplete_response_body')
            if response.status != 200:
                raise Refusal('http_status_not_200')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise Refusal('unsupported_content_encoding')
            if response.getheader('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise Refusal('unsupported_content_type')
    finally:
        record['ended_utc'] = metadata.utc()
        record['body_bytes'] = len(body)
        record['body_sha256'] = sha(body)
        # Block bodies can contain transaction hashes. Never retain those fields.
        if payload['method'] != 'eth_getBlockByNumber':
            record['body_base64'] = base64.b64encode(body).decode('ascii')
        if connection is not None:
            connection.close()
    return bytes(body)


def collect(plan, plan_sha256, out, terminal):
    trace = Trace(out)
    addresses = {key: value.lower() for key, value in CONTRACTS.items()}
    header = None
    observations = []
    budget = {'bytes': 0, 'requests': 0}
    deadline = time.monotonic() + LIMITS['request_work_seconds']
    last_start = None
    try:
        with metadata.hard_deadline(LIMITS['request_work_seconds'], 'request_work_deadline'):
            for row in plan['manifest']:
                terminal['current_rpc_id'] = row['id']
                if last_start is not None:
                    delay = LIMITS['minimum_start_spacing_seconds'] - (time.monotonic() - last_start)
                    if delay > 0:
                        time.sleep(delay)
                payload = request_for(row, addresses, header)
                record = {'id': row['id'], 'label': row['label'], 'request': payload,
                          'request_attempted': False, 'body_complete': False,
                          'body_bytes': 0, 'code': None}
                last_start = time.monotonic()
                try:
                    body = transport(payload, record, budget, deadline)
                    observed = accept(row, metadata.strict_json(body), addresses, header)
                    record['observation'] = observed
                    if row['id'] == 2:
                        header = observed
                    observations.append({'id': row['id'], 'label': row['label'], 'observation': observed})
                except Refusal as exc:
                    record['code'] = str(exc)
                    raise
                except Exception:
                    record['code'] = 'transport_or_internal_failure'
                    raise Refusal('transport_or_internal_failure') from None
                finally:
                    # A trace-cap failure keeps the last checkpoint plus a bounded
                    # receipt for the attempted row, never an incomplete pass.
                    terminal['last_request_receipt'] = {key: value for key, value in record.items()
                                                       if key not in ('body_base64', 'request', 'observation')}
                    trace.append(record)
        verify(plan_sha256)
        publish(out, 'summary.json', {
            'schema': 'polymarket-no-basket-chain-metadata-summary-v2',
            'plan_sha256': plan_sha256, 'manifest_sha256': MANIFEST_SHA,
            'input_projection_sha256': PROJECTION['sha256'], 'event_id': EVENT,
            'status': 'metadata_mapping_compatible_conversion_unproven',
            'frozen_header': header, 'addresses': addresses, 'observations': observations,
            'compiled_source_equivalence': 'unverified', 'actual_conversion': 'unobserved',
            'trading_fees_delay_and_minimum_order_unit': 'unresolved',
        })
        terminal['status'] = 'metadata_mapping_compatible_conversion_unproven'
    finally:
        terminal.update(requests_attempted=budget['requests'], total_response_bytes=budget['bytes'],
                        passed_rpc_count=len(observations), frozen_header=header,
                        retained_trace_plaintext_bytes=len(trace.plaintext))
        target = out / 'trace.jsonl.gz'
        if target.exists():
            raw = metadata.bounded_read(target, LIMITS['retained_trace_gzip_bytes'])
            terminal.update(trace_gzip_bytes=len(raw), trace_gzip_sha256=sha(raw))


def worker(plan_sha256, out):
    terminal = {'schema': 'polymarket-no-basket-chain-metadata-terminal-v2',
                'plan_sha256': plan_sha256, 'manifest_sha256': MANIFEST_SHA,
                'started_utc': metadata.utc(), 'status': 'inconclusive', 'code': None,
                'requests_attempted': 0, 'passed_rpc_count': 0, 'total_response_bytes': 0}
    try:
        plan = verify(plan_sha256)
        collect(plan, plan_sha256, out, terminal)
    except Refusal as exc:
        terminal['code'] = str(exc)
    except Exception:
        terminal['code'] = 'internal_failure'
    finally:
        terminal['ended_utc'] = metadata.utc()
        try:
            verify(plan_sha256)
        except Exception:
            terminal['status'] = 'inconclusive'
            terminal['code'] = 'post_run_pin_check_failed'
        publish(out, 'terminal.json', terminal)


def supervise(process, deadline, out, plan_sha256):
    process.start()
    process.join(max(0, deadline - time.monotonic() - 1))
    expired = process.is_alive()
    if expired:
        process.kill()
        process.join(max(0, deadline - time.monotonic()))
    record = {'schema': 'polymarket-no-basket-chain-metadata-supervisor-v2',
              'plan_sha256': plan_sha256, 'ended_utc': metadata.utc(),
              'worker_exitcode': process.exitcode,
              'terminal_exists': (out / 'terminal.json').exists(),
              'status': 'process_deadline' if expired else 'worker_finished'}
    if not record['terminal_exists'] and not expired:
        record['status'] = 'worker_failed_without_terminal'
    publish(out, 'supervisor.json', record)
    return record


def run(plan_sha256):
    deadline = time.monotonic() + LIMITS['process_seconds']
    with metadata.hard_deadline(LIMITS['process_seconds'], 'process_deadline_before_claim'):
        verify(plan_sha256)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out, 'claim.json', {
        'schema': 'polymarket-no-basket-chain-metadata-claim-v2', 'started_utc': metadata.utc(),
        'plan_sha256': plan_sha256, 'manifest_sha256': MANIFEST_SHA,
        'input_projection_sha256': PROJECTION['sha256'], 'endpoint': ENDPOINT,
        'maximum_rpc_requests': 55, 'purpose': 'public_contract_metadata_only',
    })
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        result = {'status': 'dry_no_http', 'rpc_requests': 0, 'endpoint': ENDPOINT,
                  'maximum_rpc_requests': 55, 'manifest_sha256': MANIFEST_SHA}
    else:
        try:
            result = run(args.plan_sha256)
        except Refusal as exc:
            result = {'status': 'refused_no_retry', 'code': str(exc)}
        except FileExistsError:
            result = {'status': 'refused_no_retry', 'code': 'existing_output'}
        except Exception:
            result = {'status': 'failed_no_retry', 'code': 'internal_failure'}
    print(metadata.encoded(result).decode('ascii'), end='')
    return 0 if result['status'] in ('dry_no_http', 'worker_finished') else 1


if __name__ == '__main__':
    raise SystemExit(main())
