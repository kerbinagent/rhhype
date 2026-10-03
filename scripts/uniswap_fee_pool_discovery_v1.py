"""Fixed same-block V3 pool discovery for six inventory assets; default dry."""
import argparse
import hashlib
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'scripts/uniswap_fee_pool_discovery_v1.py'
TEST = 'tests/test_uniswap_fee_pool_discovery_v1.py'
BASE = 'reports/uniswap-fee-pool-discovery-v1/'
PLAN, DESIGN, OUT = (BASE+x for x in ('plan.json', 'design.txt', 'run-v1'))
NOTES = 'reports/uniswap-fee-harvest-feasibility-v1/source-notes.json'
ALLOCATION = 'reports/experiment-storage/uniswap-fee-pool-discovery-v1-cap-amendment.json'
ORIGINAL_ALLOCATION = 'reports/experiment-storage/uniswap-fee-pool-discovery-v1-allocation.json'
INVENTORY = 'reports/uniswap-fee-auction-inventory-v2/run-v1/projection.json'
REVIEW = 'reports/uniswap-fee-auction-inventory-v2/root-review.json'
HELPER = 'scripts/sky_psm_discovery_v1.py'
HELPER_SHA = 'c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
INVENTORY_PLAN_SHA = '3bd7fbd2edca1cb6ed63ceacfb331ca41e48855ae46a58e91a0ca7f7f78ed320'
ANCHOR_NUMBER = 26108195
ANCHOR_HASH = '0xb34142f46a23b8fb29f2f0a14a704bd10915891a566e718988a2e2555f68f9f4'
FACTORY = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
DIAGNOSTIC = '0x0000000000000000000000000000000000000001'
ADAPTERS = ['0x5e74c9f42eed283bff3744fbd1889d398d40867d',
            '0xf2371551fe3937db7c750f4dfabe5c2fffdcbf5a']
ASSETS = [
    ('WETH','0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'),
    ('USDC','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
    ('DAI','0x6b175474e89094c44da98b954eedeac495271d0f'),
    ('USDT','0xdac17f958d2ee523a2206206994597c13d831ec7'),
    ('WBTC','0x2260fac5e5542a773aa44fbcfedf7c193bc2c599'),
    ('UNI','0x1f9840a85d5af5bf1d1762f925bdaddc4201f984')]
FEES = [100,500,3000,10000]
PAIRS = [(i,j) for i in range(len(ASSETS)) for j in range(i+1,len(ASSETS))]
SLOTS = [('chain',4096),('anchor',32768),('owner',4096)] + [
    ('p%02d_%d' % (i,fee),4096) for i in range(len(PAIRS)) for fee in FEES
] + [('recheck',32768)]
CAPS = dict(requests=64,body_bytes=98304,raw_bytes=155648,request_bytes=8192,
            projection_bytes=8192,request_seconds=20,work_seconds=165,wall_seconds=180,
            cpu_seconds=20,ram_bytes=536870912,total_supplied_gas=18300000)


class Refusal(Exception):
    pass


path = ROOT/HELPER
if path.is_symlink() or not path.is_file():raise Refusal('helper_nonregular')
with path.open('rb') as f: raw = f.read(32769)
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise Refusal('immutable_helper')
m = types.ModuleType('fee_pool_helpers');m.__file__=str(path)
exec(compile(raw,m.__file__,'exec'),m.__dict__)
c,h,t,s,encode,decode,read,sha = m.c,m.h,m.t,m.s,m.encode,m.decode,m.read,m.sha


def reason(exc):return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


def inputs():
    inventory = decode(read(ROOT/INVENTORY,8192));review=decode(read(ROOT/REVIEW,1536))
    if (inventory.get('plan_sha256')!=INVENTORY_PLAN_SHA or inventory.get('status')!='fixed_inventory_complete'
            or review.get('status')!='passed' or review.get('plan_sha256')!=INVENTORY_PLAN_SHA
            or review.get('projection_sha256')!=sha(read(ROOT/INVENTORY,8192))
            or inventory['block']['number']!=ANCHOR_NUMBER or inventory['block']['hash']!=ANCHOR_HASH
            or inventory.get('documented_configuration_matches') is not True
            or inventory.get('expected_units_match') is not True
            or [(x['label'],x['address']) for x in inventory['inventory'][:6]]!=ASSETS
            or len(inventory['inventory'])!=7):raise Refusal('inventory_admission')
    return inventory


def address_result(value):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(status='unknown',address=None,error='rpc:'+str(value['rpc_unavailable']))
    try: address=c.address_word(value)
    except (m.Refusal,c.Refusal,h.Refusal,TypeError,ValueError):
        return dict(status='unknown',address=None,error='null_or_noncanonical')
    return dict(status='known',address=address,error=None)


def collect(rpc,inventory):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:raise Refusal('wrong_chain')
    anchor=rpc('anchor','eth_getBlockByNumber',[hex(ANCHOR_NUMBER),False])
    if c.header(anchor)!=inventory['block'] or s.o.context(anchor)!=inventory['context']:
        raise Refusal('inventory_anchor_changed')
    state=dict(blockHash=ANCHOR_HASH,requireCanonical=True)
    def call(name,signature,args):
        payload=s.selector(signature)+''.join(s.word_address(x) if isinstance(x,str) else format(x,'064x') for x in args)
        tx={'from':DIAGNOSTIC,'to':FACTORY,'input':payload,'value':'0x0',
            'gasPrice':'0x0','gas':hex(300000)}
        return rpc(name,'eth_call',[tx,state],allow_unavailable=True)
    owner=address_result(call('owner','owner()',[]))
    owner['status']=('unknown' if owner['status']=='unknown' else
                     'documented_adapter' if owner['address'] in ADAPTERS else 'other_owner')
    rows=[];by_address={}
    for pair_index,(i,j) in enumerate(PAIRS):
        for fee in FEES:
            value=address_result(call('p%02d_%d'%(pair_index,fee),'getPool(address,address,uint24)',
                                      [ASSETS[i][1],ASSETS[j][1],fee]))
            address=value['address']
            status=('?' if value['status']=='unknown' else '0' if int(address,16)==0 else 'p')
            rows.append([pair_index,fee,status,address if status=='p' else None,value['error']])
            if status=='p':by_address.setdefault(address,[]).append(len(rows)-1)
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[anchor['number'],False]),anchor)
    aliases=[[address,indexes] for address,indexes in by_address.items() if len(indexes)>1]
    return dict(schema='uniswap-fee-pool-discovery-projection-v1',status='fixed_pool_discovery_complete',
                anchor=inventory['block'],context=inventory['context'],factory=FACTORY,owner=owner,
                assets=ASSETS,pairs=PAIRS,fees=FEES,row_columns=['pair_index','fee','status','address','error'],
                status_legend={'p':'present','0':'absent','?':'unknown'},rows=rows,aliases=aliases,
                present=sum(x[2]=='p' for x in rows),absent=sum(x[2]=='0' for x in rows),
                unknown=sum(x[2]=='?' for x in rows),fixed_rows=60,
                factory_owner_is_not_runtime_adapter_proof=True,collection_not_simulated=True,
                pool_state_not_read=True,quotes_not_read=True,token_payments_verified=False,
                cash_closed=False,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw);required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,ORIGINAL_ALLOCATION,HELPER,INVENTORY,REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
            or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT
            or p.get('assets')!=[list(x) for x in ASSETS] or p.get('pairs')!=[list(x) for x in PAIRS]
            or p.get('fees')!=FEES or p.get('adapters')!=ADAPTERS or p.get('factory')!=FACTORY
            or p.get('anchor')!=dict(number=ANCHOR_NUMBER,hash=ANCHOR_HASH)
            or p.get('allocation')!=ALLOCATION
            or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):raise Refusal('frozen_scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],32768)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>24576:
        raise Refusal('source_package_cap')
    amendment=decode(read(ROOT/ALLOCATION,4096))
    if (amendment.get('raw_bytes')!=CAPS['raw_bytes']
            or amendment.get('total_experiment_reservation_bytes')!=204800
            or amendment.get('previous_global_allocation')!=dict(path=ORIGINAL_ALLOCATION,
                  sha256=sha(read(ROOT/ORIGINAL_ALLOCATION,4096)))):
        raise Refusal('allocation_amendment')
    if len(SLOTS)!=64 or len(PAIRS)!=15 or 61*300000!=CAPS['total_supplied_gas']:
        raise Refusal('request_or_gas_cap')
    for address in [FACTORY,DIAGNOSTIC]+ADAPTERS+[x[1] for x in ASSETS]:h.hexdata(address,20)
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):
        raise Refusal('output_symlink')
    return p


def replay(path,inventory):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,inventory);reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        p=verify(digest);inventory=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=p['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason);result=collect(capture.rpc,inventory)
                check,body,raw=replay(out/'raw',inventory)
                if result!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:
                    raise Refusal('exact_replay')
                verify(digest);result['plan_sha256']=digest
                s.o.publish(out,'projection.json',result,CAPS['projection_bytes']);status='fixed_pool_discovery_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_pool_discovery_complete' and error is None


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    group.add_argument('--run',action='store_true');group.add_argument('--replay',action='store_true')
    parser.add_argument('--plan-sha256');args=parser.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw',inputs())
        print(encode(dict(status=result['status'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run:print('dry: zero requests; zero outputs; fixed 60-pool lookup');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
