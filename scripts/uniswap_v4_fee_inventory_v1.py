"""Fixed-currency V4 accrued-fee inventory; discarded public call, default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/uniswap_v4_fee_inventory_v1.py'
TEST = 'tests/test_uniswap_v4_fee_inventory_v1.py'
BASE = 'reports/uniswap-v4-fee-inventory-v1/'
PLAN, DESIGN, NOTES, OUT = (BASE + x for x in ('plan.json', 'design.txt', 'source-notes.json', 'run-v1'))
ALLOCATION = 'reports/experiment-storage/uniswap-v4-fee-inventory-allocation-v1.json'
PREP = 'reports/experiment-storage/uniswap-v4-fee-inventory-preparation-v1.json'
SOURCE_GRANT = 'reports/experiment-storage/uniswap-v4-fee-inventory-source-allocation-v1.json'
HELPER = 'scripts/uniswap_v2_fee_harvest_v1.py'
HELPER_SHA = '0c06ac62e49f00d22da2b447bc10ef1edf6f86d53c04e1098b5c7420aac8cc0d'
ADAPTER = '0x89a5d5bf00a27d55c02951e49078a5c5771051db'
CONFIG_NAMES = ['manager', 'token_jar', 'controller', 'releaser', 'threshold', 'nonce']
SLOTS = [('chain', 4096), ('block', 32768)] + [(x, 1024) for x in CONFIG_NAMES] + [
    ('accrued_' + str(i), 1024) for i in range(20)] + [
    ('jar_' + str(i), 1024) for i in range(20)] + [('collect', 1024), ('recheck', 32768)]
CAPS = dict(requests=50, body_bytes=131072, raw_bytes=139264, request_bytes=8192,
            projection_bytes=8192, request_seconds=20, work_seconds=165, wall_seconds=180,
            cpu_seconds=20, ram_bytes=536870912, total_supplied_gas=16500000)
path = ROOT / HELPER
if path.is_symlink() or not path.is_file():
    raise RuntimeError('helper_path')
with path.open('rb') as f:
    raw = f.read(32769)
if len(raw) > 32768 or hashlib.sha256(raw).hexdigest() != HELPER_SHA:
    raise RuntimeError('helper_pin')
k = types.ModuleType('v4_fee_helpers')
k.__file__ = str(path)
exec(compile(raw, k.__file__, 'exec'), k.__dict__)
m, c, h, t, s, encode, decode, read, sha = k.m, k.c, k.h, k.t, k.s, k.encode, k.decode, k.read, k.sha
JAR, FIREPIT, ZERO, DIAGNOSTIC = k.JAR, k.FIREPIT, k.ZERO, k.DIAGNOSTIC


class Refusal(Exception):
    pass


def inputs():
    return k.inputs()


def collect_data(assets):
    # One dynamic array of static (address,uint256) tuples; amount0 collects all.
    return s.selector('collect((address,uint256)[])') + format(32, '064x') + format(len(assets), '064x') + ''.join(
        s.word_address(a) + '0' * 64 for a in assets)


def void_result(value):
    if isinstance(value, dict) and 'rpc_unavailable' in value:
        return dict(available=False, reason='rpc_error', code=value['rpc_unavailable'])
    return dict(available=True) if value == '0x' else dict(available=False, reason='unexpected_void_result')


def modeled_sum(balance, accrued, collection):
    if not collection['available'] or not balance['available'] or not accrued['available']:
        return None
    result = int(balance['value']) + int(accrued['value'])
    return str(result) if result <= 2**256 - 1 else None


def collect(rpc, assets):
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('chain')
    header = rpc('block', 'eth_getBlockByNumber', ['finalized', False])
    block, context = c.header(header), s.o.context(header)
    state = dict(blockHash=block['hash'], requireCanonical=True)

    def call(name, to, signature, args=(), data=None, gas=300000):
        if data is None:
            data = s.selector(signature) + ''.join(s.word_address(x) if isinstance(x, str) else format(x, '064x') for x in args)
        tx = dict(to=to, input=data, gas=hex(gas), gasPrice='0x0', value='0x0', **{'from': DIAGNOSTIC})
        return rpc(name, 'eth_call', [tx, state], allow_unavailable=True)

    config = dict(manager=m.result(call('manager', ADAPTER, 'POOL_MANAGER()'), 'address'),
                  token_jar=m.result(call('token_jar', ADAPTER, 'TOKEN_JAR()'), 'pool'))
    if not config['manager']['available']:
        raise Refusal('manager_identity_unavailable')
    manager = config['manager']['value']
    if manager in (ADAPTER, JAR, FIREPIT):
        raise Refusal('manager_identity_conflict')
    config['controller'] = m.result(call('controller', manager, 'protocolFeeController()'), 'pool')
    config['releaser'] = m.result(call('releaser', JAR, 'releaser()'), 'pool')
    config['threshold'] = m.result(call('threshold', FIREPIT, 'threshold()'), 'uint')
    config['nonce'] = m.result(call('nonce', FIREPIT, 'nonce()'), 'uint')
    for name, expected in [('token_jar', JAR), ('controller', ADAPTER), ('releaser', FIREPIT)]:
        if not config[name]['available']:
            raise Refusal('configuration_unknown_' + name)
        if config[name]['value'] != expected:
            raise Refusal('configuration_mismatch_' + name)
    accrued = [m.result(call('accrued_' + str(i), manager, 'protocolFeesAccrued(address)', [a]), 'uint') for i, a in enumerate(assets)]
    balances = []
    for i, address in enumerate(assets):
        name = 'jar_' + str(i)
        balance = k.native_value(rpc(name, 'eth_getBalance', [JAR, state], allow_unavailable=True)) if address == ZERO else m.result(
            call(name, address, 'balanceOf(address)', [JAR]), 'uint')
        balances.append(balance)
    collection = void_result(call('collect', ADAPTER, '', data=collect_data(assets), gas=3000000))
    check = rpc('recheck', 'eth_getBlockByNumber', [hex(block['number']), False])
    s.o.same_header(check, header)
    # Compact positional rows preserve unknown metadata while bounding projection size.
    rows = [[a, b, fee, modeled_sum(b, fee, collection)] for a, b, fee in zip(assets, balances, accrued)]
    return dict(schema='uniswap-v4-fee-inventory-projection-v1', status='fixed_v4_inventory_complete',
                block=block, context=context, configuration=config, configuration_matches=True,
                row_columns=['currency', 'jar_balance', 'protocol_fees_accrued', 'conditional_jar_sum'], rows=rows,
                collection_call=collection, collection_sends_to_jar=True, source_conditionals_not_observed_transfers=True,
                state_queries=47, eth_call_slots=46, complete_currency_census=False, old_state_combined=False,
                runtime_equivalence_verified=False, post_state_observed=False, source_amounts_not_cash=True,
                release_simulated=False, cash_closed=False, economics=False, repeatable_profit=False)


def required_paths():
    return [SOURCE, TEST, DESIGN, NOTES, ALLOCATION, PREP, SOURCE_GRANT, HELPER, k.HELPER,
            k.k.HELPER, k.EVENT_BODY, k.EVENT_RECEIPT, k.EVENT_REVIEW]


def verify(digest):
    raw = read(ROOT / PLAN, 8192)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    if (p.get('status') != 'frozen' or p.get('caps') != CAPS or p.get('slots') != [list(x) for x in SLOTS]
            or p.get('runtime') != h.runtime() or p.get('output_dir') != OUT or p.get('block_selector') != 'finalized'
            or p.get('endpoint') != 'https://ethereum-rpc.publicnode.com'):
        raise Refusal('scope')
    pins = p.get('pins', [])
    if len(pins) != len(required_paths()) or {x['path'] for x in pins} != set(required_paths()):
        raise Refusal('pins')
    for x in pins:
        data = read(ROOT / x['path'], 65536)
        if len(data) != x['bytes'] or sha(data) != x['sha256']:
            raise Refusal('input_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE, TEST, DESIGN, NOTES)) > 24576:
        raise Refusal('source_cap')
    a = decode(read(ROOT / ALLOCATION, 4096))
    expected = dict(source_tests_design_notes=24576, plan_and_claim=8192,
                    controls_reviews_readout=8192, projection=8192, raw=139264)
    if a['categories_bytes'] != expected or a['total_experiment_reservation_bytes'] != sum(expected.values()):
        raise Refusal('funding')
    if p.get('assets') != inputs() or p.get('adapter') != ADAPTER or p.get('jar') != JAR:
        raise Refusal('selection_identity')
    if any(x.is_symlink() for x in (ROOT / 'reports', ROOT / BASE, ROOT / OUT)):
        raise Refusal('output_symlink')
    return p


def reason(exc):
    return str(exc)[:160] if isinstance(exc, (Refusal, k.Refusal)) else m.reason(exc)


def replay(path, assets):
    r = t.Reader(path, SLOTS, CAPS, c)
    p = collect(r.rpc, assets)
    r.finish()
    return p, r.body_bytes, r.raw_bytes


def run(digest):
    started = time.monotonic()
    capture = None
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        verify(digest)
        assets = inputs()
        out = ROOT / OUT
        out.mkdir(exist_ok=False)
        s.o.publish(out, 'claim.json', dict(plan_sha256=digest, started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds'] - (time.monotonic() - started)):
                capture = t.Capture(out / 'raw', SLOTS, CAPS, c, started, reason)
                p = collect(capture.rpc, assets)
                check, body, raw = replay(out / 'raw', assets)
                if p != check or (body, raw) != (capture.body_bytes, capture.raw_bytes):
                    raise Refusal('replay')
                verify(digest)
                p['plan_sha256'] = digest
                s.o.publish(out, 'projection.json', p, CAPS['projection_bytes'])
                status = 'fixed_v4_inventory_complete'
        except BaseException as exc:
            error = reason(exc)
        finally:
            try:
                verify(digest)
            except Exception:
                status, error = 'unavailable', 'final_pin_mismatch'
            s.o.publish(out, 'terminal.json', dict(status=status, error=error, plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0, body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0, elapsed_milliseconds=int((time.monotonic() - started) * 1000),
                ended_ns=time.time_ns(), economics=False))
    return status == 'fixed_v4_inventory_complete' and error is None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--run', action='store_true')
    g.add_argument('--replay', action='store_true')
    p.add_argument('--plan-sha256')
    a = p.parse_args()
    if a.replay:
        verify(a.plan_sha256)
        v, b, r = replay(ROOT / OUT / 'raw', inputs())
        print(encode(dict(status=v['status'], body_bytes=b, raw_bytes=r)).decode())
        return 0
    if not a.run:
        print('dry: zero requests; V4 inventory and discarded public collection only')
        return 0
    return 0 if run(a.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
