import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sp=importlib.util.spec_from_file_location('beefy',ROOT/'scripts/beefy_caller_reward_v1.py')
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
word=lambda n:'0x'+format(n,'064x')
addr=lambda a:word(int(a,16))


class RewardTests(unittest.TestCase):
    def fixture(self):
        block=dict(number='0x123',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,timestamp='0x100',
            stateRoot='0x'+'ef'*32,gasLimit='0x3938700',miner='0x'+'11'*20,mixHash='0x'+'22'*32,baseFeePerGas='0x9')
        v=dict(chain='0x1',block=block,recheck=copy.deepcopy(block))
        for i in range(2):
            strategy='0x'+str(i+1)*40
            v.update({str(i)+'_strategy':addr(strategy),str(i)+'_native':addr(m.WETH),str(i)+'_paused':word(0),str(i)+'_callReward':word(9999)})
            call=lambda n:dict(status='0x1',gasUsed='0x7530',returnData=word(n),logs=[])
            a,b,c=call(5),call(1),call(15);b['returnData']='0x'
            b['logs']=[dict(address=m.WETH,topics=[m.r.TRANSFER,addr(strategy),addr(m.r.ACTOR)],data=word(10))]
            simulated=copy.deepcopy(block);simulated.update(number='0x124',timestamp='0x10c',calls=[a,b,c]);v['branch_'+str(i)]=[simulated]
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(v[name])
        return v,seen,rpc

    def test_receipt_is_observed_independently_of_estimate(self):
        v,seen,rpc=self.fixture();p=m.collect(rpc)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS]);self.assertEqual(seen[1][2],['latest',False])
        for row in p['vaults']:
            self.assertEqual(row['metadata']['callReward']['value'],'9999');self.assertEqual(row['simulation']['weth_receipt_raw'],'10')
            self.assertEqual(row['simulation']['weth_receipt_minus_unpaid_reference_wei'],str(10-30000*9))
            self.assertEqual(row['simulation']['harvest_return_bytes'],0)
        self.assertFalse(p['cash_closed']);self.assertTrue(p['independent_same_state_branches'])
        for name,method,params,optional in seen:
            if method=='eth_call':self.assertEqual(params[1],dict(blockHash=v['block']['hash'],requireCanonical=True))
            if method=='eth_simulateV1':
                self.assertTrue(optional);self.assertFalse(params[0]['validation']);self.assertEqual(params[1],'0x123')
                state=params[0]['blockStateCalls'][0];self.assertNotIn('stateOverrides',state)
                self.assertEqual(sum(int(x['gas'],16) for x in state['calls']),4200000)
                self.assertEqual(state['calls'][1]['input'],m.s.selector('harvest(address)')+m.s.word_address(m.r.ACTOR))

    def test_metadata_unknowns_do_not_select_harvests(self):
        v,seen,rpc=self.fixture();v['0_native']={'rpc_unavailable':-32601};v['0_callReward']='0x';v['1_paused']=word(2)
        p=m.collect(rpc);self.assertEqual(len(seen),13);self.assertEqual(p['available_branches'],2)
        self.assertIsNone(p['vaults'][0]['reported_native_matches_weth'])
        self.assertFalse(p['vaults'][1]['metadata']['paused']['available'])
        v['0_strategy']=word(0)
        with self.assertRaises(Exception):m.collect(rpc)

    def test_zero_negative_revert_rpc_and_schema_failures_remain_distinct(self):
        for mode,expected in [('zero','0'),('negative','-5'),('revert',None),('rpc',None),('mismatch',None),('context',None),('topic',None)]:
            v,seen,rpc=self.fixture();b=v['branch_0'][0];calls=b['calls']
            if mode=='zero':calls[2]['returnData']=word(5);calls[1]['logs']=[]
            if mode=='negative':
                calls[2]['returnData']=word(0);calls[1]['logs'][0].update(topics=[m.r.TRANSFER,addr(m.r.ACTOR),addr('0x'+'11'*20)],data=word(5))
            if mode=='revert':calls[1].update(status='0x0',returnData='0x',logs=[],error={'code':3});calls[2]['returnData']=word(5)
            if mode=='rpc':v['branch_0']={'rpc_unavailable':-32601}
            if mode=='mismatch':calls[2]['returnData']=word(16)
            if mode=='context':b['timestamp']='0x10d'
            if mode=='topic':calls[1]['logs'][0]['topics'].pop()
            with self.subTest(mode=mode):
                p=m.collect(rpc);self.assertEqual(p['vaults'][0]['simulation']['weth_receipt_raw'],expected)
                self.assertEqual(len(seen),13);self.assertEqual(p['available_branches'],2 if expected is not None else 1)
        v,seen,rpc=self.fixture();v['recheck']['stateRoot']='0x'+'00'*32
        with self.assertRaises(Exception):m.collect(rpc)

    def test_capture_replay_and_retained_cap_or_http_failures(self):
        for mode,attempts in [('normal',13),('overflow',11),('http',4),('reserve',12)]:
            v,seen,rpc=self.fixture()
            if mode=='reserve':
                for name in ('block','recheck'):v[name]['syntheticPadding']='x'*20000
                for name in ('branch_0','branch_1'):v[name][0]['syntheticPadding']='x'*26000
            m.collect(rpc);sent=[]
            def fetch(request,cap,seconds,emit,observe,dispatch):
                name,method,params,optional=seen[len(sent)]
                self.assertEqual(request,dict(jsonrpc='2.0',id=len(sent)+1,method=method,params=params))
                dispatch();sent.append(request);code=403 if mode=='http' and name=='0_native' else 200
                observe(code,m.encode(dict(status=code,headers=[])))
                raw=b'x'*(cap+1) if mode=='overflow' and name=='branch_0' else m.encode(dict(jsonrpc='2.0',id=len(sent),result=v[name]))
                emit(raw)
                if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
                return code,len(raw)
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/m.BASE).mkdir(parents=True)
                with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}),mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
                    self.assertEqual(m.run('a'*64),mode=='normal')
                    with self.assertRaises(FileExistsError):m.run('a'*64)
                out=root/m.OUT;self.assertEqual(len(sent),attempts)
                if mode=='normal':
                    p,b,r=m.replay(out/'raw');self.assertEqual(p['available_branches'],2)
                    path=out/'raw/11.request.json';v=m.decode(path.read_bytes());v['request']['params'][0]['validation']=True;path.write_bytes(m.encode(v))
                    with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw')
                else:
                    self.assertFalse((out/'projection.json').exists())
                    if mode=='overflow':self.assertEqual((out/'raw/11.body').stat().st_size,32769)
                    if mode=='reserve':self.assertEqual(m.decode((out/'terminal.json').read_bytes())['error'],'reserve_before_dispatch')


if __name__=='__main__':unittest.main()
