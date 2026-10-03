"""Fixed exact-output DAI/USDC round-trip quote matrix; default dry."""
import argparse
from pathlib import Path
import resource
import sys
import time
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/sky_psm_discovery_v1.py'
HELPER_SHA = 'c83d1946f39ea4879029e51af6fe19fd3cee35444b969de16131370aa7230bb7'
SOURCE, TEST = 'scripts/sky_psm_quotes_v1.py', 'tests/test_sky_psm_quotes_v1.py'
BASE = 'reports/sky-psm-fixed-quotes-v1/'
PLAN, DESIGN, NOTES, OUT = (BASE+x for x in ('plan.json', 'design.txt', 'source-notes.json', 'run-v1'))
ALLOCATION = 'reports/experiment-storage/sky-psm-fixed-quotes-allocation-v1.json'
ORIGINAL_PLAN = 'reports/sky-psm-conversion-v1/plan.json'
ORIGINAL_SHA = '00e38932a4f509d107d2f1c5cd86ab955cf6291c97eb5dc3589b8b6299d5e48d'
ORIGINAL_PROJECTION = 'reports/sky-psm-conversion-v1/run-v1/projection.json'
ORIGINAL_TERMINAL = 'reports/sky-psm-conversion-v1/run-v1/terminal.json'
ORIGINAL_REVIEW = 'reports/sky-psm-conversion-v1/root-review.json'
QUOTER = '0x61ffe014ba17989e743c5f6cb21bf9697530b21e'
LOTS = [1000, 10000, 100000, 1000000]
DIRECTIONS = ['dai_cycle', 'usdc_cycle']
SIGNATURE = 'quoteExactOutputSingle((address,address,uint256,uint24,uint160))'
CAPS = dict(requests=52, body_bytes=65536, raw_bytes=114688, request_bytes=8192,
            projection_bytes=24576, request_seconds=20, work_seconds=165, wall_seconds=180,
            cpu_seconds=20, ram_bytes=536870912, total_supplied_gas=101100000)


class Refusal(Exception):
    pass


raw = (ROOT/HELPER).read_bytes()
import hashlib
if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=HELPER_SHA:
    raise Refusal('immutable_helper')
m = types.ModuleType('sky_quote_helpers')
m.__file__ = str(ROOT/HELPER)
exec(compile(raw, m.__file__, 'exec'), m.__dict__)
c, h, t, s, encode, decode, read, sha = m.c, m.h, m.t, m.s, m.encode, m.decode, m.read, m.sha
META = [('factory', 'factory()', 'address'), ('token0', 'token0()', 'address'),
        ('token1', 'token1()', 'address'), ('fee', 'fee()', 'uint')]
SLOTS = [('chain',4096),('anchor',16384),('quoter_factory',4096)] + [
    (str(fee)+'_'+name,4096) for fee in m.FEES for name,_,_ in META] + [
    (str(fee)+'_'+str(lot)+'_'+direction,4096) for fee in m.FEES for lot in LOTS for direction in DIRECTIONS
] + [('recheck',16384)]


def reason(exc):
    return str(exc)[:160] if isinstance(exc,Refusal) else m.reason(exc)


def inputs():
    if sha(read(ROOT/ORIGINAL_PLAN,8192))!=ORIGINAL_SHA:
        raise Refusal('original_plan_changed')
    original = decode(read(ROOT/ORIGINAL_PROJECTION,8192))
    terminal = decode(read(ROOT/ORIGINAL_TERMINAL,4096))
    audit = decode(read(ROOT/ORIGINAL_REVIEW,4096))
    if (original['plan_sha256']!=ORIGINAL_SHA or terminal['plan_sha256']!=ORIGINAL_SHA
            or terminal['status']!='fixed_discovery_complete' or terminal['error'] is not None
            or audit.get('status')!='passed' or audit.get('plan_sha256')!=ORIGINAL_SHA):
        raise Refusal('discovery_not_admitted')
    conditions=original['conditions']
    if conditions['documented_identity_matches'] is not True or conditions['expected_units_match'] is not True:
        raise Refusal('original_identity_or_units')
    if not all(x['available'] for x in original['values'].values()):
        raise Refusal('original_field_unavailable')
    if any(int(original['values'][name]['value'])>m.WAD for name in ('tin','tout')):
        raise Refusal('original_halted_or_invalid_fee')
    if [x['fee'] for x in original['pools']]!=m.FEES or not all(x['nonzero_address'] is True for x in original['pools']):
        raise Refusal('original_pool_domain')
    return original


def terms(original,lot,direction):
    x=lot*10**6
    v=original['values']
    scale=int(v['conversion']['value'])
    gross=x*scale
    if direction=='dai_cycle':
        proceeds=gross-gross*int(v['tin']['value'])//m.WAD
        return dict(token_in=m.DAI,token_out=m.USDC,dex_output=x,proceeds=proceeds,
                    inventory=int(v['psm_dai_balance']['value'])>=proceeds,unit='DAI',decimals=18)
    if direction=='usdc_cycle':
        dai_needed=gross+gross*int(v['tout']['value'])//m.WAD
        return dict(token_in=m.USDC,token_out=m.DAI,dex_output=dai_needed,proceeds=x,
                    inventory=min(int(v['pocket_usdc_balance']['value']),int(v['pocket_usdc_allowance']['value']))>=x,
                    unit='USDC',decimals=6)
    raise Refusal('direction')


def quote(value):
    if isinstance(value,dict) and 'rpc_unavailable' in value:
        return dict(available=False,reason='rpc_error',code=value['rpc_unavailable'])
    try:
        data=h.hexdata(value,128)[2:]
        a,p,ticks,gas=[int(data[i:i+64],16) for i in range(0,256,64)]
        if a<=0 or not 0<p<2**160 or ticks>=2**32 or gas>3000000:
            raise Refusal('quote_word_domain')
    except (Refusal,m.Refusal,c.Refusal,h.Refusal,TypeError,ValueError):
        return dict(available=False,reason='null_or_noncanonical_quote')
    return dict(available=True,amount_in=str(a),sqrt_price_after=str(p),initialized_ticks_crossed=ticks,
                swap_gas_estimate=gas)


def collect(rpc,original):
    if h.quantity(rpc('chain','eth_chainId',[]))!=1:
        raise Refusal('wrong_chain')
    anchor=rpc('anchor','eth_getBlockByNumber',[hex(original['block']['number']),False])
    if c.header(anchor)!=original['block'] or s.o.context(anchor)!=original['context']:
        raise Refusal('original_anchor_changed')
    state=dict(blockHash=original['block']['hash'],requireCanonical=True)
    def call(name,to,data,gas=300000):
        tx={'from':m.DIAGNOSTIC,'to':to,'input':data,'value':'0x0','gasPrice':'0x0','gas':hex(gas)}
        return rpc(name,'eth_call',[tx,state],allow_unavailable=True)
    factory=m.result(call('quoter_factory',QUOTER,s.selector('factory()')),'address')
    pool_rows=[]
    for pool in original['pools']:
        fee=pool['fee'];address=pool['result']['value']
        values={name:m.result(call(str(fee)+'_'+name,address,s.selector(signature)),kind)
                for name,signature,kind in META}
        expected=dict(factory=m.FACTORY,token0=min(m.DAI,m.USDC),token1=max(m.DAI,m.USDC),fee=str(fee))
        mismatch=any(values[key]['available'] and values[key]['value']!=expected[key] for key in expected)
        match=False if mismatch else True if all(x['available'] for x in values.values()) else None
        pool_rows.append(dict(fee=fee,address=address,values=values,identity_matches=match))
    quoter_matches=(factory['value']==m.FACTORY if factory['available'] else None)
    rows=[]
    for pool in pool_rows:
        fee=pool['fee']
        for lot in LOTS:
            for direction in DIRECTIONS:
                v=terms(original,lot,direction)
                payload=s.selector(SIGNATURE)+s.word_address(v['token_in'])+s.word_address(v['token_out'])+''.join(
                    format(x,'064x') for x in (v['dex_output'],fee,0))
                q=quote(call(str(fee)+'_'+str(lot)+'_'+direction,QUOTER,payload,3000000))
                delta=v['proceeds']-int(q['amount_in']) if q['available'] else None
                identity=pool['identity_matches'] is True and quoter_matches is True
                admissible=q['available'] and v['inventory'] and identity
                rows.append(dict(fee=fee,usdc_lot=lot,direction=direction,settlement_unit=v['unit'],
                    settlement_decimals=v['decimals'],dex_output_raw=str(v['dex_output']),
                    modeled_psm_proceeds_raw=str(v['proceeds']),snapshot_inventory_sufficient=v['inventory'],
                    identities_match=identity,quote=q,modeled_margin_before_gas_raw=str(delta) if delta is not None else None,
                    positive_conditional_candidate=(delta>0 if admissible else None)))
    s.o.same_header(rpc('recheck','eth_getBlockByNumber',[anchor['number'],False]),anchor)
    return dict(schema='sky-psm-fixed-quotes-projection-v1',status='fixed_quotes_complete',
        anchor=original['block'],context=original['context'],quoter_factory=factory,quoter_factory_matches=quoter_matches,
        pools=pool_rows,rows=rows,fixed_rows=32,available_quotes=sum(x['quote']['available'] for x in rows),
        positive_conditional_rows=sum(x['positive_conditional_candidate'] is True for x in rows),
        unknown_or_unadmitted_rows=sum(x['positive_conditional_candidate'] is None for x in rows),
        independent_state_calls=True,source_assumes_full_exact_output=True,runtime_equivalence_verified=False,
        actual_psm_swap_verified=False,token_payment_verified=False,closed_cash=False,
        full_transaction_gas_measured=False,quote_gas_is_total_cost=False,obtainable_inclusion_verified=False,
        margins_in_different_units_not_summed=True,economics=False,repeatable_profit=False)


def verify(digest):
    raw=read(ROOT/PLAN,8192)
    if sha(raw)!=digest:raise Refusal('plan_sha_required')
    p=decode(raw)
    required={SOURCE,TEST,DESIGN,NOTES,ALLOCATION,HELPER,ORIGINAL_PLAN,ORIGINAL_PROJECTION,ORIGINAL_TERMINAL,ORIGINAL_REVIEW}
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
            or p.get('runtime')!=h.runtime() or p.get('output_dir')!=OUT or p.get('lots')!=LOTS
            or p.get('fees')!=m.FEES or p.get('directions')!=DIRECTIONS or p.get('quoter')!=QUOTER
            or p.get('signature')!=SIGNATURE or p.get('endpoint')!='https://ethereum-rpc.publicnode.com'):
        raise Refusal('frozen_scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required) or {x.get('path') for x in pins}!=required:raise Refusal('pins_schema')
    for pin in pins:
        data=read(ROOT/pin['path'],32768)
        if len(data)!=pin['bytes'] or sha(data)!=pin['sha256']:raise Refusal('source_pin')
    if sum(x['bytes'] for x in pins if x['path'] in (SOURCE,TEST,DESIGN,NOTES))>32768:
        raise Refusal('source_package_cap')
    if len(SLOTS)!=CAPS['requests'] or 17*300000+32*3000000!=CAPS['total_supplied_gas']:
        raise Refusal('request_or_gas_cap')
    if any(p.is_symlink() for p in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise Refusal('output_symlink')
    return p


def replay(path,original):
    reader=t.Reader(path,SLOTS,CAPS,c);p=collect(reader.rpc,original);reader.finish()
    return p,reader.body_bytes,reader.raw_bytes


def run(digest):
    started,capture=time.monotonic(),None;status,error='unavailable',None
    with h.alarm(CAPS['wall_seconds']):
        p=verify(digest);original=inputs();out=ROOT/OUT;out.mkdir(exist_ok=False)
        s.o.publish(out,'claim.json',dict(plan_sha256=digest,pins=p['pins'],started_ns=time.time_ns()))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_AS,(CAPS['ram_bytes'],CAPS['ram_bytes']))
        try:
            with h.alarm(CAPS['work_seconds']-(time.monotonic()-started)):
                capture=t.Capture(out/'raw',SLOTS,CAPS,c,started,reason)
                result=collect(capture.rpc,original);check,body,raw=replay(out/'raw',original)
                if result!=check or body!=capture.body_bytes or raw!=capture.raw_bytes:raise Refusal('exact_replay')
                verify(digest);result['plan_sha256']=digest
                s.o.publish(out,'projection.json',result,CAPS['projection_bytes']);status='fixed_quotes_complete'
        except BaseException as exc:error=reason(exc)
        finally:
            try:verify(digest)
            except Exception:status,error='unavailable','final_pin_mismatch'
            s.o.publish(out,'terminal.json',dict(status=status,error=error,plan_sha256=digest,
                requests_attempted=capture.attempts if capture else 0,body_bytes=capture.body_bytes if capture else 0,
                raw_bytes=capture.raw_bytes if capture else 0,elapsed_milliseconds=int((time.monotonic()-started)*1000),
                ended_ns=time.time_ns(),economics=False))
    return status=='fixed_quotes_complete' and error is None


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true');p.add_argument('--plan-sha256')
    args=p.parse_args()
    if args.replay:
        verify(args.plan_sha256);result,body,raw=replay(ROOT/OUT/'raw',inputs())
        print(encode(dict(status=result['status'],quotes=result['available_quotes'],positive=result['positive_conditional_rows'],body_bytes=body,raw_bytes=raw)).decode());return 0
    if not args.run:print('dry: zero requests; zero outputs; fixed32-row exact-output matrix');return 0
    return 0 if run(args.plan_sha256) else 1


if __name__=='__main__':raise SystemExit(main())
