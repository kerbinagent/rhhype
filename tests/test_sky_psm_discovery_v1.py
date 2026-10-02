import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('psm', ROOT/'scripts/sky_psm_discovery_v1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def word(n):
    return '0x'+format(n, '064x')


class PsmDiscoveryTests(unittest.TestCase):
    def fixture(self):
        block = dict(number='0x123', hash='0x'+'ab'*32, parentHash='0x'+'cd'*32,
                     timestamp='0x100', stateRoot='0x'+'ef'*32, gasLimit='0x3938700',
                     miner='0x'+'11'*20, mixHash='0x'+'22'*32, baseFeePerGas='0x9')
        values = dict(chain='0x1', block=block, recheck=copy.deepcopy(block))
        fields = dict(gem=int(m.USDC,16), dai=int(m.DAI,16), pocket=int(m.POCKET,16),
                      conversion=10**12, tin=0, tout=10**15, buf=100*10**18, live=1,
                      dai_decimals=18, usdc_decimals=6, psm_dai_balance=100*10**18,
                      pocket_usdc_balance=100*10**6, pocket_usdc_allowance=2**256-1)
        values.update({key:word(value) for key,value in fields.items()})
        for fee in m.FEES:
            values['pool_'+str(fee)] = word(0 if fee==10000 else fee)
        seen = []
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable))
            return copy.deepcopy(values[name])
        return values,seen,rpc

    def test_fixed_calls_use_documented_addresses_at_one_hash(self):
        values,seen,rpc=self.fixture()
        p=m.collect(rpc)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(len(seen),20)
        self.assertEqual(p['calls_available'],17)
        self.assertTrue(p['conditions']['documented_identity_matches'])
        self.assertTrue(p['conditions']['expected_units_match'])
        self.assertEqual([x['nonzero_address'] for x in p['pools']],[True,True,True,False])
        gas=0
        for name,method,params,optional in seen[2:-1]:
            self.assertEqual(method,'eth_call')
            self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=values['block']['hash'],requireCanonical=True))
            call=params[0]
            self.assertEqual(call['from'],m.DIAGNOSTIC)
            self.assertEqual(call['value'],'0x0')
            self.assertEqual(call['gasPrice'],'0x0')
            gas+=int(call['gas'],16)
            if name.startswith('pool_'):
                fee=int(name.split('_')[1])
                self.assertEqual(call['to'],m.FACTORY)
                self.assertEqual(call['input'],m.s.selector('getPool(address,address,uint24)')+
                                 m.s.word_address(m.DAI)+m.s.word_address(m.USDC)+format(fee,'064x'))
        self.assertEqual(gas,5100000)
        self.assertFalse(p['economics'])
        self.assertFalse(p['conditions']['eligibility_or_executability_proved'])

    def test_unknown_and_halted_fees_preserve_complete_denominator(self):
        values,seen,rpc=self.fixture()
        values.update(tin=word(m.HALTED),tout={'rpc_unavailable':3},pocket_usdc_allowance=None,pool_500={'rpc_unavailable':-32000})
        p=m.collect(rpc)
        self.assertFalse(p['conditions']['sell_fee_not_halted'])
        self.assertIsNone(p['conditions']['buy_fee_not_halted'])
        self.assertIsNone(p['conditions']['positive_observed_inventory_or_allowance']['pocket_usdc_allowance'])
        self.assertIsNone(p['pools'][1]['nonzero_address'])
        self.assertEqual(len(seen),20)
        self.assertEqual(p['calls_available'],14)

    def test_identity_mismatch_does_not_redirect_other_calls(self):
        values,seen,rpc=self.fixture()
        values['pocket']=word(42)
        values['dai_decimals']=word(6)
        p=m.collect(rpc)
        self.assertFalse(p['conditions']['documented_identity_matches'])
        self.assertFalse(p['conditions']['expected_units_match'])
        for name,method,params,optional in seen:
            if name=='pocket_usdc_balance':
                self.assertEqual(params[0]['to'],m.USDC)
                self.assertTrue(params[0]['input'].endswith(m.s.word_address(m.POCKET)))

    def test_canonical_abi_and_fee_domain(self):
        for value in (None,True,1,'0x','0x00',word(1)+'00'):
            self.assertFalse(m.result(value,'uint')['available'])
        for kind,value in [('address',word(0)),('address',word(2**160)),('decimal',word(256)),
                           ('boolean',word(2)),('fee',word(m.WAD+1))]:
            self.assertFalse(m.result(value,kind)['available'])
        self.assertTrue(m.result(word(0),'pool')['available'])
        self.assertTrue(m.result(word(m.WAD),'fee')['available'])
        self.assertTrue(m.result(word(m.HALTED),'fee')['available'])

    def test_known_mismatch_survives_another_unknown_getter(self):
        values,seen,rpc=self.fixture()
        values.update(gem=word(42),dai={'rpc_unavailable':3},conversion=word(1),usdc_decimals=None)
        p=m.collect(rpc)
        self.assertFalse(p['conditions']['documented_identity_matches'])
        self.assertFalse(p['conditions']['expected_units_match'])
        values.update(gem=word(int(m.USDC,16)),conversion=word(10**12))
        p=m.collect(rpc)
        self.assertIsNone(p['conditions']['documented_identity_matches'])
        self.assertIsNone(p['conditions']['expected_units_match'])

    def test_empty_inventory_is_distinct_from_unavailable(self):
        values,seen,rpc=self.fixture()
        values.update(psm_dai_balance=word(0),pocket_usdc_balance=None,pocket_usdc_allowance=word(0))
        flags=m.collect(rpc)['conditions']['positive_observed_inventory_or_allowance']
        self.assertEqual(flags,dict(psm_dai_balance=False,pocket_usdc_balance=None,pocket_usdc_allowance=False))

    def test_wrong_chain_or_changed_header_rejects_projection(self):
        for field in ('chain','hash','stateRoot','timestamp','baseFeePerGas'):
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
            if failure=='sentinel' and i==1:
                raw=b'x'*(cap+1)
            elif failure=='rpc' and name=='tin':
                raw=m.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=3,message='reverted')))
            else:
                raw=m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
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

    def test_capture_replays_and_preserves_optional_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ok,sent=self.execute(root,'rpc')
            self.assertTrue(ok)
            self.assertEqual(len(sent),20)
            out=root/m.OUT
            p,body,raw=m.replay(out/'raw')
            self.assertIsNone(p['conditions']['sell_fee_not_halted'])
            self.assertEqual(len(list((out/'raw').iterdir())),80)
            terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            path=out/'raw/20.body'
            changed=m.decode(path.read_bytes())
            changed['result']['hash']='0x'+'99'*32
            path.write_bytes(m.encode(changed))
            with self.assertRaisesRegex(m.t.Refusal,'incomplete_rpc'):m.replay(out/'raw')

    def test_header_cap_failure_retained_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ok,sent=self.execute(root,'sentinel')
            self.assertFalse(ok)
            self.assertEqual(len(sent),2)
            out=root/m.OUT
            self.assertFalse((out/'projection.json').exists())
            self.assertEqual((out/'raw/02.body').stat().st_size,65537)
            self.assertEqual(m.decode((out/'terminal.json').read_bytes())['status'],'unavailable')


if __name__=='__main__':
    unittest.main()
