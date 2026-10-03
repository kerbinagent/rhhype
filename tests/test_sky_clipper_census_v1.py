import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('clipper_live',ROOT/'scripts/sky_clipper_census_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
word=lambda n:'0x'+format(n,'064x')


class CensusTests(unittest.TestCase):
    def fixture(self,count=0):
        block=dict(number='0x123',hash='0x'+'ab'*32,parentHash='0x'+'cd'*32,timestamp='0x100',
            stateRoot='0x'+'ef'*32,gasLimit='0x3938700',miner='0x'+'11'*20,mixHash='0x'+'22'*32,baseFeePerGas='0x9')
        active=list(range(count,0,-1))
        values=dict(chain='0x1',block=block,recheck=copy.deepcopy(block),ilk=m.q.ILK,
            count=word(count),count_recheck=word(count),list='0x'+''.join(format(x,'064x') for x in [32,count]+active))
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return values,seen,rpc

    def test_complete_empty_and_maximal_cohorts(self):
        for n in (0,1,64):
            v,seen,rpc=self.fixture(n);p=m.collect(rpc)
            self.assertEqual(p['count'],n);self.assertEqual(p['active_ids'],[str(i) for i in range(n,0,-1)])
            self.assertEqual([r[0] for r in seen],[r[0] for r in m.SLOTS]);self.assertFalse(p['economics'])
            self.assertFalse(p['reset_eligibility_observed']);self.assertFalse(p['deployed_source_equivalence_proved'])
            self.assertEqual(seen[1][2],['finalized',False]);gas=0
            for name,method,params,optional in seen[2:-1]:
                self.assertEqual(params[1],dict(blockHash=v['block']['hash'],requireCanonical=True))
                self.assertEqual(params[0]['to'],m.q.CLIPPER);self.assertEqual(params[0]['from'],m.q.ZERO)
                self.assertEqual(params[0]['value'],'0x0');gas+=int(params[0]['gas'],16)
            self.assertEqual(gas,800000)

    def test_incomplete_census_stops_and_never_becomes_zero(self):
        for mode in ('overcap','duplicate','zeroid','truncated','trailing','offset','count_change','ilk','reorg','rpc'):
            v,seen,rpc=self.fixture(2)
            if mode=='overcap':v['count']=word(65)
            elif mode=='duplicate':v['list']='0x'+''.join(format(x,'064x') for x in (32,2,1,1))
            elif mode=='zeroid':v['list']='0x'+''.join(format(x,'064x') for x in (32,2,0,1))
            elif mode=='truncated':v['list']=v['list'][:-2]
            elif mode=='trailing':v['list']+='00'
            elif mode=='offset':v['list']=word(64)+v['list'][66:]
            elif mode=='count_change':v['count_recheck']=word(1)
            elif mode=='ilk':v['ilk']=word(42)
            elif mode=='reorg':v['recheck']['stateRoot']='0x'+'55'*32
            else:v['count']={'rpc_unavailable':-32601}
            with self.subTest(mode=mode),self.assertRaises(Exception):m.collect(rpc)
            if mode=='overcap':self.assertEqual(len(seen),4)
        with self.assertRaises(Exception):m.ids('0x',0)

    def execute(self,root,mode='normal'):
        values,seen,rpc=self.fixture(64);m.collect(rpc);sent=[]
        if mode=='reserve':
            for name in ('block','recheck'):values[name]['syntheticPadding']='x'*31000
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if mode=='overflow' and name=='list' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            if mode=='rpc' and name=='count':raw=m.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=-32601,message='unsupported')))
            observe(200,m.encode(dict(status=200,headers=[['x-test','x'*512]])))
            for i in range(0,len(raw),1024):emit(raw[i:i+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent

    def test_capture_exact_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent=self.execute(root);out=root/m.OUT
            self.assertTrue(ok,(out/'terminal.json').read_text());self.assertEqual(len(sent),7)
            p,body,raw=m.replay(out/'raw');v=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(v['body_bytes'],v['raw_bytes']));self.assertEqual(len(list((out/'raw').iterdir())),28)
            path=out/'raw/05.request.json';v=m.decode(path.read_bytes());v['request']['params'][1]['requireCanonical']=False;path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw')

    def test_transport_failures_and_full_reservation(self):
        for mode,attempts in [('overflow',5),('rpc',4),('reserve',6)]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent=self.execute(root,mode);out=root/m.OUT
                self.assertFalse(ok);self.assertEqual(len(sent),attempts);self.assertFalse((out/'projection.json').exists())
                if mode=='overflow':self.assertEqual((out/'raw/05.body').stat().st_size,8193)
                if mode=='reserve':self.assertEqual(m.decode((out/'terminal.json').read_bytes())['error'],'reserve_before_dispatch')


if __name__=='__main__':unittest.main()
