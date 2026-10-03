import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('clipper_events',ROOT/'scripts/sky_clipper_reward_events_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
word=lambda n:'0x'+format(n,'064x')


class EventTests(unittest.TestCase):
    def fixture(self,n=2):
        header=m.inputs();logs=[]
        for i in range(n):
            logs.append(dict(address='0x'+'11'*20,blockNumber=hex(m.ANCHOR),blockHash=header['hash'],
                transactionHash='0x'+format(i+1,'064x'),transactionIndex=hex(i),logIndex=hex(i),removed=False,
                topics=[list(m.TOPICS)[i%2],word(i+1),word(42),word(43)],
                data='0x'+''.join(format(x,'064x') for x in (2*10**27,100*10**45,10**18,(i%2)*10**45))))
        values=dict(chain='0x1',events=logs,recheck=copy.deepcopy(header));seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return header,values,seen,rpc

    def test_complete_signature_cohort_includes_zero_rewards(self):
        for n in (0,2,8):
            header,v,seen,rpc=self.fixture(n);p=m.collect(rpc,header)
            self.assertEqual(p['event_count'],n);self.assertEqual(p['positive_claimed_incentive_events'],n//2)
            self.assertFalse(p['sky_emitter_identity_proved']);self.assertFalse(p['cash_closed'])
            self.assertEqual([r[0] for r in seen],[r[0] for r in m.SLOTS])
            query=seen[1][2][0];self.assertNotIn('address',query)
            self.assertEqual(query,dict(fromBlock=hex(m.ANCHOR-4095),toBlock=hex(m.ANCHOR),topics=[list(m.TOPICS)]))
            self.assertLessEqual(len(m.encode(p)),m.CAPS['projection_bytes'])

    def test_unknown_malformed_duplicate_and_reorg_never_count_as_empty(self):
        for mode in ('too_many','removed','topic','address','data','window','anchor_hash','duplicate','order','conflict','duplicate_index','reversed_index','rpc','reorg'):
            header,v,seen,rpc=self.fixture(2);e=v['events'][0]
            if mode=='too_many':v['events']*=5
            elif mode=='removed':e['removed']=True
            elif mode=='topic':e['topics'][0]='0x'+'ff'*32
            elif mode=='address':e['topics'][3]=word(2**160)
            elif mode=='data':e['data']+='00'
            elif mode=='window':e['blockNumber']=hex(m.ANCHOR-4096)
            elif mode=='anchor_hash':e['blockHash']='0x'+'aa'*32
            elif mode=='duplicate':v['events']=[e,e]
            elif mode=='order':v['events'].reverse()
            elif mode=='conflict':v['events'][1]['transactionIndex']='0x0'
            elif mode=='duplicate_index':v['events'][1]['logIndex']='0x0'
            elif mode=='reversed_index':e['logIndex']='0x1';v['events'][1]['logIndex']='0x0'
            elif mode=='rpc':v['events']={'rpc_unavailable':-32601}
            else:v['recheck']['stateRoot']='0x'+'55'*32
            with self.subTest(mode=mode),self.assertRaises(Exception):m.collect(rpc,header)

    def execute(self,root,mode='normal'):
        header,values,seen,rpc=self.fixture(8);m.collect(rpc,header);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if mode=='overflow' and name=='events' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            if mode=='rpc' and name=='events':raw=m.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=-32601,message='unsupported')))
            observe(200,m.encode(dict(status=200,headers=[['x-test','x'*512]])))
            for i in range(0,len(raw),1024):emit(raw[i:i+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=header),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,header

    def test_capture_exact_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,header=self.execute(root);out=root/m.OUT
            self.assertTrue(ok,(out/'terminal.json').read_text());self.assertEqual(len(sent),3)
            p,body,raw=m.replay(out/'raw',header);terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']));self.assertEqual(len(list((out/'raw').iterdir())),12)
            path=out/'raw/02.request.json';v=m.decode(path.read_bytes());v['request']['params'][0]['fromBlock']='0x1';path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',header)

    def test_transport_failures_retain_evidence_and_stop(self):
        for mode in ('overflow','rpc'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,_=self.execute(root,mode);out=root/m.OUT
                self.assertFalse(ok);self.assertEqual(len(sent),2);self.assertFalse((out/'projection.json').exists())
                self.assertFalse((out/'raw/03.body').exists())
                if mode=='overflow':self.assertEqual((out/'raw/02.body').stat().st_size,16385)


if __name__=='__main__':unittest.main()
