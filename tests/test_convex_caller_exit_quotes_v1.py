import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sp=importlib.util.spec_from_file_location('exit_quotes',ROOT/'scripts/convex_caller_exit_quotes_v1.py')
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
word=lambda n:'0x'+format(n,'064x')


class ExitTests(unittest.TestCase):
    def fixture(self):
        setup=m.inputs();value=copy.deepcopy(setup['prefix']);calls=value[0]['calls']
        reference=int(setup['receipt']['simulated_gas_used'][1])*int(setup['context']['baseFeePerGas'],16)
        for amount in (reference-1,reference,reference+1,reference+2):
            calls.append(dict(status='0x1',gasUsed='0x30d40',returnData='0x'+''.join(format(x,'064x') for x in (amount,2**96,0,100000)),logs=[]))
        calls.append(copy.deepcopy(calls[2]))
        values=dict(chain='0x1',factory='0x'+m.q.FACTORY[2:].rjust(64,'0'),simulation=value,recheck=copy.deepcopy(setup['block']))
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return setup,values,seen,rpc

    def test_quotes_after_exact_original_prefix(self):
        setup,v,seen,rpc=self.fixture();p=m.collect(rpc,setup);z=p['result']
        self.assertEqual([x['quote_minus_simulated_harvest_gas_wei'] for x in z['quotes']],['-1','0','1','2'])
        self.assertEqual(z['complete_quotes'],4);self.assertTrue(z['original_harvest_prefix_matched']);self.assertFalse(p['cash_closed'])
        self.assertEqual([x[0] for x in seen],['chain','factory','simulation','recheck'])
        params=seen[2][2];state=params[0]['blockStateCalls'][0]
        original=m.r.sim_params(setup['block'],setup['context'],0)
        self.assertEqual(state['calls'][:3],original[0]['blockStateCalls'][0]['calls']);self.assertNotIn('stateOverrides',state)
        self.assertFalse(params[0]['validation']);self.assertEqual(sum(int(x['gas'],16) for x in state['calls']),16300000)
        for call,fee in zip(state['calls'][3:7],m.FEES):
            self.assertEqual(call['input'],m.q.calldata(False,m.r.CRV,m.WETH,m.AMOUNT,fee))

    def test_reverts_partial_and_rpc_stay_unknown(self):
        for mode in ('revert','partial','rpc'):
            setup,v,seen,rpc=self.fixture();calls=v['simulation'][0]['calls']
            if mode=='revert':calls[3].update(status='0x0',returnData='0x',error={'code':3})
            if mode=='partial':
                amount=int(calls[3]['returnData'][2:66],16)
                calls[3]['returnData']='0x'+''.join(format(x,'064x') for x in (amount,m.q.MAX_PRICE-1,0,100000))
            if mode=='rpc':v['simulation']={'rpc_unavailable':-32601}
            with self.subTest(mode=mode):
                z=m.collect(rpc,setup)['result'];self.assertEqual(len(seen),4)
                if mode=='rpc':self.assertFalse(z['available']);self.assertEqual(z['quotes'],[])
                else:self.assertEqual(z['complete_quotes'],3);self.assertIsNone(z['quotes'][0]['quote_minus_simulated_harvest_gas_wei'])

    def test_prefix_context_final_balance_and_header_tampering(self):
        for mode in ('prefix','context','balance','header','factory','status','log'):
            setup,v,seen,rpc=self.fixture();calls=v['simulation'][0]['calls']
            if mode=='prefix':calls[1]['gasUsed']=hex(int(calls[1]['gasUsed'],16)+1)
            if mode=='context':v['simulation'][0]['timestamp']='0x1'
            if mode=='balance':calls[7]['returnData']=word(m.AMOUNT+1)
            if mode=='header':v['recheck']['stateRoot']='0x'+'00'*32
            if mode=='factory':v['factory']=word(0)
            if mode=='status':calls[3]['status']='0x2'
            if mode=='log':calls[3]['logs']=copy.deepcopy(calls[1]['logs'][:1])
            with self.subTest(mode=mode),self.assertRaises(Exception):m.collect(rpc,setup)

    def test_transport_replay_and_failure_retention(self):
        for overflow in (False,True):
            setup,values,seen,rpc=self.fixture();m.collect(rpc,setup);sent=[]
            def fetch(request,cap,seconds,emit,observe,dispatch):
                name,method,params,optional=seen[len(sent)]
                self.assertEqual(request,dict(jsonrpc='2.0',id=len(sent)+1,method=method,params=params))
                dispatch();sent.append(request);observe(200,m.encode(dict(status=200,headers=[])))
                raw=b'x'*(cap+1) if overflow and name=='simulation' else m.encode(dict(jsonrpc='2.0',id=len(sent),result=values[name]))
                emit(raw)
                if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
                return 200,len(raw)
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/m.BASE).mkdir(parents=True)
                with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value=setup),mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
                    self.assertEqual(m.run('a'*64),not overflow)
                    with self.assertRaises(FileExistsError):m.run('a'*64)
                out=root/m.OUT
                if overflow:
                    self.assertFalse((out/'projection.json').exists());self.assertEqual(len(sent),3)
                    self.assertEqual((out/'raw/03.body').stat().st_size,32769)
                else:
                    p,b,r=m.replay(out/'raw',setup);self.assertEqual(p['result']['complete_quotes'],4)
                    path=out/'raw/03.request.json';v=m.decode(path.read_bytes());v['request']['params'][0]['validation']=True;path.write_bytes(m.encode(v))
                    with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',setup)


if __name__=='__main__':unittest.main()
