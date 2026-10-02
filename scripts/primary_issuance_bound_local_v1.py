"""Fixed compiler-free issuance upper-bound screen; dry mode makes no HTTP.

The bound is conditional on the reviewed source arithmetic and runtime binding.
Sequential hypothetical transactions are not a composed sale or inclusion proof.
"""
import argparse
import base64
import datetime
import gzip
import hashlib
import multiprocessing
import os
from pathlib import Path
import platform
import re
import ssl
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
PLAN = 'reports/experiment-storage/primary-issuance-bound-local-v1.json'
SOURCE = 'scripts/primary_issuance_bound_local_v1.py'
TEST = 'tests/test_primary_issuance_bound_local_v1.py'
OUT = 'reports/primary-issuance-bound-local-v1'
ENDPOINT = 'https://ethereum-rpc.publicnode.com'
HELPER = dict(path='reports/peer-research/20261002-0846/peer_primary_issuance_preflight_v2.py',
              bytes=31282, sha256='7d43d16ecaac0c8cb72940beb11d434091fcd6c539d052f3d8327f1419da9ec4')
DESIGN = dict(path='reports/peer-research/20261002-0941/peer-primary-issuance-bound-design-v1.json',
              bytes=11247, sha256='3718dd5c2e05448dcfd51cce3e528d74efa4fda78dbca27da5559c14b7b76866')
PRIOR = dict(path='reports/peer-research/20261002-0910/root-receipt.json', bytes=3687,
             sha256='64addb0ce5f6a9f1a42c62f264c64e08fcadc9c70fc984f6e00aa4f1ee2fe8e8')
CAPS = dict(rpc_requests=19, request_seconds=12, minimum_start_spacing_seconds=1,
            process_seconds=180, response_bytes=131072, cumulative_response_bytes=1048576,
            trace_plaintext_bytes_in_memory=262144, trace_gzip_bytes=131072,
            gzip_copies_including_pending=2, derived_run_bytes=16384)
ARMS = (10**16, 10**17, 10**18, 10**19)
SENDER = '0x000000000000000000000000000000000000f103'
RECIPIENT = '0x000000000000000000000000000000000000f104'
LIDO = '0xae7ab96520de3a18e5e111b5eaab095312d7fe84'
IMPL = '0x028271e30a695c0527a0c50ca30603fed004cdb0'
CURVE = '0xdc24316b9ae028f1497c275eb9192a3ea0f67022'
NATIVE = '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
CODE_SHA = {LIDO: 'a0c39c8f8658ba7d2f91e20e81ca0ecf754ded062ee08b4f24c82902d98c2865',
            IMPL: 'c60a3b8430fbf46ed14f52c4d30b50c14c8eb359e041014d2936846d6fd01bb8',
            CURVE: '3a4e671f0d4c269a4d09a5ad616455d28f64fedeecc0044a44c00a5185041183'}
SELECTORS = dict(zip(('implementation()', 'proxyType()', 'getContractVersion()', 'decimals()',
    'isStakingPaused()', 'getCurrentStakeLimit()', 'coins(uint256)', 'fee()', 'admin_fee()',
    'getTotalShares()', 'getExternalShares()', 'getTotalPooledEther()', 'getExternalEther()',
    'getBufferedEther()', 'sharesOf(address)', 'submit(address)', 'balanceOf(address)',
    'get_dy(int128,int128,uint256)'), ('5c60da1b', '4555d5c9', '8aa10435', '313ce567',
    '1ea7ca89', '609c4c6c', 'c6610657', 'ddca3f43', 'fee3f7f9', 'd5002f2e', '63021d8b',
    '37cfdaca', 'e16a9065', '47b714e0', 'f5eb42dc', 'a1903eab', '70a08231', '5e0d443f')))
DOMAIN = ('getTotalShares()', 'getExternalShares()', 'getTotalPooledEther()',
          'getExternalEther()', 'getBufferedEther()', 'isStakingPaused()',
          'getCurrentStakeLimit()', 'fee()', 'admin_fee()')
LIMIT128 = 2**128


class Refusal(Exception):
    pass


class ArmUnavailable(Exception):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, cap):
    if path.is_symlink() or not path.is_file():
        raise Refusal('nonregular_pinned_file')
    with path.open('rb') as handle:
        raw = handle.read(cap + 1)
    if len(raw) > cap:
        raise Refusal('pinned_file_byte_cap')
    return raw


def pinned(pin, cap):
    raw = bounded(ROOT / pin['path'], cap)
    if len(raw) != pin['bytes'] or sha(raw) != pin['sha256']:
        raise Refusal('pinned_file_identity')
    return raw


# Loading the reviewed module invokes no old authorize/run function and writes no cache.
helper = types.ModuleType('issuance_reviewed_pure_helpers')
helper.__file__ = str(ROOT / HELPER['path'])
exec(compile(pinned(HELPER, 32768), helper.__file__, 'exec'), helper.__dict__)
encoded, decode, quantity = helper.encoded, helper.decode_json, helper.quantity


def runtime_identity():
    return dict(python_version=sys.version, python_executable=sys.executable,
                python_implementation=platform.python_implementation(), machine=platform.machine(),
                platform=platform.platform(), openssl=ssl.OPENSSL_VERSION)


def data(signature, *args):
    return '0x' + SELECTORS[signature] + ''.join(format(x, '064x') for x in args)


def transaction(nonce, target, payload, value=0):
    return dict(**{'from': SENDER}, to=target, input=payload, value=hex(value), nonce=hex(nonce),
                gas=hex(1000000), maxFeePerGas=hex(2000000000), maxPriorityFeePerGas=hex(1000000000))


def simulation(calls, number, timestamp):
    return [dict(blockStateCalls=[dict(blockOverrides=dict(number=number, time=timestamp,
        gasLimit=hex(30000000), baseFeePerGas=hex(1000000000), feeRecipient=RECIPIENT,
        withdrawals=[]), stateOverrides={SENDER: dict(balance=hex(11*10**18), nonce='0x0')},
        calls=calls)], validation=True, traceTransfers=False, returnFullTransactions=False), '$parent.number']


def build_manifest():
    """Exact templates; only parent-derived substitutions are allowed at runtime."""
    selector = dict(blockHash='$parent.hash', requireCanonical=True)
    manifest = [dict(method='eth_chainId', params=[]),
                dict(method='eth_getBlockByNumber', params=['latest', False])]
    for addr in (SENDER, RECIPIENT, LIDO):
        manifest.append(dict(method='eth_getCode', params=[addr, selector]))
    manifest.append(dict(method='eth_call', params=[dict(to=LIDO, data=data('implementation()')), selector]))
    for addr in (IMPL, CURVE):
        manifest.append(dict(method='eth_getCode', params=[addr, selector]))
    for target, signature, args in ((LIDO, 'proxyType()', ()), (LIDO, 'getContractVersion()', ()),
        (LIDO, 'decimals()', ()), (CURVE, 'coins(uint256)', (0,)), (CURVE, 'coins(uint256)', (1,))):
        manifest.append(dict(method='eth_call', params=[dict(to=target, data=data(signature, *args)), selector]))
    calls = [transaction(i, LIDO if i < 7 else CURVE, data(signature))
             for i, signature in enumerate(DOMAIN)]
    manifest.append(dict(method='eth_simulateV1', params=simulation(calls, '$child.number', '$child.time')))
    for principal in ARMS:
        args = [(LIDO, data('sharesOf(address)', int(SENDER, 16)), 0),
                (LIDO, data('submit(address)', 0), principal),
                (LIDO, data('balanceOf(address)', int(SENDER, 16)), 0),
                (CURVE, data('get_dy(int128,int128,uint256)', 1, 0, principal), 0),
                (CURVE, data('fee()'), 0)]
        calls = [transaction(i, *args[i]) for i in range(5)]
        manifest.append(dict(method='eth_simulateV1', params=simulation(calls, '$child.number', '$child.time')))
    manifest.append(dict(method='eth_getBlockByNumber', params=['$parent.number', False]))
    assert len(manifest) == 19
    return manifest


def resolve(value, parent):
    values = {'$parent.number': parent['number'], '$parent.hash': parent['hash'],
              '$child.number': hex(quantity(parent['number']) + 1),
              '$child.time': hex(quantity(parent['timestamp']) + 12)}
    if isinstance(value, str):
        return values.get(value, value)
    if isinstance(value, list):
        return [resolve(x, parent) for x in value]
    if isinstance(value, dict):
        return {k: resolve(v, parent) for k, v in value.items()}
    return value


def verify(plan_sha):
    if not isinstance(plan_sha, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha):
        raise Refusal('exact_plan_sha_required')
    raw = bounded(ROOT / PLAN, 32768)
    if sha(raw) != plan_sha:
        raise Refusal('plan_sha_mismatch')
    plan = decode(raw)
    if (plan.get('schema') != 'primary-issuance-bound-local-v1'
        or plan.get('status') != 'frozen_primary_issuance_bound' or plan.get('endpoint') != ENDPOINT
        or plan.get('output_dir') != OUT or plan.get('resource_limits') != CAPS
        or plan.get('fixed_principals_wei') != [str(x) for x in ARMS]
        or plan.get('domain_views') != list(DOMAIN)
        or plan.get('design') != DESIGN or plan.get('prior_metadata_receipt') != PRIOR
        or plan.get('runtime') != runtime_identity()
        or plan.get('request_manifest') != build_manifest()):
        raise Refusal('frozen_scope_or_runtime_mismatch')
    pins = plan.get('source_pins', [])
    required = {SOURCE, TEST, HELPER['path'], DESIGN['path'], PRIOR['path']}
    if not isinstance(pins, list) or len(pins) != 5 or {x.get('path') for x in pins} != required:
        raise Refusal('exact_source_test_transitive_pins_required')
    cap_by_path = {SOURCE:32768, TEST:16384, HELPER['path']:32768, DESIGN['path']:16384, PRIOR['path']:8192}
    for pin in pins:
        if set(pin) != {'path', 'bytes', 'sha256'} or type(pin['bytes']) is not int:
            raise Refusal('pin_schema_mismatch')
        pinned(pin, cap_by_path[pin['path']])
    for fixed in (HELPER, DESIGN, PRIOR):
        if next(x for x in pins if x['path'] == fixed['path']) != fixed:
            raise Refusal('fixed_dependency_pin_mismatch')
    receipt = decode(pinned(PRIOR, 8192))
    if receipt.get('status') != 'metadata_compatibility_confirmed_full_route_unproven':
        raise Refusal('prior_metadata_binding_unavailable')
    if (ROOT / OUT).is_symlink():
        raise Refusal('symlink_output')
    return plan


def utc(ns):
    return datetime.datetime.fromtimestamp(ns / 10**9, datetime.timezone.utc).isoformat()


def publish(out, name, value):
    body = encoded(value) + b'\n'
    identities = {}
    for path in out.iterdir():
        if path.is_file() and (path.name.endswith('.json') or path.name.endswith('.json.pending')):
            stat = path.stat()
            identities[stat.st_dev, stat.st_ino] = stat.st_size
    used = sum(identities.values())
    if len(body) > 10000 or used + len(body) > CAPS['derived_run_bytes']:
        raise Refusal('derived_receipt_cap')
    pending = out / (name + '.pending')
    with pending.open('xb') as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(pending, out / name)
    finally:
        pending.unlink()


class Trace:
    def __init__(self, out):
        self.out, self.records = out, []

    def checkpoint(self, records):
        body = encoded(records)
        if len(body) > CAPS['trace_plaintext_bytes_in_memory'] - 4096:
            raise Refusal('trace_plaintext_cap')
        packed = gzip.compress(body, mtime=0)
        if len(packed) > CAPS['trace_gzip_bytes']:
            raise Refusal('trace_gzip_cap')
        pending = self.out / 'trace.pending.gz'
        with pending.open('xb') as handle:
            handle.write(packed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, self.out / 'trace.json.gz')
        self.records = records

    def put(self, record, replace=False):
        records = self.records[:-1] + [record] if replace else self.records + [record]
        try:
            self.checkpoint(records)
        except Refusal:
            limited = dict(record)
            raw = base64.b64decode(limited.pop('response_body_base64', ''))
            prefix = raw[:1024]
            limited.update(response_body_base64=base64.b64encode(prefix).decode(),
                           body_retained_bytes=len(prefix), retained_body_sha256=sha(prefix),
                           body_retention='prefix_trace_resource_cap')
            self.checkpoint((self.records[:-1] if replace else self.records) + [limited])
            raise Refusal('trace_resource_cap')


def unknown_arms(reason='future_unavailable'):
    return [dict(principal_wei=str(x), status='unavailable', reason=reason,
                 upper_payout_wei=None, optimistic_margin_wei=None, nonpositive_bound=None) for x in ARMS]


def check_child(value, parent, count):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise Refusal('simulation_child_shape')
    child = value[0]
    if (quantity(child.get('number')) != quantity(parent['number']) + 1
        or child.get('parentHash', '').lower() != parent['hash'].lower()
        or quantity(child.get('timestamp')) != quantity(parent['timestamp']) + 12
        or quantity(child.get('baseFeePerGas')) != 1000000000
        or quantity(child.get('gasLimit')) != 30000000
        or child.get('miner', '').lower() != RECIPIENT or child.get('withdrawals') != []):
        raise Refusal('simulation_child_context_mismatch')
    calls = child.get('calls')
    if not isinstance(calls, list) or len(calls) != count:
        raise Refusal('simulation_receipt_count')
    gas = []
    for call in calls:
        if not isinstance(call, dict):
            raise Refusal('simulation_receipt_shape')
        status = quantity(call.get('status'))
        used = quantity(call.get('gasUsed'))
        helper.hex_data(call.get('returnData'))
        if status not in (0, 1) or not 21000 <= used <= 1000000:
            raise Refusal('simulation_status_or_gas')
        gas.append(used)
        if status == 0:
            if not isinstance(call.get('error'), dict):
                raise Refusal('simulation_failure_without_error')
        elif call.get('error') is not None:
            raise Refusal('simulation_success_with_error')
    if quantity(child.get('gasUsed')) != sum(gas):
        raise Refusal('simulation_gas_sum')
    return calls, gas


def domain_values(value, parent):
    calls, _ = check_child(value, parent, 9)
    if any(quantity(x['status']) != 1 for x in calls):
        raise Refusal('domain_view_failed')
    numbers = [helper.abi_uint(x['returnData']) for x in calls]
    total, external, pooled, ext_ether, buffer, paused, limit, fee, admin = numbers
    if (not 0 <= external < total < LIMIT128 or not pooled > ext_ether >= 0
        or buffer >= LIMIT128 or paused not in (0, 1) or fee > 10**10 or admin > 10**10):
        raise Refusal('domain_invalid')
    return dict(total_shares=total, external_shares=external, internal_shares=total-external,
                internal_ether=pooled-ext_ether, buffered_ether=buffer,
                staking_paused=bool(paused), stake_limit=limit, fee=fee, admin_fee=admin)


def arm_domain(principal, domain):
    m = principal * domain['internal_shares'] // domain['internal_ether']
    if (principal >= LIMIT128 - 1 or domain['buffered_ether'] + principal >= LIMIT128
        or domain['total_shares'] + m >= LIMIT128 or domain['staking_paused']
        or principal > domain['stake_limit']):
        raise ArmUnavailable('issuance_domain_or_eligibility')
    return m


def arm_result(value, parent, principal, domain):
    m = arm_domain(principal, domain)
    calls, gas = check_child(value, parent, 5)
    if any(quantity(x['status']) != 1 for x in calls):
        raise ArmUnavailable('simulation_call_failed')
    initial, minted, balance, quote, fee = [helper.abi_uint(x['returnData']) for x in calls]
    predicted = m * (domain['internal_ether'] + principal) // (domain['internal_shares'] + m)
    if initial != 0 or minted != m or balance != predicted or balance > principal:
        raise ArmUnavailable('issuance_model_or_initial_shares_mismatch')
    if fee > 10**10 or fee != domain['fee']:
        raise ArmUnavailable('fee_invalid_or_changed')
    upper = quote + 1
    return dict(principal_wei=str(principal), status='valid_conditional_bound', reason=None,
                minted_shares=str(minted), displayed_balance_wei=str(balance), quote_wei=str(quote),
                upper_payout_wei=str(upper), optimistic_margin_wei=str(upper-principal),
                nonpositive_bound=upper <= principal, simulated_call_gas=gas)


class Study:
    def __init__(self, out, plan_sha, deadline, transport=helper.http_transport,
                 clock=time.monotonic, sleep=time.sleep, wall=time.time_ns):
        self.out, self.plan_sha, self.deadline = out, plan_sha, deadline
        self.transport, self.clock, self.sleep, self.wall = transport, clock, sleep, wall
        self.trace = Trace(out)
        self.manifest = build_manifest()
        self.attempts = self.total_bytes = 0
        self.last_start = None
        self.arms = unknown_arms()
        self.parent = self.domain = None
        self.final_parent_verified = False
        self.decision_ns = self.decision_mono = None

    def remaining(self):
        remain = self.deadline - self.clock()
        if remain <= 0:
            raise Refusal('request_work_deadline')
        return remain

    def rpc(self, index):
        item = self.manifest[index]
        item = resolve(item, self.parent) if self.parent is not None else item
        cap = min(CAPS['response_bytes'], CAPS['cumulative_response_bytes'] - self.total_bytes)
        if cap <= 0 or self.attempts >= 19:
            raise Refusal('request_or_cumulative_cap')
        record = dict(id=index+1, request=dict(jsonrpc='2.0', id=index+1, **item),
                      request_attempted=None, outcome='admitted_request_dispatch_unresolved')
        self.trace.put(record)
        if self.last_start is not None:
            delay = self.last_start + 1 - self.clock()
            if delay > 0:
                self.sleep(min(delay, self.remaining()))
        self.remaining()
        if index in range(14,18) and self.clock() < self.decision_mono + 0.4:
            self.sleep(min(self.decision_mono + 0.4 - self.clock(), self.remaining()))
        self.remaining()
        start = self.clock()
        timeout = min(12, self.remaining())
        self.last_start = start
        self.attempts += 1
        record.update(request_attempted=True, request_start_monotonic=start,
                      request_start_utc=utc(self.wall()), read_limit_bytes=cap)
        status, raw, error = None, b'', None
        try:
            status, raw = self.transport(record['request'], timeout, cap)
        except helper.TransportError as exc:
            status, raw, error = exc.status, exc.partial, 'transport_failure'
        except Exception:
            error = 'transport_failure'
        if not isinstance(raw, bytes) or len(raw) > cap:
            raw, error = b'', 'transport_read_contract_violation'
        self.total_bytes += len(raw)
        ended, wall = self.clock(), self.wall()
        record.update(http_status=status, response_bytes=len(raw), response_sha256=sha(raw),
                      response_body_base64=base64.b64encode(raw).decode(), body_retained_bytes=len(raw),
                      retained_body_sha256=sha(raw), body_retention='all_received_bytes',
                      receipt_monotonic=ended, receipt_utc=utc(wall), duration_seconds=ended-start,
                      outcome='received' if error is None else error)
        self.trace.put(record, replace=True)
        if error or status != 200 or len(raw) >= cap or ended-start > timeout:
            raise Refusal(error or 'transport_status_time_or_unproven_eof_boundary')
        self.remaining()
        try:
            obj = decode(raw)
        except Exception:
            raise Refusal('malformed_rpc_json') from None
        if (not isinstance(obj, dict) or obj.get('jsonrpc') != '2.0' or type(obj.get('id')) is not int
            or obj['id'] != index+1 or 'error' in obj or 'result' not in obj):
            raise Refusal('rpc_envelope_or_error')
        self.last_receipt_wall, self.last_receipt_mono = wall, ended
        return obj['result']

    def execute(self):
        if self.rpc(0) != '0x1':
            raise Refusal('chain_identity')
        self.parent = helper.header(self.rpc(1))
        self.decision_ns, self.decision_mono = self.last_receipt_wall, self.last_receipt_mono
        if quantity(self.parent['number']) >= 2**64-1 or quantity(self.parent['timestamp']) > 2**64-13:
            raise Refusal('child_number_or_time_uint64_domain')
        if (quantity(self.parent['timestamp'])+12)*10**9 < self.decision_ns + 400000000:
            raise Refusal('fixed_child_before_decision_delay_floor')
        for index, address in ((2,SENDER), (3,RECIPIENT), (4,LIDO)):
            raw = helper.hex_data(self.rpc(index))
            if (address in (SENDER,RECIPIENT) and raw) or (address == LIDO and sha(raw) != CODE_SHA[address]):
                raise Refusal('sender_fee_recipient_or_proxy_code_identity')
        if helper.abi_address(self.rpc(5)) != IMPL:
            raise Refusal('implementation_identity')
        for index, address in ((6,IMPL),(7,CURVE)):
            if sha(helper.hex_data(self.rpc(index))) != CODE_SHA[address]:
                raise Refusal('implementation_or_pool_code_identity')
        for index, expected in ((8,2),(9,4),(10,18)):
            if helper.abi_uint(self.rpc(index)) != expected:
                raise Refusal('proxy_type_version_or_decimals_identity')
        for index, expected in ((11,NATIVE),(12,LIDO)):
            if helper.abi_address(self.rpc(index)) != expected:
                raise Refusal('pool_coin_identity')
        self.domain = domain_values(self.rpc(13), self.parent)
        for k, principal in enumerate(ARMS):
            # Always issue all four fixed arm requests. Each failed receipt stays unknown.
            value = self.rpc(14+k)
            try:
                self.arms[k] = arm_result(value, self.parent, principal, self.domain)
            except ArmUnavailable as exc:
                self.arms[k]['reason'] = str(exc)
        final = helper.header(self.rpc(18))
        if final != self.parent:
            raise Refusal('final_parent_changed')
        self.final_parent_verified = True

    def summary(self, status, code, pins_valid):
        admitted = pins_valid and self.final_parent_verified
        rows = self.arms if admitted else unknown_arms(code or 'run_binding_unavailable')
        return dict(schema='primary-issuance-bound-local-summary-v1', plan_sha256=self.plan_sha,
            status=status, code=code, arms=rows, scheduled_arms=4,
            valid_arms=sum(x['status']=='valid_conditional_bound' for x in rows),
            all_four_nonpositive=admitted and all(x['nonpositive_bound'] is True for x in rows),
            parent=self.parent, final_parent_verified=self.final_parent_verified, source_pins_verified=pins_valid,
            decision_utc=utc(self.decision_ns) if self.decision_ns is not None else None,
            child_timestamp=hex(quantity(self.parent['timestamp'])+12) if self.parent is not None else None,
            domain={k:str(v) if type(v) is int else v for k,v in self.domain.items()} if self.domain else None,
            requests_attempted=self.attempts, total_response_bytes=self.total_bytes,
            source_runtime_equivalence_proven=False, full_route_proven=False,
            interpretation='Conditional source-model upper bound. Positive margin only fails to reject; unavailable is not negative.',
            limitations=['numeric_parent_reorg_out_and_back_not_excluded',
                'hypothetical_child_no_unrelated_transactions_no_obtainable_inclusion_claim',
                'simulated_view_transaction_gas_is_not_composed_route_cost',
                'no_exchange_approval_flatness_or_closed_cash_execution'])


def worker(plan_sha, out, deadline):
    study = Study(out, plan_sha, deadline)
    status, code, pins_valid = 'inconclusive', None, False
    try:
        verify(plan_sha)
        with helper.hard_timeout(max(0.000001, deadline-time.monotonic())):
            study.execute()
        status = 'fixed_arm_screen_finished'
    except Refusal as exc:
        code = str(exc)
    except Exception:
        code = 'bounded_worker_failure'
    finally:
        try:
            verify(plan_sha)
            pins_valid = True
        except Exception:
            status, code = 'inconclusive', 'post_run_pin_check_failed'
        publish(out, 'summary.json', study.summary(status, code, pins_valid))
        terminal = dict(schema='primary-issuance-bound-local-terminal-v1', plan_sha256=plan_sha,
                        status=status, code=code, requests_attempted=study.attempts,
                        total_response_bytes=study.total_bytes)
        trace = out / 'trace.json.gz'
        if trace.exists():
            raw = bounded(trace, CAPS['trace_gzip_bytes'])
            terminal.update(trace_bytes=len(raw), trace_sha256=sha(raw))
        publish(out, 'terminal.json', terminal)


def run(plan_sha):
    with helper.hard_timeout(180):
        return _run(plan_sha, time.monotonic())


def _run(plan_sha, began):
    plan = verify(plan_sha)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out, 'claim.json', dict(schema='primary-issuance-bound-local-claim-v1', plan_sha256=plan_sha,
        source_pins=plan['source_pins'], request_manifest_sha256=sha(encoded(build_manifest())),
        claimed_utc=utc(time.time_ns()), modeled_sender_funding_wei=str(11*10**18),
        source_runtime_equivalence_proven=False, scheduled_arms=4))
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha,out,began+170))
    process.start()
    process.join(max(0,began+179-time.monotonic()))
    expired = process.is_alive()
    if expired:
        process.kill()
        process.join(max(0,began+180-time.monotonic()))
    terminal_exists = (out/'terminal.json').exists()
    if not (out/'summary.json').exists():
        publish(out, 'summary.json', dict(schema='primary-issuance-bound-local-summary-v1', plan_sha256=plan_sha,
            status='interrupted_observations_unresolved', arms=unknown_arms('worker_interrupted'), scheduled_arms=4,
            valid_arms=0, all_four_nonpositive=False, requests_attempted=None,
            source_runtime_equivalence_proven=False, full_route_proven=False))
    if not terminal_exists:
        publish(out, 'terminal.json', dict(schema='primary-issuance-bound-local-terminal-v1', plan_sha256=plan_sha,
            status='process_deadline' if expired else 'worker_failed_without_terminal', requests_attempted=None,
            total_response_bytes=None))
    result = dict(schema='primary-issuance-bound-local-supervisor-v1', plan_sha256=plan_sha,
                  status='process_deadline' if expired else 'worker_finished' if process.exitcode==0 and terminal_exists
                  else 'worker_failed_without_terminal', worker_exitcode=process.exitcode,
                  original_terminal_exists=terminal_exists)
    publish(out, 'supervisor.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        result = dict(status='dry_no_http', http_requests=0, scheduled_arms=4, maximum_rpc_requests=19,
                      request_manifest_sha256=sha(encoded(build_manifest())))
    else:
        try:
            result = run(args.plan_sha256)
        except FileExistsError:
            result = dict(status='refused_no_retry', code='existing_output')
        except Refusal as exc:
            result = dict(status='refused_no_retry', code=str(exc))
        except Exception:
            result = dict(status='failed_no_retry', code='internal_failure')
    print(encoded(result).decode(), flush=True)
    return 0 if result['status'] in ('dry_no_http','worker_finished') else 1


if __name__ == '__main__':
    raise SystemExit(main())
