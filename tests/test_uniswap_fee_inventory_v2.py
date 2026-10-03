import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fee_inventory',ROOT/'scripts/uniswap_fee_inventory_v2.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def word(value):
    return '0x'+format(value,'064x')


class FeeInventoryTests(unittest.TestCase):
    def fixture(self):
        block=dict(number='0x123',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,timestamp='0x100',
                   stateRoot='0x'+'ef'*32,gasLimit='0x3938700',miner='0x'+'11'*20,
                   mixHash='0x'+'22'*32,baseFeePerGas='0x9')
        values=dict(chain='0x1',block=block,recheck=copy.deepcopy(block),ETH_balance='0x0')
        fields=dict(resource=int(m.UNI,16),resource_recipient=int(m.BURN,16),token_jar=int(m.JAR,16),
                    threshold=100*10**18,nonce=42,max_release_length=20,releaser=int(m.FIREPIT,16))
        for label,address,decimals in m.ASSETS:
            fields[label+'_decimals']=decimals
            fields[label+'_balance']=10**decimals
        values.update({key:word(value) for key,value in fields.items()})
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable))
            return copy.deepcopy(values[name])
        return values,seen,rpc

    def test_frozen_basket_targets_and_state(self):
        values,seen,rpc=self.fixture()
        p=m.collect(rpc)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(len(seen),23)
        self.assertEqual(p['calls_available'],20)
        self.assertTrue(p['documented_configuration_matches'])
        self.assertTrue(p['expected_units_match'])
        self.assertEqual([x['label'] for x in p['inventory']],['WETH','USDC','DAI','USDT','WBTC','UNI','ETH'])
        gas=0
        for name,method,params,optional in seen[2:-1]:
            self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=values['block']['hash'],requireCanonical=True))
            if name=='ETH_balance':
                self.assertEqual((method,params[0]),('eth_getBalance',m.JAR))
            else:
                self.assertEqual(method,'eth_call')
                tx=params[0]
                self.assertEqual((tx['from'],tx['value'],tx['gasPrice']),(m.DIAGNOSTIC,'0x0','0x0'))
                gas+=int(tx['gas'],16)
                if name.endswith('_balance'):
                    label=name.split('_')[0]
                    self.assertEqual(tx['to'],next(a for s,a,d in m.ASSETS if s==label))
                    self.assertEqual(tx['input'],m.s.selector('balanceOf(address)')+m.s.word_address(m.JAR))
        self.assertEqual(gas,5700000)
        for key in ('runtime_source_correspondence_verified','release_simulated','token_payments_verified',
                    'transaction_gas_measured','basket_valued','cash_closed','economics','repeatable_profit'):
            self.assertFalse(p[key])

    def test_known_mismatch_beats_unavailable_without_redirect(self):
        values,seen,rpc=self.fixture()
        values.update(resource=word(42),token_jar={'rpc_unavailable':3},WETH_decimals=word(6),USDC_decimals=None)
        p=m.collect(rpc)
        self.assertFalse(p['documented_configuration_matches'])
        self.assertFalse(p['expected_units_match'])
        values.update(resource=word(int(m.UNI,16)),WETH_decimals=word(18))
        p=m.collect(rpc)
        self.assertIsNone(p['documented_configuration_matches'])
        self.assertIsNone(p['expected_units_match'])
        self.assertTrue(all(x[2][0]['input'].endswith(m.s.word_address(m.JAR))
                            for x in seen if x[0].endswith('_balance') and x[0]!='ETH_balance'))

    def test_native_quantities_and_empty_vs_unknown(self):
        for v in (None,True,1,'0x','0x00','0X1','0x'+format(2**256,'x')):
            with self.subTest(v=v):self.assertFalse(m.native_result(v)['available'])
        self.assertEqual(m.native_result('0x0'),dict(available=True,value='0'))
        values,seen,rpc=self.fixture()
        values.update(ETH_balance={'rpc_unavailable':-32000},UNI_balance=word(0),threshold=word(0),nonce=word(0))
        p=m.collect(rpc)
        self.assertEqual(p['configuration']['threshold']['value'],'0')
        self.assertEqual(p['configuration']['nonce']['value'],'0')
        self.assertEqual(p['inventory'][-2]['balance'],dict(available=True,value='0'))
        self.assertFalse(p['inventory'][-1]['balance']['available'])

    def test_wrong_chain_or_changed_header_refuses_projection(self):
        for field in ('chain','hash','stateRoot','baseFeePerGas','timestamp'):
            values,seen,rpc=self.fixture()
            if field=='chain':values['chain']='0x2'
            else:values['recheck'][field]='0x'+'99'*32 if field in ('hash','stateRoot') else '0x2'
            with self.subTest(field=field),self.assertRaises((m.Refusal,m.s.o.Refusal)):
                m.collect(rpc)

    def execute(self,root,failure=None):
        values,seen,rpc=self.fixture()
        m.collect(rpc)
        sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent)
            name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch()
            sent.append(request)
            if failure=='sentinel' and i==1:raw=b'x'*(cap+1)
            elif failure=='rpc' and name=='ETH_balance':
                raw=m.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=3,message='unavailable')))
            else:raw=m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['content-length',str(len(raw))]])))
            for at in range(0,len(raw),1024):emit(raw[at:at+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={'pins':[]}), \
             mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent

    def test_capture_exact_replay_error_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ok,sent=self.execute(root,'rpc')
            self.assertTrue(ok)
            self.assertEqual(len(sent),23)
            out=root/m.OUT
            p,body,raw=m.replay(out/'raw')
            self.assertFalse(p['inventory'][-1]['balance']['available'])
            self.assertEqual(len(list((out/'raw').iterdir())),92)
            terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            path=out/'raw/23.body'
            changed=m.decode(path.read_bytes());changed['result']['hash']='0x'+'99'*32
            path.write_bytes(m.encode(changed))
            with self.assertRaisesRegex(m.t.Refusal,'incomplete_rpc'):m.replay(out/'raw')

    def test_header_overflow_stops_and_retains_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ok,sent=self.execute(root,'sentinel')
            self.assertFalse(ok)
            self.assertEqual(len(sent),2)
            out=root/m.OUT
            self.assertFalse((out/'projection.json').exists())
            self.assertEqual((out/'raw/02.body').stat().st_size,65537)
            self.assertEqual(m.decode((out/'terminal.json').read_bytes())['status'],'unavailable')


if __name__=='__main__':unittest.main()
