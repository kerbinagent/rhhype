import importlib.util
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fee_collect',ROOT/'scripts/uniswap_fee_collect_v1.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def result(values,offset=32):
    return '0x'+''.join(format(x,'064x') for x in [offset,len(values)]+[x for pair in values for x in pair])


class FeeCollectAbiTests(unittest.TestCase):
    def test_max_requests_and_exact_static_tuple_array(self):
        pools=['0x'+format(x,'040x') for x in range(1,61)]
        data=m.call_data(pools)
        self.assertEqual(len(bytes.fromhex(data[2:])),4+64+60*96)
        words=[int(data[i:i+64],16) for i in range(10,len(data),64)]
        self.assertEqual(words[:2],[32,60])
        self.assertEqual(words[2:],[v for i in range(1,61) for v in (i,m.MAX128,m.MAX128)])
        for bad in ([],pools+[pools[0]],[pools[0],pools[0]],['0x'+'0'*40]):
            with self.subTest(bad=len(bad)),self.assertRaises(m.Refusal):m.call_data(bad)

    def test_zero_is_observed_and_last_unit_not_subtracted_twice(self):
        p=m.amounts(result([[0,1],[m.MAX128,2]]),2)
        self.assertEqual(p['amounts'],[['0','1'],[str(m.MAX128),'2']])
        a,b,c=['0x'+format(i,'040x') for i in range(1,4)]
        totals=m.aggregate([[a,b],[b,c]],p)
        self.assertEqual(totals,{a:'0',b:str(m.MAX128+1),c:'2'})
        with self.assertRaises(m.Refusal):m.aggregate([[b,a],[b,c]],p)

    def test_malformed_or_unavailable_never_becomes_zero(self):
        good=result([[1,2]])
        for value in (None,'0x',good+'00',good[:-2],result([[1,2]],64),result([[2**128,2]]),result([[1,2],[3,4]])):
            with self.subTest(value=value):self.assertFalse(m.amounts(value,1)['available'])
        failed=m.amounts({'rpc_unavailable':3},1)
        self.assertFalse(failed['available'])
        self.assertIsNone(m.aggregate([],failed))
        with self.assertRaises(m.Refusal):m.aggregate([],m.amounts(good,1))

    def fixture(self):
        d,j,pools=m.inputs()
        header=m.decode((ROOT/'reports/uniswap-fee-pool-discovery-v1/run-v1/raw/02.body').read_bytes())['result']
        values={'chain':'0x1','recheck':header,'collect':result([[i,i+1] for i in range(55)])}
        values.update({k:'0x'+format(int(v,16),'064x') for k,v in
                       [('owner',m.ADAPTER),('factory',m.FACTORY),('jar',m.JAR)]})
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable))
            return copy.deepcopy(values[name])
        return d,j,pools,values,seen,rpc

    def test_hash_bound_calls_and_token_accounting(self):
        d,j,pools,values,seen,rpc=self.fixture();p=m.collect(rpc,d,j,pools)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(len(seen),6);self.assertTrue(p['configuration_matches'])
        self.assertEqual(sum(int(x[2][0]['gas'],16) for x in seen[1:5]),10900000)
        for name,method,params,optional in seen[1:5]:
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=d['anchor']['hash'],requireCanonical=True))
            self.assertEqual((params[0]['from'],params[0]['value'],params[0]['gasPrice']),(m.m.DIAGNOSTIC,'0x0','0x0'))
        expected={row['address']:int(row['balance']['value']) for row in j['inventory'][:6]}
        for i,pool in enumerate(pools):
            expected[pool[2][0]]+=i;expected[pool[2][1]]+=i+1
        self.assertEqual(p['modeled_jar_after_collection_native'],{k:str(v) for k,v in sorted(expected.items())})
        self.assertLess(len(m.encode(p)),m.CAPS['projection_bytes'])
        for key in ('release_simulated','cash_closed','economics','repeatable_profit'):self.assertFalse(p[key])

    def test_unavailable_configuration_and_collect_do_not_make_inventory(self):
        for field,value,expected in [('owner',{'rpc_unavailable':3},None),('jar','0x'+'0'*64,False),
                                     ('collect',{'rpc_unavailable':-32000},True)]:
            d,j,pools,values,seen,rpc=self.fixture();values[field]=value;p=m.collect(rpc,d,j,pools)
            self.assertIs(p['configuration_matches'],expected)
            self.assertIsNone(p['collected_native']);self.assertIsNone(p['modeled_jar_after_collection_native'])
            self.assertEqual(len(seen),6)

    def test_wrong_chain_or_reorg_refuses(self):
        for key in ('chain','recheck'):
            d,j,pools,values,seen,rpc=self.fixture()
            if key=='chain':values[key]='0x2'
            else:values[key]['stateRoot']='0x'+'99'*32
            with self.subTest(key=key),self.assertRaises(m.Refusal):m.collect(rpc,d,j,pools)

    def execute(self,root,overflow=False):
        d,j,pools,values,seen,rpc=self.fixture();m.collect(rpc,d,j,pools);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch();sent.append(request)
            raw=b'x'*(cap+1) if overflow and name=='collect' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['content-length',str(len(raw))],['x-test-padding','x'*1000]])))
            for at in range(0,len(raw),1024):emit(raw[at:at+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=(d,j,pools)),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,d,j,pools

    def test_capture_real_header_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,d,j,pools=self.execute(root)
            self.assertTrue(ok);self.assertEqual(len(sent),6)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',d,j,pools)
            self.assertEqual(len(list((out/'raw').iterdir())),24)
            terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertLessEqual(raw,m.CAPS['raw_bytes'])
            path=out/'raw/05.request.json';data=m.decode(path.read_bytes())
            data['request']['params'][1]['requireCanonical']=False;path.write_bytes(m.encode(data))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',d,j,pools)

    def test_collect_overflow_stops_and_preserves_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,_,_,_=self.execute(root,True)
            self.assertFalse(ok);self.assertEqual(len(sent),5)
            out=root/m.OUT;self.assertFalse((out/'projection.json').exists())
            self.assertEqual((out/'raw/05.body').stat().st_size,16385)
            self.assertEqual(m.decode((out/'terminal.json').read_bytes())['requests_attempted'],5)


if __name__=='__main__':unittest.main()
