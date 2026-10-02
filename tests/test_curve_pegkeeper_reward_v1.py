import copy
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('keeper',ROOT/'scripts/curve_pegkeeper_reward_v1.py')
k=importlib.util.module_from_spec(spec);spec.loader.exec_module(k)


def word(n):return '0x'+format(n,'064x')


class KeeperTests(unittest.TestCase):
    def fixture(self):
        block=dict(number='0x123',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,
                   timestamp='0x100',stateRoot='0x'+'ef'*32,gasLimit='0x3938700',
                   miner='0x'+'11'*20,mixHash='0x'+'22'*32,baseFeePerGas='0x9')
        values=dict(chain='0x1',block=block,recheck=copy.deepcopy(block))
        for i in range(4):
            for name,_,_ in k.FIELDS:
                n={'pool':int('33'*20,16),'pegged':int(k.CRVUSD,16),
                   'regulator':int(k.REGULATOR,16),'caller_share':20000,'last_change':128,
                   'estimate':0,'update':7 if i==0 else 0}[name]
                values[str(i)+'_'+name]=word(n)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable))
            return copy.deepcopy(values[name])
        return values,seen,rpc

    def test_manifest_state_and_diagnostic_caller(self):
        values,seen,rpc=self.fixture();projection=k.collect(rpc)
        self.assertEqual([x[0] for x in seen],[x[0] for x in k.SLOTS])
        gas=0
        for i,(label,keeper) in enumerate(k.KEEPERS):
            for j,(name,signature,limit) in enumerate(k.FIELDS):
                slot,method,params,optional=seen[2+i*7+j]
                self.assertEqual(method,'eth_call');self.assertTrue(optional)
                self.assertEqual(params[1],dict(blockHash=values['block']['hash'],requireCanonical=True))
                call=params[0];self.assertEqual(set(call),{'from','to','input','value','gasPrice','gas'})
                self.assertEqual(call['from'],k.DIAGNOSTIC);self.assertEqual(call['to'],keeper)
                self.assertEqual(call['value'],'0x0');self.assertEqual(call['gasPrice'],'0x0')
                self.assertEqual(int(call['gas'],16),limit);gas+=limit
                self.assertEqual(call['input'],k.s.selector(signature)+(k.s.word_address(k.DIAGNOSTIC) if name=='update' else ''))
        self.assertEqual(gas,20000000)
        self.assertTrue(projection['independent_state_calls']);self.assertFalse(projection['rewards_summed'])
        for flag in ('diagnostic_sender_control_claimed','lp_cash_conversion_verified',
                     'token_transfer_or_balance_verified','runtime_equivalence_verified',
                     'obtainable_inclusion_verified','gas_cost_measured','live_profit','repeatable_profit'):
            self.assertFalse(projection[flag])

    def test_zero_estimate_does_not_discard_positive_update(self):
        values,seen,rpc=self.fixture();p=k.collect(rpc)
        self.assertEqual(p['rows'][0]['values']['estimate']['value'],'0')
        self.assertTrue(p['rows'][0]['positive_returned_reward'])
        self.assertEqual(p['positive_returned_reward_rows'],1)
        self.assertEqual(p['update_results_available'],4)
        self.assertEqual(len(p['rows']),4)

    def test_revert_null_and_malformed_stay_unknown(self):
        values,seen,rpc=self.fixture()
        values.update({'1_update':{'rpc_unavailable':-32000},'2_update':None,
                       '3_update':'0x','1_pegged':None,'2_regulator':word(0),
                       '3_caller_share':word(100001)})
        p=k.collect(rpc)
        self.assertEqual(p['update_results_available'],1)
        for row in p['rows'][1:]:self.assertIsNone(row['positive_returned_reward'])
        self.assertIsNone(p['rows'][1]['documented_pegged_and_regulator_match'])
        self.assertIsNone(p['rows'][2]['documented_pegged_and_regulator_match'])
        self.assertFalse(p['rows'][3]['all_fields_available'])
        self.assertEqual(len(seen),31)

    def test_abi_width_and_address_padding(self):
        for value in (None,True,1,'0x','0x00',word(1)+'00',{'other':1}):
            self.assertFalse(k.result(value,'update')['available'])
        for value in (word(0),word(2**160),'0x00'):
            self.assertFalse(k.result(value,'pool')['available'])
        self.assertEqual(k.result(word(2**256-1),'update')['value'],str(2**256-1))
        self.assertEqual(k.result(word(100000),'caller_share')['value'],'100000')

    def test_identity_mismatch_is_explicit_not_runtime_proof(self):
        values,seen,rpc=self.fixture();values['0_regulator']=word(int('55'*20,16))
        row=k.collect(rpc)['rows'][0]
        self.assertFalse(row['documented_pegged_and_regulator_match'])
        self.assertTrue(row['positive_returned_reward'])

    def test_chain_and_header_change_stop(self):
        for field in ('chain','hash','timestamp','baseFeePerGas','stateRoot'):
            values,seen,rpc=self.fixture()
            if field=='chain':values['chain']='0x2'
            else:values['recheck'][field]='0x'+'aa'*32 if field in ('hash','stateRoot') else '0x2'
            with self.subTest(field=field),self.assertRaises((k.Refusal,k.s.o.Refusal)):
                k.collect(rpc)

    def execute(self,root,failure=None):
        values,seen,rpc=self.fixture();k.collect(rpc);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            index=len(sent);name,method,params,optional=seen[index]
            self.assertEqual(request,dict(jsonrpc='2.0',id=index+1,method=method,params=params))
            dispatch();sent.append(request)
            status=403 if failure=='http' and index==2 else 200
            if failure=='rpc' and index==8:
                raw=k.encode(dict(jsonrpc='2.0',id=index+1,error=dict(code=-32000,message='reverted')))
            elif failure=='identity' and index==2:
                raw=k.encode(dict(jsonrpc='2.0',id=999,result=values[name]))
            elif failure=='sentinel' and index==0:raw=b'x'*(cap+1)
            elif status!=200:raw=b'HTTP refusal'
            else:raw=k.encode(dict(jsonrpc='2.0',id=index+1,result=values[name]))
            observe(status,k.encode(dict(status=status,headers=[['content-length',str(len(raw))]])))
            for at in range(0,len(raw),97):emit(raw[at:at+97])
            if len(raw)>cap:raise k.h.Refusal('response_cap_sentinel_retained')
            return status,len(raw)
        (root/k.BASE).mkdir(parents=True)
        with mock.patch.object(k,'ROOT',root),mock.patch.object(k,'verify',return_value={'pins':[]}), \
             mock.patch.object(k.resource,'setrlimit'),mock.patch.object(k.h,'fetch',side_effect=fetch):
            ok=k.run('a'*64)
            with self.assertRaises(FileExistsError):k.run('a'*64)
        return ok,sent

    def test_exact_capture_replay_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),31)
            out=root/k.OUT;p,body,raw=k.replay(out/'raw')
            terminal=k.decode((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['body_bytes'],body);self.assertEqual(terminal['raw_bytes'],raw)
            self.assertEqual(len(list((out/'raw').iterdir())),124)
            path=out/'raw/09.request.json';original=path.read_bytes();changed=k.decode(original)
            changed['request']['params'][0]['from']='0x'+'44'*20;path.write_bytes(k.encode(changed))
            with self.assertRaisesRegex(k.t.Refusal,'request_manifest'):k.replay(out/'raw')
            path.write_bytes(original);(out/'raw/09.body').write_bytes(word(0).encode())
            with self.assertRaisesRegex(k.t.Refusal,'incomplete_rpc'):k.replay(out/'raw')

    def test_rpc_revert_does_not_select_another_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent=self.execute(root,'rpc');self.assertTrue(ok)
            p,_,_=k.replay(root/k.OUT/'raw')
            self.assertIsNone(p['rows'][0]['positive_returned_reward'])
            self.assertEqual(p['positive_returned_reward_rows'],0)
            self.assertEqual(p['update_results_available'],3);self.assertEqual(len(sent),31)

    def test_failed_capture_is_preserved_without_projection(self):
        for failure in ('http','identity','sentinel'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent=self.execute(root,failure);self.assertFalse(ok)
                self.assertEqual(len(sent),1 if failure=='sentinel' else 3)
                out=root/k.OUT;self.assertFalse((out/'projection.json').exists())
                self.assertEqual(k.decode((out/'terminal.json').read_bytes())['status'],'unavailable')
                if failure=='sentinel':self.assertEqual((out/'raw/01.body').stat().st_size,4097)

    def test_reserve_before_network(self):
        for key in ('raw_bytes','body_bytes'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                cap=dict(k.CAPS,**{key:100})
                capture=k.t.Capture(Path(tmp)/'raw',k.SLOTS,cap,k.c,time.monotonic(),k.reason)
                with mock.patch.object(k.h,'fetch') as fetch,self.assertRaisesRegex(k.t.Refusal,'reserve_before_dispatch'):
                    capture.rpc('chain','eth_chainId',[])
                fetch.assert_not_called();self.assertEqual(capture.attempts,0)


if __name__=='__main__':unittest.main()
