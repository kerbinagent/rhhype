import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('convex',ROOT/'scripts/convex_caller_incentive_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
word=lambda n:'0x'+format(n,'064x')
addr=lambda a:word(int(a,16))


class RewardTests(unittest.TestCase):
    def fixture(self):
        block=dict(number='0x123',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,timestamp='0x100',
            stateRoot='0x'+'ef'*32,gasLimit='0x3938700',miner='0x'+'11'*20,mixHash='0x'+'22'*32,baseFeePerGas='0x9')
        v=dict(chain='0x1',block=block,recheck=copy.deepcopy(block),crv=addr(m.CRV),staker=addr(m.STAKER),operator=addr(m.BOOSTER),
            shutdown=word(0),denominator=word(10000),incentive=word(50),length=word(301),decimals=word(18))
        for i in range(4):
            v['pool_'+str(i)]='0x'+''.join(format(x,'064x') for x in (1,2,3,4,0,0))
            call=lambda n:dict(status='0x1',gasUsed='0x7530',returnData=word(n),logs=[])
            a,b,c=call(5),call(1),call(15)
            b['logs']=[dict(address=m.CRV,topics=[m.TRANSFER,addr(m.BOOSTER),addr(m.ACTOR)],data=word(10))]
            simulated=copy.deepcopy(block);simulated.update(number='0x124',timestamp='0x10c',calls=[a,b,c])
            v['branch_'+str(i)]=[simulated]
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(v[name])
        return v,seen,rpc

    def test_independent_receipts_and_explicit_nonpaid_scope(self):
        v,seen,rpc=self.fixture();p=m.collect(rpc)
        self.assertEqual([x['pid'] for x in p['branches']],[0,100,200,300])
        self.assertTrue(all(x['receipt_raw']=='10' for x in p['branches']));self.assertFalse(p['economics'])
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        for _,method,params,optional in seen:
            if method=='eth_call':self.assertEqual(params[1],dict(blockHash=v['block']['hash'],requireCanonical=True))
            if method=='eth_simulateV1':
                self.assertTrue(optional);self.assertFalse(params[0]['validation']);self.assertEqual(params[1],'0x123')
                state=params[0]['blockStateCalls'][0];self.assertNotIn('stateOverrides',state)
                self.assertEqual(sum(int(x['gas'],16) for x in state['calls']),4200000)
                self.assertTrue(all(x['from']==m.ACTOR and x['gasPrice']=='0x0' for x in state['calls']))

    def test_zero_negative_revert_and_unknown_are_distinct(self):
        for mode,expected in [('zero','0'),('negative','-5'),('revert',None),('rpc',None),('mismatch',None),('context',None),('bool',None)]:
            v,seen,rpc=self.fixture();b=v['branch_0'][0];calls=b['calls']
            if mode=='zero':calls[2]['returnData']=word(5);calls[1]['logs']=[]
            if mode=='negative':
                calls[2]['returnData']=word(0);calls[1]['logs'][0].update(topics=[m.TRANSFER,addr(m.ACTOR),addr(m.BOOSTER)],data=word(5))
            if mode=='revert':calls[1].update(status='0x0',returnData='0x',logs=[],error={'code':3});calls[2]['returnData']=word(5)
            if mode=='rpc':v['branch_0']={'rpc_unavailable':-32601}
            if mode=='mismatch':calls[2]['returnData']=word(16)
            if mode=='context':b['timestamp']='0x10d'
            if mode=='bool':calls[1]['returnData']=word(2)
            with self.subTest(mode=mode):
                p=m.collect(rpc);self.assertEqual(p['branches'][0]['receipt_raw'],expected)
                self.assertEqual(len(seen),19);self.assertEqual(p['available_branches'],4 if expected is not None else 3)

    def test_mandatory_metadata_and_reorg_stop(self):
        for key,value in [('length',word(4097)),('length',word(3)),('operator',addr(m.ACTOR)),('shutdown',word(2)),('pool_0','0x')]:
            v,seen,rpc=self.fixture();v[key]=value
            with self.subTest(key=key),self.assertRaises(Exception):m.collect(rpc)
        v,seen,rpc=self.fixture();v['recheck']['stateRoot']='0x'+'00'*32
        with self.assertRaises(Exception):m.collect(rpc)

    def test_capture_replay_and_retained_overflow(self):
        for overflow in (False,True):
            v,seen,rpc=self.fixture();m.collect(rpc);sent=[]
            def fetch(request,cap,seconds,emit,observe,dispatch):
                name,method,params,optional=seen[len(sent)]
                self.assertEqual(request,dict(jsonrpc='2.0',id=len(sent)+1,method=method,params=params))
                dispatch();sent.append(request);observe(200,m.encode(dict(status=200,headers=[])))
                raw=b'x'*(cap+1) if overflow and name=='branch_0' else m.encode(dict(jsonrpc='2.0',id=len(sent),result=v[name]))
                emit(raw)
                if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
                return 200,len(raw)
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/m.BASE).mkdir(parents=True)
                with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}),mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
                    self.assertEqual(m.run('a'*64),not overflow)
                    with self.assertRaises(FileExistsError):m.run('a'*64)
                out=root/m.OUT
                if overflow:
                    self.assertFalse((out/'projection.json').exists());self.assertEqual(len(sent),15)
                    self.assertEqual((out/'raw/15.body').stat().st_size,32769)
                else:
                    p,b,r=m.replay(out/'raw');self.assertEqual(p['available_branches'],4)
                    path=out/'raw/15.request.json';x=m.decode(path.read_bytes());x['request']['params'][0]['validation']=True;path.write_bytes(m.encode(x))
                    with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw')


if __name__=='__main__':unittest.main()
