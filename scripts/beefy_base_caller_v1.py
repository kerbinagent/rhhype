"""Two fixed Base public caller-reward diagnostics; default dry."""
import gzip
import hashlib
import http.client
from pathlib import Path
import sys
import types
import zlib

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/beefy_base_caller_v1.py';TEST='tests/test_beefy_base_caller_v1.py'
BASE='reports/beefy-base-caller-v1/'
PLAN,DESIGN,NOTES,AMEND,CAPSULE,OUT=(BASE+x for x in ('plan.json','design.txt','source-notes.json','source-read-amendment.json','source-selection.json.gz','run-v1'))
PREP='reports/experiment-storage/beefy-base-caller-preparation-v1.json'
ALLOCATION='reports/experiment-storage/beefy-base-caller-allocation-v1.json'
OLD='scripts/beefy_caller_reward_v1.py';OLD_PLAN='reports/beefy-caller-reward-v1/plan.json'
ZIP='scripts/bounded_rpc_gzip_v1.py'
CATEGORY=BASE+'category-amendment.json'
HOST='base-rpc.publicnode.com';WETH='0x4200000000000000000000000000000000000006'
VAULTS=[('aerodrome-cow-base-usdc-tao-vault','0xb13384c75f019d0f7a9fe661b90e18e660a6e9b9'),
        ('pancakeswap-cow-base-cbeth-weth-vault','0xafc09a027f62b1a9378d9bdd46f6afa177e3ffdd')]
CAPS=dict(requests=13,body_bytes=524288,raw_bytes=96256,request_bytes=8192,projection_bytes=4096,
          request_seconds=20,work_seconds=105,wall_seconds=120,cpu_seconds=20,ram_bytes=536870912,
          total_supplied_gas=10800000)


def load(name,path,digest):
    p=ROOT/path
    if p.is_symlink():raise RuntimeError('source_symlink')
    with p.open('rb') as f:raw=f.read(32769)
    if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('source_pin')
    m=types.ModuleType(name);m.__file__=str(p);exec(compile(raw,m.__file__,'exec'),m.__dict__);return m


b=load('base_beefy_semantics',OLD,'da99aff547f5f5a221c03f057e205e390cdf1da38fef6f27ef512e45fbd83c9f')
old_plan=b.verify('0dea7b8d0d60e456a9c10162c5ce3bbdf65fa25a3b45031baeacb966e9397ce8')
z=load('bounded_gzip',ZIP,'8ca144ba39ca43a30271af3c026e94b68bddd330c3b6efe7d638100c6a95b57d')
z.Refusal=b.t.Refusal
encode,decode,read,sha=b.encode,b.decode,b.read,b.sha
SLOTS=[('chain',4096,1024),('block',65536,24576)]+[(str(i)+'_'+x[0],2048,1024) for i in range(2) for x in b.FIELDS]+[
    ('branch_'+str(i),131072,16384) for i in range(2)]+[('recheck',65536,24576)]
old_fetch=b.c.h.fetch


def base_fetch(*args):
    return old_fetch(*args,factory=lambda ignored,**kw:http.client.HTTPSConnection(HOST,**kw))


def collect(rpc):
    if b.h.quantity(rpc('chain','eth_chainId',[]))!=8453:raise b.Refusal('chain')
    block=rpc('block','eth_getBlockByNumber',['latest',False]);header=b.c.header(block);context=b.r.target_context(block)
    context['time']=hex(b.h.quantity(block['timestamp'])+2)
    state=dict(blockHash=header['hash'],requireCanonical=True);rows=[]
    for i,(name,vault) in enumerate(VAULTS):
        metadata={};strategy=None
        for field,signature,kind in b.FIELDS:
            value=rpc(str(i)+'_'+field,'eth_call',[b.r.tx(vault if field=='strategy' else strategy,signature),state],allow_unavailable=field!='strategy')
            parsed=b.r.m.result(value,kind);metadata[field]=parsed
            if field=='strategy':
                if not parsed['available']:raise b.Refusal('strategy_address_unavailable')
                strategy=parsed['value']
        native=metadata['native'];rows.append(dict(id=name,vault=vault,strategy=strategy,metadata=metadata,
            reported_native_matches_weth=native['value']==WETH if native['available'] else None))
    for i,row in enumerate(rows):
        row['simulation']=b.branch(rpc('branch_'+str(i),'eth_simulateV1',b.sim_params(block,context,row['strategy']),allow_unavailable=True),context)
    b.s.o.same_header(rpc('recheck','eth_getBlockByNumber',[block['number'],False]),block)
    return dict(schema='beefy-base-caller-projection-v1',status='fixed_branches_complete',chain_id=8453,block=header,
        hypothetical_context=context,diagnostic_actor=b.r.ACTOR,weth=WETH,vaults=rows,
        available_branches=sum(x['simulation']['available'] for x in rows),independent_same_state_branches=True,
        validation=False,state_overrides=False,simulated_gas_price=0,actor_control_claimed=False,
        gas_reference_excludes_l1_and_other_chain_fees=True,gas_reference_is_not_paid_cost_or_lower_bound=True,
        runtime_equivalence_proved=False,native_cash_exit_verified=False,paid_execution_verified=False,cash_closed=False,
        economics=False,repeatable_profit=False)


def owned_source():return [SOURCE,TEST,DESIGN,NOTES,AMEND,CAPSULE,PREP,ZIP]
def required_paths():return owned_source()+[ALLOCATION,OLD,OLD_PLAN,CATEGORY]
def runtime():return dict(b.h.runtime(),zlib=zlib.ZLIB_RUNTIME_VERSION)


def verify(digest):
    raw=read(ROOT/PLAN,4096)
    if sha(raw)!=digest:raise b.Refusal('plan_sha_required')
    p=decode(raw)
    if (p.get('status')!='frozen' or p.get('caps')!=CAPS or p.get('slots')!=[list(x) for x in SLOTS]
        or p.get('runtime')!=runtime() or p.get('output_dir')!=OUT or p.get('vaults')!=[list(x) for x in VAULTS]
        or p.get('endpoint')!='https://'+HOST or p.get('weth')!=WETH):raise b.Refusal('scope')
    pins=p.get('pins',[])
    if len(pins)!=len(required_paths()) or {x['path'] for x in pins}!=set(required_paths()):raise b.Refusal('pins')
    for x in pins+old_plan['pins']:
        data=read(ROOT/x['path'],65536)
        if len(data)!=x['bytes'] or sha(data)!=x['sha256']:raise b.Refusal('input_pin')
    if sum((ROOT/x).stat().st_size for x in owned_source())>26624:raise b.Refusal('source_cap')
    a=decode(read(ROOT/ALLOCATION,4096))
    if (a['total_experiment_reservation_bytes']!=139264 or a['categories_bytes']!=dict(source_tests_design_preparation=24576,
        plan_and_claim=4096,controls_reviews_readout=8192,projection=4096,raw=98304)):raise b.Refusal('funding')
    amendment=decode(read(ROOT/CATEGORY,2048))
    if (amendment['total_reservation_bytes']!=139264 or amendment['raw']!=96256
        or amendment['source_tests_design_preparation']!=26624):raise b.Refusal('category_amendment')
    selection=decode(gzip.decompress(read(ROOT/CAPSULE,4096)));seen=set();indices=[]
    for index,kind,status,platform in selection['selection_prefix']:
        if kind=='standard' and status=='active' and platform not in seen:seen.add(platform);indices.append(index)
    chosen=selection['selected']
    if indices!=[2,57] or [(x['id'],x['vault']) for x in chosen]!=VAULTS:raise b.Refusal('selection')
    if any(x.is_symlink() for x in (ROOT/'reports',ROOT/BASE,ROOT/OUT)):raise b.Refusal('output_symlink')
    return p


api=types.SimpleNamespace(**vars(b.c));api.h=types.SimpleNamespace(**vars(b.c.h));api.h.fetch=base_fetch
b.c,b.t,b.WETH,b.VAULTS,b.SLOTS,b.CAPS=api,z,WETH,VAULTS,SLOTS,CAPS
b.BASE,b.PLAN,b.OUT,b.verify,b.collect=BASE,PLAN,OUT,verify,collect
replay=b.replay
if __name__=='__main__':raise SystemExit(b.main())
