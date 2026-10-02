"""Fixed public LitePSM metadata/inventory and four-pool discovery; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/sky_psm_discovery_v1.py'
TEST = 'tests/test_sky_psm_discovery_v1.py'
BASE = 'reports/sky-psm-conversion-v1/'
PLAN, DESIGN, NOTES, OUT = (BASE+x for x in ('plan.json', 'design.txt', 'source-notes.json', 'run-v1'))
ALLOCATION = 'reports/experiment-storage/sky-psm-conversion-discovery-allocation-v1.json'
HELPER = 'scripts/aave_state_transition_v1.py'
HELPER_SHA = '9bb451c71b62a6ee67447cf991c795877e3431b6659dc1a8344345455c9cedd1'
PSM = '0xf6e72db5454dd049d0788e411b06cfaf16853042'
DAI = '0x6b175474e89094c44da98b954eedeac495271d0f'
USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
POCKET = '0x37305b1cd40574e4c5ce33f8e8306be057fd7341'
FACTORY = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
DIAGNOSTIC = '0x0000000000000000000000000000000000000001'
FEES = [100, 500, 3000, 10000]
WAD, HALTED = 10**18, 2**256-1
FIELDS = [
    ('gem', PSM, 'gem()', 'address', []),
    ('dai', PSM, 'dai()', 'address', []),
    ('pocket', PSM, 'pocket()', 'address', []),
    ('conversion', PSM, 'to18ConversionFactor()', 'uint', []),
    ('tin', PSM, 'tin()', 'fee', []),
    ('tout', PSM, 'tout()', 'fee', []),
    ('buf', PSM, 'buf()', 'uint', []),
    ('live', PSM, 'live()', 'boolean', []),
    ('dai_decimals', DAI, 'decimals()', 'decimal', []),
    ('usdc_decimals', USDC, 'decimals()', 'decimal', []),
    ('psm_dai_balance', DAI, 'balanceOf(address)', 'uint', [PSM]),
    ('pocket_usdc_balance', USDC, 'balanceOf(address)', 'uint', [POCKET]),
    ('pocket_usdc_allowance', USDC, 'allowance(address,address)', 'uint', [POCKET, PSM]),
]
SLOTS = [('chain', 4096), ('block', 65536)] + [(x[0], 4096) for x in FIELDS] + [
    ('pool_'+str(fee), 4096) for fee in FEES] + [('recheck', 65536)]
CAPS = dict(requests=20, body_bytes=131072, raw_bytes=163840, request_bytes=8192,
            projection_bytes=8192, request_seconds=20, work_seconds=165, wall_seconds=180,
            cpu_seconds=20, ram_bytes=536870912, total_supplied_gas=5100000)


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


raw = read(ROOT/HELPER, 32768)
if sha(raw) != HELPER_SHA:
    raise Refusal('immutable_helper')
s = types.ModuleType('psm_discovery_helpers')
s.__file__ = str(ROOT/HELPER)
exec(compile(raw, s.__file__, 'exec'), s.__dict__)
c, h, t, encode, decode = s.o.c, s.h, s.t, s.encode, s.decode


def reason(exc):
    return str(exc)[:160] if isinstance(exc, Refusal) else s.reason(exc)


def result(value, kind):
    if isinstance(value, dict) and 'rpc_unavailable' in value:
        return dict(available=False, reason='rpc_error', code=value['rpc_unavailable'])
    try:
        parsed = c.address_word(value) if kind in ('address', 'pool') else s.uint_word(value)
        if kind == 'address' and int(parsed, 16) == 0:
            raise Refusal('zero_identity_address')
        if kind == 'decimal' and int(parsed) >= 256:
            raise Refusal('decimal_width')
        if kind == 'boolean' and int(parsed) not in (0, 1):
            raise Refusal('boolean_width')
        if kind == 'fee' and int(parsed) > WAD and int(parsed) != HALTED:
            raise Refusal('fee_outside_source_range')
    except (Refusal, s.Refusal, c.Refusal, h.Refusal, TypeError, ValueError):
        return dict(available=False, reason='null_or_noncanonical_result')
    return dict(available=True, value=parsed)


def conditions(values):
    def compare(expected):
        if any(values[key]['available'] and values[key]['value'] != expected[key] for key in expected):
            return False
        if not all(values[key]['available'] for key in expected):
            return None
        return True
    identity = compare(dict(gem=USDC, dai=DAI, pocket=POCKET))
    units = compare(dict(conversion=str(10**12), dai_decimals='18', usdc_decimals='6'))
    def fee_open(name):
        value = values[name]
        return int(value['value']) != HALTED if value['available'] else None
    stock = {}
    for key in ('psm_dai_balance', 'pocket_usdc_balance', 'pocket_usdc_allowance'):
        stock[key] = int(values[key]['value']) > 0 if values[key]['available'] else None
    return dict(documented_identity_matches=identity, expected_units_match=units,
                sell_fee_not_halted=fee_open('tin'), buy_fee_not_halted=fee_open('tout'),
                positive_observed_inventory_or_allowance=stock,
                eligibility_or_executability_proved=False)


def collect(rpc):
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('wrong_chain')
    block = rpc('block', 'eth_getBlockByNumber', ['finalized', False])
    header, context = c.header(block), s.o.context(block)
    state = dict(blockHash=header['hash'], requireCanonical=True)
    def call(name, to, signature, args):
        data = s.selector(signature) + ''.join(s.word_address(x) if isinstance(x, str) else format(x, '064x') for x in args)
        tx = {'from': DIAGNOSTIC, 'to': to, 'input': data, 'value': '0x0',
              'gasPrice': '0x0', 'gas': hex(300000)}
        return rpc(name, 'eth_call', [tx, state], allow_unavailable=True)
    values = {name: result(call(name, target, signature, args), kind)
              for name, target, signature, kind, args in FIELDS}
    pools = []
    for fee in FEES:
        value = result(call('pool_'+str(fee), FACTORY, 'getPool(address,address,uint24)', [DAI, USDC, fee]), 'pool')
        pools.append(dict(fee=fee, result=value,
                          nonzero_address=(int(value['value'], 16) != 0 if value['available'] else None)))
    s.o.same_header(rpc('recheck', 'eth_getBlockByNumber', [block['number'], False]), block)
    return dict(schema='sky-psm-discovery-projection-v1', status='fixed_discovery_complete',
                block=header, context=context, psm=PSM, values=values, conditions=conditions(values),
                factory=FACTORY, pools=pools, calls_available=sum(v['available'] for v in values.values())+
                sum(x['result']['available'] for x in pools), fixed_call_slots=17,
                independent_state_calls=True, diagnostic_sender_control_claimed=False,
                runtime_equivalence_verified=False, token_transfer_verified=False,
                public_source_permission_is_not_runtime_proof=True, liquidity_or_price_measured=False,
                gas_cost_measured=False, obtainable_inclusion_verified=False, economics=False, repeatable_profit=False)


def verify(digest):
    raw = read(ROOT/PLAN, 8192)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    required = {SOURCE, TEST, DESIGN, NOTES, ALLOCATION, HELPER}
    if (p.get('status') != 'frozen' or p.get('caps') != CAPS or p.get('slots') != [list(x) for x in SLOTS]
            or p.get('runtime') != h.runtime() or p.get('output_dir') != OUT
            or p.get('fields') != [list(x) for x in FIELDS] or p.get('fees') != FEES
            or p.get('factory') != FACTORY or p.get('endpoint') != 'https://ethereum-rpc.publicnode.com'):
        raise Refusal('frozen_scope')
    pins = p.get('pins', [])
    if len(pins) != len(required) or {x.get('path') for x in pins} != required:
        raise Refusal('pins_schema')
    for pin in pins:
        data = read(ROOT/pin['path'], 65536)
        if len(data) != pin['bytes'] or sha(data) != pin['sha256']:
            raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE, TEST, DESIGN, NOTES)) > 32768:
        raise Refusal('source_package_cap')
    if 300000*(len(FIELDS)+len(FEES)) != CAPS['total_supplied_gas'] or len(SLOTS) != CAPS['requests']:
        raise Refusal('gas_or_request_cap')
    for address in (PSM, DAI, USDC, POCKET, FACTORY, DIAGNOSTIC):
        h.hexdata(address, 20)
    if any(p.is_symlink() for p in (ROOT/'reports', ROOT/BASE, ROOT/OUT)):
        raise Refusal('output_symlink')
    return p


def replay(path):
    reader = t.Reader(path, SLOTS, CAPS, c)
    p = collect(reader.rpc)
    reader.finish()
    return p, reader.body_bytes, reader.raw_bytes


def run(digest):
    started, capture = time.monotonic(), None
    status, error = 'unavailable', None
    with h.alarm(CAPS['wall_seconds']):
        plan = verify(digest)
        out = ROOT/OUT
        out.mkdir(exist_ok=False)
        s.o.publish(out, 'claim.json', dict(plan_sha256=digest, pins=plan['pins'], started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (CAPS['ram_bytes'], CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture = t.Capture(out/'raw', SLOTS, CAPS, c, started, reason)
                p = collect(capture.rpc)
                check, body, raw = replay(out/'raw')
                if p != check or body != capture.body_bytes or raw != capture.raw_bytes:
                    raise Refusal('exact_replay')
                verify(digest)
                p['plan_sha256'] = digest
                s.o.publish(out, 'projection.json', p, CAPS['projection_bytes'])
                status = 'fixed_discovery_complete'
        except BaseException as exc:
            error = reason(exc)
        finally:
            try:
                verify(digest)
            except Exception:
                status, error = 'unavailable', 'final_pin_mismatch'
            s.o.publish(out, 'terminal.json', dict(status=status, error=error, plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0, body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0, elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(), economics=False))
    return status == 'fixed_discovery_complete' and error is None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--run', action='store_true')
    g.add_argument('--replay', action='store_true')
    p.add_argument('--plan-sha256')
    args = p.parse_args()
    if args.replay:
        verify(args.plan_sha256)
        result, body, raw = replay(ROOT/OUT/'raw')
        print(encode(dict(status=result['status'], available=result['calls_available'], body_bytes=body, raw_bytes=raw)).decode())
        return 0
    if not args.run:
        print('dry: zero requests; zero outputs; fixed LitePSM and four fee-tier discovery')
        return 0
    return 0 if run(args.plan_sha256) else 1


if __name__ == '__main__':
    raise SystemExit(main())
