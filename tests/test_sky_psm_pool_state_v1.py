import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('state',ROOT/'scripts/sky_psm_pool_state_v1.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def words(*values):return '0x'+''.join(format(x%(2**256),'064x') for x in values)


class PoolStateTests(unittest.TestCase):
    def fixture(self):
        d,q=p.inputs();b=d['block'];c=d['context']
        block=dict(number=hex(b['number']),hash=b['hash'],parentHash=b['parentHash'],timestamp=hex(b['timestamp']),stateRoot=b['stateRoot'],
                   gasLimit=c['gasLimit'],miner=c['feeRecipient'],mixHash=c['prevRandao'],baseFeePerGas=c['baseFeePerGas'])
        values=dict(chain='0x1',anchor=block,recheck=copy.deepcopy(block))
        for fee in p.FEES:
            values[str(fee)+'_slot0']=words(2**96//10**6,-276325,0,1,1,0,1)
            values[str(fee)+'_liquidity']=words(10**20)
            values[str(fee)+'_dai_balance']=words(200000*10**18)
            values[str(fee)+'_usdc_balance']=words(200000*10**6)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return d,q,values,seen,rpc

    def test_fixed_state_calls_and_correct_token_balance_targets(self):
        d,q,values,seen,rpc=self.fixture();r=p.collect(rpc,d,q)
        self.assertEqual([x[0] for x in seen],[x[0] for x in p.SLOTS]);self.assertEqual(len(seen),19)
        gas=0
        for name,method,params,optional in seen[2:-1]:
            fee,field=name.split('_',1);address=next(x['address'] for x in q['pools'] if x['fee']==int(fee))
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=d['block']['hash'],requireCanonical=True));call=params[0]
            expected=p.m.DAI if field=='dai_balance' else p.m.USDC if field=='usdc_balance' else address
            self.assertEqual(call['to'],expected);gas+=int(call['gas'],16)
            if field.endswith('_balance'):self.assertEqual(call['input'],p.s.selector('balanceOf(address)')+p.s.word_address(address))
        self.assertEqual(gas,4800000);self.assertLessEqual(len(p.encode(r)),p.CAPS['projection_bytes'])
        for row in r['rows']:
            flags=[x['pool_output_inventory_sufficient'] for x in row['requested_output_inventory']]
            self.assertEqual(flags,[True]*6+[False]*2)
            b=row['conditional_bound'];self.assertTrue(b['dai_cycle_nonpositive_all_positive_usdc_units']);self.assertTrue(b['usdc_cycle_nonpositive_all_positive_usdc_units'])
        self.assertTrue(r['original_unknown_quote_rows_remain_unknown']);self.assertFalse(r['underlying_quote_error_diagnosed']);self.assertFalse(r['economics'])

    def test_slot0_signed_tick_and_abi_boundaries(self):
        good=p.result(words(1,-1,65535,65535,65535,255,1),'slot0');self.assertEqual(good['value']['tick'],-1)
        for row in [(2**160,0,0,1,1,0,1),(1,2**24-1,0,1,1,0,1),(1,-2**23-1,0,1,1,0,1),
                    (1,0,65536,1,1,0,1),(1,0,0,1,1,256,1),(1,0,0,1,1,0,2)]:
            self.assertFalse(p.result(words(*row),'slot0')['available'])
        self.assertFalse(p.result(words(2**128),'liquidity')['available'])
        self.assertTrue(p.result(words(0),'liquidity')['available'])

    def test_unknown_price_and_balance_stay_unknown(self):
        d,q,values,seen,rpc=self.fixture();values['100_slot0']={'rpc_unavailable':3};values['500_usdc_balance']=None
        r=p.collect(rpc,d,q);self.assertFalse(r['rows'][0]['conditional_bound']['available'])
        self.assertIsNone(r['rows'][1]['requested_output_inventory'][0]['pool_output_inventory_sufficient'])
        self.assertEqual(len(seen),19)
        zero=p.result(words(0,0,0,0,0,0,0),'slot0');self.assertTrue(zero['available']);self.assertFalse(p.price_bound(zero,100,10**12)['available'])

    def test_price_orientation_and_fee_band(self):
        for sqrt,expected in [(2**96,(True,True)),(2**97,(False,True)),(2**95,(True,False))]:
            slot=p.result(words(sqrt,0,0,1,1,0,1),'slot0');b=p.price_bound(slot,100,1)
            self.assertEqual((b['dai_cycle_nonpositive_all_positive_usdc_units'],b['usdc_cycle_nonpositive_all_positive_usdc_units']),expected)

    def test_bound_survives_native_integer_psm_fee_rounding(self):
        unit=2**192
        for sqrt in [2**95,2**96,2**97,2**96//10**6]:
            slot=p.result(words(sqrt,0,0,1,1,0,1),'slot0')
            for conversion in [1,10**12]:
                for fee in p.FEES:
                    bound=p.price_bound(slot,fee,conversion);price=sqrt**2
                    for x in [1,2,17,1000000,10**12]:
                        for psm_fee in [0,1,p.m.WAD//3,p.m.WAD]:
                            sell=x*conversion-(x*conversion*psm_fee)//p.m.WAD
                            buy=x*conversion+(x*conversion*psm_fee)//p.m.WAD
                            dai_den=price*(1000000-fee);dai_min=(x*unit*1000000+dai_den-1)//dai_den
                            usdc_den=unit*(1000000-fee);usdc_min=(buy*price*1000000+usdc_den-1)//usdc_den
                            if bound['dai_cycle_nonpositive_all_positive_usdc_units']:self.assertLessEqual(sell-dai_min,0)
                            if bound['usdc_cycle_nonpositive_all_positive_usdc_units']:self.assertLessEqual(x-usdc_min,0)

    def test_changed_original_or_final_header_rejected(self):
        for name in ('anchor','recheck'):
            d,q,values,seen,rpc=self.fixture();values[name]['hash']='0x'+'99'*32
            with self.subTest(name=name),self.assertRaises((p.Refusal,p.s.o.Refusal)):p.collect(rpc,d,q)

    def test_complete_capture_and_tampered_replay(self):
        d,q,values,seen,rpc=self.fixture();p.collect(rpc,d,q);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i];self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch();sent.append(request);raw=p.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,p.encode(dict(status=200,headers=[['content-length',str(len(raw))]])));emit(raw);return 200,len(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/p.BASE).mkdir(parents=True)
            with mock.patch.object(p,'ROOT',root),mock.patch.object(p,'verify',return_value={'pins':[]}), \
                 mock.patch.object(p,'inputs',return_value=(d,q)),mock.patch.object(p.resource,'setrlimit'),mock.patch.object(p.h,'fetch',side_effect=fetch):
                self.assertTrue(p.run('a'*64))
                with self.assertRaises(FileExistsError):p.run('a'*64)
            out=root/p.OUT;r,body,raw=p.replay(out/'raw',d,q);self.assertEqual(len(sent),19);self.assertEqual(len(list((out/'raw').iterdir())),76)
            self.assertLessEqual(raw,65536)
            path=out/'raw/03.request.json';v=p.decode(path.read_bytes());v['request']['params'][1]['requireCanonical']=False;path.write_bytes(p.encode(v))
            with self.assertRaisesRegex(p.t.Refusal,'request_manifest'):p.replay(out/'raw',d,q)


if __name__=='__main__':unittest.main()
