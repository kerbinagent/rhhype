import gzip
import importlib.util
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('basecaller','scripts/beefy_base_caller_v1.py')
f=load('oldfixture','tests/test_beefy_caller_reward_v1.py')


class BaseCaptureTests(unittest.TestCase):
    def test_base_cohort_context_receipts_and_large_exact_compressed_replay(self):
        v,seen,rpc=f.RewardTests().fixture();v['chain']='0x2105'
        for i in range(2):
            v[str(i)+'_native']=f.addr(m.WETH);s=v['branch_'+str(i)][0];s['timestamp']='0x102';s['padding']='x'*60000
            for log in s['calls'][1]['logs']:log['address']=m.WETH
        v['0_callReward']={'rpc_unavailable':-32601};expected=m.collect(rpc);sent=[]
        def fetch(request,cap,seconds,emit,headers,dispatch):
            name,method,params,optional=seen[len(sent)]
            self.assertEqual(request,dict(jsonrpc='2.0',id=len(sent)+1,method=method,params=params))
            dispatch();sent.append(request);headers(200,m.encode(dict(status=200,headers=[])))
            raw=m.encode(dict(jsonrpc='2.0',id=len(sent),result=v[name]))
            for offset in range(0,len(raw),4096):emit(raw[offset:offset+4096])
            return 200,len(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/m.BASE).mkdir(parents=True)
            with mock.patch.object(m.b,'ROOT',root),mock.patch.object(m.b,'verify',return_value={}),mock.patch.object(m.b.resource,'setrlimit'),mock.patch.object(m.b.c.h,'fetch',side_effect=fetch):
                self.assertTrue(m.b.run('c'*64))
                with self.assertRaises(FileExistsError):m.b.run('c'*64)
            actual,wire,raw=m.replay(root/m.OUT/'raw');self.assertEqual(actual,expected)
            self.assertEqual(len(sent),13);self.assertGreater(wire,120000);self.assertLess(raw,m.CAPS['raw_bytes'])
            self.assertEqual(actual['chain_id'],8453);self.assertEqual(actual['hypothetical_context']['time'],'0x102')
            self.assertEqual([x['simulation']['weth_receipt_raw'] for x in actual['vaults']],['10','10'])
            self.assertTrue(actual['gas_reference_excludes_l1_and_other_chain_fees']);self.assertFalse(actual['cash_closed'])
            self.assertFalse(actual['vaults'][0]['metadata']['callReward']['available'])

    def test_wire_zip_http_and_reservation_failures_are_retained(self):
        for mode in ('wire','zip','http','reserve'):
            cap=2048;slots=[('one',cap,128)];caps=dict(m.CAPS,requests=1);sent=[]
            if mode=='reserve':caps['raw_bytes']=1
            raw=(b'x'*(cap+1) if mode=='wire' else random.Random(8).randbytes(1500) if mode=='zip' else b'{}')
            def fetch(request,limit,seconds,emit,headers,dispatch):
                dispatch();sent.append(request);code=403 if mode=='http' else 200;headers(code,m.encode(dict(status=code,headers=[])))
                emit(raw)
                if len(raw)>limit:raise m.b.h.Refusal('response_cap_sentinel_retained')
                return code,len(raw)
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp,mock.patch.object(m.b.c.h,'fetch',side_effect=fetch):
                p=Path(tmp)/'raw';c=m.z.Capture(p,slots,caps,m.b.c,time.monotonic(),m.b.r.m.reason)
                with self.assertRaises(m.z.Refusal):c.rpc('one','eth_chainId',[])
                self.assertEqual(len(sent),0 if mode=='reserve' else 1)
                if mode=='reserve':self.assertEqual(list(p.iterdir()),[]);continue
                receipt=m.decode((p/'01.receipt.json').read_bytes());self.assertIsNotNone(receipt['error'])
                self.assertEqual(receipt['response_bytes'],len(raw))
                if mode=='zip':self.assertEqual((p/'01.body.gz').stat().st_size,129);self.assertFalse(receipt['gzip_complete'])
                else:self.assertEqual(gzip.decompress((p/'01.body.gz').read_bytes()),raw)

    def test_bounded_replay_rejects_bad_gzip_extra_members_and_false_wire_hash(self):
        slots=[('one',1024,2048)];raw=m.encode(dict(jsonrpc='2.0',id=1,result='0x1'))
        def fetch(request,cap,seconds,emit,headers,dispatch):
            dispatch();headers(200,m.encode(dict(status=200,headers=[])));emit(raw);return 200,len(raw)
        for mode in ('crc','extra','wirehash'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp,mock.patch.object(m.b.c.h,'fetch',side_effect=fetch):
                p=Path(tmp)/'raw';c=m.z.Capture(p,slots,m.CAPS,m.b.c,time.monotonic(),m.b.r.m.reason);self.assertEqual(c.rpc('one','eth_chainId',[]),'0x1')
                reader=m.z.Reader(p,slots,m.CAPS,m.b.c);self.assertEqual(reader.rpc('one','eth_chainId',[]),'0x1');reader.finish()
                file=p/'01.body.gz';z=file.read_bytes();r=p/'01.receipt.json';v=m.decode(r.read_bytes())
                if mode=='crc':z=z[:-1]
                if mode=='extra':z+=gzip.compress(b'',mtime=0)
                file.write_bytes(z);v.update(gzip_bytes=len(z),gzip_sha256=m.sha(z))
                if mode=='wirehash':v['response_sha256']='0'*64
                r.write_bytes(m.encode(v))
                with self.assertRaises(m.z.Refusal):m.z.Reader(p,slots,m.CAPS,m.b.c).rpc('one','eth_chainId',[])

    def test_endpoint_factory_is_fixed_to_base(self):
        def fetch(*args,factory):return factory('ethereum-rpc.publicnode.com',timeout=1,context=None)
        with mock.patch.object(m,'old_fetch',side_effect=fetch),mock.patch.object(m.http.client,'HTTPSConnection',return_value='ok') as conn:
            self.assertEqual(m.base_fetch({},1,1,None,None,None),'ok');conn.assert_called_once_with('base-rpc.publicnode.com',timeout=1,context=None)


if __name__=='__main__':unittest.main()
