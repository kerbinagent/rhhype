import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cash_screen',ROOT/'scripts/uniswap_fee_cash_screen_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def answer(amount,price=2**96,ticks=0,gas=100000):
    return '0x'+''.join(format(x,'064x') for x in (amount,price,ticks,gas))


class CashScreenTests(unittest.TestCase):
    def fixture(self):
        args=m.inputs();values={'chain':'0x1','factory':'0x'+m.s.word_address(m.FACTORY)}
        for i,row in enumerate(m.ROUTES):values[row[0]]=answer((i+1)*10**6)
        values['recheck']=m.decode((ROOT/'reports/uniswap-fee-collect-v1/run-v1/raw/06.body').read_bytes())['result']
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return args,values,seen,rpc

    def test_exact_quantities_distinct_pools_and_closed_token_math(self):
        args,v,seen,rpc=self.fixture();p=m.collect(rpc,*args)
        self.assertTrue(p['all_quotes_admitted']);self.assertEqual(len(set(p['pools'])),6)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(int(p['rows'][1]['quantity']),args[2]['WETH']+10**6)
        self.assertEqual(int(p['rows'][5]['quantity']),4000*10**18)
        expected=args[2]['USDC']+(2+3+4+5)*10**6-6*10**6
        self.assertEqual(int(p['quoted_surplus_before_transaction_costs']),expected)
        self.assertFalse(p['cash_closed']);self.assertFalse(p['repeatable_profit'])
        self.assertLessEqual(len(m.encode(dict(p,plan_sha256='a'*64))),4096)
        self.assertEqual(sum(int(x[2][0]['gas'],16) for x in seen[1:-1]),18300000)
        for i,row in enumerate(p['rows']):
            tx,state=seen[i+2][2];raw=tx['input'][10:];words=[int(raw[k:k+64],16) for k in range(0,len(raw),64)]
            name,a,b,fee=m.ROUTES[i]
            self.assertEqual(words,[int(args[1][a],16),int(args[1][b],16),int(row['quantity']),fee,0])
            self.assertEqual(state,dict(blockHash=args[0]['anchor']['hash'],requireCanonical=True))
        self.assertNotEqual(seen[2][2][0]['input'][:10],seen[7][2][0]['input'][:10])

    def test_unknown_partial_input_and_zero_factory_suppress_totals(self):
        for key,value in [('uni_exit',{'rpc_unavailable':3}),('uni_exit',answer(1,m.MIN_PRICE+1)),
                          ('factory','0x'+'0'*64),('purchase',None)]:
            args,v,seen,rpc=self.fixture();v[key]=value;p=m.collect(rpc,*args)
            self.assertFalse(p['all_quotes_admitted']);self.assertIsNone(p['quoted_surplus_before_transaction_costs'])
            self.assertEqual(len(seen),9)
            if key=='uni_exit':
                self.assertFalse(p['rows'][1]['dependency_available'])
                self.assertEqual(int(p['rows'][1]['quantity']),args[2]['WETH'])

    def test_abi_domains_and_reorg(self):
        for value in (None,'0x',answer(1)+'00',answer(1,m.MIN_PRICE),answer(1,ticks=2**32),answer(1,gas=3000001)):
            self.assertFalse(m.quote(value)['available'])
        self.assertEqual(m.quote(answer(0))['amount'],'0')
        args,v,seen,rpc=self.fixture();v['recheck']['stateRoot']='0x'+'99'*32
        with self.assertRaisesRegex(m.Refusal,'anchor_changed'):m.collect(rpc,*args)
        with self.assertRaises(m.Refusal):m.calldata(False,args[1]['UNI'],args[1]['WETH'],2**255,3000)

    def execute(self,root,overflow=False):
        args,values,seen,rpc=self.fixture();m.collect(rpc,*args);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if overflow and name=='uni_exit' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['x-test-padding','x'*1000]])))
            for k in range(0,len(raw),1024):emit(raw[k:k+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=args),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,args

    def test_full_capture_header_budget_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,args=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),9)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',args)
            terminal=m.decode((out/'terminal.json').read_bytes());self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),36)
            path=out/'raw/03.request.json';v=m.decode(path.read_bytes());v['request']['params'][1]['requireCanonical']=False;path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',args)

    def test_overflow_is_retained_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,args=self.execute(root,True);self.assertFalse(ok);self.assertEqual(len(sent),3)
            out=root/m.OUT;self.assertFalse((out/'projection.json').exists())
            self.assertEqual((out/'raw/03.body').stat().st_size,4097)


if __name__=='__main__':unittest.main()
