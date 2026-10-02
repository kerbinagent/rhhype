"""Post-hoc cost threshold, with an explicitly unverified peer gain input."""
from pathlib import Path
from fractions import Fraction
from decimal import Decimal,localcontext
import hashlib,json,re,struct

ROOT=Path(__file__).resolve().parents[2]
BASE='reports/comet-route-gas-threshold-v1/'
PINS=[
 ('reports/comet-collateral-inventory-v1/run-v1/responses.frames',149135,'cda935fa13d73b609b500f2c5bcee3e469a8ad3ba8f384d7a3806731ec16f518'),
 ('reports/comet-collateral-inventory-v1/run-v1/projection.json',12368,'77ece9feac7ee802ad9ec675b1d058c015b19aa510f3a6a00783abe6a5f171c0'),
 ('reports/peer-comet-oct02-continuation/direct-projection.json',7346,'a022db4917b47367299dc18328713def94205414503c72f52cb024267c06b26d'),
 ('reports/peer-comet-oct02-continuation/pool-state-0-projection.json',1741,'394eba5444504e66c76bc1b98687bab9d0d210c4b2dd9254e2aabc578b6e9f8c')]
GAIN_NATIVE=4275
SCALE=10**6


def enc(x):return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()


def sha(x):return hashlib.sha256(x).hexdigest()


def readpin(pin):
    name,size,digest=pin;p=ROOT/name
    assert not p.is_symlink() and p.is_file()
    with p.open('rb') as f:b=f.read(size+1)
    assert len(b)==size and sha(b)==digest
    return b


def quantity(x):
    assert isinstance(x,str) and re.fullmatch('0x(?:0|[1-9a-f][0-9a-f]*)',x)
    return int(x,16)


def rational(x):
    with localcontext() as ctx:
        ctx.prec=60
        return dict(numerator=str(x.numerator),denominator=str(x.denominator),decimal=str(Decimal(x.numerator)/Decimal(x.denominator)))


def headers(raw):
    magic=b'COMET-COLLATERAL-INVENTORY-V1\n';assert raw.startswith(magic)
    pos=len(magic);records=[];active=None
    while pos<len(raw):
        assert pos+5<=len(raw)
        kind=chr(raw[pos]);length=struct.unpack('>I',raw[pos+1:pos+5])[0];pos+=5
        assert length<=8192 and pos+length<=len(raw)
        data=raw[pos:pos+length];pos+=length
        if kind=='B':
            assert active is None;active=dict(begin=json.loads(data),body=bytearray(),http=None)
        elif kind=='H':
            assert active is not None and active['http'] is None;active['http']=json.loads(data)
        elif kind=='D':
            assert active is not None and active['http'] is not None
            active['body'].extend(data);assert len(active['body'])<=65536
        elif kind=='E':
            end=json.loads(data);assert active is not None
            body=bytes(active['body']);request=active['begin']['request'];reply=json.loads(body)
            assert end['body_bytes']==len(body) and end['body_sha256']==sha(body) and end['outcome']=='received'
            assert end['error'] is None and end['eof'] is True and end['http_status']==active['http']['http_status']==200
            assert reply['jsonrpc']=='2.0' and type(reply['id']) is int and reply['id']==request['id'] and 'error' not in reply
            if request['method']=='eth_getBlockByNumber':records.append(dict(request=request,body_sha256=sha(body),header=reply['result']))
            active=None
        else:raise AssertionError('unknown frame')
    assert active is None and len(records)==2
    return records


def calculate():
    raw,inventory,direct,pools=[readpin(p) for p in PINS]
    inventory,direct,pools=map(json.loads,(inventory,direct,pools));records=headers(raw)
    first,last=[r['header'] for r in records]
    fields=('number','hash','parentHash','stateRoot','timestamp','baseFeePerGas','gasLimit','gasUsed')
    assert {f:first[f] for f in fields}=={f:last[f] for f in fields}
    parent=inventory['result']['metadata']['parent']
    assert all(first[f]==parent[f] for f in parent) and direct['parent']==parent and pools['parent_hash']==parent['hash']
    assert inventory['result']['rows'][2]['tuple']['asset']=='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
    basefee=quantity(first['baseFeePerGas']);assert basefee>0
    gas_wei=21000*basefee
    threshold=Fraction(GAIN_NATIVE*10**18,SCALE*gas_wei)
    queue=[row for row in direct['rows'] if row['status']=='reported_nonzero_address']
    spots=[]
    for i,row in enumerate(queue):
        if row['index']!=2:continue
        observed=next(p for p in pools['rows'] if p['id']==i)
        assert observed['identity_checks_passed']==4 and observed['status']=='reported_slot0'
        sqrt=int(observed['slot0'][0]);assert sqrt>0
        # token0=USDC(1e6),token1=WETH(1e18): native token1/token0=P^2/2^192.
        usdc_per_eth=Fraction(10**12*(1<<192),sqrt*sqrt)
        spots.append(dict(pool=row['pool'],fee=row['fee'],sqrtPriceX96=str(sqrt),usdc_per_eth_spot_mark=rational(usdc_per_eth),
            gas_cost_native_usdc_mark=rational(Fraction(gas_wei*SCALE,10**18)*usdc_per_eth),
            mark_exceeds_required_threshold=usdc_per_eth>=threshold))
    assert len(spots)==4
    scenarios=[dict(assumed_usdc_per_eth=str(mark),gas_cost_native_usdc=rational(Fraction(gas_wei*SCALE*mark,10**18)),
                    erases_preliminary_upper_gain=Fraction(gas_wei*SCALE*mark,10**18)>=GAIN_NATIVE) for mark in (0,1000,2000,3000)]
    return dict(schema='comet-route-gas-threshold-v1',classification='post_hoc_conditional_sensitivity_only',
        input_pins=[dict(path=p,bytes=s,sha256=h) for p,s,h in PINS],input_read_bytes=sum(p[1] for p in PINS),
        parent={key:first[key] for key in fields},both_retained_parent_fee_fields_match=True,
        preliminary_peer_gain_upper_native_usdc=str(GAIN_NATIVE),peer_upper_bound_independently_admitted=False,
        peer_message='d2425ada-3254-45a6-b83a-6153e0da1772',native_usdc_scale=SCALE,
        conventional_standalone_intrinsic_gas_floor=21000,parent_base_fee_wei=str(basefee),parent_gas_floor_wei=str(gas_wei),
        required_eth_valuation_usdc_per_eth_to_erase_preliminary_gain=rational(threshold),spot_marks=spots,scenarios=scenarios,
        actual_native_usdc_gas_debit_proved=False,executable_conversion_proved=False,child_or_future_fee_proved=False,
        unconditional_route_rejection=False,profitability_proven=False,
        premises=['Conventional standalone Ethereum transaction under the21000gas minimum, with caller bearing total gas.',
                  'Parent basefee and state only; no child override or future state inference.',
                  'Peer4275unit upper bound is preliminary and unverified here; all its source/token/state/debit assumptions remain.',
                  'Converting ETH cost into USDC uses an explicit valuation premise. Spot marks lack liquidity/depth and are not cash conversion proofs.',
                  'Batching,sponsored or externalized gas and alternative account paths are outside this comparison.'])


if __name__=='__main__':
    result=calculate();raw=enc(result);assert len(raw)<=8192
    with (ROOT/BASE/'projection.json').open('xb') as f:f.write(raw)
    print(json.dumps({key:result[key] for key in ('parent_base_fee_wei','parent_gas_floor_wei','required_eth_valuation_usdc_per_eth_to_erase_preliminary_gain')}))
