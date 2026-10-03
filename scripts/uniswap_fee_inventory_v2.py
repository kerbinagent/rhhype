"""One fixed public fee-basket inventory, with no release or trade; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/uniswap_fee_inventory_v2.py'
TEST = 'tests/test_uniswap_fee_inventory_v2.py'
BASE = 'reports/uniswap-fee-auction-inventory-v2/'
PLAN, DESIGN, NOTES, OUT = (BASE+x for x in ('plan.json', 'design.txt', 'source-notes.json', 'run-v1'))
ALLOCATION = 'reports/experiment-storage/uniswap-fee-auction-inventory-v2-allocation.json'
NOTES = 'reports/uniswap-fee-auction-v1/source-notes.json'
PREDECESSOR = 'reports/uniswap-fee-auction-v1/root-review.json'
HELPER = 'scripts/sky_psm_discovery_v1.py'
HELPER_SHA = 'c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
FIREPIT = '0x0d5cd355e2abeb8fb1552f56c965b867346d6721'
JAR = '0xf38521f130fccf29db1961597bc5d2b60f995f85'
UNI = '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984'
BURN = '0x000000000000000000000000000000000000dead'
DIAGNOSTIC = '0x0000000000000000000000000000000000000001'
ASSETS = [
    ('WETH', '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', 18),
    ('USDC', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 6),
    ('DAI', '0x6b175474e89094c44da98b954eedeac495271d0f', 18),
    ('USDT', '0xdac17f958d2ee523a2206206994597c13d831ec7', 6),
    ('WBTC', '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599', 8),
    ('UNI', UNI, 18),
]
FIELDS = [
    ('resource', FIREPIT, 'RESOURCE()', 'address', []),
    ('resource_recipient', FIREPIT, 'RESOURCE_RECIPIENT()', 'address', []),
    ('token_jar', FIREPIT, 'TOKEN_JAR()', 'address', []),
    ('threshold', FIREPIT, 'threshold()', 'uint', []),
    ('nonce', FIREPIT, 'nonce()', 'uint', []),
    ('max_release_length', FIREPIT, 'MAX_RELEASE_LENGTH()', 'uint', []),
    ('releaser', JAR, 'releaser()', 'address', []),
] + [item for label, address, decimals in ASSETS for item in (
    (label+'_decimals', address, 'decimals()', 'decimal', []),
    (label+'_balance', address, 'balanceOf(address)', 'uint', [JAR]))]
SLOTS = [('chain', 4096), ('block', 65536)] + [(x[0], 4096) for x in FIELDS] + [('ETH_balance', 4096), ('recheck', 65536)]
CAPS = dict(requests=23, body_bytes=147456, raw_bytes=196608, request_bytes=8192,
            projection_bytes=8192, request_seconds=20, work_seconds=165, wall_seconds=180,
            cpu_seconds=20, ram_bytes=536870912, total_supplied_gas=5700000)


class Refusal(Exception):
    pass


path = ROOT/HELPER
if path.is_symlink() or not path.is_file():
    raise Refusal('nonregular_helper')
with path.open('rb') as f:
    raw = f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:
    raise Refusal('immutable_helper')
m = types.ModuleType('fee_inventory_helpers')
m.__file__ = str(path)
exec(compile(raw, m.__file__, 'exec'), m.__dict__)
c, h, t, s, encode, decode, read, sha = m.c, m.h, m.t, m.s, m.encode, m.decode, m.read, m.sha


def reason(exc):
    return str(exc)[:160] if isinstance(exc, Refusal) else m.reason(exc)


def compare(values, expected):
    if any(values[k]['available'] and values[k]['value']!=v for k,v in expected.items()):
        return False
    if not all(values[k]['available'] for k in expected):
        return None
    return True


def native_result(value):
    if isinstance(value, dict) and 'rpc_unavailable' in value:
        return dict(available=False, reason='rpc_error', code=value['rpc_unavailable'])
    try:
        n = h.quantity(value)
        if n >= 2**256:
            raise Refusal('balance_width')
    except (Refusal, h.Refusal, TypeError, ValueError):
        return dict(available=False, reason='null_or_noncanonical_quantity')
    return dict(available=True, value=str(n))


def collect(rpc):
    if h.quantity(rpc('chain', 'eth_chainId', [])) != 1:
        raise Refusal('wrong_chain')
    block = rpc('block', 'eth_getBlockByNumber', ['finalized', False])
    header, context = c.header(block), s.o.context(block)
    state = dict(blockHash=header['hash'], requireCanonical=True)
    values = {}
    for name, target, signature, kind, args in FIELDS:
        data = s.selector(signature)+''.join(s.word_address(x) for x in args)
        tx = {'from': DIAGNOSTIC, 'to': target, 'input': data, 'value': '0x0',
              'gasPrice': '0x0', 'gas': hex(300000)}
        values[name] = m.result(rpc(name, 'eth_call', [tx, state], allow_unavailable=True), kind)
    values['ETH_balance'] = native_result(rpc('ETH_balance', 'eth_getBalance', [JAR, state], allow_unavailable=True))
    s.o.same_header(rpc('recheck', 'eth_getBlockByNumber', [block['number'], False]), block)
    identity = compare(values, dict(resource=UNI, resource_recipient=BURN, token_jar=JAR,
                                   releaser=FIREPIT, max_release_length='20'))
    units = compare(values, {label+'_decimals':str(decimals) for label,address,decimals in ASSETS})
    inventory = [dict(label=label, address=address, expected_decimals=decimals,
                     decimals=values[label+'_decimals'], balance=values[label+'_balance'])
                 for label,address,decimals in ASSETS]
    inventory.append(dict(label='ETH', address='0x'+'0'*40, expected_decimals=18,
                          decimals=dict(available=True, value='18'), balance=values['ETH_balance']))
    return dict(schema='uniswap-fee-inventory-projection-v2', status='fixed_inventory_complete',
                block=header, context=context, firepit=FIREPIT, token_jar=JAR,
                configuration={key:values[key] for key,_,_,_,_ in FIELDS[:7]},
                inventory=inventory, documented_configuration_matches=identity, expected_units_match=units,
                calls_available=sum(v['available'] for v in values.values()), fixed_inventory_view_slots=20,
                selection='Six fixed ERC20 candidates plus native ETH; not an all-token census',
                balance_is_not_release_proof=True, runtime_source_correspondence_verified=False,
                release_simulated=False, token_payments_verified=False, transaction_gas_measured=False,
                basket_valued=False, cash_closed=False, economics=False, repeatable_profit=False)


def verify(digest):
    raw = read(ROOT/PLAN, 8192)
    if sha(raw) != digest:
        raise Refusal('plan_sha_required')
    p = decode(raw)
    required = {SOURCE, TEST, DESIGN, NOTES, ALLOCATION, HELPER, PREDECESSOR}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
            or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
            or p.get('fields')!=[list(x) for x in FIELDS] or p.get('assets')!=[list(x) for x in ASSETS]
            or p.get('firepit')!=FIREPIT or p.get('token_jar')!=JAR
            or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):
        raise Refusal('frozen_scope')
    pins=p.get('pins', [])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:
        raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'], 32768)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:
            raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>32768:
        raise Refusal('source_package_cap')
    if 300000*len(FIELDS)!=CAPS['total_supplied_gas'] or len(SLOTS)!=CAPS['requests']:
        raise Refusal('gas_or_request_cap')
    if len(ASSETS)+1>20 or len({x[1] for x in ASSETS})!=len(ASSETS):
        raise Refusal('basket_scope')
    for address in [FIREPIT,JAR,UNI,BURN,DIAGNOSTIC]+[x[1] for x in ASSETS]:
        h.hexdata(address,20)
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):
        raise Refusal('output_symlink')
    return p


def replay(path):
    reader=t.Reader(path,SLOTS,CAPS,c)
    p=collect(reader.rpc)
    reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None
    status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        plan=verify(digest)
        out=ROOT/OUT
        out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=plan['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason)
                p=collect(capture.rpc)
                check,body,raw=replay(out/'raw')
                if p!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:
                    raise Refusal('exact_replay')
                verify(digest)
                p['plan_sha256']=digest
                s.o.publish(out,'projection.json',p,CAPS['projection_bytes'])
                status='fixed_inventory_complete'
        except BaseException as exc:
            error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_inventory_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true')
    g.add_argument('--replay',action='store_true')
    p.add_argument('--plan-sha256')
    a=p.parse_args()
    if a.replay:
        verify(a.plan_sha256)
        result,body,raw=replay(ROOT/OUT/'raw')
        print(encode(dict(status=result['status'],body_bytes=body,raw_bytes=raw)).decode())
        return 0
    if not a.run:
        print('dry: zero requests; zero outputs; fixed seven-asset fee inventory')
        return 0
    return 0 if run(a.plan_sha256) else 1


if __name__=='__main__':
    raise SystemExit(main())
