import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    sp=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
m=load('beefyv2','scripts/beefy_caller_reward_v2.py')
fixture=load('beefyv1test','tests/test_beefy_caller_reward_v1.py')


class LargerResponseTests(unittest.TestCase):
    def test_large_complete_responses_replay_without_changing_cohort_or_outcome(self):
        v,seen,rpc=fixture.RewardTests().fixture()
        for name in ('branch_0','branch_1'):v[name][0]['syntheticPadding']='x'*70000
        expected=m.collect(rpc);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            name,method,params,optional=seen[len(sent)]
            self.assertEqual(request,dict(jsonrpc='2.0',id=len(sent)+1,method=method,params=params))
            dispatch();sent.append(request);observe(200,m.encode(dict(status=200,headers=[])))
            raw=m.encode(dict(jsonrpc='2.0',id=len(sent),result=v[name]));self.assertLessEqual(len(raw),cap)
            emit(raw);return 200,len(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/m.BASE).mkdir(parents=True)
            with mock.patch.object(m.b,'ROOT',root),mock.patch.object(m.b,'verify',return_value={}),mock.patch.object(m.b.resource,'setrlimit'),mock.patch.object(m.b.h,'fetch',side_effect=fetch):
                self.assertTrue(m.b.run('b'*64))
                with self.assertRaises(FileExistsError):m.b.run('b'*64)
            out=root/m.OUT;actual,body,raw=m.replay(out/'raw')
            self.assertEqual(actual,expected);self.assertEqual(len(sent),13)
            self.assertGreater((out/'raw/11.body').stat().st_size,32768)
            self.assertGreater((out/'raw/12.body').stat().st_size,32768)
            self.assertLessEqual(raw,m.CAPS['raw_bytes']);self.assertEqual(actual['available_branches'],2)
            self.assertEqual([x['simulation']['weth_receipt_raw'] for x in actual['vaults']],['10','10'])
            self.assertFalse(actual['cash_closed']);self.assertTrue(actual['prior_capture_unavailable'])
            p=out/'raw/11.request.json';d=m.decode(p.read_bytes());d['request']['params'][0]['validation']=True;p.write_bytes(m.encode(d))
            with self.assertRaisesRegex(m.b.t.Refusal,'request_manifest'):m.replay(out/'raw')

    def test_larger_limit_still_retains_overflow_http_and_global_reservation_failures(self):
        for mode,n in [('overflow',11),('http',4),('reserve',11)]:
            v,seen,rpc=fixture.RewardTests().fixture();m.collect(rpc);sent=[]
            if mode=='reserve':v['branch_0'][0]['syntheticPadding']='x'*100000
            def fetch(request,cap,seconds,emit,observe,dispatch):
                name=seen[len(sent)][0];dispatch();sent.append(request)
                code=403 if mode=='http' and name=='0_native' else 200
                observe(code,m.encode(dict(status=code,headers=[])))
                raw=b'x'*(cap+1) if mode=='overflow' and name=='branch_0' else m.encode(dict(jsonrpc='2.0',id=len(sent),result=v[name]))
                emit(raw)
                if len(raw)>cap:raise m.b.h.Refusal('response_cap_sentinel_retained')
                return code,len(raw)
            caps=copy.deepcopy(m.CAPS)
            if mode=='reserve':caps['raw_bytes']=200000
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/m.BASE).mkdir(parents=True)
                with mock.patch.object(m.b,'ROOT',root),mock.patch.object(m.b,'verify',return_value={}),mock.patch.object(m.b,'CAPS',caps),mock.patch.object(m.b.resource,'setrlimit'),mock.patch.object(m.b.h,'fetch',side_effect=fetch):
                    self.assertFalse(m.b.run('b'*64))
                out=root/m.OUT;terminal=m.decode((out/'terminal.json').read_bytes())
                self.assertEqual(len(sent),n);self.assertFalse((out/'projection.json').exists())
                if mode=='overflow':self.assertEqual((out/'raw/11.body').stat().st_size,131073)
                if mode=='reserve':
                    self.assertEqual(terminal['error'],'reserve_before_dispatch')
                    self.assertFalse((out/'raw/12.request.json').exists())


if __name__=='__main__':unittest.main()
