import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pool_discovery',ROOT/'scripts/uniswap_fee_pool_discovery_v1.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def word(n):return '0x'+format(n,'064x')


class PoolDiscoveryTests(unittest.TestCase):
    def fixture(self):
        inv=p.inputs();b=inv['block'];c=inv['context']
        block=dict(number=hex(b['number']),hash=b['hash'],parentHash=b['parentHash'],timestamp=hex(b['timestamp']),
                   stateRoot=b['stateRoot'],gasLimit=c['gasLimit'],miner=c['feeRecipient'],mixHash=c['prevRandao'],
                   baseFeePerGas=c['baseFeePerGas'])
        values=dict(chain='0x1',anchor=block,recheck=copy.deepcopy(block),owner=word(int(p.ADAPTERS[0],16)))
        for i in range(len(p.PAIRS)):
            for fee in p.FEES:values['p%02d_%d'%(i,fee)]=word(0x100000+i*10000+fee)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable))
            return copy.deepcopy(values[name])
        return inv,values,seen,rpc

    def test_fixed_64_slots_abi_and_compact_projection(self):
        inv,values,seen,rpc=self.fixture();result=p.collect(rpc,inv)
        self.assertEqual([x[0] for x in seen],[x[0] for x in p.SLOTS]);self.assertEqual(len(seen),64)
        self.assertEqual((result['present'],result['absent'],result['unknown']),(60,0,0))
        self.assertEqual(result['owner']['status'],'documented_adapter')
        self.assertEqual(len(result['pairs']),15);self.assertEqual(len(result['rows']),60)
        self.assertLessEqual(len(p.encode(result)),p.CAPS['projection_bytes'])
        self.assertEqual(seen[1][1:3],('eth_getBlockByNumber',[hex(p.ANCHOR_NUMBER),False]))
        gas=0
        for index,(name,method,params,optional) in enumerate(seen[2:-1]):
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            tx,state=params;self.assertEqual(state,dict(blockHash=p.ANCHOR_HASH,requireCanonical=True))
            self.assertEqual((tx['from'],tx['to'],tx['value'],tx['gasPrice']),
                             (p.DIAGNOSTIC,p.FACTORY,'0x0','0x0'))
            gas+=int(tx['gas'],16)
            if index==0:self.assertEqual(tx['input'],p.s.selector('owner()'))
            else:
                pair=(index-1)//4;fee=p.FEES[(index-1)%4];i,j=p.PAIRS[pair]
                expected=p.s.selector('getPool(address,address,uint24)')+p.s.word_address(p.ASSETS[i][1])+p.s.word_address(p.ASSETS[j][1])+format(fee,'064x')
                self.assertEqual(tx['input'],expected)
        self.assertEqual(gas,18300000)
        for key in ('collection_not_simulated','pool_state_not_read','quotes_not_read'):
            self.assertTrue(result[key])
        for key in ('cash_closed','economics','repeatable_profit'):self.assertFalse(result[key])

    def test_zero_error_alias_and_owner_classes(self):
        inv,values,seen,rpc=self.fixture()
        values['owner']=word(0)
        values['p00_100']=word(0)
        values['p00_500']={'rpc_unavailable':3}
        values['p00_3000']=values['p00_10000']
        result=p.collect(rpc,inv)
        self.assertEqual(len(seen),64)
        self.assertEqual(result['owner'],dict(status='other_owner',address='0x'+'0'*40,error=None))
        self.assertEqual((result['present'],result['absent'],result['unknown']),(58,1,1))
        self.assertEqual(result['rows'][0],[0,100,'0',None,None])
        self.assertEqual(result['rows'][1],[0,500,'?',None,'rpc:3'])
        self.assertEqual(result['aliases'],[[result['rows'][2][3],[2,3]]])
        values['owner']={'rpc_unavailable':-32000};values['p00_500']=None
        result=p.collect(rpc,inv)
        self.assertEqual(result['owner'],dict(status='unknown',address=None,error='rpc:-32000'))
        self.assertEqual(result['rows'][1],[0,500,'?',None,'null_or_noncanonical'])

    def test_wrong_chain_and_anchor_or_recheck_mismatch_refuse(self):
        for name in ('chain','anchor','recheck'):
            inv,values,seen,rpc=self.fixture()
            if name=='chain':values['chain']='0x2'
            else:values[name]['stateRoot']='0x'+'99'*32
            with self.subTest(name=name),self.assertRaises((p.Refusal,p.s.o.Refusal)):
                p.collect(rpc,inv)

    def test_noncanonical_addresses_are_unknown_and_do_not_alias(self):
        inv,values,seen,rpc=self.fixture()
        values['owner']='0x1';values['p00_100']='0x1';values['p00_500']=None
        result=p.collect(rpc,inv)
        self.assertEqual(result['owner']['status'],'unknown')
        self.assertEqual(result['rows'][0][2:],[ '?',None,'null_or_noncanonical'])
        self.assertEqual(result['rows'][1][2:],[ '?',None,'null_or_noncanonical'])
        self.assertEqual(result['aliases'],[])

    def execute(self,root,failure=None):
        inv,values,seen,rpc=self.fixture();p.collect(rpc,inv);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch();sent.append(request)
            raw=b'x'*(cap+1) if failure=='sentinel' and i==1 else p.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,p.encode(dict(status=200,headers=[['content-length',str(len(raw))]])))
            for at in range(0,len(raw),1024):emit(raw[at:at+1024])
            if len(raw)>cap:raise p.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/p.BASE).mkdir(parents=True)
        with mock.patch.object(p,'ROOT',root),mock.patch.object(p,'verify',return_value={'pins':[]}), \
             mock.patch.object(p,'inputs',return_value=inv),mock.patch.object(p.resource,'setrlimit'), \
             mock.patch.object(p.h,'fetch',side_effect=fetch):
            ok=p.run('a'*64)
            with self.assertRaises(FileExistsError):p.run('a'*64)
        return ok,sent,inv

    def test_complete_capture_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,inv=self.execute(root)
            self.assertTrue(ok);self.assertEqual(len(sent),64)
            out=root/p.OUT;result,body,raw=p.replay(out/'raw',inv)
            self.assertEqual((result['present'],len(list((out/'raw').iterdir()))),(60,256))
            terminal=p.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertLessEqual(raw,p.CAPS['raw_bytes'])
            path=out/'raw/04.request.json';v=p.decode(path.read_bytes())
            v['request']['params'][1]['requireCanonical']=False;path.write_bytes(p.encode(v))
            with self.assertRaisesRegex(p.t.Refusal,'request_manifest'):p.replay(out/'raw',inv)

    def test_header_overflow_retains_sentinel_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,_=self.execute(root,'sentinel')
            self.assertFalse(ok);self.assertEqual(len(sent),2)
            out=root/p.OUT;self.assertFalse((out/'projection.json').exists())
            self.assertEqual((out/'raw/02.body').stat().st_size,32769)
            terminal=p.decode((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['status'],'unavailable')
            self.assertEqual(terminal['requests_attempted'],2)


if __name__=='__main__':unittest.main()
