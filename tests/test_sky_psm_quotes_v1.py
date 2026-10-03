import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('quotes',ROOT/'scripts/sky_psm_quotes_v1.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)


def words(*n):return '0x'+''.join(format(x,'064x') for x in n)


class QuoteTests(unittest.TestCase):
    def fixture(self):
        original=q.inputs();b=original['block'];c=original['context']
        block=dict(number=hex(b['number']),hash=b['hash'],parentHash=b['parentHash'],timestamp=hex(b['timestamp']),
                   stateRoot=b['stateRoot'],gasLimit=c['gasLimit'],miner=c['feeRecipient'],mixHash=c['prevRandao'],baseFeePerGas=c['baseFeePerGas'])
        values=dict(chain='0x1',anchor=block,recheck=copy.deepcopy(block),quoter_factory=words(int(q.m.FACTORY,16)))
        for fee in q.m.FEES:
            for name,address in [('factory',q.m.FACTORY),('token0',q.m.DAI),('token1',q.m.USDC)]:
                values[str(fee)+'_'+name]=words(int(address,16))
            values[str(fee)+'_fee']=words(fee)
            for lot in q.LOTS:
                for direction in q.DIRECTIONS:
                    t=q.terms(original,lot,direction)
                    values[str(fee)+'_'+str(lot)+'_'+direction]=words(t['proceeds']+10,2**96,2,123456)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return original,values,seen,rpc

    def test_full_fixed_matrix_and_exact_output_abi(self):
        original,values,seen,rpc=self.fixture();p=q.collect(rpc,original)
        self.assertEqual([x[0] for x in seen],[x[0] for x in q.SLOTS]);self.assertEqual(len(seen),52)
        self.assertEqual(p['fixed_rows'],32);self.assertEqual(p['available_quotes'],32)
        self.assertEqual(p['positive_conditional_rows'],0);self.assertEqual(p['unknown_or_unadmitted_rows'],0)
        gas=0
        for name,method,params,optional in seen[2:-1]:
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=original['block']['hash'],requireCanonical=True))
            tx=params[0];gas+=int(tx['gas'],16);self.assertEqual(tx['from'],q.m.DIAGNOSTIC)
            self.assertEqual(tx['value'],'0x0');self.assertEqual(tx['gasPrice'],'0x0')
            if name.endswith('_cycle'):
                fee,lot,direction=name.split('_',2);t=q.terms(original,int(lot),direction)
                expected=q.s.selector(q.SIGNATURE)+q.s.word_address(t['token_in'])+q.s.word_address(t['token_out'])+''.join(
                    format(x,'064x') for x in (t['dex_output'],int(fee),0))
                self.assertEqual(tx['input'],expected);self.assertEqual(tx['to'],q.QUOTER)
        self.assertEqual(gas,101100000)
        self.assertLessEqual(len(q.encode(p)),q.CAPS['projection_bytes'])
        for flag in ('closed_cash','token_payment_verified','actual_psm_swap_verified','full_transaction_gas_measured','economics','repeatable_profit'):
            self.assertFalse(p[flag])

    def test_fee_rounding_and_settlement_units(self):
        original,_,_,_=self.fixture();v=original['values']
        v['tin']['value']='1';v['tout']['value']='1'
        d=q.terms(original,1,'dai_cycle');u=q.terms(original,1,'usdc_cycle')
        self.assertEqual(d['dex_output'],10**6);self.assertEqual(d['proceeds'],10**18-1)
        self.assertEqual(u['dex_output'],10**18+1);self.assertEqual(u['proceeds'],10**6)
        self.assertEqual((d['unit'],d['decimals']),('DAI',18));self.assertEqual((u['unit'],u['decimals']),('USDC',6))
        v['psm_dai_balance']['value']='0';v['pocket_usdc_allowance']['value']='0'
        self.assertFalse(q.terms(original,1,'dai_cycle')['inventory'])
        self.assertFalse(q.terms(original,1,'usdc_cycle')['inventory'])

    def test_errors_and_positive_margins_without_identity_are_unadmitted(self):
        original,values,seen,rpc=self.fixture()
        values['100_1000_dai_cycle']={'rpc_unavailable':3}
        values['500_token0']=words(42);values['500_token1']=None
        values['500_1000_usdc_cycle']=words(1,2**96,0,20000)
        p=q.collect(rpc,original)
        self.assertEqual(len(seen),52);self.assertEqual(p['available_quotes'],31)
        self.assertIsNone(p['rows'][0]['positive_conditional_candidate'])
        self.assertFalse(p['pools'][1]['identity_matches'])
        row=next(x for x in p['rows'] if (x['fee'],x['usdc_lot'],x['direction'])==(500,1000,'usdc_cycle'))
        self.assertGreater(int(row['modeled_margin_before_gas_raw']),0)
        self.assertIsNone(row['positive_conditional_candidate'])

    def test_positive_candidate_is_separate_from_cash_and_gas(self):
        original,values,seen,rpc=self.fixture()
        values['100_1000_usdc_cycle']=words(999*10**6,2**96,0,20000)
        p=q.collect(rpc,original);self.assertEqual(p['positive_conditional_rows'],1)
        row=p['rows'][1];self.assertEqual(row['modeled_margin_before_gas_raw'],'1000000')
        self.assertEqual(row['settlement_unit'],'USDC');self.assertFalse(p['quote_gas_is_total_cost']);self.assertFalse(p['closed_cash'])

    def test_quote_abi_rejects_truncation_padding_and_gas_overrun(self):
        for value in (None,'0x',words(1,2,3),words(1,2,3,4,5),words(1,2**160,0,1),words(1,1,2**32,1),words(1,1,0,3000001),words(0,1,0,1)):
            with self.subTest(value=value):self.assertFalse(q.quote(value)['available'])
        self.assertTrue(q.quote(words(1,1,0,3000000))['available'])

    def test_original_and_final_headers_are_required(self):
        for name in ('anchor','recheck'):
            original,values,seen,rpc=self.fixture();values[name]['hash']='0x'+'99'*32
            with self.subTest(name=name),self.assertRaises((q.Refusal,q.s.o.Refusal)):q.collect(rpc,original)

    def test_complete_capture_replay_single_use_and_preserved_rpc_error(self):
        original,values,seen,rpc=self.fixture();values['3000_1000000_usdc_cycle']={'rpc_unavailable':3}
        q.collect(rpc,original);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch();sent.append(request)
            v=values[name]
            response=dict(jsonrpc='2.0',id=i+1)
            if isinstance(v,dict) and 'rpc_unavailable' in v:response['error']=dict(code=3,message='reverted')
            else:response['result']=v
            raw=q.encode(response);observe(200,q.encode(dict(status=200,headers=[['content-length',str(len(raw))]])));emit(raw)
            return 200,len(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/q.BASE).mkdir(parents=True)
            with mock.patch.object(q,'ROOT',root),mock.patch.object(q,'verify',return_value={'pins':[]}), \
                 mock.patch.object(q,'inputs',return_value=original),mock.patch.object(q.resource,'setrlimit'),mock.patch.object(q.h,'fetch',side_effect=fetch):
                self.assertTrue(q.run('a'*64))
                with self.assertRaises(FileExistsError):q.run('a'*64)
            out=root/q.OUT;p,body,raw=q.replay(out/'raw',original)
            self.assertEqual(len(sent),52);self.assertEqual(p['available_quotes'],31)
            self.assertEqual(len(list((out/'raw').iterdir())),208)
            self.assertLessEqual(raw,114688)
            terminal=q.decode((out/'terminal.json').read_bytes());self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            path=out/'raw/20.request.json';r=q.decode(path.read_bytes());r['request']['params'][0]['to']=q.m.DAI;path.write_bytes(q.encode(r))
            with self.assertRaisesRegex(q.t.Refusal,'request_manifest'):q.replay(out/'raw',original)


if __name__=='__main__':unittest.main()
